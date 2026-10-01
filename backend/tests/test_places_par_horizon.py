"""Une place PAR HORIZON, pas une place par paire.

⛔ **Le constat du 2026-10-01.** Les six horizons de l'or ont été ouverts sur
`admin_live` à la demande de Xavier. Dans les minutes qui ont suivi, un
`engulfing_bearish` **15 min** a franchi la porte d'horizon — et s'est fait
refuser en `max_positions_per_pair` par une position **5 min** ouverte 31
minutes plus tôt.

> **Ouvrir six horizons pour les faire retomber dans une seule place, ce n'est
> pas les ouvrir.**

🔑 **Ce que fait ce dispositif, et sa LIMITE assumée.** Le courtier ne dit pas
l'horizon : une position, c'est un symbole, un sens, un ticket. L'horizon vit
dans `mt5_pushes`, notre propre mémoire. On garde donc DEUX plafonds
superposés, et ce n'est pas une redondance :

    plafond de PAIRE      compté CHEZ LE COURTIER, toutes positions, la main
                          comprise — la vérité du monde, et le filet
    plafond d'HORIZON     compté par attribution de ticket dans `mt5_pushes` —
                          plus fin, mais seulement aussi bon que notre journal

⛔ Si notre journal se trompe, le plafond de paire rattrape. L'inverse serait
faux : raffiner sans filet remplacerait une porte qui compte le monde par une
porte qui compte sa mémoire — le défaut du 31/07 (47 ordres WTI) et celui du
garde de corrélation le matin même.

⚠️ Une position ouverte À LA MAIN n'a pas d'horizon. Elle ne consomme donc
aucune place d'horizon, et compte dans le plafond de paire. C'est délibéré :
elle n'a pas été prise par une échelle, mais elle existe bien.
"""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from backend.services import mt5_bridge as mb


def _dest(dest_id="admin_live"):
    return NS(destination_id=dest_id, bridge_url="http://pont.invalide",
              bridge_api_key="k", bridge_type="mt5", user_id=None,
              symbol_map=None, allowed_horizons=frozenset())


def _pos(symbol="XAUUSD", type_="buy", ticket=1):
    return {"symbol": symbol, "type": type_, "ticket": ticket}


@pytest.fixture
def courtier(monkeypatch):
    """Positions du courtier + horizon de chaque ticket dans notre journal."""
    etat = {"positions": [], "horizons": {}}
    # ⛔ Le reglage sous test se DECLARE ici. Sans lui, les tests retombaient
    # sur le plafond de paire et l'un d'eux passait pour la mauvaise raison.
    monkeypatch.setattr(mb, "MT5_BRIDGE_PLACES_PAR_HORIZON", {"XAU/USD": 1},
                        raising=False)
    monkeypatch.setattr(mb, "_positions_courtier",
                        lambda dest, sans_cache=False: etat["positions"])
    monkeypatch.setattr(mb, "_horizon_du_ticket",
                        lambda t: etat["horizons"].get(t), raising=False)
    return etat


# --- Le défaut lui-même --------------------------------------------------

def test_une_position_5min_ne_bloque_pas_un_signal_30min(courtier):
    """⛔ Le cœur : c'est la séquence du 01/10 à 18h42, rejouée."""
    courtier["positions"] = [_pos(ticket=1360199305)]
    courtier["horizons"] = {1360199305: "5min"}
    assert mb._places_libres_pour("XAU/USD", "30min", _dest()) > 0


def test_une_position_5min_bloque_un_AUTRE_signal_5min(courtier):
    """La place de l'horizon reste à UNE : le même horizon est refusé."""
    courtier["positions"] = [_pos(ticket=1360199305)]
    courtier["horizons"] = {1360199305: "5min"}
    assert mb._places_libres_pour("XAU/USD", "5min", _dest()) == 0


def test_le_plafond_de_PAIRE_rattrape_quand_tout_est_plein(courtier):
    """⛔ Le filet : six positions or, même réparties sur six horizons,
    atteignent le plafond de paire et un septième horizon ne passe pas.

    Sans ce plafond, raffiner par horizon aurait retiré toute borne globale
    sur l'instrument — exactement ce que le cap par paire existe pour tenir.
    """
    horizons = ["5min", "15min", "30min", "1h", "4h", "1d"]
    courtier["positions"] = [_pos(ticket=100 + i) for i in range(len(horizons))]
    courtier["horizons"] = {100 + i: h for i, h in enumerate(horizons)}
    assert mb._places_libres_pour("XAU/USD", "5min", _dest()) == 0


# --- Ce que notre journal ne sait pas ------------------------------------

def test_une_position_a_la_main_ne_consomme_aucune_place_d_horizon(courtier):
    """Pas d'horizon dans `mt5_pushes` ⇒ aucune place d'échelle consommée."""
    courtier["positions"] = [_pos(ticket=999999)]
    courtier["horizons"] = {}
    assert mb._places_libres_pour("XAU/USD", "5min", _dest()) > 0


def test_un_pont_muet_ne_dit_PAS_qu_il_reste_de_la_place(courtier, monkeypatch):
    """⛔ « On ne sait pas » n'est pas « il reste de la place ».

    `None` doit remonter comme indécidable, jamais comme une place libre.
    """
    monkeypatch.setattr(mb, "_positions_courtier",
                        lambda dest, sans_cache=False: None)
    assert mb._places_libres_pour("XAU/USD", "5min", _dest()) is None


# --- Les autres paires et comptes ne bougent pas -------------------------

def test_une_position_sur_une_AUTRE_paire_ne_compte_pas(courtier):
    courtier["positions"] = [_pos(symbol="EURUSD", ticket=7)]
    courtier["horizons"] = {7: "5min"}
    assert mb._places_libres_pour("XAU/USD", "5min", _dest()) > 0


# --- Le troisieme retrecisseur : le garde de CORRELATION -----------------
#
# ⛔ Une place par horizon ne suffit pas. L'or contre l'or dans le MEME sens
# vaut une exposition de 1,0, et `LIMITE_PAR_PAIRE` valait 2 : la troisieme
# echelle se faisait refuser en `correlated_exposure` quoi qu'on fasse au cap
# par paire. Ouvrir six horizons pour en servir deux, ce n'est pas les ouvrir.
#
# ⚠️ Ce que cela coute, et qui est assume : six positions or simultanees
# engagent la somme de leurs risques. Mesure du 01/10 au lot minimum —
# 5min 8,77 € + 15min 15,38 € + 30min 23,53 € + 1h 31,69 € = 79,37 €, soit
# 12,2 % d'un capital de 650 €, contre un plafond journalier de 3 % (19,50 €).
# Le plafond journalier devient donc la protection qui tranche, et c'est lui
# qui doit rester intact.

def test_cinq_echelles_ouvertes_ne_bloquent_pas_la_sixieme(monkeypatch):
    """Le garde de correlation doit laisser une place par echelle."""
    from backend.services import correlation_guard as cg

    ouvertes = [("XAU/USD", "buy")] * 5
    monkeypatch.setattr(cg, "positions_ouvertes", lambda _id: list(ouvertes))
    pris, en_cause = cg.pari_deja_pris(_dest(), "XAU/USD", "buy")
    assert pris is False, (
        "le garde de correlation ecrase les horizons : limite=%s pour 5 "
        "positions deja ouvertes" % cg.limite(_dest(), "XAU/USD"))


def test_la_septieme_position_or_est_bien_refusee(monkeypatch):
    """⛔ La borne existe toujours — on la deplace, on ne la retire pas."""
    from backend.services import correlation_guard as cg

    ouvertes = [("XAU/USD", "buy")] * 6
    monkeypatch.setattr(cg, "positions_ouvertes", lambda _id: list(ouvertes))
    pris, _ = cg.pari_deja_pris(_dest(), "XAU/USD", "buy")
    assert pris is True


def test_une_autre_paire_garde_sa_limite_d_UNE_position(monkeypatch):
    """La derogation est nommee `(admin_live, XAU/USD)` — rien d'autre."""
    from backend.services import correlation_guard as cg

    assert cg.limite(_dest(), "EUR/USD") == 1
    assert cg.limite(_dest("admin_legacy"), "XAU/USD") == 1
