"""Test métier end-to-end : modifier les prefs depuis /v2/settings se répercute
sur les dispatches d'un user Premium.

Reproduit le pipeline complet `resolve_destinations` + `_check_rejection` qui
décide si un setup est dispatché à un user donné. Vérifie :

1. **TEST 1** : modifier ``broker_config.min_confidence`` (via l'helper qu'utilise
   le PATCH /api/user/trading-prefs) filtre bien les setups en dessous du seuil.
2. **TEST 2** : modifier ``users.watched_pairs`` (via le PUT /api/user/watched-pairs)
   ajoute/retire bien la paire des destinations résolues.
3. **TEST 3** : modifier les prefs d'un user N'IMPACTE PAS les autres destinations
   (isolation per-user — l'admin_live garde sa propre min_conf env-based).

Exécution :
    pytest backend/tests/test_user_prefs_e2e.py

⚠️ Ce test touche la DB réelle (users id=2 = Cédric). L'état initial est
restauré dans le ``finally`` même en cas d'échec. À ne pas lancer en parallèle
d'un autre process qui modifierait broker_config user_id=2.

Driver : demande Xavier 2026-06-14 « preuve par test métier que le workflow
modification UI → dispatch EA est fonctionnel ».
"""

from types import SimpleNamespace

import pytest

from backend.models.schemas import TradeDirection
from backend.services import users_service
from backend.services.bridge_destinations import resolve_destinations
from backend.services.mt5_bridge import _check_rejection


CEDRIC_USER_ID = 2
CEDRIC_DEST_ID = f"user:{CEDRIC_USER_ID}"
LIVE_DEST_ID = "admin_live"


def _mock_setup(pair: str, confidence: float, direction=TradeDirection.SELL):
    """Setup mock avec attributs minimums pour le pipeline dispatch.

    Direction par défaut = SELL : matche les rows AUTO_EXEC majoritaires en DB.
    Pour ETH/USD : pair_admission_state.direction='sell' = AUTO_EXEC alors que
    'buy' = OBSERVED → le check rejection retournerait `_not_admitted` si BUY.
    """
    return SimpleNamespace(
        pair=pair,
        confidence_score=confidence,
        direction=direction,
        entry_price=1.0,
        stop_loss=0.99,
        take_profit_1=1.02,
        take_profit_2=1.03,
        risk_pips=10,
        reward_pips_1=20,
        reward_pips_2=30,
        risk_reward_1=2.0,
        risk_reward_2=3.0,
        validity_minutes=60,
        verdict_action="TAKE",
        verdict_blockers=None,
        pattern=None,
    )


def _dest_accepts(setup, destination_id: str) -> tuple[bool, str | None]:
    """Reproduit le pipeline réel : resolve_destinations puis _check_rejection.

    Retourne (accepté, reason_code). Accepté=True signifie que le setup est
    bien dispatché vers cette destination.
    """
    dests = resolve_destinations(setup)
    matching = next((d for d in dests if d.destination_id == destination_id), None)
    if matching is None:
        return False, "_no_dest"
    reason = _check_rejection(setup, matching)
    return (reason is None), reason


@pytest.fixture
def cedric_backup():
    """Sauvegarde + restaure l'état initial de Cédric (broker_config + watched_pairs).

    Évite toute pollution de la DB de test si un test plante en milieu de course.
    """
    initial_cfg = users_service.get_broker_config(CEDRIC_USER_ID)
    initial_pairs = users_service.get_watched_pairs(CEDRIC_USER_ID)
    yield {
        "min_confidence": initial_cfg.get("min_confidence"),
        "watched_pairs": list(initial_pairs),
    }
    # Restore (toujours, même en cas d'exception du test)
    if initial_cfg.get("min_confidence") is not None:
        users_service.update_min_confidence(
            CEDRIC_USER_ID, initial_cfg["min_confidence"]
        )
    users_service.update_watched_pairs(CEDRIC_USER_ID, initial_pairs)


def test_min_confidence_filters_dispatches(cedric_backup):
    """TEST 1 : modifier min_confidence via l'API filtre bien les setups."""
    # Seuil 70 : setup conf 65 rejeté, conf 75 accepté
    users_service.update_min_confidence(CEDRIC_USER_ID, 70)
    accepted_low, reason_low = _dest_accepts(_mock_setup("ETH/USD", 65), CEDRIC_DEST_ID)
    accepted_high, reason_high = _dest_accepts(_mock_setup("ETH/USD", 75), CEDRIC_DEST_ID)
    assert not accepted_low and reason_low == "below_confidence", \
        f"ETH conf=65 devrait être rejeté (below_confidence), got: {reason_low}"
    assert accepted_high, f"ETH conf=75 devrait être accepté, got: {reason_high}"

    # Baisser le seuil à 60 : conf 65 doit maintenant passer
    users_service.update_min_confidence(CEDRIC_USER_ID, 60)
    accepted_now, reason_now = _dest_accepts(_mock_setup("ETH/USD", 65), CEDRIC_DEST_ID)
    assert accepted_now, f"Après baisse seuil à 60, ETH conf=65 devrait passer, got: {reason_now}"

    # Monter le seuil à 85 : conf 75 doit maintenant être rejeté
    users_service.update_min_confidence(CEDRIC_USER_ID, 85)
    rejected_now, reason_high2 = _dest_accepts(_mock_setup("ETH/USD", 75), CEDRIC_DEST_ID)
    assert not rejected_now and reason_high2 == "below_confidence", \
        f"Après hausse seuil à 85, ETH conf=75 devrait être rejeté, got: {reason_high2}"


def test_watched_pairs_filters_dispatches(cedric_backup):
    """TEST 2 : retirer une paire de watched_pairs la sort des destinations."""
    # S'assurer du seuil pour ce test
    users_service.update_min_confidence(CEDRIC_USER_ID, 70)

    # Avec SOL dans watched_pairs (état initial : Cédric a 20+ paires incl. SOL)
    if "SOL/USD" not in users_service.get_watched_pairs(CEDRIC_USER_ID):
        pairs_with_sol = users_service.get_watched_pairs(CEDRIC_USER_ID) + ["SOL/USD"]
        users_service.update_watched_pairs(CEDRIC_USER_ID, pairs_with_sol)

    accepted_with, _ = _dest_accepts(_mock_setup("SOL/USD", 80), CEDRIC_DEST_ID)
    assert accepted_with, "SOL/USD conf=80 devrait être accepté quand SOL dans watched_pairs"

    # Retirer SOL/USD via l'helper qu'utilise PUT /api/user/watched-pairs
    current = users_service.get_watched_pairs(CEDRIC_USER_ID)
    users_service.update_watched_pairs(
        CEDRIC_USER_ID, [p for p in current if p != "SOL/USD"]
    )
    rejected, reason = _dest_accepts(_mock_setup("SOL/USD", 80), CEDRIC_DEST_ID)
    assert not rejected, f"SOL/USD retiré → ne doit plus être dispatché, got reason: {reason}"

    # Re-ajouter SOL/USD
    users_service.update_watched_pairs(CEDRIC_USER_ID, current)
    accepted_again, _ = _dest_accepts(_mock_setup("SOL/USD", 80), CEDRIC_DEST_ID)
    assert accepted_again, "SOL/USD re-ajouté → doit redevenir dispatché"


def test_user_pref_isolation_from_admin_live(cedric_backup):
    """TEST 3 : modifier les prefs d'un user n'impacte pas admin_live.

    Admin_live a sa propre min_confidence (env MT5_BRIDGE_LIVE_MIN_CONFIDENCE,
    actuellement 50). Si Cédric passe à 90 (très strict), Cédric ne reçoit plus
    un setup conf=60, mais admin_live le reçoit toujours.
    """
    users_service.update_min_confidence(CEDRIC_USER_ID, 90)
    setup = _mock_setup("ETH/USD", 60)

    cedric_accepted, cedric_reason = _dest_accepts(setup, CEDRIC_DEST_ID)
    live_accepted, live_reason = _dest_accepts(setup, LIVE_DEST_ID)

    assert not cedric_accepted and cedric_reason == "below_confidence", \
        f"Cédric min_conf=90 devrait rejeter conf=60, got: {cedric_reason}"
    assert live_accepted, \
        f"admin_live (min_conf env=50) devrait accepter conf=60 indépendamment de Cédric, got: {live_reason}"
