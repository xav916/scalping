"""Le plancher du stop indexé sur le SPREAD, pas sur un montant fixe.

> Xavier, 2026-10-12 : « ne plus avoir la limite de SL à moins 2, mais
> toujours la division par 2 » — puis, après mes objections, « avoir comme
> variable le spread ».

## ✅ CE QUE LA MESURE A DIT

Banc pré-inscrit en `45b2526`, 3 298 970 ticks, 4 115 positions, 15 jours :

    A production (plancher 2,00)   moyenne +0,0000   pire jour -0,151
    B plancher au spread           moyenne -0,0032   pire jour -0,129

Rendement identique au bruit près (`t = -0,81`), **pire journée améliorée de
15 %**, réussite quasi inchangée. Et la mesure confirme l'intuition de Xavier :
le plancher de 2 € était **quasi décoratif**, parce que le point milieu
converge vers la PERTE et non vers le plancher.

⛔ Son second souhait — passer le stop à l'équilibre dès le premier centime —
a été mesuré puis **écarté** : 51 % de trades nuls pour un rendement
indistinguable.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def P(monkeypatch):
    import scripts.protection_perte_or as mod
    monkeypatch.delenv("PROTECTION_PERTE_PLANCHER_SPREAD_K", raising=False)
    monkeypatch.delenv("PROTECTION_PERTE_PLANCHER_EUR", raising=False)
    return importlib.reload(mod)


# ─── ① Inerte par défaut ─────────────────────────────────────────────────

def test_inerte_par_defaut(P):
    assert P._plancher_spread_k() is None


@pytest.mark.parametrize("brut", ["", "   ", "deux", "0", "-1"])
def test_une_valeur_illisible_ou_nulle_ne_pose_aucun_plancher(P, monkeypatch, brut):
    monkeypatch.setenv("PROTECTION_PERTE_PLANCHER_SPREAD_K", brut)
    assert P._plancher_spread_k() is None
    # et le comportement d'avant est conservé au centime
    assert P.nouveau_stop_eur(13.0, 3.0, spread_eur_courant=0.07) == pytest.approx(8.0)


@pytest.mark.parametrize("brut,attendu", [("1", 1.0), ("2", 2.0), (" 1.5 ", 1.5)])
def test_le_k_se_lit(P, monkeypatch, brut, attendu):
    monkeypatch.setenv("PROTECTION_PERTE_PLANCHER_SPREAD_K", brut)
    assert P._plancher_spread_k() == pytest.approx(attendu)


# ─── ② Le plancher suit vraiment le spread ───────────────────────────────

def test_la_descente_va_jusqu_a_k_fois_le_spread(P, monkeypatch):
    """⛔ LE CŒUR. Avant, la descente s'arrêtait à 2,00 €. Elle doit
    maintenant atteindre `k × spread`."""
    monkeypatch.setenv("PROTECTION_PERTE_PLANCHER_SPREAD_K", "2")
    sp = 0.0714                      # le spread médian mesuré
    stop, vus = 13.0, []
    for _ in range(20):
        v = P.nouveau_stop_eur(stop, 0.05, spread_eur_courant=sp)
        if v is None:
            break
        stop = v
        vus.append(stop)
    assert vus, "aucun resserrage"
    assert vus[-1] == pytest.approx(2 * sp, abs=1e-6), (
        f"la descente s'arrête à {vus[-1]:.3f} au lieu de {2 * sp:.3f}")
    assert all(b < a for a, b in zip(vus, vus[1:])), "jamais de desserrage"


def test_un_spread_LARGE_durcit_le_plancher(P, monkeypatch):
    """🔑 Tout l'intérêt : à la réouverture du dimanche le spread valait
    19 points (0,38 €). Le plancher se durcit alors tout seul."""
    monkeypatch.setenv("PROTECTION_PERTE_PLANCHER_SPREAD_K", "2")

    def fond(sp):
        stop = 13.0
        for _ in range(30):
            v = P.nouveau_stop_eur(stop, 0.05, spread_eur_courant=sp)
            if v is None:
                return stop
            stop = v
        return stop

    calme, cher = fond(0.0714), fond(0.38)
    assert cher > calme, f"plancher cher {cher} <= calme {calme}"
    assert cher == pytest.approx(0.76, abs=1e-6)


def test_un_spread_ILLISIBLE_retombe_sur_le_plancher_fixe(P, monkeypatch, caplog):
    """⛔ Un plancher calculé sur un spread devine serait posé sur de l'argent
    réel. On retombe, et on le DIT."""
    monkeypatch.setenv("PROTECTION_PERTE_PLANCHER_SPREAD_K", "2")
    with caplog.at_level("WARNING"):
        v = P.nouveau_stop_eur(2.5, 0.05, spread_eur_courant=None)
    assert any("spread illisible" in r.message for r in caplog.records)
    # comportement d'avant : le plancher reste `perte + marge` = 2,05
    assert v is None or v >= 2.0


# ─── ③ La garde qui a déjà coûté : le réglage ne doit pas être INERTE ────

def test_le_spread_est_bien_TRANSMIS_par_l_appelant(P):
    """⛔ LE DÉFAUT À NE PAS REFAIRE. Si l'appelant ne passe pas le spread,
    `_plancher_spread_k` trouve son k, ne reçoit rien, et retombe sur le
    plancher fixe EN SILENCE : un réglage armé et inerte. C'est exactement
    `XAU_SL_FIXE_EUR` la veille."""
    import inspect
    src = inspect.getsource(P)
    assert "spread_eur_courant=sp" in src, "l'appel ne transmet pas le spread"
    i = src.index("vise_eur = nouveau_stop_eur")
    avant = src[max(0, i - 400):i]
    assert "spread_eur(" in avant, "le spread n'est pas lu avant l'appel"


def test_le_plancher_ne_passe_jamais_derriere_le_cours(P, monkeypatch):
    """La garde d'origine tient : perte 10 €, plancher 0,14 € — le stop ne
    doit pas se poser derrière le prix."""
    monkeypatch.setenv("PROTECTION_PERTE_PLANCHER_SPREAD_K", "2")
    v = P.nouveau_stop_eur(13.0, 10.0, spread_eur_courant=0.0714)
    assert v is None or v > 10.0, f"stop {v} derrière un cours à 10 € de perte"


def test_le_plancher_au_spread_n_elargit_jamais(P, monkeypatch):
    monkeypatch.setenv("PROTECTION_PERTE_PLANCHER_SPREAD_K", "2")
    for perte in (0.05, 0.5, 1.0, 3.0, 6.0):
        for stop in (13.0, 9.0, 4.0, 2.0, 0.5):
            v = P.nouveau_stop_eur(stop, perte, spread_eur_courant=0.0714)
            if v is not None:
                assert v < stop, f"desserrage {stop} -> {v} (perte {perte})"


def test_la_lecture_du_spread_ne_leve_jamais(P):
    """Sans réseau, `spread_eur` doit rendre None, pas exploser."""
    assert P.spread_eur("XAU/USD", 1.125) is None or isinstance(
        P.spread_eur("XAU/USD", 1.125), float)
    assert P.spread_eur("XAU/USD", 0) is None


# ─── ④ La couverture que la RÉINJECTION a révélée manquante ──────────────

def test_le_plafond_de_largeur_ne_reimpose_pas_les_2_EUR_en_dur(P, monkeypatch):
    """⛔ TROUVÉ PAR RÉINJECTION, pas par relecture.

    Retirer `marge_min_eur = k * spread` laissait mes 8 premiers tests VERTS :
    le plancher suit le spread, donc rien ne bougeait. Sauf que `marge_min_eur`
    ressort plus bas dans le plafond de largeur — `min(vise, max(largeur_max,
    perte + marge_min_eur))`. Avec `PROTECTION_PERTE_LARGEUR_MAX_EUR` armé,
    les 2,00 € en dur redeviendraient dominants et le réglage serait à moitié
    inerte, SANS qu'aucun test ne proteste.

    🔑 Une réinjection qui ne mord pas est une couverture manquante, jamais
    une bonne nouvelle. Ce test est cette couverture.
    """
    monkeypatch.setenv("PROTECTION_PERTE_PLANCHER_SPREAD_K", "2")
    monkeypatch.setenv("PROTECTION_PERTE_LARGEUR_MAX_EUR", "9")
    sp = 0.0714                                  # k × spread = 0,143

    # Perte 10 € > plafond 9 € : la branche `max(largeur_max, perte + marge)`
    # est la seule à décider. Elle doit coller au cours à un spread indexé,
    # soit 10,143 — et non 12,00 comme avec la marge fixe de 2 €.
    v = P.nouveau_stop_eur(13.0, 10.0, spread_eur_courant=sp)
    assert v is not None, "aucun resserrage alors que 13 > plafond"
    assert v == pytest.approx(10.0 + 2 * sp, abs=1e-6), (
        f"stop {v:.3f} : la marge au cours n'est pas indexée sur le spread "
        f"(attendu {10.0 + 2 * sp:.3f}, le fixe aurait donné 12,000)")
    assert v < 12.0, "les 2,00 EUR en dur dominent encore"


def test_sans_spread_le_plafond_garde_son_comportement_d_avant(P, monkeypatch):
    """Et la non-régression : sans le réglage, 12,00 € à l'identique."""
    monkeypatch.setenv("PROTECTION_PERTE_LARGEUR_MAX_EUR", "9")
    assert P.nouveau_stop_eur(13.0, 10.0) == pytest.approx(12.0)
