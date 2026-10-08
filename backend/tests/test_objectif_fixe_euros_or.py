"""Objectif fixe en euros sur l'or — demandé par Xavier le 2026-10-08.

> « Je veux quand même tester le TP à 2 euros et le SL à moins 12 euros. »

## ⛔ CE QUE LA MESURE DIT, ET QUI N'A PAS CHANGÉ

Un an d'or, 910 entrées, **ordre respecté** (`_issue` teste le stop AVANT
l'objectif) :

```
objectif 0,167 R : 81,9 % au TP, 18,1 % au stop, -0,70 €/trade
objectif 1,800 R : 37,9 % au TP, 62,1 % au stop, +0,58 €/trade
```

🔑 Et la **géométrie**, avant toute mesure : pour un prix **sans tendance**,
toucher +2 avant −12 arrive avec probabilité `12/14 = 85,71 %` — **exactement**
le seuil de rentabilité de cette configuration. Un prix sans tendance rend donc
**zéro**, le spread part de là vers le bas, et la mesure donne 81,9 % : **3,8
points sous le prix sans tendance**.

⇒ Ces tests ne disent pas que l'idée est bonne. Ils garantissent qu'elle fait
**exactement ce qui est demandé**, qu'elle est **inerte par défaut**, et qu'elle
ne casse rien d'autre.

## ⚠️ Pourquoi le stop N'EST PAS à 12 €

À 12 € (13,50 $) le coût vaut **0,03052 R** contre un plafond de **0,0300** : la
porte des frais **refuserait chaque ordre**. Le minimum viable est **12,21 €**
au prix du jour, et il **monte avec le prix de l'or** (12,74 € à 4 300 $).

Le `0,35 %` en place vaut **12,81 €** — le seuil de viabilité **plus la marge**
que le modèle de coût exige. C'est donc lui qu'on garde.
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "backend" / "services" / "pattern_detector.py"


def _charger(tp_eur: float, taux: float | None = 1.125):
    """Extrait `_distance_tp_or` du source, avec le réglage voulu."""
    src = _SRC.read_text(encoding="utf-8")
    debut = src.index("def _distance_tp_or(")
    fin = src.index("def _distance_sl_or(")
    mod = types.ModuleType("detecteur_extrait")
    mod.__dict__.update({
        "XAU_TP_FIXE_EUR": tp_eur,
        "_eur_usd_courant": lambda: taux,
    })
    exec(compile(src[debut:fin], str(_SRC), "exec"), mod.__dict__)
    return mod


# ─── Le réglage fait ce qu'il dit ─────────────────────────────────────────

def test_deux_euros_donnent_la_bonne_distance_de_prix():
    """2 € au taux 1,125 = 2,25 $ de prix, parce qu'un lot de 0,01 vaut UNE once."""
    m = _charger(2.0)
    assert m._distance_tp_or(4120.0) == pytest.approx(2.25)


def test_le_taux_est_LU_et_non_fige():
    """⛔ Un taux figé à 1,155 avait déjà surévalué tous les euros du système
    de 2,7 % (corrigé le 02/10). On lit le taux vivant."""
    assert _charger(2.0, taux=1.08)._distance_tp_or(4120.0) == pytest.approx(2.16)
    assert _charger(2.0, taux=1.20)._distance_tp_or(4120.0) == pytest.approx(2.40)


# ─── ⛔ INERTE par défaut, et sur chaque donnée manquante ─────────────────

def test_INERTE_quand_le_reglage_vaut_zero():
    """🔑 LE test qui compte : rien ne change tant que Xavier n'arme pas."""
    assert _charger(0.0)._distance_tp_or(4120.0) is None


def test_le_defaut_du_SOURCE_est_bien_zero():
    """⛔ Épingle le défaut dans le fichier, pas dans le harnais : un réglage
    arrivé à 2 par inadvertance changerait tous les objectifs de l'or."""
    src = _SRC.read_text(encoding="utf-8")
    ligne = next(l for l in src.splitlines() if l.startswith("XAU_TP_FIXE_EUR"))
    assert '"0"' in ligne, f"le defaut n'est plus inerte : {ligne!r}"


def test_un_reglage_NEGATIF_est_inerte_aussi():
    assert _charger(-2.0)._distance_tp_or(4120.0) is None


def test_taux_ILLISIBLE_rend_None_et_PAS_une_distance_devinee():
    """⚠️ Chemin d'un ordre réel : une cible de taille inconnue serait pire
    que de garder la règle en place."""
    for mauvais in (None, 0.0, -1.0):
        assert _charger(2.0, taux=mauvais)._distance_tp_or(4120.0) is None


def test_prix_ILLISIBLE_rend_None():
    m = _charger(2.0)
    for mauvais in (None, 0, -5, "abc"):
        assert m._distance_tp_or(mauvais) is None


# ─── La porte qui décide de l'appliquer ──────────────────────────────────

def test_le_chemin_generique_le_conditionne_a_l_or_ET_au_stop_uniforme():
    """⛔ Le laboratoire passe `stop_uniforme=False` : il doit garder SES
    objectifs, sinon les quatre contrôles du labo mesurent autre chose que la
    production — et on ne le verrait pas."""
    src = _SRC.read_text(encoding="utf-8")
    bloc = src[src.index("dist_tp = (_distance_tp_or(entry)"):]
    bloc = bloc[:400]
    assert "stop_uniforme" in bloc and "_est_de_l_or(pair)" in bloc


def test_TP2_EGALE_TP1_quand_l_objectif_fixe_est_arme():
    """⚠️ À 2 € de cible, un second palier à 3 R ferait croire à une gestion
    en deux temps qui n'existe pas."""
    src = _SRC.read_text(encoding="utf-8")
    bloc = src[src.index("if dist_tp is not None:"):]
    bloc = bloc[:300]
    assert "take_profit_2 = take_profit_1" in bloc


def test_le_stop_de_l_or_n_est_PAS_touche():
    """🔑 Le stop reste à 0,35 % : à 12 € la porte des frais refuserait tout
    (coût 0,03052 R contre un plafond de 0,0300)."""
    src = _SRC.read_text(encoding="utf-8")
    ligne = next(l for l in src.splitlines() if l.startswith("XAU_SL_PCT"))
    assert '"0.35"' in ligne, f"le stop de l'or a change : {ligne!r}"
