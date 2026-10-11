"""Le PLAFOND DE LARGEUR du stop — le « 9 euros » de Xavier, là où il tient.

> Xavier, 2026-10-11, deux fois : « le plancher serait à 13 euros, est-ce que
> je l'ai ? Moi, je l'avais demandé à 9 euros. »

## ⛔ POURQUOI 9 € EST IMPOSSIBLE À L'OUVERTURE — de l'arithmétique

    la porte des frais exige   cout_r <= 0,30 x edge_r
    ce qui impose un stop      >= prix / 300
    à un or à 4 150 $          >= 13,83 $  =  12,35 €
    son 9 €  vaut                10,08 $   =  **27 % sous le plancher**

Et la conséquence est **mesurée** : avec un stop fixe de 10 €, l'or est resté
**muet trois jours** en octobre 2026 (`fees_exceed_edge`, 1 238 refus).

## ✅ POURQUOI 9 € TIENT DU CÔTÉ DE LA PERTE

Le trade **ouvre** à 0,35 % du prix (≈ 13 €) — ce que le courtier et la porte
des frais exigent — puis, **dès le premier passage éligible**, le stop est
ramené à **9 € au plus**. L'ouverture satisfait la porte, la vie du trade
satisfait Xavier.

## ⚠️ CE QUE CES TESTS NE PROUVENT PAS

Que la perte est bornée à 9 € par les mathématiques. Deux fuites subsistent :
l'**âge minimal** (avant lui, seul le stop d'ouverture protège) et un **saut
de cours** entre deux passages. Le plafond dit « la perte ne croît plus
au-delà de 9 € **une fois qu'on l'a vue** ».
"""
from __future__ import annotations

import importlib

import pytest


def _module(monkeypatch, **env):
    """Recharge le script avec un environnement donné (les réglages sont lus
    au chargement pour `FENETRE_SEC`, mais le plafond est lu à CHAQUE appel —
    ce test vérifie justement les deux comportements)."""
    import scripts.protection_perte_or as P
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    return importlib.reload(P)


@pytest.fixture
def P(monkeypatch):
    return _module(monkeypatch, PROTECTION_PERTE_LARGEUR_MAX_EUR=None,
                   PROTECTION_PERTE_PLANCHER_EUR=None)


# ─── Inerte par défaut ───────────────────────────────────────────────────

def test_inerte_par_defaut(P):
    assert P._largeur_max_eur() is None


def test_sans_plafond_le_point_milieu_est_inchange(P):
    # 13 € de stop, 3 € de perte -> le milieu, exactement comme avant
    assert P.nouveau_stop_eur(13.0, 3.0) == pytest.approx(8.0)


@pytest.mark.parametrize("brut", ["", "   ", "neuf", "abc", "0", "-1", "-9"])
def test_une_valeur_illisible_ou_negative_ne_pose_aucun_plafond(
        P, monkeypatch, brut):
    monkeypatch.setenv("PROTECTION_PERTE_LARGEUR_MAX_EUR", brut)
    assert P._largeur_max_eur() is None
    # et la décision reste celle d'avant
    assert P.nouveau_stop_eur(13.0, 3.0) == pytest.approx(8.0)


@pytest.mark.parametrize("brut,attendu", [("9", 9.0), ("9.0", 9.0),
                                          (" 9.5 ", 9.5), ("2", 2.0)])
def test_le_plafond_se_lit(P, monkeypatch, brut, attendu):
    monkeypatch.setenv("PROTECTION_PERTE_LARGEUR_MAX_EUR", brut)
    assert P._largeur_max_eur() == pytest.approx(attendu)


# ─── Le cœur : le 9 € est servi dès le PREMIER passage ───────────────────

def test_le_stop_tombe_a_9_des_le_premier_passage(P, monkeypatch):
    """⛔ C'est la différence qui compte pour Xavier. Sans plafond, depuis 13 €
    avec 6 € de perte, le point milieu donne 9,50 € et il faut DEUX passages
    de plus pour descendre sous 9. Avec le plafond : 9 tout de suite."""
    monkeypatch.delenv("PROTECTION_PERTE_LARGEUR_MAX_EUR", raising=False)
    assert P.nouveau_stop_eur(13.0, 6.0) == pytest.approx(9.5)

    monkeypatch.setenv("PROTECTION_PERTE_LARGEUR_MAX_EUR", "9")
    assert P.nouveau_stop_eur(13.0, 6.0) == pytest.approx(9.0)


def test_sous_le_plafond_le_point_milieu_garde_la_parole(P, monkeypatch):
    """Le plafond n'est pas un plancher : quand le milieu est DÉJÀ plus serré
    que 9, c'est lui qui s'applique — le resserrage continue vers −2 €."""
    monkeypatch.setenv("PROTECTION_PERTE_LARGEUR_MAX_EUR", "9")
    monkeypatch.setenv("PROTECTION_PERTE_PLANCHER_EUR", "2")
    # 9 € de stop, 1 € de perte -> milieu 5,0, bien sous le plafond
    assert P.nouveau_stop_eur(9.0, 1.0) == pytest.approx(5.0)
    # puis 5 -> 3 -> 2 (le plancher absolu)
    assert P.nouveau_stop_eur(5.0, 1.0) == pytest.approx(3.0)
    assert P.nouveau_stop_eur(3.0, 1.0) == pytest.approx(2.0)
    assert P.nouveau_stop_eur(2.0, 1.0) is None


def test_la_descente_complete_depuis_13_euros(P, monkeypatch):
    """La trajectoire que Xavier verra, avec 3 € de perte stable."""
    monkeypatch.setenv("PROTECTION_PERTE_LARGEUR_MAX_EUR", "9")
    monkeypatch.setenv("PROTECTION_PERTE_PLANCHER_EUR", "2")
    stop, vus = 13.0, []
    for _ in range(12):
        v = P.nouveau_stop_eur(stop, 3.0)
        if v is None:
            break
        stop = v
        vus.append(round(stop, 4))
    assert vus[0] == pytest.approx(8.0), "le milieu suffit déjà : 8 < 9"
    assert all(b < a for a, b in zip(vus, vus[1:])), "jamais de desserrage"
    # 🔑 CE QUE J'AVAIS FAUX, et c'est instructif : je croyais qu'on finissait
    # au plancher absolu de 2 €. Non — le point milieu converge vers LA PERTE
    # (3 €), jamais en dessous, et le plancher absolu ne mord donc que pour une
    # perte inférieure à lui. Le stop talonne le cours ; il ne le dépasse pas.
    assert 3.0 < vus[-1] < 3.3, f"converge vers la perte, pas vers 2 : {vus[-1]}"
    assert P.nouveau_stop_eur(2.5, 0.1) == pytest.approx(2.0), (
        "pour une perte SOUS le plancher, c'est bien 2 € qui s'applique")


# ─── Les deux gardes, prouvées par ce qui casse quand on les retire ──────

def test_le_plafond_ne_passe_jamais_derriere_le_cours(P, monkeypatch):
    """⛔ Perte 10 €, plafond 9 € : poser le stop à 9 le mettrait DERRIÈRE le
    prix. On colle au cours à la place.

    Réinjection : remplacer `max(largeur_max, perte + marge)` par
    `largeur_max` seul rend 9.0 et ce test tombe."""
    monkeypatch.setenv("PROTECTION_PERTE_LARGEUR_MAX_EUR", "9")
    monkeypatch.setenv("PROTECTION_PERTE_PLANCHER_EUR", "2")
    v = P.nouveau_stop_eur(13.0, 10.0)
    assert v is not None
    assert v > 10.0, f"stop {v} derrière un cours à 10 € de perte"


def test_le_plafond_n_elargit_jamais(P, monkeypatch):
    """⛔ LE DÉFAUT DE MON PREMIER JET. J'avais écrit
    `vise = max(plafond, perte + marge)` : à une perte de 10 € pour un plafond
    de 9, il rendait **12** là où le point milieu donnait **11,5**. Un plafond
    qui ÉLARGIT le stop.

    Réinjection : retirer le `min(vise, ...)` et ce test tombe."""
    monkeypatch.delenv("PROTECTION_PERTE_LARGEUR_MAX_EUR", raising=False)
    sans = P.nouveau_stop_eur(13.0, 10.0)
    monkeypatch.setenv("PROTECTION_PERTE_LARGEUR_MAX_EUR", "9")
    avec = P.nouveau_stop_eur(13.0, 10.0)
    # 🔑 Et ici j'avais annoncé 11,5 (le point milieu) : c'est 12, parce que
    # `MARGE_MIN_EUR` vaut 2 € et que le plancher du cours (`perte + 2`) mord
    # AVANT le milieu. Mon arithmétique était fausse, pas le code.
    assert sans == pytest.approx(12.0)
    assert avec is not None and avec <= sans + 1e-9, (
        f"le plafond a ÉLARGI le stop : {avec} > {sans}")


def test_le_cliquet_tient_malgre_le_plafond(P, monkeypatch):
    """Un stop DÉJÀ plus serré que le plafond ne doit jamais être desserré
    jusqu'à 9."""
    monkeypatch.setenv("PROTECTION_PERTE_LARGEUR_MAX_EUR", "9")
    monkeypatch.setenv("PROTECTION_PERTE_PLANCHER_EUR", "2")
    assert P.nouveau_stop_eur(4.0, 0.5) == pytest.approx(2.25)
    v = P.nouveau_stop_eur(2.5, 0.2)
    assert v is None or v < 2.5


# ─── L'invariant, sur toute la grille ────────────────────────────────────

def test_invariant_sur_la_grille(P, monkeypatch):
    """Sur 2 000 configurations : le plafond ne desserre jamais, ne passe
    jamais derrière le cours, et ne rend jamais une valeur plus grande que
    sans lui."""
    monkeypatch.setenv("PROTECTION_PERTE_PLANCHER_EUR", "2")
    for stop_c in range(2, 42):          # 0,5 € à 20,5 €
        stop = stop_c / 2.0
        for perte_c in range(1, 51):     # 0,1 € à 5,0 €
            perte = perte_c / 10.0
            monkeypatch.delenv("PROTECTION_PERTE_LARGEUR_MAX_EUR",
                               raising=False)
            sans = P.nouveau_stop_eur(stop, perte)
            monkeypatch.setenv("PROTECTION_PERTE_LARGEUR_MAX_EUR", "9")
            avec = P.nouveau_stop_eur(stop, perte)
            if avec is None:
                continue
            assert avec < stop, f"desserrage {stop} -> {avec}"
            assert avec > perte, f"stop {avec} derrière un cours à {perte}"
            if sans is not None:
                assert avec <= sans + 1e-9, (
                    f"stop={stop} perte={perte} : plafond élargit "
                    f"{sans} -> {avec}")
