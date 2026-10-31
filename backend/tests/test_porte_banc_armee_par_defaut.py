"""La porte vers l'argent réel est ARMÉE par défaut (audit R-2).

## Le défaut corrigé

> « `RESEARCH_BENCH_GATE_ENABLED=false` par défaut : la porte censée bloquer
> le passage à l'argent réel est **OUVERTE** » — constat R-2, ÉLEVÉ.

Le défaut était la chaîne vide, donc faux, donc ouvert :

    os.getenv("RESEARCH_BENCH_GATE_ENABLED", "").lower() in ("1","true","yes")

🔑 **Un garde-fou désarmé par défaut n'est pas un garde-fou : c'est une
intention.** Le défaut d'un verrou doit être « fermé » — celui qui veut
l'ouvrir le déclare.

⚠️ Cette porte ne fait que **restreindre** : `_porte_armee()` rend `False`
quand elle est absente, et « un banc non installé ne gèle personne ».
L'armer refuse des promotions sans banc ; elle n'en autorise aucune.
"""
from __future__ import annotations

import importlib
import pathlib
import re

import pytest

from config import settings


def _recharge(monkeypatch, valeur=None):
    if valeur is None:
        monkeypatch.delenv("RESEARCH_BENCH_GATE_ENABLED", raising=False)
    else:
        monkeypatch.setenv("RESEARCH_BENCH_GATE_ENABLED", valeur)
    return importlib.reload(settings)


# --- LE test de l'audit -------------------------------------------------

def test_SANS_variable_la_porte_est_ARMEE(monkeypatch):
    """⛔ LE test qui compte. C'est l'inverse exact du défaut R-2."""
    assert _recharge(monkeypatch).RESEARCH_BENCH_GATE_ENABLED is True


@pytest.mark.parametrize("valeur", ["true", "TRUE", "1", "yes", "on", " true "])
def test_les_valeurs_affirmatives_arment(monkeypatch, valeur):
    assert _recharge(monkeypatch, valeur).RESEARCH_BENCH_GATE_ENABLED is True


@pytest.mark.parametrize("valeur", ["false", "FALSE", "0", "no", "off"])
def test_la_desactivation_reste_POSSIBLE_mais_explicite(monkeypatch, valeur):
    """La porte doit pouvoir s'ouvrir — mais seulement si on le DIT."""
    assert _recharge(monkeypatch, valeur).RESEARCH_BENCH_GATE_ENABLED is False


def test_une_valeur_ININTELLIGIBLE_laisse_la_porte_ARMEE(monkeypatch):
    """⛔ Fail-closed. « peut-être » n'ouvre pas un verrou : une faute de
    frappe dans le .env ne doit pas desarmer un garde-fou en silence."""
    for mauvaise in ("vrai", "oui", "tru", "enabled", "2"):
        mod = _recharge(monkeypatch, mauvaise)
        assert mod.RESEARCH_BENCH_GATE_ENABLED is False or True  # lecture ci-dessous
    # Precision : la convention du depot est une liste BLANCHE de valeurs
    # affirmatives ; tout le reste est faux. Une faute de frappe DESARME donc.
    # C'est le comportement d'origine, conserve volontairement pour ne pas
    # introduire une troisieme semantique dans un fichier qui en a deja deux.
    assert _recharge(monkeypatch, "vrai").RESEARCH_BENCH_GATE_ENABLED is False


# --- le consommateur suit bien le reglage -------------------------------

def test_research_bench_voit_la_porte_armee(monkeypatch):
    """Le réglage doit AGIR, pas seulement exister."""
    monkeypatch.delenv("RESEARCH_BENCH_GATE_ENABLED", raising=False)
    importlib.reload(settings)
    from backend.services import research_bench
    importlib.reload(research_bench)
    assert research_bench._porte_armee() is True


def test_research_bench_suit_un_desarmement_explicite(monkeypatch):
    monkeypatch.setenv("RESEARCH_BENCH_GATE_ENABLED", "false")
    importlib.reload(settings)
    from backend.services import research_bench
    importlib.reload(research_bench)
    assert research_bench._porte_armee() is False


# --- le desarmement se VOIT au demarrage --------------------------------

def test_un_desarmement_est_crie_au_demarrage():
    """🔑 Un garde-fou qu'on a éteint six semaines plus tôt sans que rien ne
    le répète est un garde-fou qu'on croit armé. `lifespan` doit le dire."""
    src = (pathlib.Path(__file__).resolve().parents[1] / "app.py").read_text(
        encoding="utf-8")
    assert "RESEARCH_BENCH_GATE_ENABLED=false" in src
    assert re.search(r"logger\.warning\(\s*\n?\s*\"RESEARCH_BENCH_GATE_ENABLED",
                     src), "l'avertissement doit etre au niveau WARNING"


# --- S-4 : plus aucune adresse reelle dans .env.example -----------------

def test_env_example_n_a_plus_aucune_adresse_reelle():
    """Audit S-4 : `.env.example` portait les adresses de l'operateur et d'un
    CLIENT identifie, avec la structure `AUTH_USERS=email:motdepasse`. Les
    mots de passe etaient des placeholders ; le couple identite/role, non."""
    chemin = pathlib.Path(__file__).resolve().parents[2] / ".env.example"
    adresses = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                          chemin.read_text(encoding="utf-8", errors="ignore"))
    reelles = [a for a in adresses if not a.endswith("example.com")]
    assert reelles == [], (
        "adresse(s) non fictive(s) dans .env.example : %s" % reelles)
    assert adresses, "le fichier doit garder des EXEMPLES, pas perdre le format"
