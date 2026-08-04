"""Plafond de notionnel sur le dimensionnement (2026-08-04).

Le sizing vise un **risque** constant, pas une taille. Or :

    notionnel = risque × entrée / distance du stop

Cette identité vaut sur toutes les plateformes — la taille de contrat
s'annule entre le calcul du volume et celui du notionnel. Un stop serré
produit donc mécaniquement une position énorme, sans que le risque affiché
bouge d'un centime.

Le cas réel : le 2026-08-04, un ordre de 0,215 ETH est parti pour cette
seule raison. 403 USD de notionnel sur un compte de 103 — 3,9× — alors que
le risque visé n'était que de 0,66 USD.

Le plafond se déclare par destination : le forex MT5 à 0,1 lot atteint
naturellement 3,8×, ce qui n'a rien d'anormal ; le même multiple sur un
perpétuel crypto engage un actif d'une tout autre volatilité.
"""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from backend.services import destinations_registry as reg
from backend.services import sizing


def _setup(pair="ETH/USD", entry=1874.6, sl=1877.67):
    return NS(pair=pair, direction=NS(value="sell"),
              entry_price=entry, stop_loss=sl)


def _dest(dest_id="admin_kraken"):
    return NS(destination_id=dest_id)


def _notionnel(risque, setup):
    return risque * setup.entry_price / abs(setup.entry_price - setup.stop_loss)


# --- le cas réel -----------------------------------------------------------

def test_l_ordre_de_0215_eth_aurait_ete_reduit():
    """403 USD de notionnel sur un compte de 103 : 3,9×."""
    s = _setup()
    avant = _notionnel(0.66, s)
    assert avant == pytest.approx(403, abs=2), "jeu de donnees incoherent"

    risque, notionnel, plafond = sizing.plafonner_notionnel(
        0.66, s, _dest(), capital=103.26)

    assert notionnel == pytest.approx(403, abs=2), "le notionnel constate doit etre expose"
    assert plafond == pytest.approx(206.5, abs=1)
    assert _notionnel(risque, s) == pytest.approx(plafond, rel=0.02)


def test_la_quantite_finale_tient_dans_le_plafond():
    s = _setup()
    risque, _, plafond = sizing.plafonner_notionnel(0.66, s, _dest(), 103.26)
    qty = risque / abs(s.entry_price - s.stop_loss)
    assert qty * s.entry_price <= plafond * 1.02
    assert qty == pytest.approx(0.11, abs=0.01)


# --- ce que le plafond ne doit PAS faire ----------------------------------

def test_sous_le_plafond_le_risque_est_intact():
    """Le plafond est un garde-fou, pas une politique de sizing."""
    s = _setup(entry=1874.6, sl=1837.1)  # stop large : notionnel modeste
    risque, notionnel, plafond = sizing.plafonner_notionnel(
        0.66, s, _dest(), 103.26)
    assert risque == 0.66
    assert notionnel < plafond


def test_le_stop_n_est_jamais_deplace():
    """Élargir le stop réduirait aussi le notionnel — mais ce serait changer
    le trade. Le stop appartient au setup, on réduit le risque."""
    s = _setup()
    avant = (s.entry_price, s.stop_loss)
    sizing.plafonner_notionnel(0.66, s, _dest(), 103.26)
    assert (s.entry_price, s.stop_loss) == avant


def test_mt5_n_est_pas_perturbe():
    """Le forex à 0,1 lot atteint 3,8× naturellement : le garde-fou global
    est à 5×, il ne doit pas mordre sur le fonctionnement normal."""
    s = _setup("EUR/USD", entry=1.1525, sl=1.1500)
    risque, notionnel, plafond = sizing.plafonner_notionnel(
        30.0, s, _dest("admin_live"), capital=3000.0)
    assert risque == 30.0
    assert plafond == pytest.approx(15000.0)


# --- le plafond vient du registre -----------------------------------------

@pytest.mark.parametrize("dest_id", ["admin_kraken", "admin_kraken_spot",
                                     "admin_kraken_stocks"])
def test_les_destinations_crypto_sont_plafonnees_a_2x(dest_id):
    assert reg.DESTINATIONS[dest_id].max_notional_leverage == 2.0


@pytest.mark.parametrize("dest_id", ["admin_live", "admin_legacy"])
def test_mt5_retombe_sur_le_garde_fou_global(dest_id):
    assert reg.DESTINATIONS[dest_id].max_notional_leverage is None


def test_le_plafond_declare_est_bien_celui_applique():
    """Sinon le champ du registre serait décoratif."""
    s = _setup()
    _, _, plafond = sizing.plafonner_notionnel(0.66, s, _dest("admin_kraken"), 100.0)
    assert plafond == pytest.approx(200.0)
    _, _, global_ = sizing.plafonner_notionnel(0.66, s, _dest("admin_live"), 100.0)
    assert global_ == pytest.approx(100.0 * sizing.MAX_NOTIONAL_LEVERAGE)


def test_une_destination_inconnue_prend_le_garde_fou_global():
    s = _setup()
    _, _, plafond = sizing.plafonner_notionnel(0.66, s, _dest("admin_inexistant"), 100.0)
    assert plafond == pytest.approx(100.0 * sizing.MAX_NOTIONAL_LEVERAGE)


# --- refuser de calculer plutôt que calculer faux --------------------------

@pytest.mark.parametrize("entry,sl", [(0, 1877.0), (1874.0, 0), (1874.0, 1874.0)])
def test_sans_stop_exploitable_aucun_plafonnement(entry, sl):
    """`distance = 0` diviserait par zéro : ne rien affirmer."""
    s = _setup(entry=entry, sl=sl)
    risque, notionnel, plafond = sizing.plafonner_notionnel(0.66, s, _dest(), 103.26)
    assert risque == 0.66
    assert notionnel is None and plafond is None


@pytest.mark.parametrize("capital", [None, 0])
def test_sans_capital_connu_aucun_plafonnement(capital):
    """Le capital indisponible est déjà traité en amont par un risque nul."""
    risque, _, _ = sizing.plafonner_notionnel(0.66, _setup(), _dest(), capital)
    assert risque == 0.66


def test_un_risque_nul_reste_nul():
    assert sizing.plafonner_notionnel(0.0, _setup(), _dest(), 103.26)[0] == 0.0


# --- visibilité ------------------------------------------------------------

def test_le_plafonnement_est_visible_dans_le_resultat(monkeypatch):
    """Un trade pris plus petit que visé doit se voir, pas se deviner."""
    monkeypatch.setattr(sizing, "destination_capital",
                        lambda d: (103.26, "test"))
    monkeypatch.setattr(sizing, "recent_pnl_multiplier", lambda **kw: 1.0)
    sz = sizing.compute_risk_money(_setup(), _dest())
    assert sz["notionnel_plafonne"] is True
    assert sz["plafond_notionnel"] == pytest.approx(206.5, abs=1)
    assert sz["notionnel"] > sz["plafond_notionnel"]


def test_sans_plafonnement_le_drapeau_reste_baisse(monkeypatch):
    monkeypatch.setattr(sizing, "destination_capital",
                        lambda d: (103.26, "test"))
    monkeypatch.setattr(sizing, "recent_pnl_multiplier", lambda **kw: 1.0)
    sz = sizing.compute_risk_money(_setup(entry=1874.6, sl=1837.1), _dest())
    assert sz["notionnel_plafonne"] is False


def test_le_dict_porte_les_memes_cles_sans_capital(monkeypatch):
    """Un consommateur ne doit pas lever selon la branche empruntée."""
    monkeypatch.setattr(sizing, "destination_capital", lambda d: (None, "absent"))
    sz = sizing.compute_risk_money(_setup(), _dest())
    for cle in ("notionnel", "plafond_notionnel", "notionnel_plafonne"):
        assert cle in sz
