"""Tout motif de refus affiche a un humain doit avoir un libelle francais.

Mesure du 2026-10-29 : **neuf** `reason_code` rendus par
`mt5_bridge._check_rejection` n'avaient aucune entree dans
`REASON_LABELS_FR`, dont `pair_not_whitelisted` -- la porte qui protege
l'argent reel sur MT5. Partout ou ce refus est montre, il s'affichait en
code brut.

🔑 Ce test est un garde de DERIVE, pas une liste figee : il enumere les
codes par analyse AST de la fonction de production et exige un libelle pour
chacun. Ajouter un dixieme motif sans son libelle le fait echouer, ce qu'une
liste ecrite a la main n'aurait pas fait.

ⓘ Les codes prefixes `_` sont exclus : ce sont des early-returns techniques
que `_check_rejection` documente comme « prives, non enregistres », donc
jamais affiches.
"""
from __future__ import annotations

import ast
import inspect

import pytest

prod = pytest.importorskip(
    "backend.services.mt5_bridge",
    reason="mt5_bridge indisponible dans cet environnement")

from backend.services.rejection_service import REASON_LABELS_FR  # noqa: E402


def _codes_rendus() -> set[str]:
    """Les `reason_code` que `_check_rejection` peut rendre."""
    arbre = ast.parse(inspect.getsource(prod._check_rejection))
    codes = set()
    for n in ast.walk(arbre):
        if (isinstance(n, ast.Return) and isinstance(n.value, ast.Constant)
                and isinstance(n.value.value, str)):
            codes.add(n.value.value)
    return {c for c in codes if not c.startswith("_")}


def test_la_fonction_rend_bien_des_codes():
    """Temoin de l'instrument : un ensemble vide ferait passer le test
    suivant pour de mauvaises raisons. Cf. la lecon du 28/10 -- un « aucun »
    est ambigu, un « present » ne l'est pas."""
    codes = _codes_rendus()
    assert len(codes) >= 15, (
        "seulement %d codes trouves : l'analyse AST ne lit probablement plus "
        "la bonne fonction" % len(codes))
    assert "below_confidence" in codes


def test_chaque_motif_rendu_a_un_libelle_francais():
    sans = sorted(c for c in _codes_rendus() if c not in REASON_LABELS_FR)
    assert sans == [], (
        "%d motif(s) sans libelle FR : %s. Ils s'affichent en code brut a "
        "l'utilisateur. Ajouter une entree dans REASON_LABELS_FR."
        % (len(sans), sans))


def test_aucun_libelle_n_est_vide():
    vides = sorted(k for k, v in REASON_LABELS_FR.items()
                   if not (v or "").strip())
    assert vides == [], "libelle(s) vide(s) : %s" % vides
