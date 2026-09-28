"""REM-002 / REM-003 — verrou d'execution global et manifest de deploiement.

Tous les scenarios de la section 31 du cahier des charges qui relevent de
l'integrite : manifest absent, manifest corrompu, divergence de commit, etat
absent, etat corrompu, blocage pose, desarmement.

    POUR CHACUN : RESULTAT ATTENDU = DENY.

⚠️ Ces tests DESARMENT explicitement ce que la fixture globale du harnais a
arme. C'est le seul endroit du depot ou c'est legitime : on y eprouve la
fermeture elle-meme.
"""
from __future__ import annotations

import json

import pytest

from backend.services import deployment_manifest as dm
from backend.services import global_execution_switch as ges


MANIFEST_VALIDE = {
    "git_commit_sha": "a" * 40,
    "git_branch": "main",
    "git_dirty": False,
    "build_timestamp": "2026-09-28T10:00:00+00:00",
    "configuration_hash": "abcdef0123456789",
    "build_environment": "pytest",
    "manifest_schema": 1,
}


@pytest.fixture
def bac(tmp_path, monkeypatch):
    """Un bac a sable ou manifest et etat sont sous notre controle."""
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


# ══════════════════════════════════════════════════════════════════════
# REM-003 — integrite du deploiement
# ══════════════════════════════════════════════════════════════════════


def test_manifest_absent_est_MANIFEST_MISSING(bac):
    i = dm.check_integrity()
    assert i.status == dm.MANIFEST_MISSING
    assert i.ok is False


def test_manifest_corrompu_est_MANIFEST_UNREADABLE(bac):
    bac["manifest"].write_text("{ceci n'est pas du json", encoding="utf-8")
    i = dm.check_integrity()
    assert i.status == dm.MANIFEST_UNREADABLE
    assert i.ok is False


def test_manifest_json_mais_pas_un_objet_est_UNREADABLE(bac):
    bac["manifest"].write_text("[1, 2, 3]", encoding="utf-8")
    assert dm.check_integrity().status == dm.MANIFEST_UNREADABLE


@pytest.mark.parametrize("champ", dm.CHAMPS_REQUIS)
def test_manifest_incomplet_est_refuse_champ_par_champ(bac, champ):
    """Chaque champ requis est requis. Un manifest a trous ne dit rien."""
    _ecrire_manifest(bac, **{champ: ""})
    i = dm.check_integrity()
    assert i.status == dm.MANIFEST_INCOMPLETE
    assert i.ok is False


def test_divergence_de_commit_est_COMMIT_MISMATCH(bac, monkeypatch):
    _ecrire_manifest(bac)
    monkeypatch.setenv("EXPECTED_GIT_COMMIT", "b" * 40)
    i = dm.check_integrity()
    assert i.status == dm.COMMIT_MISMATCH
    assert i.running_commit.startswith("a")
    assert i.expected_commit.startswith("b")


def test_commit_attendu_en_sha_court_est_accepte(bac, monkeypatch):
    """Le deploiement pose un sha complet, mais un sha court doit matcher."""
    _ecrire_manifest(bac)
    monkeypatch.setenv("EXPECTED_GIT_COMMIT", "aaaaaaa")
    assert dm.check_integrity().status == dm.OK


def test_manifest_valide_sans_commit_attendu_est_OK(bac):
    _ecrire_manifest(bac)
    assert dm.check_integrity().ok is True


def test_l_empreinte_de_configuration_ne_contient_aucun_secret():
    """⛔ Un hash qui embarquerait un jeton serait une fuite.

    On verifie que la valeur d'un secret plausible ne change PAS le hash —
    donc qu'il n'entre pas dedans.
    """
    base = {"MT5_BRIDGE_ENABLED": "true", "WATCHED_PAIRS": "XAU/USD"}
    avec_secret = dict(base, MT5_PASSWORD="tres-secret",
                       TELEGRAM_BOT_TOKEN="123:abc",
                       STRIPE_SECRET_KEY="sk_live_x")
    assert dm.configuration_hash(base) == dm.configuration_hash(avec_secret)


def test_l_empreinte_de_configuration_bouge_sur_un_reglage_de_decision():
    a = dm.configuration_hash({"MT5_BRIDGE_MIN_CONFIDENCE": "60"})
    b = dm.configuration_hash({"MT5_BRIDGE_MIN_CONFIDENCE": "42"})
    assert a != b


def test_public_version_n_expose_aucun_secret(bac, monkeypatch):
    _ecrire_manifest(bac)
    monkeypatch.setenv("MT5_PASSWORD", "tres-secret")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    charge = json.dumps(dm.public_version())
    assert "tres-secret" not in charge
    assert "123:abc" not in charge


# ══════════════════════════════════════════════════════════════════════
# REM-002 — le verrou lui-meme
# ══════════════════════════════════════════════════════════════════════


def test_etat_absent_donne_DENY(bac):
    _ecrire_manifest(bac)
    d = ges.execution_allowed()
    assert d.decision == ges.DENY
    assert d.reason_code == ges.STATE_MISSING
    assert d.allowed is False


def test_etat_corrompu_donne_DENY(bac):
    _ecrire_manifest(bac)
    bac["etat"].write_text("pas du json", encoding="utf-8")
    d = ges.execution_allowed()
    assert d.decision == ges.DENY
    assert d.reason_code == ges.STATE_UNREADABLE


def test_manifest_absent_ferme_l_execution(bac):
    """⛔ On ne laisse pas partir un ordre quand on ignore quel code tourne."""
    bac["etat"].write_text(json.dumps({"armed": True}), encoding="utf-8")
    d = ges.execution_allowed()
    assert d.decision == ges.DENY
    assert d.reason_code == ges.DEPLOYMENT_INTEGRITY


def test_armement_puis_ALLOW(bac):
    _ecrire_manifest(bac)
    d = ges.arm("mise en service verifiee", by="test")
    assert d.decision == ges.ALLOW
    assert d.reason_code == ges.ARMED
    assert ges.execution_allowed().allowed is True


def test_desarmement_donne_DENY(bac):
    _ecrire_manifest(bac)
    ges.arm("ouverture", by="test")
    d = ges.disarm("fermeture demandee", by="test")
    assert d.decision == ges.DENY
    assert d.reason_code == ges.DISARMED_MANUALLY


def test_un_NOUVEAU_DEPLOIEMENT_referme_la_porte(bac):
    """LE scenario du cahier des charges : FALSE par defaut au deploiement.

    ⛔ C'est exactement le moment du 2026-09-25 : une image neuve est partie
    en production avec un fail-open, sans geste explicite.
    """
    _ecrire_manifest(bac)
    ges.arm("arme pour le commit a...", by="test")
    assert ges.execution_allowed().allowed is True

    # Nouveau build : le manifest change de commit.
    _ecrire_manifest(bac, git_commit_sha="c" * 40)
    d = ges.execution_allowed()
    assert d.decision == ges.DENY
    assert d.reason_code == ges.NEW_DEPLOYMENT
    assert d.fingerprint_armed != d.fingerprint_running


def test_armer_est_REFUSE_si_l_integrite_n_est_pas_bonne(bac, monkeypatch):
    """On ne peut pas armer un code qu'on ne sait pas identifier."""
    _ecrire_manifest(bac)
    monkeypatch.setenv("EXPECTED_GIT_COMMIT", "d" * 40)
    d = ges.arm("tentative", by="test")
    assert d.decision == ges.DENY
    assert d.reason_code == ges.DEPLOYMENT_INTEGRITY
    assert ges.execution_allowed().allowed is False


@pytest.mark.parametrize("blocage", ges.BLOCAGES_CONNUS)
def test_chaque_blocage_d_integrite_ferme_la_porte(bac, blocage):
    _ecrire_manifest(bac)
    ges.arm("ouverture", by="test")
    ges.set_blocage(blocage, True, detail="essai")
    d = ges.execution_allowed()
    assert d.decision == ges.DENY
    assert d.reason_code == ges.INTEGRITY_BLOCK
    assert blocage in d.blocages

    ges.set_blocage(blocage, False)
    assert ges.execution_allowed().allowed is True


def test_un_blocage_NON_declare_ferme_aussi(bac):
    """⛔ Un nom inconnu doit fermer, pas etre ignore.

    Refuser un blocage au motif qu'il n'est pas dans la liste rendrait le
    garde-fou silencieux — le defaut le plus repandu de ce depot.
    """
    _ecrire_manifest(bac)
    ges.arm("ouverture", by="test")
    ges.set_blocage("blocage_jamais_declare", True, detail="essai")
    d = ges.execution_allowed()
    assert d.decision == ges.DENY
    assert d.reason_code == ges.INTEGRITY_BLOCK


def test_le_desarmement_reste_possible_meme_integrite_cassee(bac):
    """Une coupure ne se negocie pas : elle doit toujours aboutir."""
    d = ges.disarm("coupure d'urgence", by="test")
    assert d.decision == ges.DENY


def test_la_derive_de_configuration_est_PUBLIEE(bac, monkeypatch):
    """🔴 Elle est mesuree, elle ne ferme PAS encore — REM-023.

    Ce test verrouille l'etat REEL du dispositif, pour qu'on ne croie pas
    etre protege. Le jour ou REM-023 est livre, il doit ECHOUER et etre
    reecrit : c'est son role.
    """
    _ecrire_manifest(bac)
    monkeypatch.setenv("MT5_BRIDGE_MIN_CONFIDENCE", "60")
    ges.arm("ouverture", by="test")
    assert ges.status()["configuration_drift"] is False

    monkeypatch.setenv("MT5_BRIDGE_MIN_CONFIDENCE", "42")
    st = ges.status()
    assert st["configuration_drift"] is True, "la derive doit se voir"
    assert st["live_execution"] == "ON", (
        "REM-023 non livre : la derive ne ferme pas encore la porte. "
        "Si cette assertion tombe, c'est que REM-023 a ete implemente — "
        "reecrire ce test au lieu de le desactiver."
    )


# ══════════════════════════════════════════════════════════════════════
# Integration : la porte est-elle BRANCHEE dans le dispatch ?
# ══════════════════════════════════════════════════════════════════════


def test_integration_le_dispatch_refuse_quand_l_execution_est_fermee(bac):
    """⛔ Verifie par mutation : sans ce test, debrancher le verrou de
    `_check_rejection` laisse tous les autres verts.
    """
    from backend.services import mt5_bridge
    from backend.services.bridge_destinations import BridgeConfig
    import dataclasses

    _ecrire_manifest(bac)
    ges.disarm("ferme pour le test", by="test")

    champs = {f.name for f in dataclasses.fields(BridgeConfig)}
    base = {
        "destination_id": "admin_live", "user_id": None,
        "bridge_url": "http://127.0.0.1:0", "bridge_api_key": "t",
        "min_confidence": 0.0,
        "allowed_asset_classes": frozenset({"forex", "metal"}),
        "auto_exec_enabled": True,
    }
    dest = BridgeConfig(**{k: v for k, v in base.items() if k in champs})

    class _E:
        def __init__(self, v):
            self.value = v

    class _PD:
        def __init__(self, v):
            self.pattern = _E(v)

    class _S:
        pair = "XAU/USD"
        horizon = "5min"
        direction = "buy"
        chaine = None

        def __init__(self):
            self.pattern = _PD("range_bounce_up")

    raison = mt5_bridge._check_rejection(_S(), dest)
    assert raison == ges.REJECTION_REASON, (
        f"attendu {ges.REJECTION_REASON!r}, obtenu {raison!r} — si ce n'est "
        "pas ca, le verrou global n'est pas branche dans le dispatch"
    )


def test_le_motif_de_refus_est_declare_et_tracable():
    from backend.services.rejection_service import REASON_LABELS_FR

    assert ges.REJECTION_REASON == "execution_globale_fermee"
    assert not ges.REJECTION_REASON.startswith("_")
    assert ges.REJECTION_REASON in REASON_LABELS_FR


def test_status_est_lisible_meme_quand_tout_est_casse(bac):
    """Le tableau de bord d'audit doit pouvoir afficher l'etat d'une panne."""
    st = ges.status()
    assert st["live_execution"] == "OFF"
    assert st["decision"] == ges.DENY
    assert st["reason_code"]
