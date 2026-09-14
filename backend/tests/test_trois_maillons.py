"""Les trois maillons qui manquaient a la chaine — opening range, retest,
reintegration.

⛔ **Pourquoi ils existent** (declares le 2026-09-14 dans
`docs/concepts-trading.md`, commit `0977890`, AVANT la premiere ligne de code).
L'architecture rapportee par Xavier compte treize maillons ; ces trois
manquaient et ils sont **au milieu**, donc aucun n'etait contournable. Les
douze chaines du laboratoire s'arretaient a deux maillons parce que les
suivants n'existaient pas.

🔑 **Chaque detecteur est teste sur un cas qui declenche ET sur le cas voisin
qui ne doit PAS declencher.** Un detecteur qui dit oui partout est aussi
inutile qu'un detecteur muet — et bien plus dangereux, parce qu'il remplit le
laboratoire de cellules qui ressemblent a des resultats.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.models.schemas import Candle, PatternType
from backend.services.pattern_detector import detect_patterns

# 07:00 UTC = 08:00 a Londres en heure d'ete : l'ouverture de la session.
OUVERTURE_LONDRES = datetime(2026, 9, 14, 7, 0, tzinfo=timezone.utc)


def _bougies(specs, depart=None, pas_min=5):
    """`[(ouverture, haut, bas, cloture), ...]` -> bougies horodatees."""
    t0 = depart or datetime(2026, 9, 14, 1, 0, tzinfo=timezone.utc)
    return [Candle(timestamp=t0 + timedelta(minutes=pas_min * i),
                   open=o, high=h, low=b, close=c, volume=0)
            for i, (o, h, b, c) in enumerate(specs)]


def _plat(n, prix=100.0, amplitude=0.2):
    """Des bougies calmes, pour remplir la fenetre de reference."""
    return [(prix, prix + amplitude, prix - amplitude, prix)] * n


def _motifs(bougies):
    return {p.pattern for p in detect_patterns(bougies)}


# ─── 1. Opening Range ───────────────────────────────────────────────

def test_opening_range_haussier_declenche_sur_la_cassure_du_range():
    # 6 bougies de range (30 min) depuis l'ouverture de Londres, puis cassure.
    avant = _plat(26)
    dans_le_range = [(100.0, 100.5, 99.5, 100.0)] * 6
    apres = [(100.0, 100.6, 99.9, 100.2), (100.2, 101.5, 100.1, 101.4)]
    b = _bougies(avant + dans_le_range + apres,
                 depart=OUVERTURE_LONDRES - timedelta(minutes=5 * 26))
    assert PatternType.OPENING_RANGE_UP in _motifs(b)


def test_opening_range_ne_declenche_PAS_pendant_la_formation_du_range():
    """⛔ Une cassure a l'interieur des 30 premieres minutes ne casse rien :
    le range n'est pas encore forme."""
    avant = _plat(26)
    dedans = [(100.0, 100.5, 99.5, 100.0), (100.0, 101.5, 99.9, 101.4)]
    b = _bougies(avant + dedans,
                 depart=OUVERTURE_LONDRES - timedelta(minutes=5 * 26))
    assert PatternType.OPENING_RANGE_UP not in _motifs(b)


def test_opening_range_ne_declenche_PAS_hors_session():
    """Le meme prix, huit heures apres l'ouverture : ce n'est plus ce range."""
    avant = _plat(26)
    suite = [(100.0, 100.5, 99.5, 100.0)] * 6 + [(100.0, 101.5, 99.9, 101.4)]
    b = _bougies(avant + suite,
                 depart=OUVERTURE_LONDRES + timedelta(hours=10))
    assert PatternType.OPENING_RANGE_UP not in _motifs(b)


# ─── 2. Retest ──────────────────────────────────────────────────────

def test_retest_haussier_declenche_quand_le_niveau_TIENT():
    reference = _plat(20)                       # niveau = 100,2
    cassure = [(100.0, 101.0, 100.0, 100.9)]    # cloture au-dessus
    derive = [(100.9, 101.1, 100.5, 100.8)] * 7
    retour = [(100.8, 101.0, 100.1, 100.7)]     # revient toucher, tient
    b = _bougies(reference + cassure + derive + retour)
    assert PatternType.RETEST_UP in _motifs(b)


def test_retest_ne_declenche_PAS_si_le_niveau_LACHE():
    reference = _plat(20)
    cassure = [(100.0, 101.0, 100.0, 100.9)]
    derive = [(100.9, 101.1, 100.5, 100.8)] * 7
    lache = [(100.8, 101.0, 100.1, 100.0)]      # cloture SOUS le niveau
    b = _bougies(reference + cassure + derive + lache)
    assert PatternType.RETEST_UP not in _motifs(b)


def test_retest_ne_declenche_PAS_sans_cassure_prealable():
    """Toucher un niveau qui n'a jamais ete casse n'est pas un retest."""
    b = _bougies(_plat(28) + [(100.0, 100.3, 99.8, 100.25)])
    assert PatternType.RETEST_UP not in _motifs(b)


# ─── 3. Reintegration ───────────────────────────────────────────────

def test_reintegration_baissiere_declenche_apres_acceptation_dehors():
    reference = _plat(27)                        # niveau = 100,2
    dehors = [(100.3, 100.9, 100.3, 100.8),      # deux CLOTURES au-dessus
              (100.8, 101.0, 100.4, 100.7)]
    rentre = [(100.7, 100.8, 99.8, 100.0)]       # cloture en deca
    b = _bougies(reference + dehors + rentre)
    assert PatternType.REINTEGRATION_DOWN in _motifs(b)


def test_reintegration_ne_declenche_PAS_sur_une_simple_MECHE():
    """⛔ Le critere qui la separe du balayage est la CLOTURE. Une meche
    rejetee dans la meme bougie est un balayage, pas une reintegration."""
    reference = _plat(27)
    meche = [(100.0, 101.0, 99.9, 100.0), (100.0, 100.9, 99.9, 100.0)]
    rentre = [(100.0, 100.2, 99.5, 99.8)]
    b = _bougies(reference + meche + rentre)
    motifs = _motifs(b)
    assert PatternType.REINTEGRATION_DOWN not in motifs


def test_reintegration_ne_declenche_PAS_si_le_prix_reste_dehors():
    reference = _plat(27)
    dehors = [(100.3, 100.9, 100.3, 100.8), (100.8, 101.0, 100.4, 100.7)]
    reste = [(100.7, 101.2, 100.6, 101.1)]       # toujours au-dessus
    b = _bougies(reference + dehors + reste)
    assert PatternType.REINTEGRATION_DOWN not in _motifs(b)


# ─── Ce que les trois doivent respecter ─────────────────────────────

@pytest.mark.parametrize("motif", [
    PatternType.OPENING_RANGE_UP, PatternType.OPENING_RANGE_DOWN,
    PatternType.RETEST_UP, PatternType.RETEST_DOWN,
    PatternType.REINTEGRATION_UP, PatternType.REINTEGRATION_DOWN,
])
def test_les_six_motifs_ont_un_sens_lisible_dans_leur_nom(motif):
    """Le defaut du 14/09 : neuf motifs haussiers vendaient. Ces six-la
    passent par la regle de nom des leur naissance."""
    from backend.services.pattern_detector import _est_un_achat
    assert _est_un_achat(motif) is motif.name.endswith("_UP")


def test_les_sessions_ne_sont_declarees_QU_UNE_FOIS():
    """⛔ Deux tables d'heures de session finiraient par diverger, et deux
    mesures porteraient le meme nom en decrivant deux fenetres."""
    from backend.services import laboratoire_or as labo
    from backend.services import sessions_marche as sm
    assert labo._SESSIONS is sm.SESSIONS
