"""REM-001 — la porte des chaines est fail-CLOSED et sa decision est explicite.

Les six tests d'acceptation du cahier des charges, plus le test de
non-regression qui aurait attrape le defaut d'origine.

⛔ Ce fichier ne teste PAS le code source par inspection de chaine de
caracteres. Il fait passer de vrais setups dans la vraie porte, et lit la
decision. Le motif : un test qui cherche une chaine dans `inspect.getsource`
lit aussi le commentaire qui explique pourquoi cette chaine ne doit pas
exister — trois faux positifs le 2026-09-14.
"""
from __future__ import annotations

import pytest

from backend.services import chain_execution_gate as gate_mod
from backend.services.chain_execution_gate import (
    ALLOW,
    CHAIN_ARMED,
    CHAIN_NOT_ARMED,
    CHAIN_PATTERN_INDETERMINATE,
    CHAIN_REGISTRY_UNREADABLE,
    CONTROL_ERROR,
    DENY,
    NO_CHAIN,
    chain_execution_gate,
)


# ─── Doublures ayant la FORME de la production ──────────────────────────
# ⛔ Le 2026-09-15, une doublure sans la forme de l'objet reel a rendu la
# suite verte sur un no-op : 8 h d'armement sans qu'un ordre puisse partir.
# `setup.pattern` est un PatternDetection, dont le motif est
# `setup.pattern.pattern.value` — DEUX niveaux, pas un.
class _MotifEnum:
    def __init__(self, value: str) -> None:
        self.value = value


class _PatternDetection:
    def __init__(self, motif: str) -> None:
        self.pattern = _MotifEnum(motif)


class _Setup:
    def __init__(self, motif="liquidity_sweep_up", chaine=None,
                 pair="XAU/USD", horizon="5min", direction="buy"):
        self.pattern = _PatternDetection(motif) if motif else None
        self.chaine = chaine
        self.pair = pair
        self.horizon = horizon
        self.direction = direction


def _Dest(destination_id="admin_live", **over):
    """Destination ayant la FORME REELLE de la production.

    ⛔ Une doublure maison a fait echouer le test d'integration ci-dessous :
    elle n'avait que `destination_id`, et `_check_rejection` lit
    `min_confidence`, `allowed_asset_classes`, etc. C'est le defaut
    `feedback_doublure_de_test_absente_en_prod` — on construit donc le VRAI
    `BridgeConfig`, jamais un objet ad hoc.
    """
    from backend.services.bridge_destinations import BridgeConfig
    import dataclasses

    champs = {f.name for f in dataclasses.fields(BridgeConfig)}
    base = {
        "destination_id": destination_id,
        "user_id": None,
        "bridge_url": "http://127.0.0.1:0",
        "bridge_api_key": "test",
        "min_confidence": 0.0,
        "allowed_asset_classes": frozenset({"forex", "metal"}),
        "auto_exec_enabled": True,
    }
    base.update(over)
    return BridgeConfig(**{k: v for k, v in base.items() if k in champs})


@pytest.fixture
def dest():
    return _Dest()


# ─── Test 1 — chaine armee + figure autorisee => ALLOW ──────────────────
def test_1_chaine_armee_et_motif_lisible_donne_allow(monkeypatch, dest):
    monkeypatch.setattr(
        "backend.services.chaines_autorisees.autorisee",
        lambda nom, destination_id, horizon: True,
    )
    d = chain_execution_gate(
        _Setup(chaine="chaine:sweep_avec_biais_haussier"), dest)
    assert d.decision == ALLOW
    assert d.reason_code == CHAIN_ARMED
    assert d.allowed is True
    assert d.trigger_id == "liquidity_sweep_up"
    assert d.chain_id == "chaine:sweep_avec_biais_haussier"


# ─── Test 2 — chaine non armee => DENY ──────────────────────────────────
def test_2_chaine_non_armee_donne_deny(monkeypatch, dest):
    monkeypatch.setattr(
        "backend.services.chaines_autorisees.autorisee",
        lambda nom, destination_id, horizon: False,
    )
    d = chain_execution_gate(
        _Setup(chaine="chaine:choch_puis_fvg_baissier"), dest)
    assert d.decision == DENY
    assert d.reason_code == CHAIN_NOT_ARMED
    assert d.allowed is False


# ─── Test 3 — registre VIDE => DENY ─────────────────────────────────────
# C'est le coeur du defaut : un registre vide doit FERMER, jamais ouvrir.
def test_3_registre_vide_donne_deny(monkeypatch, dest):
    monkeypatch.setattr(
        "backend.services.chaines_autorisees.tout", lambda: {})
    monkeypatch.setattr(
        "backend.services.chaines_autorisees.armees", lambda: [])
    monkeypatch.setattr(
        "backend.services.chaines_autorisees.autorisee",
        lambda nom, destination_id, horizon: False,
    )
    d = chain_execution_gate(_Setup(chaine="chaine:quelconque"), dest)
    assert d.decision == DENY
    assert d.allowed is False


# ─── Test 4 — configuration ABSENTE => DENY ─────────────────────────────
def test_4_registre_illisible_donne_deny(monkeypatch, dest):
    def _explose(*a, **k):
        raise FileNotFoundError("registre absent")

    monkeypatch.setattr(
        "backend.services.chaines_autorisees.autorisee", _explose)
    d = chain_execution_gate(_Setup(chaine="chaine:quelconque"), dest)
    assert d.decision == DENY
    assert d.reason_code == CHAIN_REGISTRY_UNREADABLE
    assert d.allowed is False


# ─── Test 5 — exception interne => DENY ─────────────────────────────────
def test_5_exception_interne_donne_deny(monkeypatch, dest):
    class _SetupPiege:
        pair = "XAU/USD"
        horizon = "5min"

        @property
        def chaine(self):
            raise RuntimeError("attribut qui explose")

    d = chain_execution_gate(_SetupPiege(), dest)
    assert d.decision == DENY
    assert d.reason_code == CONTROL_ERROR
    assert d.allowed is False


# ─── Test 6 — figure artificielle non declaree => refusee ───────────────
def test_6_motif_inconnu_avec_chaine_non_armee_est_refuse(monkeypatch, dest):
    monkeypatch.setattr(
        "backend.services.chaines_autorisees.autorisee",
        lambda nom, destination_id, horizon: False,
    )
    d = chain_execution_gate(
        _Setup(motif="motif_totalement_inconnu",
               chaine="chaine:inventee_de_toutes_pieces"), dest)
    assert d.decision == DENY
    assert d.allowed is False


def test_6b_motif_indeterminable_sur_chaine_armee_est_refuse(
        monkeypatch, dest):
    """Armee mais motif illisible : on ne sait pas ce qu'on ouvrirait."""
    monkeypatch.setattr(
        "backend.services.chaines_autorisees.autorisee",
        lambda nom, destination_id, horizon: True,
    )
    d = chain_execution_gate(_Setup(motif=None, chaine="chaine:armee"), dest)
    assert d.decision == DENY
    assert d.reason_code == CHAIN_PATTERN_INDETERMINATE


# ─── Un setup ORDINAIRE traverse sans etre gene ─────────────────────────
def test_setup_sans_chaine_passe_en_allow_no_chain(dest):
    d = chain_execution_gate(_Setup(chaine=None), dest)
    assert d.decision == ALLOW
    assert d.reason_code == NO_CHAIN


# ─── PR-02 : aucun type ambigu ne porte la decision ─────────────────────
def test_la_decision_ne_repose_sur_aucun_type_ambigu():
    """Un booleen implicite sur l'objet de decision ne doit rien decider.

    ⛔ Le defaut d'origine venait de `if allowed_patterns:` — la verite d'un
    conteneur. On verifie qu'aucun appelant ne peut refaire cette erreur :
    `allowed` est une propriete nommee, et elle exige l'egalite a ALLOW.
    """
    deny = gate_mod.ChainDecision(decision=DENY, reason_code=CHAIN_NOT_ARMED)
    allow = gate_mod.ChainDecision(decision=ALLOW, reason_code=NO_CHAIN)
    assert deny.allowed is False
    assert allow.allowed is True
    # Une decision inconnue n'est PAS un ALLOW.
    inconnu = gate_mod.ChainDecision(decision="PEUT-ETRE", reason_code="?")
    assert inconnu.allowed is False


def test_toute_decision_porte_un_motif_auditable():
    for dec in (
        gate_mod.ChainDecision(decision=DENY, reason_code=CHAIN_NOT_ARMED),
        gec := gate_mod.ChainDecision(decision=ALLOW, reason_code=NO_CHAIN),
    ):
        det = dec.as_details()
        assert det["reason_code"]
        assert det["decision"] in (ALLOW, DENY)
        assert det["timestamp"]
    assert gec.reason_code == NO_CHAIN


# ─── NON-REGRESSION : le refus est DISTINCT de pattern_not_allowed ──────
def test_le_motif_de_refus_est_distinct_et_traçable():
    """⛔ Avant REM-001, le refus sortait en `pattern_not_allowed` — donc
    indiscernable d'un motif ordinaire hors liste blanche. Et il ne devait
    surtout pas etre un code prive (prefixe `_`), qui ne laisse aucune trace.
    """
    from backend.services.rejection_service import REASON_LABELS_FR

    assert gate_mod.REJECTION_REASON == "chaine_non_armee"
    assert not gate_mod.REJECTION_REASON.startswith("_")
    assert gate_mod.REJECTION_REASON in REASON_LABELS_FR
    assert gate_mod.REJECTION_REASON != "pattern_not_allowed"


# ─── NON-REGRESSION : la liste blanche ne peut plus etre SUPPRIMEE ──────
def test_une_chaine_non_armee_ne_supprime_plus_la_liste_blanche(monkeypatch):
    """Le test qui aurait attrape le defaut d'origine.

    On appelle `_patterns_autorises` avec un setup portant une chaine NON
    armee et l'on exige qu'il ne rende pas un ensemble vide — parce qu'un
    ensemble vide est lu « aucun filtre » par le consommateur.
    """
    from backend.services import mt5_bridge

    monkeypatch.setattr(
        "backend.services.chaines_autorisees.autorisee",
        lambda nom, destination_id, horizon: False,
    )
    monkeypatch.setattr(
        mt5_bridge, "MT5_BRIDGE_ALLOWED_PATTERNS",
        frozenset({"range_bounce_up", "range_bounce_down"}), raising=False,
    )
    setup = _Setup(motif="fvg_down", chaine="chaine:non_armee")
    autorises = mt5_bridge._patterns_autorises(setup, _Dest("admin_live"))

    # ⛔ L'assertion qui compte : pas d'ensemble vide comme signal de refus.
    assert autorises, (
        "un ensemble vide serait relu « aucun filtre de motif » par "
        "`if allowed_patterns and ...` — c'est le fail-open de REM-001"
    )
    # Et la chaine non armee n'a rien ouvert : son motif reste dehors.
    assert "fvg_down" not in autorises


# ─── INTEGRATION : le dispatch APPELLE-T-IL vraiment la porte ? ─────────
# ⛔ Les tests ci-dessus valident le module en ISOLATION. Verifie par
# mutation le 2026-09-28 : debrancher la porte de `_check_rejection` les
# laissait tous VERTS. C'est la famille de defauts « patch sur import mort »
# et « doublure absente en prod ». Ce test-ci est le seul qui morde.
def test_integration_le_dispatch_refuse_une_chaine_non_armee(monkeypatch):
    from backend.services import mt5_bridge

    monkeypatch.setattr(
        "backend.services.chaines_autorisees.autorisee",
        lambda nom, destination_id, horizon: False,
    )
    setup = _Setup(motif="fvg_down", chaine="chaine:non_armee")
    raison = mt5_bridge._check_rejection(setup, _Dest("admin_live"))

    assert raison == gate_mod.REJECTION_REASON, (
        "`_check_rejection` doit refuser via chain_execution_gate et rendre "
        f"{gate_mod.REJECTION_REASON!r} ; il a rendu {raison!r}. Si c'est "
        "None ou un autre motif, la porte n'est pas branchee."
    )


def test_integration_la_porte_passe_avant_les_autres(monkeypatch):
    """Le refus de chaine doit primer sur tout autre motif.

    Un setup de chaine non armee dont la paire est AUSSI hors univers doit
    sortir en `chaine_non_armee`, pas en `pair_not_whitelisted` : sinon
    l'ordre des portes a change et le motif redevient indiscernable.
    """
    from backend.services import mt5_bridge

    monkeypatch.setattr(
        "backend.services.chaines_autorisees.autorisee",
        lambda nom, destination_id, horizon: False,
    )
    setup = _Setup(motif="motif_inconnu", chaine="chaine:non_armee",
                   pair="PAIRE/INEXISTANTE")
    raison = mt5_bridge._check_rejection(setup, _Dest("admin_live"))
    assert raison == gate_mod.REJECTION_REASON


def test_integration_un_setup_ordinaire_n_est_pas_refuse_par_cette_porte(
        monkeypatch):
    """Non-regression inverse : la porte ne doit RIEN casser pour les autres.

    Un setup sans chaine ne doit jamais sortir en `chaine_non_armee`, quelle
    que soit la raison pour laquelle il est par ailleurs refuse.
    """
    from backend.services import mt5_bridge

    setup = _Setup(motif="range_bounce_up", chaine=None)
    raison = mt5_bridge._check_rejection(setup, _Dest("admin_live"))
    assert raison != gate_mod.REJECTION_REASON
