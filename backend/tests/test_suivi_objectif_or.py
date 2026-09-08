"""La surveillance quotidienne de l'objectif sur l'or.

Demandé par Xavier le 08/09 : « l'amélioration quotidienne des trades or en
fonction de la médiane des valeurs et du lot ».

⛔ Ce module **n'ajuste rien**. Il affiche la distribution du plus haut atteint
pour qu'une dérive DURABLE se voie. Ré-optimiser l'objectif à chaque mesure
serait du surajustement en boucle — l'erreur qui a tué l'étude CAC 40 la veille.

🔑 Ce que la mesure du 08/09 avait établi et qu'on ne veut pas perdre : le R
moyen **croît** avec la distance de l'objectif (0,75 R → −0,004 ; 1,80 R →
+0,139 ; 2,50 R → +0,190). Raccourcir l'objectif COÛTE.
"""
from __future__ import annotations

import io

import pytest

from backend.services import suivi_objectif_or as suivi


def _mesure(**extra) -> dict:
    base = {"n": 23, "jours": 30, "objectif_R": 1.8, "mediane_R": 1.20,
            "mediane_eur": 22.33, "risque_median_eur": 18.61,
            "lot_median": 0.01, "pct_1R": 58.0, "pct_objectif": 40.0}
    base.update(extra)
    return base


# ── Le bloc affiché ──────────────────────────────────────────────────

def test_la_mediane_est_donnee_en_R_ET_en_euros():
    """🔑 Le lot est SUBI (0,01, plancher du courtier) et la distance du stop
    varie : le même 1,8 R vaut des euros très différents. Les deux unités sont
    donc nécessaires — c'est la demande explicite de Xavier."""
    texte = "\n".join(suivi.lignes(_mesure()))
    assert "+1.20 R" in texte
    assert "22.33 €" in texte
    assert "lot 0.01" in texte
    assert "18.61 €" in texte           # le risque médian


def test_les_deux_taux_d_atteinte_sont_dits():
    texte = "\n".join(suivi.lignes(_mesure()))
    assert "58 %" in texte and "40 %" in texte


def test_une_mediane_SAINE_confirme_l_objectif():
    texte = "\n".join(suivi.lignes(_mesure(mediane_R=1.20)))
    assert "✅" in texte
    assert "raccourcir" in texte.lower()


def test_une_mediane_BASSE_avertit_sans_regler():
    """⛔ L'avertissement doit dire « si ça DURE » : une journée ne décide de
    rien, et un module qui règle tout seul reproduirait le surajustement."""
    texte = "\n".join(suivi.lignes(_mesure(mediane_R=0.40)))
    assert "⚠️" in texte
    assert "DURE" in texte or "dure" in texte
    assert "pas sur un jour" in texte


def test_le_module_NE_REGLE_rien():
    """⛔ La propriété qui compte : il OBSERVE, il ne modifie aucun réglage.

    ⚠️ Première version trop grossière : elle interdisait `os.environ[`, qui
    sert ici à LIRE l'URL du bridge. Un test qui confond lecture et écriture
    crie sur du code juste — la leçon d'août, reprise.
    """
    src = io.open("backend/services/suivi_objectif_or.py", encoding="utf-8").read()
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    for interdit in ("UPDATE ", "INSERT ", "set_state(", "putenv",
                     "os.environ.__setitem__"):
        assert interdit not in code, interdit
    # Une ÉCRITURE d'environnement s'écrirait `os.environ[...] = ...`
    import re
    assert not re.search(r"os\.environ\[[^\]]+\]\s*=", code)
    # La base est ouverte en LECTURE SEULE, et ça se lit.
    assert "mode=ro" in code


# ── Les silences qu'on refuse ────────────────────────────────────────

def test_une_ERREUR_ne_se_lit_pas_comme_rien_a_signaler():
    """⛔ Un bridge muet et « aucun trade or » ne veulent pas dire la même
    chose. Les confondre, c'est le défaut que ce dépôt répare sans cesse."""
    texte = "\n".join(suivi.lignes({"erreur": "bridge non configuré"}))
    assert "❓" in texte
    assert "rien à signaler" in texte


def test_une_mesure_ABSENTE_ne_produit_aucune_ligne():
    """⚠️ Le récap doit partir même sans cet indicateur."""
    assert suivi.lignes(None) == []
    assert suivi.lignes({}) == []


def test_la_fenetre_evite_le_piege_du_T():
    """⛔ Le piège de la journée : `datetime('now',...)` rend une ESPACE alors
    que les dates sont stockées avec un `T`, et la fenêtre ne filtre RIEN.
    Ici la borne est construite en ISO côté Python."""
    src = io.open("backend/services/suivi_objectif_or.py", encoding="utf-8").read()
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    assert "datetime('now'" not in code
    assert "isoformat()" in code


def test_la_boucle_s_ARRETE_au_stop():
    """⛔ Défaut vu le 08/09 : une boucle qui continue après le SL mesure
    l'amplitude du MARCHÉ, pas le chemin du trade — elle rendait des +13 R sur
    un objectif à 1,8 R."""
    src = io.open("backend/services/suivi_objectif_or.py", encoding="utf-8").read()
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    assert "break" in code
    assert "defavorable <= -1.0" in code


# ── Le câblage au récap ──────────────────────────────────────────────

def test_le_recap_APPELLE_le_module():
    src = io.open("scripts/daily_recap.py", encoding="utf-8").read()
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    assert "fetch_objectif_or" in code
    assert "suivi_objectif_or" in code


def test_le_recap_NE_RECOPIE_pas_le_calcul():
    """⛔ Une deuxième copie est une copie qui dérive — quatre fois vérifié
    aujourd'hui. Le récap appelle, il ne recalcule pas."""
    src = io.open("scripts/daily_recap.py", encoding="utf-8").read()
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    assert "mediane_R" not in code, "le récap recalcule la médiane au lieu de l'appeler"
    assert "pct_objectif" not in code


def test_un_echec_du_collecteur_ne_casse_PAS_le_recap():
    """⚠️ Le récap du soir doit partir même si le bridge est muet."""
    src = io.open("scripts/daily_recap.py", encoding="utf-8").read()
    debut = src.index("def fetch_objectif_or")
    fin = src.index("def render(")
    bloc = src[debut:fin]
    assert "except Exception" in bloc
    assert "erreur" in bloc
