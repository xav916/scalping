"""REM-002-LIVE — double verrou pour la destination compte RÉEL (admin_live).

Scénarios couverts :

1. authorize_live refuse si l'intégrité du manifest n'est pas OK
2. live_destination_authorized DENY par défaut (state vide)
3. live_destination_authorized DENY si état illisible (fail-closed)
4. live_destination_authorized DENY si fingerprint mismatch (après redeploy)
5. live_destination_authorized DENY si expiration passée
6. live_destination_authorized DENY si expiration invalide (fail-closed)
7. live_destination_authorized ALLOW une fois autorise + fingerprint match
8. revoke_live_authorization coupe immédiatement
9. bridge_destinations._live_destination() ignore la destination si pas autorisé
10. bridge_destinations._live_destination() retourne la config une fois autorisé

⛔ Ces tests sont essentiels : la logique fail-closed de REM-002-LIVE est
la seule chose qui empêche qu'un simple `MT5_BRIDGE_LIVE_ENABLED=true` dans
`.env` envoie à nouveau des ordres au compte réel sans signature explicite.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import deployment_manifest as dm
from backend.services import global_execution_switch as ges


MANIFEST_VALIDE = {
    "git_commit_sha": "a" * 40,
    "git_branch": "main",
    "git_dirty": False,
    "build_timestamp": "2026-11-13T22:00:00+00:00",
    "configuration_hash": "feedc0de12345678",
    "build_environment": "pytest",
    "manifest_schema": 1,
}


@pytest.fixture
def bac(tmp_path, monkeypatch):
    """Sandbox : manifest + état du switch sous contrôle, isolés du filesystem réel."""
    manifest = tmp_path / "m.json"
    etat = tmp_path / "e.json"
    monkeypatch.setenv("DEPLOYMENT_MANIFEST_PATH", str(manifest))
    monkeypatch.setenv("GLOBAL_EXECUTION_STATE_PATH", str(etat))
    monkeypatch.delenv("EXPECTED_GIT_COMMIT", raising=False)
    return {"manifest": manifest, "etat": etat}


def _ecrire_manifest(bac, **over):
    d = dict(MANIFEST_VALIDE)
    d.update(over)
    bac["manifest"].write_text(json.dumps(d), encoding="utf-8")
    return d


def _ecrire_etat(bac, **champs):
    bac["etat"].write_text(json.dumps(champs), encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════
# 1. authorize_live : garde-fou sur l'intégrité
# ══════════════════════════════════════════════════════════════════════


def test_authorize_live_REFUSE_si_manifest_absent(bac):
    res = ges.authorize_live("motif", by="Xavier")
    assert res["ok"] is False
    assert res["reason"] == ges.DEPLOYMENT_INTEGRITY


def test_authorize_live_REFUSE_si_manifest_corrompu(bac):
    bac["manifest"].write_text("{pas du json", encoding="utf-8")
    res = ges.authorize_live("motif", by="Xavier")
    assert res["ok"] is False


# ══════════════════════════════════════════════════════════════════════
# 2-6. live_destination_authorized : fail-closed par défaut
# ══════════════════════════════════════════════════════════════════════


def test_live_pas_autorise_par_defaut_etat_absent(bac):
    """Fail-closed : aucun état = pas de live."""
    _ecrire_manifest(bac)
    allowed, code, detail = ges.live_destination_authorized()
    assert allowed is False
    assert code in (ges.STATE_MISSING, ges.LIVE_NOT_AUTHORIZED)


def test_live_pas_autorise_etat_vide(bac):
    _ecrire_manifest(bac)
    _ecrire_etat(bac)
    allowed, code, _ = ges.live_destination_authorized()
    assert allowed is False
    assert code == ges.LIVE_NOT_AUTHORIZED


def test_live_pas_autorise_si_etat_illisible(bac):
    """État non-JSON → fail-closed."""
    _ecrire_manifest(bac)
    bac["etat"].write_text("{pas du json", encoding="utf-8")
    allowed, code, _ = ges.live_destination_authorized()
    assert allowed is False
    assert code == ges.STATE_UNREADABLE


def test_live_DENY_si_fingerprint_different_de_running(bac):
    """Autorisation faite pour un ancien build → nouvelle version = DENY."""
    _ecrire_manifest(bac)
    _ecrire_etat(
        bac,
        live_authorized=True,
        live_authorized_fingerprint="old_fingerprint_12345",
        live_authorized_by="Xavier",
        live_authorized_reason="test",
    )
    allowed, code, _ = ges.live_destination_authorized()
    assert allowed is False
    assert code == ges.LIVE_FINGERPRINT_MISMATCH


def test_live_DENY_si_expiration_passee(bac):
    _ecrire_manifest(bac)
    empreinte = dm.fingerprint()
    passe = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    _ecrire_etat(
        bac,
        live_authorized=True,
        live_authorized_fingerprint=empreinte,
        live_authorized_by="Xavier",
        live_authorized_reason="test",
        live_authorized_expires_at=passe,
    )
    allowed, code, _ = ges.live_destination_authorized()
    assert allowed is False
    assert code == ges.LIVE_EXPIRED


def test_live_DENY_si_expiration_malformee(bac):
    _ecrire_manifest(bac)
    empreinte = dm.fingerprint()
    _ecrire_etat(
        bac,
        live_authorized=True,
        live_authorized_fingerprint=empreinte,
        live_authorized_by="Xavier",
        live_authorized_reason="test",
        live_authorized_expires_at="pas-une-date",
    )
    allowed, code, _ = ges.live_destination_authorized()
    assert allowed is False
    assert code == ges.LIVE_EXPIRED


# ══════════════════════════════════════════════════════════════════════
# 7. ALLOW lorsque tout matche
# ══════════════════════════════════════════════════════════════════════


def test_live_ALLOW_apres_authorize_sur_le_bon_fingerprint(bac):
    _ecrire_manifest(bac)
    res = ges.authorize_live(
        "test authorize", by="Xavier (delegation)",
    )
    assert res["ok"] is True
    allowed, code, _ = ges.live_destination_authorized()
    assert allowed is True
    assert code == ges.LIVE_AUTHORIZED


def test_live_ALLOW_avec_expiration_future(bac):
    _ecrire_manifest(bac)
    futur = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    ges.authorize_live("test", by="Xavier", expires_at=futur)
    allowed, _, _ = ges.live_destination_authorized()
    assert allowed is True


# ══════════════════════════════════════════════════════════════════════
# Blackout automatique 24h (plafond absolu)
# ══════════════════════════════════════════════════════════════════════


def test_live_DENY_apres_24h_meme_sans_expires_at(bac, monkeypatch):
    """L'oubli de révoquer ne doit PAS maintenir le live éternellement."""
    _ecrire_manifest(bac)
    empreinte = dm.fingerprint()
    # Autorisation posée il y a 25h, sans expires_at explicite.
    vieux = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    _ecrire_etat(
        bac,
        live_authorized=True,
        live_authorized_fingerprint=empreinte,
        live_authorized_at=vieux,
        live_authorized_by="Xavier",
        live_authorized_reason="old session",
    )
    allowed, code, _ = ges.live_destination_authorized()
    assert allowed is False
    assert code == ges.LIVE_MAX_AGE_EXCEEDED


def test_live_plafond_configurable_via_env(bac, monkeypatch):
    """LIVE_AUTHORIZATION_MAX_AGE_SEC permet de borner différemment (ex: 1h)."""
    _ecrire_manifest(bac)
    empreinte = dm.fingerprint()
    monkeypatch.setenv("LIVE_AUTHORIZATION_MAX_AGE_SEC", "3600")  # 1h
    il_y_a_2h = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    _ecrire_etat(
        bac,
        live_authorized=True,
        live_authorized_fingerprint=empreinte,
        live_authorized_at=il_y_a_2h,
        live_authorized_by="Xavier",
        live_authorized_reason="test cap 1h",
    )
    allowed, code, _ = ges.live_destination_authorized()
    assert allowed is False
    assert code == ges.LIVE_MAX_AGE_EXCEEDED


# ══════════════════════════════════════════════════════════════════════
# 8. revoke : coupure immédiate
# ══════════════════════════════════════════════════════════════════════


def test_revoke_live_authorization_coupe_immediatement(bac):
    _ecrire_manifest(bac)
    ges.authorize_live("test", by="Xavier")
    assert ges.live_destination_authorized()[0] is True

    res = ges.revoke_live_authorization("stop urgence", by="Xavier")
    assert res["ok"] is True
    allowed, code, _ = ges.live_destination_authorized()
    assert allowed is False
    assert code == ges.LIVE_NOT_AUTHORIZED


# ══════════════════════════════════════════════════════════════════════
# 9-10. bridge_destinations : la destination live suit le verrou
# ══════════════════════════════════════════════════════════════════════


def test_bridge_destination_live_NONE_sans_authorize(bac, monkeypatch):
    """Même avec MT5_BRIDGE_LIVE_ENABLED=true dans la config, la destination
    doit rester None si REM-002-LIVE n'est pas armé."""
    _ecrire_manifest(bac)
    from config import settings as st
    monkeypatch.setattr(st, "MT5_BRIDGE_LIVE_ENABLED", True, raising=False)
    monkeypatch.setattr(st, "MT5_BRIDGE_LIVE_URL",
                        "http://100.74.160.72:8788", raising=False)
    monkeypatch.setattr(st, "MT5_BRIDGE_LIVE_API_KEY",
                        "test-key", raising=False)

    from backend.services import bridge_destinations as bd
    # Accès à la fonction interne du module :
    assert bd._live_destination() is None


def test_bridge_destination_live_OK_une_fois_authorize(bac, monkeypatch):
    _ecrire_manifest(bac)
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

    ges.authorize_live("test suite", by="pytest")

    from backend.services import bridge_destinations as bd
    config = bd._live_destination()
    assert config is not None
    assert config.destination_id == "admin_live"
    assert "8788" in config.bridge_url
