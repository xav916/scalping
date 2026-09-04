"""Horizons servis, découpés PAR DESTINATION (2026-09-04).

Xavier veut ouvrir le 1 jour sur la démo, à condition que le compte réel n'en
subisse rien. C'était impossible :

    MT5_LONG_HORIZON_ROUTES  ->  tout ou rien
    une route reçoit 4h ET 1d ensemble, ou aucun des deux

Retirer `admin_live` de cette liste lui aurait coupé le **4h**, qu'il trade
activement (11 ordres, le dernier le 04/09 à 09:10). Le remède aurait été pire
que le mal.

⛔ **Cette variable ne peut que RESTREINDRE.** Le résultat est l'INTERSECTION
de ce que la route sert déjà et de ce qui est déclaré : déclarer un horizon
qu'elle ne servait pas ne l'ouvre pas. Sans cette règle, une ligne de `.env`
mal comprise ouvrirait un horizon sur l'argent réel — exactement ce que ce
découpage est censé empêcher.

C'est la dernière porte du système à passer par destination ; l'admission, le
plafond journalier, le disjoncteur de rafale et les motifs l'ont déjà fait.
"""
from __future__ import annotations

import pytest


@pytest.fixture()
def routes_longues(monkeypatch):
    """Les deux routes MT5 servent les horizons longs, comme en prod."""
    from backend.services import bridge_destinations as bd
    monkeypatch.setattr(bd, "_mt5_long_horizon_routes",
                        lambda: frozenset({"admin_legacy", "admin_live"}),
                        raising=False)
    monkeypatch.setattr(bd, "_mt5_scalping_horizons",
                        lambda: frozenset({"5min"}), raising=False)
    return bd


def _declarer(monkeypatch, **valeurs):
    from config import settings as st
    for cle, val in valeurs.items():
        monkeypatch.setattr(st, cle, val, raising=False)


# ── Le cas demandé ────────────────────────────────────────────────────────

def test_le_reel_peut_garder_le_4h_sans_le_1d(routes_longues, monkeypatch):
    """⛔ LE test de la demande du 04/09."""
    _declarer(monkeypatch, MT5_BRIDGE_LIVE_ALLOWED_HORIZONS=frozenset({"5min", "4h"}))

    h = routes_longues._mt5_horizons("admin_live")
    assert "4h" in h, "le réel trade activement en 4h — le lui couper serait une régression"
    assert "1d" not in h
    assert "5min" in h


def test_la_demo_garde_tout_quand_seul_le_reel_est_restreint(routes_longues, monkeypatch):
    _declarer(monkeypatch, MT5_BRIDGE_LIVE_ALLOWED_HORIZONS=frozenset({"5min", "4h"}))

    h = routes_longues._mt5_horizons("admin_legacy")
    assert {"5min", "4h", "1d"} <= h


# ── La variable ne peut que RESTREINDRE ───────────────────────────────────

def test_declarer_un_horizon_non_servi_ne_l_OUVRE_pas(routes_longues, monkeypatch):
    """⛔ La garantie qui rend cette variable sûre.

    Si elle pouvait ajouter, une ligne de `.env` mal comprise ouvrirait un
    horizon sur l'argent réel — l'inverse exact de son but.
    """
    monkeypatch.setattr(routes_longues, "_mt5_long_horizon_routes",
                        lambda: frozenset(), raising=False)   # aucune route longue
    _declarer(monkeypatch,
              MT5_BRIDGE_LIVE_ALLOWED_HORIZONS=frozenset({"5min", "4h", "1d"}))

    h = routes_longues._mt5_horizons("admin_live")
    assert h == {"5min"}, "seul le scalping était servi : rien ne doit s'ouvrir"


def test_sans_declaration_rien_ne_change(routes_longues, monkeypatch):
    """⚠️ Le défaut compte : ne rien déclarer conserve le comportement."""
    _declarer(monkeypatch, MT5_BRIDGE_LIVE_ALLOWED_HORIZONS=None)
    assert routes_longues._mt5_horizons("admin_live") == {"5min", "4h", "1d"}


def test_une_declaration_VIDE_ne_ferme_pas_tout(routes_longues, monkeypatch):
    """⚠️ Une intersection vide bloquerait TOUS les pushes de la route.

    C'est le mode de défaillance du kill-switch oublié : zéro push, zéro
    explication. On conserve la base et on le dit dans les logs.
    """
    _declarer(monkeypatch, MT5_BRIDGE_LIVE_ALLOWED_HORIZONS=frozenset({"12h"}))

    h = routes_longues._mt5_horizons("admin_live")
    assert h == {"5min", "4h", "1d"}, "intersection vide -> on garde la base"


def test_chaque_destination_a_sa_propre_declaration(routes_longues, monkeypatch):
    _declarer(monkeypatch,
              MT5_BRIDGE_LIVE_ALLOWED_HORIZONS=frozenset({"5min"}),
              MT5_BRIDGE_LEGACY_ALLOWED_HORIZONS=frozenset({"5min", "1d"}))

    assert routes_longues._mt5_horizons("admin_live") == {"5min"}
    assert routes_longues._mt5_horizons("admin_legacy") == {"5min", "1d"}


def test_une_destination_tierce_n_est_pas_touchee(routes_longues, monkeypatch):
    """Kraken et les autres ne lisent pas ces variables."""
    _declarer(monkeypatch, MT5_BRIDGE_LIVE_ALLOWED_HORIZONS=frozenset({"5min"}))
    assert routes_longues._mt5_horizons("admin_kraken") == {"5min"}


# ── Bout en bout : un setup 1d est refusé côté réel ───────────────────────

def test_un_setup_1d_est_refuse_sur_le_REEL_accepte_sur_la_DEMO(monkeypatch):
    from backend.services import bridge_destinations as bd
    from backend.services import mt5_bridge as mb

    class _Dest:
        def __init__(self, i, h):
            self.destination_id = i
            self.allowed_horizons = h

    class _Setup:
        pair, horizon, direction = "XAU/USD", "1d", "buy"

    reel = _Dest("admin_live", frozenset({"5min", "4h"}))
    demo = _Dest("admin_legacy", frozenset({"5min", "4h", "1d"}))

    assert mb._horizon_rejection(_Setup(), reel) is not None, "le réel doit refuser"
    assert mb._horizon_rejection(_Setup(), demo) is None, "la démo doit accepter"
