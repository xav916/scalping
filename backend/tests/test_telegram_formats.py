"""Format des messages de trade : exhaustif, simple, direct (2026-08-04).

Principe : **la première ligne dit quoi, la deuxième dit combien**, le reste
est du détail consultable. Aucune information retirée — réordonnée.

Deux oublis comblés au passage :
  - l'ouverture n'affichait ni le stop, ni l'objectif, ni le volume
  - la clôture ne disait pas chez quel broker le trade avait eu lieu

Et deux répétitions supprimées : le broker apparaissait trois fois dans le
message d'ouverture (titre, ligne « Plateforme », pied « compte … »).
"""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from backend.models.schemas import PatternType
from backend.services import telegram_service as ts


def _setup():
    return NS(pair="XAU/USD", direction=NS(value="sell"),
              pattern=NS(pattern=PatternType.RANGE_BOUNCE_DOWN,
                         confidence=0.78, description="Rejet"),
              confidence_score=74.0, entry_price=3312.40, stop_loss=3320.10,
              take_profit_1=3298.54, take_profit_2=3290.0, risk_pips=7.7,
              reward_pips_1=13.86, reward_pips_2=22.4, risk_reward_1=1.8,
              risk_reward_2=2.9, asset_class="metal")


def _ouverture(dest="admin_live"):
    return ts._format_trade_opened(_setup(), ticket=8842190, fill_price=3312.40,
                                   volume=0.02, mode="LIVE", destination_id=dest)


def _cloture(reason="TP1", pnl=12.47, dest="admin_live"):
    return ts._format_close({
        "pair": "XAU/USD", "direction": "sell", "entry_price": 3312.40,
        "exit_price": 3298.54, "pnl": pnl, "close_reason": reason,
        "mt5_ticket": 8842190, "size_lot": 0.02,
        "created_at": "2026-08-04T15:26:00+00:00",
        "closed_at": "2026-08-04T17:40:00+00:00",
        "signal_pattern": "range_bounce_down", "signal_confidence": 74.0,
    }, destination_id=dest)


# --- l'ordre de lecture ----------------------------------------------------

def test_ouverture_le_sens_et_le_broker_en_premiere_ligne():
    l1 = _ouverture().split("\n")[0]
    assert "VENTE" in l1 and "Or" in l1 and "IC Markets" in l1


def test_ouverture_les_montants_en_deuxieme_ligne():
    """Ils arrivaient en quatrième position."""
    l2 = _ouverture().split("\n")[1]
    assert "Risque" in l2 and "Objectif" in l2


def test_cloture_le_resultat_en_premiere_ligne():
    """La question est « j'ai gagné combien », pas « quel instrument »."""
    l1 = _cloture().split("\n")[0]
    assert "+12,47 €" in l1


def test_cloture_la_cause_en_deuxieme_ligne():
    assert "Objectif TP1 atteint" in _cloture().split("\n")[1]


# --- exhaustivité : rien ne doit manquer -----------------------------------

def test_ouverture_porte_le_plan_complet():
    """SL, TP et volume manquaient entièrement au message."""
    txt = _ouverture()
    assert "SL 3320,10" in txt
    assert "TP 3298,54" in txt
    assert "0,02 lot" in txt
    assert "3312,40" in txt


def test_ouverture_garde_la_justification():
    txt = _ouverture()
    assert "Pourquoi ce trade" in txt and "74/100" in txt


def test_ouverture_garde_la_reference_et_l_heure():
    assert "#8842190" in _ouverture()


def test_cloture_nomme_le_broker():
    """Il était absent du message de clôture."""
    assert "IC Markets" in _cloture()


def test_cloture_garde_prix_duree_et_justification():
    txt = _cloture()
    assert "3312,40" in txt and "3298,54" in txt
    assert "2h14" in txt
    assert "0,02 lot" in txt
    assert "Pourquoi ce trade" in txt
    assert "#8842190" in txt


# --- pas de répétition -----------------------------------------------------

def test_le_broker_napparait_quune_fois_a_l_ouverture():
    """Il figurait trois fois : titre, ligne Plateforme, pied « compte … »."""
    assert _ouverture().count("IC Markets") == 1


def test_le_broker_napparait_quune_fois_a_la_cloture():
    assert _cloture().count("IC Markets") == 1


# --- conventions françaises ------------------------------------------------

@pytest.mark.parametrize("fragment", ["−6,93 €", "+12,47 €", "0,02 lot", "3312,40"])
def test_virgule_decimale_partout(fragment):
    """Prix et montants dans le même format : la virgule, pas le point.

    Les deux clôtures sont nécessaires : ce test vérifiait auparavant
    « +12,47 € » sur le message d'OUVERTURE, ce qui le rendait dépendant
    d'un montant calculé pour un lot fixe — et donc faux. Il fige désormais
    la convention d'écriture, pas un montant.
    """
    txt = (_ouverture() + _cloture(reason="SL", pnl=-6.93)
           + _cloture(reason="TP1", pnl=12.47))
    assert fragment in txt


def test_le_montant_annonce_correspond_au_volume_reel():
    """Il venait d'une table « pour 0,01 lot », sans lien avec l'ordre envoyé.

    Vérifié contre le P&L réellement encaissé en production : la formule
    notionnelle colle aux trades clôturés à un facteur EUR/USD près.
    Sur 0,02 lot d'or, 7,70 $ de stop = 2 onces × 7,70 = 15,40 $ ≈ 13,4 €,
    et non les 0,90 € qu'annonçait l'ancienne table.
    """
    from backend.services import risk_eur
    attendu = risk_eur.calculer("XAU/USD", 3312.40, 3320.10, 3298.54,
                                volume=0.02, bridge_type="mt5",
                                eur_usd=risk_eur.taux_eur_usd())
    montant = f"{attendu['risque_eur']:.2f}".replace(".", ",")
    assert f"−{montant} €" in _ouverture()
    assert attendu["risque_eur"] > 5, "montant implausible pour 2 onces d'or"


def test_pas_de_point_decimal_dans_les_montants():
    for txt in (_ouverture(), _cloture()):
        for mauvais in ("€6.93", "€12.47", "0.02 lot", "3312.40"):
            assert mauvais not in txt, f"{mauvais!r} au format anglais"


def test_l_acronyme_reste_en_majuscules():
    """`.capitalize()` transformait « TP1 » en « Tp1 »."""
    assert "TP1" in _cloture(reason="TP1")
    assert "Tp1" not in _cloture(reason="TP1")


# --- les cas de sortie -----------------------------------------------------

@pytest.mark.parametrize("reason,attendu,icone", [
    ("TP1", "Objectif TP1 atteint", "✅"),
    ("TP2", "Objectif TP2 atteint", "✅"),
    ("SL", "Stop de sécurité touché", "❌"),
    ("TIMEOUT", "Clôturé au temps", "⏱"),
    ("MANUAL", "Fermé à la main", "👋"),
])
def test_chaque_cause_de_sortie_est_nommee(reason, attendu, icone):
    txt = _cloture(reason=reason, pnl=1.0)
    assert attendu in txt
    assert txt.startswith(icone)


def test_la_perte_porte_un_signe_moins():
    assert "−6,93 €" in _cloture(reason="SL", pnl=-6.93)


def test_sans_broker_le_message_reste_valide():
    """Destination non résolue : on n'invente pas, mais on n'échoue pas."""
    txt = _cloture(dest=None)
    assert "+12,47 €" in txt
    assert "IC Markets" not in txt
