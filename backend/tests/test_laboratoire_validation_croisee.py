"""Un verdict sur UN instrument ne vaut rien : la validation croisée.

⛔ **Le trou que ça ferme.** Le laboratoire mesure 120 cellules — toutes sur
`XAU/USD`. Sur 120 tests, une cellule finit par dépasser le plafond **par
hasard** ; le plafond corrige ce risque, mais il ne dit **pas** si le résultat
se reproduit ailleurs.

Or c'est précisément ce que la mesure du 25/08 a établi : `PBO = 0,579` sur
l'argent réel — **sélectionner sur la performance mesurée ne généralise pas**,
pire que pile ou face. Un motif validé sur un seul instrument est exactement
l'objet que le PBO condamne.

⇒ Un motif qui bat le plafond sur **6 instruments sur 20** est une information
d'une tout autre nature qu'un motif qui le bat sur l'or seul.

## ⛔ Le piège : le plafond doit compter TOUS les tests

`mesurer()` calcule `plafond_hasard(len(cellules))` — les cellules **de cette
paire**. Lancer la mesure 20 fois produirait 20 plafonds calculés chacun comme
si l'on n'avait fait que 120 tests, alors qu'on en a fait 2 400.

**Ce serait la porte grande ouverte aux fausses découvertes** : plus on ajoute
d'instruments, plus on tire de billets, et un plafond par instrument ne le voit
pas. Le plafond doit être calculé sur le **total**, puis appliqué à toutes les
cellules.

Mesuré : 120 cellules → 2,81 · 2 400 cellules → **3,66**.

⚠️ Coût assumé : la barre monte pour tout le monde. C'est le prix d'une preuve
qui vaut quelque chose.
"""
import pytest

from backend.services import laboratoire_or as labo


def _cellule(pair, motif, t, n=60, horizon="5min", sens="buy"):
    return {"pair": pair, "motif": motif, "horizon": horizon, "sens": sens,
            "n": n, "r_moyen": 0.2, "t": t, "delta_hasard": 0.1}


# ─── Le plafond commun ───────────────────────────────────────────────

def test_le_plafond_compte_TOUTES_les_cellules_pas_celles_d_une_paire():
    """⛔ Le cœur. Vingt plafonds calculés sur 120 cellules chacun laisseraient
    passer ce qu'un plafond calculé sur 2 400 refuse."""
    par_paire = {f"P{i}": [_cellule(f"P{i}", "m", 3.0) for _ in range(120)]
                 for i in range(20)}
    plafond = labo.plafond_commun(par_paire)

    assert plafond == pytest.approx(labo.plafond_hasard(2400), abs=1e-6)
    assert plafond > labo.plafond_hasard(120), (
        "le plafond commun n'est pas plus exigeant que celui d'une seule paire")


def test_une_SEULE_paire_retombe_sur_le_plafond_habituel():
    """Rétrocompatible : le comportement d'aujourd'hui ne change pas."""
    par_paire = {"XAU/USD": [_cellule("XAU/USD", "m", 1.0) for _ in range(120)]}
    assert labo.plafond_commun(par_paire) == pytest.approx(
        labo.plafond_hasard(120), abs=1e-6)


def test_AUCUNE_cellule_ne_leve_pas():
    """Une nuit où rien n'a pu être mesuré ne doit pas tuer le cycle."""
    assert labo.plafond_commun({}) > 0


# ─── La concordance entre instruments ────────────────────────────────

def test_un_motif_qui_gagne_PARTOUT_est_signale():
    """Le cas qui vaut quelque chose : la même règle tient sur des marchés
    différents."""
    par_paire = {p: [_cellule(p, "fvg_up", 4.5), _cellule(p, "bruit", 0.2)]
                 for p in ("XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY")}
    conc = labo.concordance(par_paire, plafond=3.0)

    assert conc["fvg_up"]["instruments"] == 4
    assert conc["fvg_up"]["sur"] == 4
    assert "bruit" not in conc


def test_un_motif_qui_gagne_sur_UNE_SEULE_paire_est_signale_comme_tel():
    """⛔ Il ne doit pas disparaître — il doit apparaître AVEC son 1/4, pour
    qu'on lise l'isolement au lieu de le deviner."""
    par_paire = {p: [_cellule(p, "fvg_up", 4.5 if p == "XAU/USD" else 0.3)]
                 for p in ("XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY")}
    conc = labo.concordance(par_paire, plafond=3.0)

    assert conc["fvg_up"]["instruments"] == 1
    assert conc["fvg_up"]["sur"] == 4


def test_le_SIGNE_compte_une_concordance_doit_aller_dans_LE_MEME_sens():
    """⛔ Un motif qui gagne ici et perd là n'est pas « validé sur 2
    instruments » : c'est du bruit qui change de signe. Les compter ensemble
    fabriquerait une concordance."""
    par_paire = {
        "XAU/USD": [_cellule("XAU/USD", "m", +4.0)],
        "EUR/USD": [_cellule("EUR/USD", "m", -4.0)],
    }
    conc = labo.concordance(par_paire, plafond=3.0)
    assert conc["m"]["instruments"] == 1, (
        f"des signes opposes ont ete comptes ensemble : {conc['m']}")


def test_une_cellule_TROP_PAUVRE_ne_compte_pas():
    """Un `t` élevé sur n=4 n'est pas une victoire, c'est un petit
    échantillon."""
    par_paire = {p: [_cellule(p, "m", 5.0, n=4)]
                 for p in ("XAU/USD", "EUR/USD")}
    assert labo.concordance(par_paire, plafond=3.0) == {}


def test_la_concordance_rend_les_PAIRES_pour_pouvoir_verifier():
    """Un chiffre sans les noms n'est pas refaisable par un lecteur."""
    par_paire = {p: [_cellule(p, "m", 4.0)] for p in ("XAU/USD", "EUR/USD")}
    conc = labo.concordance(par_paire, plafond=3.0)
    assert set(conc["m"]["paires"]) == {"XAU/USD", "EUR/USD"}
