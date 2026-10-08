"""Stop de l'or FIXE EN EUROS — demandé par Xavier le 2026-10-08.

> « Je veux que le stop loss soit à 20 euros et pas à 12 comme précisé
> précédemment. »

## ⛔ CE QUE LA MESURE DIT, et qui ne change pas parce qu'on code

À 20 € de stop pour 2 € de cible, le rapport vaut **0,1000 R** et le seuil de
rentabilité monte à **90,91 %**. Le banc d'un an (910 entrées, ordre respecté)
donne **86,2 %** à cette géométrie exacte :

```
stop 12,88 €  ->  TP/SL 0,1553 R   requis 86,56 %   obtenu 81,9 %   z -2,97
stop 20,00 €  ->  TP/SL 0,1000 R   requis 90,91 %   obtenu 86,2 %   z -4,94
```

⇒ Élargir le stop **aggrave** la configuration, et plus nettement qu'avant :
−0,80 €/trade contre −0,70 €.

⚠️ Ces tests ne disent donc pas que l'idée est bonne. Ils garantissent qu'elle
fait **exactement** ce qui est demandé, qu'elle est **inerte par défaut**, et
qu'elle ne rend pas l'or muet en silence.

## 🔑 LE PIÈGE RÉINTRODUIT SCIEMMENT

Un stop **fixe en euros** se resserre en proportion quand l'or monte, et
referme la porte des frais tout seul. L'or est resté **muet trois jours** pour
cette raison avec un stop fixe de 10 €, et c'est pourquoi `XAU_SL_PCT` l'avait
remplacé le 05/10.

Mais la marge n'est plus la même : la porte exige `cout_r ≤ 0,30 × edge_r`,
soit un stop d'au moins `prix / 300`. À 20 € (22,39 $) cela tient jusqu'à un or
à **6 717 $**, contre 4 123 $ aujourd'hui.

⇒ D'où un **détecteur** qui parle AVANT que la porte ne refuse — et non une
seconde porte des frais, qui ferait deux endroits à tenir d'accord.
"""
from __future__ import annotations

import ast
import logging
import types
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "backend" / "services" / "pattern_detector.py"


def _charger(sl_eur: float, pct: float = 0.35, taux: float | None = 1.1197):
    """Extrait `_distance_sl_or` du source, avec les réglages voulus.

    ⛔ Découpé par `ast` et non entre deux ancres textuelles : une tranche
    bornée par la fonction suivante suppose l'adjacence, et l'insertion de ce
    réglage-ci a fait tomber six tests d'un coup le 2026-10-08.
    """
    src = _SRC.read_text(encoding="utf-8")
    noeud = next(n for n in ast.parse(src).body
                 if isinstance(n, ast.FunctionDef) and n.name == "_distance_sl_or")
    mod = types.ModuleType("stop_extrait")
    mod.__dict__.update({
        "XAU_SL_FIXE_EUR": sl_eur,
        "XAU_SL_PCT": pct,
        "_MARGE_ALERTE_STOP": 1.20,
        "_eur_usd_courant": lambda: taux,
        "logger": logging.getLogger("stop_extrait"),
    })
    exec(compile(ast.get_source_segment(src, noeud), str(_SRC), "exec"),
         mod.__dict__)
    return mod


# ─── ⛔ INERTE par défaut : c'est LE test qui compte ──────────────────────

def test_le_defaut_du_SOURCE_est_INERTE():
    """⛔ Épingle le défaut dans le FICHIER. Un `20` arrivé là par
    inadvertance élargirait le stop de tout l'or au prochain déploiement."""
    ligne = next(l for l in _SRC.read_text(encoding="utf-8").splitlines()
                 if l.startswith("XAU_SL_FIXE_EUR"))
    assert '"0"' in ligne, f"le defaut n'est plus inerte : {ligne!r}"


def test_sans_reglage_c_est_le_POURCENTAGE_qui_gouverne():
    """🔑 Le comportement d'avant, intact : 0,35 % de 4123 = 14,43 $."""
    m = _charger(0.0, pct=0.35)
    assert m._distance_sl_or(4123.0) == pytest.approx(14.4305)


def test_un_reglage_NEGATIF_retombe_sur_le_pourcentage():
    m = _charger(-20.0, pct=0.35)
    assert m._distance_sl_or(4123.0) == pytest.approx(14.4305)


# ─── Le réglage fait ce qu'il dit ────────────────────────────────────────

def test_vingt_euros_donnent_la_bonne_distance():
    """20 € au taux 1,1197 = 22,394 $, parce qu'un lot de 0,01 vaut UNE once."""
    m = _charger(20.0)
    assert m._distance_sl_or(4123.0) == pytest.approx(22.394)


def test_le_montant_PRIME_sur_le_pourcentage():
    """⚠️ Les deux réglages peuvent coexister ; le montant en euros gagne,
    sinon poser `XAU_SL_FIXE_EUR` ne changerait rien et le silence
    ressemblerait à « le réglage ne marche pas »."""
    m = _charger(20.0, pct=0.35)
    assert m._distance_sl_or(4123.0) == pytest.approx(22.394)
    assert m._distance_sl_or(4123.0) != pytest.approx(14.4305)


def test_la_distance_NE_DEPEND_PAS_du_prix():
    """🔑 C'est toute la différence avec le pourcentage : 20 € restent 20 €
    quand l'or monte — et c'est précisément ce qui crée le piège des frais."""
    m = _charger(20.0)
    for prix in (3000.0, 4123.0, 5000.0, 6000.0):
        assert m._distance_sl_or(prix) == pytest.approx(22.394)


def test_le_taux_est_LU_et_non_fige():
    """⛔ Un taux figé à 1,155 avait surévalué tous les euros du système de
    2,7 % (corrigé le 02/10)."""
    assert _charger(20.0, taux=1.08)._distance_sl_or(4123.0) == pytest.approx(21.6)
    assert _charger(20.0, taux=1.20)._distance_sl_or(4123.0) == pytest.approx(24.0)


# ─── Les données manquantes ──────────────────────────────────────────────

def test_taux_ILLISIBLE_retombe_sur_le_POURCENTAGE_et_pas_sur_None():
    """🔑 Chemin d'un ordre réel. Rendre `None` ferait retomber l'appelant sur
    le stop ATR, c'est-à-dire sur une taille qui n'a rien à voir. Le
    pourcentage, lui, ne dépend d'aucune conversion."""
    for mauvais in (None, 0.0, -1.0):
        m = _charger(20.0, pct=0.35, taux=mauvais)
        assert m._distance_sl_or(4123.0) == pytest.approx(14.4305)


def test_taux_illisible_ET_pourcentage_nul_rend_None():
    """⚠️ Plus aucun repli : on ne devine pas un stop sur l'argent réel."""
    m = _charger(20.0, pct=0.0, taux=None)
    assert m._distance_sl_or(4123.0) is None


def test_prix_ILLISIBLE_rend_None():
    m = _charger(20.0)
    for mauvais in (None, 0, -5, "abc"):
        assert m._distance_sl_or(mauvais) is None


# ─── 🔑 LE DÉTECTEUR : parler AVANT que la porte des frais ne refuse ─────

def test_il_ALERTE_quand_le_stop_approche_du_plancher(caplog):
    """🔑 La garde qui empêche l'or de redevenir muet sans explication. À
    20 € le plancher de viabilité (`prix/300`) est atteint vers un or à
    6 717 $ ; on parle dès qu'il reste moins de 20 % de marge."""
    m = _charger(20.0)
    with caplog.at_level(logging.WARNING, logger="stop_extrait"):
        # or a 6 000 $ : plancher 20,00 $, stop 22,39 $ -> marge 12 %, on parle
        d = m._distance_sl_or(6000.0)
    assert d == pytest.approx(22.394)
    assert any("porte" in r.message or "frais" in r.message
               for r in caplog.records), caplog.text


def test_il_NE_PARLE_PAS_au_prix_du_jour(caplog):
    """⚠️ Une alerte qui crie tout le temps ne se lit plus. À 4 123 $ le
    plancher vaut 13,74 $ pour un stop de 22,39 $ : 63 % de marge."""
    m = _charger(20.0)
    with caplog.at_level(logging.WARNING, logger="stop_extrait"):
        m._distance_sl_or(4123.0)
    assert not caplog.records, caplog.text


def test_il_RETOURNE_quand_meme_la_distance_en_alertant():
    """⛔ Le détecteur ALERTE, il ne décide pas. Refuser ici dupliquerait la
    porte des frais, qui est le seul endroit où ce refus appartient."""
    m = _charger(20.0)
    assert m._distance_sl_or(6500.0) == pytest.approx(22.394)


def test_le_detecteur_n_est_PAS_une_seconde_porte_des_frais():
    """🔑 Épingle l'intention : aucun `return None` ni `refus` dans la branche
    du montant fixe. Deux portes à tenir d'accord, c'est la garantie qu'elles
    divergeront — et `fees_exceed_edge` existe déjà."""
    src = _SRC.read_text(encoding="utf-8")
    noeud = next(n for n in ast.parse(src).body
                 if isinstance(n, ast.FunctionDef) and n.name == "_distance_sl_or")
    corps = ast.get_source_segment(src, noeud)
    bloc = corps[corps.index("if XAU_SL_FIXE_EUR > 0:"):]
    bloc = bloc[:bloc.index("if XAU_SL_PCT <= 0:")]
    assert "logger.warning" in bloc
    assert "return distance" in bloc
    assert "EDGE_COST_MAX_SHARE" not in bloc, (
        "la porte des frais est dupliquee ici")


# ─── Ce qui NE doit pas avoir bougé ──────────────────────────────────────

def test_le_POURCENTAGE_par_defaut_est_inchange():
    """⚠️ Il reste le filet : si le montant en euros est retiré, l'or revient
    à 0,35 % et non au stop ATR."""
    ligne = next(l for l in _SRC.read_text(encoding="utf-8").splitlines()
                 if l.startswith("XAU_SL_PCT"))
    assert '"0.35"' in ligne, f"le pourcentage a change : {ligne!r}"


def test_la_cible_en_euros_n_est_PAS_touchee():
    ligne = next(l for l in _SRC.read_text(encoding="utf-8").splitlines()
                 if l.startswith("XAU_TP_FIXE_EUR"))
    assert '"0"' in ligne


def test_la_constante_est_declaree_UNE_SEULE_fois():
    """⛔ Le défaut qui a failli passer, le 2026-10-08.

    `XAU_SL_FIXE_EUR` **existait déjà** (ligne 980, défaut `"10"`), morte depuis
    que `XAU_SL_PCT` l'avait remplacée le 05/10 — plus personne ne la lisait. En
    la recâblant, j'en ai d'abord écrit une **seconde** déclaration : Python
    garde la dernière, donc le défaut réel devenait illisible à la lecture.

    🔑 Et surtout : son défaut de `10` aurait armé un stop de **DIX euros** au
    prochain déploiement — 11,20 $, sous le plancher de viabilité de 13,74 $,
    donc porte des frais fermée et or **muet**, les trois jours de silence
    d'octobre à l'identique.

    ⇒ Deux déclarations d'une même constante de production ne sont jamais un
    détail de style.
    """
    src = _SRC.read_text(encoding="utf-8")
    n = sum(1 for l in src.splitlines() if l.startswith("XAU_SL_FIXE_EUR = "))
    assert n == 1, f"{n} declarations de XAU_SL_FIXE_EUR (il en faut UNE)"

    # Et la même exigence pour la cible, construite le même jour.
    m = sum(1 for l in src.splitlines() if l.startswith("XAU_TP_FIXE_EUR = "))
    assert m == 1, f"{m} declarations de XAU_TP_FIXE_EUR (il en faut UNE)"
