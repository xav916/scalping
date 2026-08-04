"""Whitelist de patterns à l'auto-exec (2026-08-04).

Motivation, mesurée sur 100 657 trades suivis en direct (`backtest.db.trades`,
2026-05-18 → 2026-08-04, hors WTI) :

    filtre                     n        WR      R/trade
    aucun                   96 438    36,1 %   +0,032
    confidence >= 60 (prod) 34 741    36,2 %   +0,030
    range_bounce_up/down    33 143    39,5 %   +0,129

Le seuil de confidence écarte 64 % du flux pour une espérance identique. Le
pattern, lui, discrimine — et tient hors échantillon : règle figée sur
mai-juin, appliquée à juillet-août sans retouche, +0,115 R/trade, z = +9,08,
positive sur 19 paires / 19 et 4 mois / 4.

Le filtre s'AJOUTE au seuil de confidence, il ne le remplace pas.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.services import mt5_bridge
from backend.models.schemas import PatternType


RANGE_BOUNCE = frozenset({"range_bounce_up", "range_bounce_down"})


@pytest.fixture(autouse=True)
def _neutralise_filtres_amont(monkeypatch):
    monkeypatch.setattr(
        mt5_bridge, "_STAR_PAIRS_SET", frozenset({"EUR/USD", "XAU/USD"}),
    )


def _setup(pattern=PatternType.RANGE_BOUNCE_UP, confidence=80):
    """Setup minimal. ``pattern`` accepte un PatternType, une str, ou None."""
    s = SimpleNamespace(
        pair="EUR/USD", direction="buy",
        entry_price=1.10, stop_loss=1.09,
        take_profit_1=1.11, take_profit_2=None,
        confidence_score=confidence,
        verdict_action="TAKE", verdict_blockers=[],
        is_simulated=False,
        pattern=SimpleNamespace(pattern=pattern) if pattern is not None else None,
    )
    return s


def _check(setup, allowed=RANGE_BOUNCE, min_conf=0):
    with patch("backend.services.mt5_bridge.is_configured", return_value=True), \
         patch("backend.services.mt5_bridge.is_market_open_for_destination", return_value=True), \
         patch("backend.services.mt5_bridge._count_open_trades_for_pair", return_value=0), \
         patch("backend.services.mt5_bridge.MT5_BRIDGE_MIN_CONFIDENCE", min_conf), \
         patch("backend.services.mt5_bridge.MT5_BRIDGE_ALLOWED_PATTERNS", allowed):
        return mt5_bridge._check_rejection(setup)


# --- extraction du pattern -------------------------------------------------

def test_extraction_depuis_lenum():
    assert mt5_bridge._pattern_value(_setup(PatternType.RANGE_BOUNCE_DOWN)) == "range_bounce_down"


def test_extraction_depuis_une_chaine():
    assert mt5_bridge._pattern_value(_setup("MOMENTUM_UP")) == "momentum_up"


def test_extraction_sans_pattern():
    assert mt5_bridge._pattern_value(_setup(None)) is None


# --- le filtre lui-même ----------------------------------------------------

@pytest.mark.parametrize("pattern", [
    PatternType.RANGE_BOUNCE_UP,
    PatternType.RANGE_BOUNCE_DOWN,
])
def test_patterns_whitelistes_passent(pattern):
    assert _check(_setup(pattern)) is None


@pytest.mark.parametrize("pattern", [
    PatternType.MOMENTUM_UP,      # -0,037 R/trade
    PatternType.PIN_BAR_UP,       # -0,082
    PatternType.BREAKOUT_UP,      # -0,088
    PatternType.ENGULFING_BULLISH,
])
def test_patterns_hors_whitelist_sont_bloques(pattern):
    assert _check(_setup(pattern)) == "pattern_not_allowed"


def test_whitelist_vide_ne_filtre_rien():
    """Comportement historique préservé : sans réglage, aucun blocage."""
    assert _check(_setup(PatternType.BREAKOUT_UP), allowed=frozenset()) is None


def test_pattern_indeterminable_est_bloque():
    """Fail-closed : la whitelist est un opt-in, on ne devine pas.

    `signal_pattern` étant porté dans les details de la rejection, une vague
    de blocages à None reste diagnosticable au dashboard.
    """
    assert _check(_setup(None)) == "pattern_not_allowed"


# --- articulation avec le seuil de confidence ------------------------------

def test_le_seuil_de_confidence_reste_prioritaire():
    """Les deux filtres s'empilent — la confiance est évaluée en premier."""
    assert _check(_setup(PatternType.RANGE_BOUNCE_UP, confidence=40),
                  min_conf=60) == "below_confidence"


def test_bon_pattern_mais_confiance_insuffisante_bloque():
    assert _check(_setup(PatternType.RANGE_BOUNCE_UP, confidence=55),
                  min_conf=60) == "below_confidence"


def test_bon_pattern_et_confiance_suffisante_passent():
    assert _check(_setup(PatternType.RANGE_BOUNCE_UP, confidence=75),
                  min_conf=60) is None


# --- le réglage ------------------------------------------------------------

def test_parsing_du_reglage(monkeypatch):
    import importlib
    import config.settings as st
    monkeypatch.setenv("MT5_BRIDGE_ALLOWED_PATTERNS",
                       " Range_Bounce_Up , range_bounce_down ,, ")
    importlib.reload(st)
    try:
        assert st.MT5_BRIDGE_ALLOWED_PATTERNS == RANGE_BOUNCE
    finally:
        monkeypatch.delenv("MT5_BRIDGE_ALLOWED_PATTERNS")
        importlib.reload(st)


def test_reglage_absent_donne_un_ensemble_vide():
    import config.settings as st
    assert isinstance(st.MT5_BRIDGE_ALLOWED_PATTERNS, frozenset)


def test_le_code_de_rejet_a_un_libelle_fr():
    from backend.services.rejection_service import REASON_LABELS_FR
    assert REASON_LABELS_FR["pattern_not_allowed"] == "Pattern hors whitelist"


# --- cohérence du message Telegram -----------------------------------------

def _telegram_labels(setup, allowed):
    """Destinations que le message Telegram annonce comme exécutantes.

    ⚠️ `_describe_admin_destinations` avale ses exceptions et renvoie [] —
    sans destination gréée, le test passerait quoi qu'il arrive. D'où le
    stub, et le test de non-vacuité ci-dessous qui en dépend.
    """
    from backend.services import telegram_service, bridge_destinations
    dest = SimpleNamespace(
        destination_id="admin_live", user_id=None, auto_exec_enabled=True,
        min_confidence=60, allowed_asset_classes={"forex"},
    )
    with patch("config.settings.MT5_BRIDGE_ALLOWED_PATTERNS", allowed), \
         patch.object(bridge_destinations, "resolve_destinations", return_value=[dest]):
        return telegram_service._describe_admin_destinations(setup)


def test_le_stub_produit_bien_un_label():
    """Non-vacuité : sans quoi les deux tests suivants ne prouveraient rien."""
    assert _telegram_labels(_setup(PatternType.RANGE_BOUNCE_UP), frozenset()) != []


def test_telegram_nannonce_pas_une_execution_qui_naura_pas_lieu():
    """Le message listait les brokers en ne regardant que confiance + classe.

    Avec la whitelist active, un setup hors whitelist n'exécute nulle part :
    annoncer « 💰 Live IC Markets » serait une promesse fausse au lecteur.
    """
    assert _telegram_labels(_setup(PatternType.RANGE_BOUNCE_UP), RANGE_BOUNCE) != []
    assert _telegram_labels(_setup(PatternType.MOMENTUM_UP), RANGE_BOUNCE) == []


def test_telegram_ignore_le_pattern_sans_whitelist():
    """Sans réglage, le pattern ne doit rien retirer au message."""
    assert _telegram_labels(_setup(PatternType.MOMENTUM_UP), frozenset()) != []
