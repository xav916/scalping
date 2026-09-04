"""Motifs supplémentaires ouverts sur la DÉMO seule (2026-09-04).

Xavier veut ouvrir la stratégie « retour au POC » à tous les horizons, sans
rien exclure.

⛔ **Le passage par `MT5_BRIDGE_PATTERN_OVERRIDES` était impossible** : cette
table est GLOBALE et rend la main AVANT la couche destination. Y ajouter le
motif pour le 4h de `XAU/USD` l'aurait ouvert sur le **compte réel** — soit
exactement ce que la certification d'une heure plus tôt interdisait.

D'où une couche **additive par destination**, appliquée APRÈS la cascade :

    (paire, horizon)  ->  destination  ->  règle globale     [ + extras ]

🔑 Additive et non substitutive, pour deux raisons :

  1. Elle ne peut RIEN retirer. Une liste qui remplace peut fermer une porte
     par omission — c'est arrivé une heure plus tôt : `LEGACY_ALLOWED_PATTERNS`
     obligeait à recopier `range_bounce`, faute de quoi la démo cessait de
     trader ses motifs existants.
  2. Elle s'applique même quand une surcharge par paire existe, ce qui est
     précisément le cas qu'on veut ouvrir.
"""
from __future__ import annotations

import pytest


class _Setup:
    def __init__(self, pair="XAU/USD", horizon="4h"):
        self.pair = pair
        self.horizon = horizon


class _Dest:
    def __init__(self, dest_id, allowed=None, extras=None):
        self.destination_id = dest_id
        self.allowed_patterns = allowed
        self.extra_patterns = extras


@pytest.fixture()
def bridge(monkeypatch):
    from backend.services import mt5_bridge as mb
    monkeypatch.setattr(mb, "MT5_BRIDGE_ALLOWED_PATTERNS",
                        frozenset({"range_bounce_up"}), raising=False)
    monkeypatch.setattr(mb, "MT5_BRIDGE_PATTERN_OVERRIDES",
                        {"XAU/USD": {"4h": ["momentum_up", "breakout_up"]}},
                        raising=False)
    return mb


# ── Le cas qui motive tout ────────────────────────────────────────────────

def test_les_extras_s_ajoutent_MALGRE_une_surcharge_par_paire(bridge):
    """XAU 4h a une surcharge : c'est exactement là qu'il faut pouvoir ouvrir."""
    demo = _Dest("admin_legacy", extras=frozenset({"poc_return_up"}))
    autorises = bridge._patterns_autorises(_Setup("XAU/USD", "4h"), demo)

    assert "poc_return_up" in autorises
    assert "momentum_up" in autorises, "la surcharge existante doit survivre"


def test_le_compte_REEL_reste_ferme_sur_la_meme_paire(bridge):
    """⛔ Le test qui protège la certification.

    Même paire, même horizon, même surcharge — mais pas d'extras déclarés.
    """
    reel = _Dest("admin_live")
    autorises = bridge._patterns_autorises(_Setup("XAU/USD", "4h"), reel)

    assert "poc_return_up" not in autorises
    assert "momentum_up" in autorises


# ── La couche n'enlève jamais rien ────────────────────────────────────────

def test_les_extras_s_ajoutent_a_la_regle_GLOBALE(bridge):
    """Sur une paire sans surcharge, la base est la liste globale."""
    demo = _Dest("admin_legacy", extras=frozenset({"poc_return_up"}))
    autorises = bridge._patterns_autorises(_Setup("WTI/USD", "5min"), demo)

    assert autorises == {"range_bounce_up", "poc_return_up"}


def test_les_extras_s_ajoutent_a_une_liste_de_DESTINATION(bridge):
    demo = _Dest("admin_legacy",
                 allowed=frozenset({"engulfing_bullish"}),
                 extras=frozenset({"poc_return_up"}))
    autorises = bridge._patterns_autorises(_Setup("WTI/USD", "1d"), demo)

    assert autorises == {"engulfing_bullish", "poc_return_up"}


def test_sans_extras_rien_ne_change(bridge):
    """⚠️ Le défaut compte : ne rien déclarer ne doit rien ouvrir."""
    demo = _Dest("admin_legacy")
    assert bridge._patterns_autorises(_Setup("XAU/USD", "4h"), demo) == {
        "momentum_up", "breakout_up"}


def test_une_destination_absente_ne_plante_pas(bridge):
    assert bridge._patterns_autorises(_Setup("WTI/USD", "5min"), None) == {
        "range_bounce_up"}


# ── Le câblage réel ───────────────────────────────────────────────────────

def test_la_demo_lit_la_variable_d_environnement(monkeypatch):
    from backend.services import bridge_destinations as bd
    from backend.services import mt5_bridge as mb
    from config import settings as st

    monkeypatch.setattr(mb, "MT5_BRIDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(mb, "MT5_BRIDGE_URL", "http://demo", raising=False)
    monkeypatch.setattr(mb, "MT5_BRIDGE_API_KEY", "cle", raising=False)
    monkeypatch.setattr(st, "MT5_BRIDGE_LEGACY_EXTRA_PATTERNS",
                        frozenset({"poc_return_up", "poc_return_down"}),
                        raising=False)

    demo = bd._admin_legacy_destination()
    assert demo.extra_patterns == {"poc_return_up", "poc_return_down"}


def test_le_reel_n_a_JAMAIS_d_extras(monkeypatch):
    """⛔ Aucune variable ne doit pouvoir ouvrir un motif sur l'argent réel
    par ce chemin — la couche additive est réservée à la démonstration."""
    from backend.services import bridge_destinations as bd
    from config import settings as st

    monkeypatch.setattr(st, "MT5_BRIDGE_LIVE_ENABLED", True, raising=False)
    monkeypatch.setattr(st, "MT5_BRIDGE_LIVE_URL", "http://live", raising=False)
    monkeypatch.setattr(st, "MT5_BRIDGE_LIVE_API_KEY", "cle", raising=False)
    monkeypatch.setattr(st, "MT5_BRIDGE_LIVE_MIN_CONFIDENCE", 42.0, raising=False)
    monkeypatch.setattr(st, "MT5_BRIDGE_LIVE_ALLOWED_ASSET_CLASSES",
                        ["forex", "metal", "energy"], raising=False)

    live = bd._admin_live_destination()
    assert getattr(live, "extra_patterns", None) is None
