"""La double prise de liquidité — et pourquoi elle doit battre la simple.

Codée le 2026-09-12, à la demande de Xavier, sur un corpus qui la donne comme
centrale. ⚠️ Elle est donc ici parce qu'on veut l'éprouver, **pas** parce
qu'une mesure l'aurait suggérée.

## L'idée

Une poche de liquidité prise **une seule fois** peut n'être qu'un dépassement
ordinaire. Prise **deux fois** et rejetée deux fois, elle dit que quelqu'un
défend ce niveau. C'est la deuxième prise qui porte l'information.

## La règle, sans aucun réglage neuf

```
niveau  = max(haut) de la PREMIERE MOITIE des 30 bougies de reference
compte  = bougies de la SECONDE MOITIE (derniere incluse) telles que
          haut > niveau  ET  cloture < niveau
double  <=>  compte >= 2  ET  la derniere bougie en fait partie
```

- les **30 bougies** viennent de `_detect_breakout` ;
- la **coupe en deux moitiés** est l'idiome déjà employé par
  `_tendance_de_structure` (« on coupe en deux la fenêtre de 30 déjà
  utilisée ») ;
- le « **deux fois** » est la définition du concept, pas un paramètre.

Chaque seuil neuf est un degré de liberté, donc de l'edge fabriqué.

## ⛔ La prédiction falsifiable

`double_sweep_down` doit rendre un **R moyen supérieur** à
`liquidity_sweep_down`, même instrument, même échelle. **Si le double ne bat
pas le simple, la notion n'ajoute rien** — et c'est exactement le genre de
résultat que ce laboratoire existe pour rendre.

## ⚠️ Recouvrement TOTAL avec le balayage simple

Toute double prise est aussi un balayage simple sur sa dernière bougie. Les
deux cellules ne sont donc **pas** deux tests indépendants — et c'est
précisément ce qui rend leur comparaison lisible : elle est **appariée**.

Un test le vérifie plutôt que de le supposer : c'est en croyant un recouvrement
« vrai par construction » que je me suis trompé sur `breakout` le 09/09.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.models.schemas import Candle, PatternType
from backend.services.pattern_detector import detect_patterns

_FIXTURE = Path(__file__).parent / "fixtures" / "bougies_xauusd_5min.json"
_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _c(i, o, h, l, c):
    return Candle(timestamp=_T0 + timedelta(minutes=5 * i),
                  open=o, high=h, low=l, close=c, volume=0.0)


def _serie_plate(n=31, base=100.0):
    """Une série sans relief : toute détection viendra de ce qu'on y ajoute."""
    return [_c(i, base, base + 0.5, base - 0.5, base) for i in range(n)]


def _motifs(candles):
    return {p.pattern for p in detect_patterns(candles, "XAU/USD")}


# ─── La détection ───────────────────────────────────────────────────


def test_DEUX_prises_de_la_meme_poche_sont_detectees():
    """La poche est posée dans la première moitié, prise deux fois ensuite."""
    s = _serie_plate(31)
    s[5] = _c(5, 100.0, 103.0, 99.5, 100.0)     # la poche : 103
    s[20] = _c(20, 100.0, 104.0, 99.5, 100.5)   # 1re prise, rejetee
    s[30] = _c(30, 100.0, 104.5, 99.5, 100.5)   # 2e prise, rejetee
    assert PatternType.DOUBLE_SWEEP_DOWN in _motifs(s)


def test_UNE_seule_prise_n_est_PAS_un_double():
    s = _serie_plate(31)
    s[5] = _c(5, 100.0, 103.0, 99.5, 100.0)
    s[30] = _c(30, 100.0, 104.5, 99.5, 100.5)
    assert PatternType.DOUBLE_SWEEP_DOWN not in _motifs(s)


def test_la_DERNIERE_bougie_doit_faire_partie_des_prises():
    """⛔ Sinon le signal appartient au passé : deux prises il y a dix bougies
    ne disent rien de l'instant où l'on entrerait."""
    s = _serie_plate(31)
    s[5] = _c(5, 100.0, 103.0, 99.5, 100.0)
    s[18] = _c(18, 100.0, 104.0, 99.5, 100.5)
    s[20] = _c(20, 100.0, 104.2, 99.5, 100.5)
    # la dernière est plate
    assert PatternType.DOUBLE_SWEEP_DOWN not in _motifs(s)


def test_une_prise_NON_REJETEE_ne_compte_pas():
    """⚠️ Clôturer au-dessus du niveau, c'est une cassure, pas une prise. Les
    confondre ferait compter une continuation comme un retournement."""
    s = _serie_plate(31)
    s[5] = _c(5, 100.0, 103.0, 99.5, 100.0)
    s[20] = _c(20, 100.0, 104.0, 99.5, 103.8)   # cloture AU-DESSUS : cassure
    s[30] = _c(30, 100.0, 104.5, 99.5, 100.5)
    assert PatternType.DOUBLE_SWEEP_DOWN not in _motifs(s)


def test_le_sens_BAS_est_le_miroir():
    """Deux prises des bas ⇒ signal d'ACHAT."""
    s = _serie_plate(31)
    s[5] = _c(5, 100.0, 100.5, 97.0, 100.0)     # la poche basse : 97
    s[20] = _c(20, 100.0, 100.5, 96.0, 99.5)
    s[30] = _c(30, 100.0, 100.5, 95.5, 99.5)
    assert PatternType.DOUBLE_SWEEP_UP in _motifs(s)


def test_une_serie_trop_COURTE_ne_leve_pas():
    assert PatternType.DOUBLE_SWEEP_DOWN not in _motifs(_serie_plate(12))


# ─── Le libellé ─────────────────────────────────────────────────────


def test_les_deux_motifs_ont_un_libelle_francais():
    """Un test du dépôt l'exige déjà pour tous les motifs ; on le vérifie ici
    pour que l'échec pointe le bon concept."""
    from backend.services.telegram_service import _PATTERN_EXPLAIN_FR
    for p in (PatternType.DOUBLE_SWEEP_UP, PatternType.DOUBLE_SWEEP_DOWN):
        assert p.value in _PATTERN_EXPLAIN_FR, f"{p.value} sans libelle FR"


# ─── La porte de fréquence, sur de VRAIES bougies ───────────────────


@pytest.fixture(scope="module")
def bougies_reelles():
    # ⚠️ La fixture stocke des quadruplets `[o, h, l, c]`, pas des
    # dictionnaires. Mon premier chargeur supposait des cles nommees et
    # rendait une TypeError — le banc avait raison, pas moi.
    brut = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return [Candle(timestamp=_T0 + timedelta(minutes=5 * i),
                   open=o, high=h, low=b, close=c, volume=0.0)
            for i, (o, h, b, c) in enumerate(brut)]


def _fenetres(bougies, pas=7):
    """⛔ Fenêtre GLISSANTE de 50, comme la production. Passer un préfixe
    croissant mesurerait un détecteur qui n'existe pas — le banc a déjà dérivé
    comme ça le 09/09."""
    for i in range(50, len(bougies), pas):
        yield bougies[i - 50:i]


def test_la_double_prise_se_declenche_AU_MOINS_une_fois(bougies_reelles):
    """⛔ Un motif qui ne se déclenche jamais n'est pas prudent, il est mort :
    sa cellule n'existerait pas et son silence passerait pour un verdict."""
    vus = 0
    for fen in _fenetres(bougies_reelles):
        m = _motifs(fen)
        if {PatternType.DOUBLE_SWEEP_UP, PatternType.DOUBLE_SWEEP_DOWN} & m:
            vus += 1
    assert vus > 0, "la double prise ne se declenche JAMAIS sur 5 000 bougies"


def test_la_double_prise_reste_RARE(bougies_reelles):
    """⚠️ Au-delà de 25 % des fenêtres, un motif ne décrit plus un événement :
    il décrit le marché, et son R moyen se confondra avec celui de l'actif."""
    total = sum(1 for _ in _fenetres(bougies_reelles))
    vus = sum(1 for fen in _fenetres(bougies_reelles)
              if {PatternType.DOUBLE_SWEEP_UP,
                  PatternType.DOUBLE_SWEEP_DOWN} & _motifs(fen))
    part = vus / total
    assert part < 0.25, f"double prise sur {part:.0%} des fenetres — trop frequent"


def test_la_double_prise_est_PLUS_RARE_que_la_simple(bougies_reelles):
    """🔑 Le contrôle de cohérence du concept. Exiger DEUX prises ne peut pas
    produire PLUS de signaux qu'en exiger une — si c'était le cas, le
    détecteur ne mesurerait pas ce que son nom annonce."""
    doubles = simples = 0
    for fen in _fenetres(bougies_reelles):
        m = _motifs(fen)
        if {PatternType.DOUBLE_SWEEP_UP, PatternType.DOUBLE_SWEEP_DOWN} & m:
            doubles += 1
        if {PatternType.LIQUIDITY_SWEEP_UP, PatternType.LIQUIDITY_SWEEP_DOWN} & m:
            simples += 1
    assert doubles <= simples, (
        f"{doubles} doubles pour {simples} simples — impossible")


def test_le_recouvrement_avec_le_simple_est_MESURE(bougies_reelles):
    """⚠️ Je l'annonce total. Je le VÉRIFIE — c'est en croyant un recouvrement
    « vrai par construction » que je me suis trompé sur `breakout` le 09/09."""
    seuls = 0
    for fen in _fenetres(bougies_reelles):
        m = _motifs(fen)
        if PatternType.DOUBLE_SWEEP_DOWN in m and \
                PatternType.LIQUIDITY_SWEEP_DOWN not in m:
            seuls += 1
        if PatternType.DOUBLE_SWEEP_UP in m and \
                PatternType.LIQUIDITY_SWEEP_UP not in m:
            seuls += 1
    assert seuls == 0, (
        f"{seuls} doubles sans balayage simple — le recouvrement annonce comme "
        "total ne l'est pas, et la comparaison appariee ne tient plus")
