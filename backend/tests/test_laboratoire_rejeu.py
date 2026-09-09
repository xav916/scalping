"""Éprouver le REJEU — la dernière pièce non testée de la chaîne.

⛔ **Pourquoi c'est la plus dangereuse.** Si `_issue` simule mal la sortie, TOUS
les R sont faux : ceux des 120 cellules, ceux du contrôle positif qui valide le
laboratoire, et ceux qui serviraient un jour à décider d'armer un motif sur de
l'argent réel. Une erreur ici se propage jusqu'au bout sans jamais produire
d'erreur visible.

## Les quatre façons dont un rejeu ment

| biais | ce qu'il produit |
|---|---|
| **SL et TP dans la même bougie** | supposer le TP gonfle chaque cellule gagnante |
| **anticipation** | utiliser la bougie que le détecteur n'a pas vue |
| **coût oublié** | le spread payé sur les gagnants mais pas les perdants |
| **chevauchement** | rejouer le même mouvement plusieurs fois |

La docstring de `_issue` **affirme** que le stop passe avant l'objectif.
⚠️ *Un commentaire faux fait renoncer à mesurer* — ces tests le vérifient au
lieu de le croire.
"""
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import laboratoire_or as labo

_T0 = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _b(o, h, l, c, i=0):
    return {"t": _T0 + timedelta(minutes=5 * i), "o": o, "h": h, "l": l, "c": c}


# ─── Le biais le plus cher : SL ou TP dans la même bougie ────────────

def test_une_bougie_qui_contient_LES_DEUX_rend_le_STOP():
    """⛔ LE test. On ne sait pas lequel est venu en premier ; supposer
    l'objectif fabriquerait une performance sur chaque cellule gagnante."""
    bougies = [_b(100, 112, 88, 100, 0)]      # touche +12 ET -12
    R, _ = labo._issue(bougies, 0, entree=100.0, risque=10.0,
                       objectif_r=1.0, sens=1, cout=0.0)
    assert R == pytest.approx(-1.0), f"le rejeu a suppose l'objectif : R={R}"


def test_le_meme_piege_en_VENTE():
    bougies = [_b(100, 112, 88, 100, 0)]
    R, _ = labo._issue(bougies, 0, entree=100.0, risque=10.0,
                       objectif_r=1.0, sens=-1, cout=0.0)
    assert R == pytest.approx(-1.0)


def test_un_objectif_SEUL_est_bien_rendu():
    """Garde-fou : si le stop gagnait toujours, le rejeu ne rendrait jamais de
    gain et toutes les cellules seraient perdantes par construction."""
    bougies = [_b(100, 112, 99, 111, 0)]      # touche +12, jamais -10
    R, _ = labo._issue(bougies, 0, 100.0, 10.0, 1.0, 1, 0.0)
    assert R == pytest.approx(1.0)


# ─── Le coût doit être payé DANS LES DEUX SENS ───────────────────────

def test_le_spread_est_paye_sur_le_PERDANT():
    bougies = [_b(100, 101, 88, 90, 0)]
    R, _ = labo._issue(bougies, 0, 100.0, 10.0, 1.0, 1, cout=0.05)
    assert R == pytest.approx(-1.05)


def test_le_spread_est_paye_sur_le_GAGNANT():
    """⛔ Un coût prélevé sur les seuls perdants embellirait chaque cellule."""
    bougies = [_b(100, 112, 99, 111, 0)]
    R, _ = labo._issue(bougies, 0, 100.0, 10.0, 1.0, 1, cout=0.05)
    assert R == pytest.approx(0.95)


def test_le_spread_est_paye_meme_a_l_EXPIRATION():
    """La sortie par le temps est une sortie comme une autre : elle traverse
    le carnet et coûte le spread."""
    bougies = [_b(100, 101, 99, 100, i) for i in range(3)]
    R, _ = labo._issue(bougies, 0, 100.0, 10.0, 5.0, 1, cout=0.05)
    assert R == pytest.approx(-0.05), R


# ─── Pas d'anticipation ──────────────────────────────────────────────

def test_le_rejeu_n_utilise_PAS_les_bougies_d_avant_l_entree():
    """⛔ Un mouvement favorable AVANT l'entrée ne doit rien rapporter — sinon
    le rejeu lirait le passé comme s'il était tradable."""
    avant = [_b(100, 200, 100, 100, i) for i in range(5)]   # enorme hausse AVANT
    apres = [_b(100, 101, 88, 90, 5)]                       # stop touche APRES
    R, _ = labo._issue(avant + apres, 5, 100.0, 10.0, 1.0, 1, 0.0)
    assert R == pytest.approx(-1.0), (
        "le rejeu a compte un mouvement anterieur a l'entree")


def test_la_fenetre_de_DETECTION_exclut_la_bougie_d_entree():
    """⛔ L'invariant qui garantit l'absence d'anticipation dans la chaîne
    complète : `detections` regarde `bougies[i-FENETRE:i]`, donc la bougie `i`
    — celle sur laquelle le trade se résout — n'a PAS été vue du détecteur.

    Vérifié sur le SOURCE plutôt que par un scénario : c'est une propriété
    structurelle, et un scénario ne couvrirait qu'un cas.
    """
    import inspect
    src = inspect.getsource(labo.detections)
    assert "bougies[i - FENETRE:i]" in src, src
    src_rejeu = inspect.getsource(labo.rejouer_cellule)
    assert "_issue(bougies, i," in src_rejeu, src_rejeu


# ─── Pas de chevauchement ────────────────────────────────────────────

def test_deux_trades_ne_se_CHEVAUCHENT_jamais():
    """⛔ `i = sortie + 1` : rejouer le même mouvement deux fois multiplierait
    artificiellement le `n` et diviserait l'écart-type — donc gonflerait `t`,
    qui est exactement ce que le plafond du hasard borne."""
    import inspect
    src = inspect.getsource(labo.rejouer_cellule)
    assert "i = sortie + 1" in src, src


def test_la_tenue_est_BORNEE():
    """Un trade qui ne sort jamais fausserait la moyenne : il faut une borne,
    et elle doit mordre."""
    assert labo.MAX_BOUGIES_TENUE > 0
    plates = [_b(100, 100.1, 99.9, 100, i) for i in range(labo.MAX_BOUGIES_TENUE + 50)]
    _, sortie = labo._issue(plates, 0, 100.0, 10.0, 5.0, 1, 0.0)
    assert sortie <= labo.MAX_BOUGIES_TENUE, sortie


# ─── Le filtre des placebos ──────────────────────────────────────────

def test_un_stop_MINUSCULE_est_ecarte():
    """⛔ Un stop sous 0,1 % du prix rend des R de plusieurs centaines et fait
    exploser toute moyenne. 155 des 181 stops du réel étaient de ce genre."""
    assert labo.PLACEBO_PCT > 0
    import inspect
    src = inspect.getsource(labo.rejouer_cellule)
    assert "PLACEBO_PCT" in src and "continue" in src


def test_la_DERNIERE_bougie_possible_ne_leve_pas():
    """⚠️ Ma première version testait une série VIDE. Elle échouait — mais elle
    exigeait une propriété qui n'est pas requise : `rejouer_cellule` part de
    `i = FENETRE` et boucle tant que `i < n`, donc `_issue` ne reçoit jamais ni
    liste vide ni indice hors bornes.

    ⛔ Ajouter du code défensif pour une entrée impossible aurait été du poids
    mort que chaque lecteur futur devrait comprendre. On teste la VRAIE borne :
    le dernier indice atteignable, celui qui sort par expiration sans bougie
    suivante.
    """
    bougies = [_b(100, 100.1, 99.9, 100, i) for i in range(3)]
    R, sortie = labo._issue(bougies, len(bougies) - 1, 100.0, 10.0, 5.0, 1, 0.0)
    assert isinstance(R, float)
    assert sortie <= len(bougies)
