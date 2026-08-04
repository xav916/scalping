"""Whitelist de patterns paramétrable par destination (2026-08-04).

`MT5_BRIDGE_ALLOWED_PATTERNS` était **globale** : impossible de garder
`range_bounce` sur l'argent réel MT5 tout en ouvrant une destination
d'observation à espérance négative assumée, où l'on cherche du volume pour
valider la chaîne d'exécution.

Sémantique de `BridgeConfig.allowed_patterns` :

    None          -> hérite du global (comportement historique)
    frozenset()   -> AUCUN filtre pattern pour cette destination
    {"a", "b"}    -> cette liste, pour cette destination seulement

⚠️ `None` et `frozenset()` doivent être distingués : les confondre ferait
hériter du global là où on voulait désactiver, ou l'inverse.
"""
from __future__ import annotations

from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from backend.models.schemas import PatternType
from backend.services import mt5_bridge


RANGE_BOUNCE = frozenset({"range_bounce_up", "range_bounce_down"})


@pytest.fixture(autouse=True)
def _neutralise_filtres_amont(monkeypatch):
    monkeypatch.setattr(mt5_bridge, "_STAR_PAIRS_SET", frozenset({"ETH/USD"}))


def _dest(allowed_patterns):
    return NS(destination_id="admin_kraken", user_id=None, min_confidence=0.0,
              allowed_asset_classes=frozenset({"crypto"}),
              excluded_pairs=frozenset(), bridge_url="", auto_exec_enabled=True,
              extra_pairs_allowed=frozenset(), allowed_patterns=allowed_patterns)


def _setup(pattern):
    return NS(pair="ETH/USD", direction=NS(value="sell"), confidence_score=90,
              entry_price=3500.0, stop_loss=3530.0, take_profit_1=3446.0,
              take_profit_2=None, verdict_action="TAKE", verdict_blockers=[],
              is_simulated=False, pattern=NS(pattern=NS(value=pattern)))


def _check(pattern, dest_patterns, global_patterns=RANGE_BOUNCE):
    with patch("backend.services.mt5_bridge.is_configured", return_value=True), \
         patch("backend.services.mt5_bridge.is_market_open_for_destination", return_value=True), \
         patch("backend.services.mt5_bridge._count_open_trades_for_pair", return_value=0), \
         patch("backend.services.mt5_bridge.MT5_BRIDGE_ALLOWED_PATTERNS", global_patterns):
        return mt5_bridge._check_rejection(_setup(pattern), _dest(dest_patterns))


# --- les trois sémantiques -------------------------------------------------

def test_none_herite_du_global():
    """Comportement historique préservé : sans override, le global s'applique."""
    assert _check("breakout_down", None) == "pattern_not_allowed"
    assert _check("range_bounce_down", None) is None


def test_frozenset_vide_desactive_le_filtre():
    """Le cas Kraken : on veut du volume, tous patterns acceptés."""
    assert _check("breakout_down", frozenset()) is None
    assert _check("momentum_down", frozenset()) is None
    assert _check("engulfing_bearish", frozenset()) is None


def test_liste_propre_a_la_destination():
    only_breakout = frozenset({"breakout_down"})
    assert _check("breakout_down", only_breakout) is None
    assert _check("range_bounce_down", only_breakout) == "pattern_not_allowed"


def test_none_et_vide_ne_sont_pas_confondus():
    """LE piège : `if dest.allowed_patterns:` traiterait les deux pareil."""
    assert _check("breakout_down", None) == "pattern_not_allowed"
    assert _check("breakout_down", frozenset()) is None


# --- l'isolation entre destinations ---------------------------------------

def test_une_destination_permissive_nouvre_pas_les_autres():
    """Kraken sans filtre ne doit rien changer pour l'argent réel MT5."""
    kraken = _dest(frozenset())
    live = NS(destination_id="admin_live", user_id=None, min_confidence=0.0,
              allowed_asset_classes=frozenset({"crypto"}), excluded_pairs=frozenset(),
              bridge_url="", auto_exec_enabled=True, extra_pairs_allowed=frozenset(),
              allowed_patterns=None)
    setup = _setup("momentum_down")
    with patch("backend.services.mt5_bridge.is_configured", return_value=True), \
         patch("backend.services.mt5_bridge.is_market_open_for_destination", return_value=True), \
         patch("backend.services.mt5_bridge._count_open_trades_for_pair", return_value=0), \
         patch("backend.services.mt5_bridge.MT5_BRIDGE_ALLOWED_PATTERNS", RANGE_BOUNCE):
        assert mt5_bridge._check_rejection(setup, kraken) is None
        assert mt5_bridge._check_rejection(setup, live) == "pattern_not_allowed"


def test_le_chemin_legacy_sans_destination_utilise_le_global():
    """`_should_push` mono-tenant n'a pas de dest : le global doit s'appliquer."""
    with patch("backend.services.mt5_bridge.is_configured", return_value=True), \
         patch("backend.services.mt5_bridge.is_market_open_for_destination", return_value=True), \
         patch("backend.services.mt5_bridge._count_open_trades_for_pair", return_value=0), \
         patch("backend.services.mt5_bridge.MT5_BRIDGE_MIN_CONFIDENCE", 0), \
         patch("backend.services.mt5_bridge.MT5_BRIDGE_ALLOWED_PATTERNS", RANGE_BOUNCE):
        assert mt5_bridge._check_rejection(_setup("breakout_down")) == "pattern_not_allowed"


# --- le réglage ------------------------------------------------------------

def test_reglage_absent_vaut_none(monkeypatch):
    """Ne PAS définir la variable doit hériter, pas désactiver."""
    import importlib, config.settings as st
    monkeypatch.delenv("KRAKEN_BRIDGE_ALLOWED_PATTERNS", raising=False)
    importlib.reload(st)
    try:
        assert st.KRAKEN_BRIDGE_ALLOWED_PATTERNS is None
    finally:
        importlib.reload(st)


def test_reglage_vide_desactive(monkeypatch):
    """Définir la variable à vide doit désactiver le filtre, pas hériter."""
    import importlib, config.settings as st
    monkeypatch.setenv("KRAKEN_BRIDGE_ALLOWED_PATTERNS", "")
    importlib.reload(st)
    try:
        assert st.KRAKEN_BRIDGE_ALLOWED_PATTERNS == frozenset()
    finally:
        monkeypatch.delenv("KRAKEN_BRIDGE_ALLOWED_PATTERNS", raising=False)
        importlib.reload(st)


def test_reglage_avec_liste(monkeypatch):
    import importlib, config.settings as st
    monkeypatch.setenv("KRAKEN_BRIDGE_ALLOWED_PATTERNS", " Breakout_Down , momentum_down ")
    importlib.reload(st)
    try:
        assert st.KRAKEN_BRIDGE_ALLOWED_PATTERNS == frozenset({"breakout_down", "momentum_down"})
    finally:
        monkeypatch.delenv("KRAKEN_BRIDGE_ALLOWED_PATTERNS", raising=False)
        importlib.reload(st)


def test_la_destination_kraken_porte_le_reglage(monkeypatch):
    """Le câblage réel : settings -> BridgeConfig."""
    import config.settings as st
    from backend.services import bridge_destinations as bd
    monkeypatch.setattr(st, "KRAKEN_BRIDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(st, "KRAKEN_BRIDGE_URL", "http://x", raising=False)
    monkeypatch.setattr(st, "KRAKEN_BRIDGE_ALLOWED_PATTERNS", frozenset(), raising=False)
    cfg = bd._admin_kraken_destination()
    assert cfg is not None and cfg.allowed_patterns == frozenset()


@pytest.mark.parametrize("pattern", [p.value for p in PatternType])
def test_tous_les_patterns_passent_sans_filtre(pattern):
    assert _check(pattern, frozenset()) is None
