"""`/health` doit publier ses garde-fous sous la cle que le radar interroge.

## Le defaut (2026-10-30)

`or-politique` regle 2 rendait **FAIL** sur `admin_kraken` : « aucun champ
publie -- on ne peut pas verifier ce qui protege l'argent reel ». C'etait le
dernier FAIL du rapport, et je l'avais classe « hors portee du backend ».

⛔ **Il etait faux.** Ce pont publiait DEJA tous ses garde-fous -- mais **a
plat**, et la regle attend un OBJET `garde_fous`. La docstring des ponts MT5
le notait meme : « le bridge Kraken publie deja le sien ». La valeur etait la,
le **contrat** ne l'etait pas.

🔑 Ce bloc n'ajoute donc AUCUNE protection : il regroupe les existantes. Ces
tests gardent exactement cela -- que le regroupement reste **fidele** aux
champs plats, et ne devienne jamais du remplissage qui ferait passer la regle
sans rien garantir.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

_BRIDGE = (pathlib.Path(__file__).resolve().parents[2]
           / "kraken-bridge" / "bridge.py")


@pytest.fixture(scope="module")
def bridge():
    spec = importlib.util.spec_from_file_location("kraken_futures_bridge",
                                                  _BRIDGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def sante(bridge, monkeypatch):
    """`/health` sans joindre Kraken : seul le bloc de config nous interesse."""
    monkeypatch.setattr(bridge, "_public_get", lambda *a, **k: {"ok": True})
    bridge.app.config["TESTING"] = True
    r = bridge.app.test_client().get("/health")
    assert r.status_code == 200
    return r.get_json()


# ── Le contrat que la regle 2 exige ───────────────────────────────────────

def test_garde_fous_est_un_OBJET_non_vide(sante):
    """⛔ LE contrat. `or-politique` rend FAIL sur `None` ou `{}`, et
    ILLISIBLE sur toute autre forme qu'un objet -- une CHAINE non vide a un
    `len()`, donc l'ancienne version de la regle annoncait « N champs » la
    ou il n'y en avait aucun."""
    gf = sante.get("garde_fous")
    assert isinstance(gf, dict), "un objet est attendu, pas %s" % type(gf).__name__
    assert gf, "un objet vide rend FAIL : on ne peut pas verifier ce qui protege"


@pytest.mark.parametrize("cle", [
    "max_daily_loss_pct", "max_open_positions", "max_risque_engage_pct",
    "live_whitelist_count", "start_of_day_balance",
    "sltp_guard_enabled", "sltp_guard_activated_at",
    "sltp_guard_frozen_count",
])
def test_chaque_garde_fou_attendu_est_publie(sante, cle):
    assert cle in sante["garde_fous"]


# ── Le regroupement doit rester FIDELE ────────────────────────────────────

@pytest.mark.parametrize("cle", [
    "max_daily_loss_pct", "max_open_positions", "max_risque_engage_pct",
    "start_of_day_balance", "sltp_guard_enabled", "sltp_guard_activated_at",
])
def test_la_valeur_groupee_est_IDENTIQUE_a_la_valeur_plate(sante, cle):
    """⛔ Deux publications de la meme grandeur qui divergent, c'est le
    defaut du 28/10 (deux `_pip_size`). Le regroupement doit refleter, pas
    recalculer."""
    assert sante["garde_fous"][cle] == sante[cle]


def test_les_COMPTES_correspondent_aux_listes_plates(sante):
    """`live_whitelist_count` et `sltp_guard_frozen_count` resument les
    listes publiees a plat : un compte qui mentirait serait pire qu'absent."""
    assert (sante["garde_fous"]["live_whitelist_count"]
            == len(sante["live_whitelist_symbols"]))
    assert (sante["garde_fous"]["sltp_guard_frozen_count"]
            == len(sante["sltp_guard_frozen_symbols"]))


def test_les_champs_PLATS_sont_CONSERVES(sante):
    """⚠️ D'autres lecteurs s'y appuient. Un regroupement n'est pas une
    raison de casser l'existant."""
    for cle in ("max_daily_loss_pct", "max_open_positions",
                "max_risque_engage_pct", "sltp_guard_enabled",
                "live_whitelist_symbols", "sltp_guard_frozen_symbols"):
        assert cle in sante, "%s a disparu de la racine" % cle


# ── La liste blanche vide doit se VOIR ────────────────────────────────────

def test_une_liste_blanche_VIDE_se_lit_dans_le_compte(bridge, monkeypatch):
    """🔑 Une liste blanche vide est INOPERANTE cote MT5 (opt-in strict).
    Publier son compte permet de le voir sans telecharger la liste."""
    monkeypatch.setattr(bridge, "_public_get", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(bridge, "LIVE_WHITELIST_SYMBOLS", set())
    bridge.app.config["TESTING"] = True
    gf = bridge.app.test_client().get("/health").get_json()["garde_fous"]
    assert gf["live_whitelist_count"] == 0


# ── Et la regle 2 d'or-politique, appliquee telle quelle ──────────────────

def test_la_regle_2_d_or_politique_passe_desormais(sante):
    """Le juge de la skill, applique au vrai contenu de `/health`. C'est lui
    qui decide, pas mon impression."""
    import importlib.util as _iu
    chemin = (pathlib.Path(__file__).resolve().parents[2]
              / ".claude" / "skills" / "or-politique" / "regles.py")
    if not chemin.exists():
        pytest.skip("skill or-politique absente de cet environnement")
    spec = _iu.spec_from_file_location("or_politique_regles", chemin)
    regles = _iu.module_from_spec(spec)
    spec.loader.exec_module(regles)

    dest = {"destination_id": "admin_kraken", "reel": True,
            "garde_fous": sante["garde_fous"], "min_confidence": 42.0,
            "auto_exec": True, "classes": ["crypto"]}
    r2 = [x for x in regles.juger_destination(dest, {}, {}) if x["regle"] == 2]
    assert r2, "la regle 2 doit rendre un verdict"
    assert r2[0]["verdict"] not in ("FAIL", "ILLISIBLE"), (
        "regle 2 = %s : %s" % (r2[0]["verdict"], r2[0].get("valeur")))
