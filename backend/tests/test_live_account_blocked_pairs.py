"""Post-audit 2026-11-13 : la paire XAG/USD ne peut atteindre l'argent réel.

70% des pertes du compte réel IC Markets viennent de XAG/USD (737 EUR /
115 trades vs -1046 EUR cumulés). Blocklist code-level : la paire est
exclue de toutes les destinations d'argent réel, et aucune env var ne
peut lever le verrou.

Test valide le comportement du filtre dans ``resolve_destinations``.
"""
from __future__ import annotations

import types

from backend.services import bridge_destinations as bd


def _make_setup(pair: str, direction: str = "buy"):
    return types.SimpleNamespace(
        pair=pair,
        direction=types.SimpleNamespace(value=direction),
        asset_class="metal" if pair.startswith(("XAU", "XAG")) else "forex",
        confidence_score=80.0,
        pattern="momentum_up",
        horizon="15min",
    )


def test_xag_est_dans_blocklist_module():
    """La constante existe et contient XAG/USD."""
    assert "XAG/USD" in bd.LIVE_ACCOUNT_BLOCKED_PAIRS


def test_xag_ne_resout_PAS_vers_admin_live(monkeypatch):
    """Si XAG/USD, même avec admin_live configuré, la destination est retirée."""
    from config import settings as st
    monkeypatch.setattr(st, "MT5_BRIDGE_LIVE_ENABLED", True, raising=False)
    monkeypatch.setattr(st, "MT5_BRIDGE_LIVE_URL",
                        "http://100.74.160.72:8788", raising=False)
    monkeypatch.setattr(st, "MT5_BRIDGE_LIVE_API_KEY",
                        "test-key", raising=False)
    monkeypatch.setattr(st, "MT5_BRIDGE_LIVE_MIN_CONFIDENCE",
                        42.0, raising=False)
    monkeypatch.setattr(st, "MT5_BRIDGE_LIVE_ALLOWED_ASSET_CLASSES",
                        frozenset({"metal", "forex"}), raising=False)

    # Autoriser live via REM-002-LIVE pour que _live_destination() retourne
    # une config non-None (test isolé du double verrou).
    from backend.services import deployment_manifest as dm
    import json
    tmp_manifest = {
        "git_commit_sha": "a" * 40, "git_branch": "main", "git_dirty": False,
        "build_timestamp": "2026-11-13T22:00:00+00:00",
        "configuration_hash": "feedc0de12345678",
        "build_environment": "pytest", "manifest_schema": 1,
    }
    import tempfile, pathlib
    tf = pathlib.Path(tempfile.mkdtemp()) / "m.json"
    tf.write_text(json.dumps(tmp_manifest), encoding="utf-8")
    te = tf.parent / "e.json"
    monkeypatch.setenv("DEPLOYMENT_MANIFEST_PATH", str(tf))
    monkeypatch.setenv("GLOBAL_EXECUTION_STATE_PATH", str(te))
    monkeypatch.delenv("EXPECTED_GIT_COMMIT", raising=False)
    from backend.services import global_execution_switch as ges
    ges.authorize_live("test blocklist", by="pytest")

    # Vérifier qu'admin_live est bien construit par ailleurs
    admin_live = bd._admin_live_destination()
    assert admin_live is not None, "sanity: admin_live doit exister sinon test inutile"

    # Pour un setup XAG/USD, aucune destination d'argent réel ne doit sortir
    setup = _make_setup("XAG/USD")
    destinations = bd.resolve_destinations(setup)

    from backend.services.destinations_registry import is_real_money
    real_destinations = [
        d for d in destinations
        if is_real_money(getattr(d, "destination_id", None))
    ]
    assert real_destinations == [], (
        f"XAG/USD ne doit JAMAIS atteindre une destination d'argent réel. "
        f"Trouvé : {[d.destination_id for d in real_destinations]}"
    )


def test_xau_reste_autorise_vers_admin_live():
    """XAU/USD n'est PAS dans la blocklist, il peut toujours aller en réel."""
    assert "XAU/USD" not in bd.LIVE_ACCOUNT_BLOCKED_PAIRS
