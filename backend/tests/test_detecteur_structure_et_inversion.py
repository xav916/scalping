"""BOS, CHoCH et Inversion FVG — trois concepts, une même exigence.

Déclarés dans `docs/concepts-trading.md` **avant** d'être codés. Troisième
application de la recette `docs/ajouter-un-motif.md`.

## BOS et CHoCH : le même événement, deux lectures

Une cassure, lue dans un **contexte de tendance** :

    tendance haussiere + cassure du SOMMET  ->  BOS,   continuation
    tendance haussiere + cassure du CREUX   ->  CHoCH, retournement

⇒ **Prédiction falsifiable, et elle est forte** : leurs R moyens doivent être de
**signes opposés**. S'ils sont identiques, le contexte de tendance n'apporte
rien et les deux ne sont qu'un `breakout` sous un autre nom.

⚠️ **Aucun réglage nouveau.** La fenêtre de 30 bougies vient de
`_detect_breakout` et du *liquidity sweep*. La tendance se lit en la coupant en
deux : haussière si la moitié récente a **à la fois** un plus-haut et un
plus-bas supérieurs à l'ancienne.

## Inversion FVG : un support devenu résistance

Le trou traversé de part en part ne soutient plus, il repousse. **Aucun seuil**,
comme le FVG dont il dérive. Sa prédiction est de **signe opposé** à celle du
`fvg_up` d'origine — c'est ce qui le rend testable plutôt que décoratif.

## Ce que les intégrations précédentes ont appris

⛔ Pour le *liquidity sweep*, j'ai affirmé une exclusivité que 4 950 fenêtres
réelles ont démentie. Ici, **rien n'est affirmé** : le recouvrement avec
`breakout` est **attendu et fort** — c'est la même cassure — et il est **mesuré**.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.models.schemas import PatternType as P
from backend.services import pattern_detector as pd
from backend.services.pattern_detector import Candle


def _c(o, h, l, c, i=0):
    return Candle(
        timestamp=datetime(2026, 9, 9, tzinfo=timezone.utc) + timedelta(minutes=5 * i),
        open=o, high=h, low=l, close=c, volume=0)


def _tendance_haussiere():
    """30 bougies dont la moitié récente monte : sommets ET creux plus hauts."""
    out = []
    for i in range(15):                       # ancienne moitie, autour de 4000
        out.append(_c(4000, 4002, 3998, 4000, i))
    for i in range(15, 30):                   # moitie recente, autour de 4010
        out.append(_c(4010, 4012, 4008, 4010, i))
    return out


def _motifs(candles):
    return {p.pattern for p in pd.detect_patterns(candles, "XAU/USD")}


# ─── BOS : la tendance continue ──────────────────────────────────────

def test_cassure_du_SOMMET_en_tendance_haussiere_donne_un_BOS():
    c = _tendance_haussiere() + [_c(4010, 4020, 4009, 4018, 30)]
    assert P.BOS_UP in _motifs(c)


def test_sans_TENDANCE_aucun_BOS():
    """⛔ Sans contexte, une cassure n'est qu'un breakout — et le concept ne
    dit plus rien de particulier."""
    plat = [_c(4000, 4002, 3998, 4000, i) for i in range(30)]
    assert P.BOS_UP not in _motifs(plat + [_c(4000, 4020, 3999, 4018, 30)])


# ─── CHoCH : la tendance se retourne ─────────────────────────────────

def test_cassure_du_CREUX_en_tendance_haussiere_donne_un_CHOCH():
    c = _tendance_haussiere() + [_c(4010, 4011, 3990, 3992, 30)]
    assert P.CHOCH_DOWN in _motifs(c)


def test_BOS_et_CHOCH_ne_sortent_JAMAIS_ensemble():
    """⛔ Ils décrivent des issues OPPOSÉES. S'ils coexistaient, comparer
    leurs R moyens — toute la prédiction du concept — n'aurait aucun sens."""
    for haut, bas, clot in ((4020, 4009, 4018), (4011, 3990, 3992),
                            (4025, 3985, 4000), (4025, 3985, 4020)):
        m = _motifs(_tendance_haussiere() + [_c(4010, haut, bas, clot, 30)])
        assert not (P.BOS_UP in m and P.CHOCH_DOWN in m), f"les deux a {clot}"


# ─── Inversion FVG : le support devenu résistance ────────────────────

def test_un_FVG_traverse_puis_reteste_par_dessous_donne_une_INVERSION():
    c = [_c(4000, 4002, 3998, 4000, i) for i in range(20)] + [
        _c(4000, 4002, 3999, 4001, 20),      # 1re : haut 4002
        _c(4001, 4020, 4001, 4019, 21),      # impulsion
        _c(4019, 4022, 4010, 4021, 22),      # 3e : bas 4010 > 4002 -> FVG [4002,4010]
        _c(4021, 4022, 3995, 3998, 23),      # traverse ENTIEREMENT vers le bas
        _c(3998, 4005, 3996, 3999, 24),      # revient toucher, refuse
    ]
    assert P.FVG_INVERSE_DOWN in _motifs(c)


def test_sans_TRAVERSEE_complete_aucune_inversion():
    """Le trou n'est inversé que s'il a été franchi de part en part."""
    c = [_c(4000, 4002, 3998, 4000, i) for i in range(20)] + [
        _c(4000, 4002, 3999, 4001, 20),
        _c(4001, 4020, 4001, 4019, 21),
        _c(4019, 4022, 4010, 4021, 22),
        _c(4021, 4022, 4006, 4012, 23),      # s'arrete DANS le trou
        _c(4012, 4014, 4008, 4011, 24),
    ]
    assert P.FVG_INVERSE_DOWN not in _motifs(c)


# ─── Ce qui protège la mesure ────────────────────────────────────────

def test_un_fond_CALME_ne_produit_aucun_des_trois():
    m = _motifs([_c(4000, 4001, 3999, 4000, i) for i in range(40)])
    assert not (m & {P.BOS_UP, P.BOS_DOWN, P.CHOCH_UP, P.CHOCH_DOWN,
                     P.FVG_INVERSE_UP, P.FVG_INVERSE_DOWN})


def test_trop_peu_de_bougies_ne_leve_pas():
    assert isinstance(pd.detect_patterns([_c(4000, 4001, 3999, 4000)], "XAU/USD"),
                      list)


def test_le_recouvrement_avec_breakout_est_MESURE():
    """⚠️ Attendu et FORT — c'est la même cassure, seule la lecture change.
    On ne l'affirme pas exclusif : on le mesure, et on vérifie que le BOS
    apporte quand même une information propre (il n'est pas TOUJOURS un
    breakout, sinon la cellule serait un doublon)."""
    brut = json.loads(
        (Path(__file__).parent / "fixtures" / "bougies_xauusd_5min.json")
        .read_text(encoding="utf-8"))
    t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    b = [Candle(timestamp=t0 + timedelta(minutes=5 * i),
                open=o, high=h, low=lo, close=cl, volume=0)
         for i, (o, h, lo, cl) in enumerate(brut)]

    bos = double = 0
    for i in range(50, len(b)):
        m = {p.pattern for p in pd.detect_patterns(b[i - 50:i], "XAU/USD")}
        if P.BOS_UP in m:
            bos += 1
            if P.BREAKOUT_UP in m:
                double += 1
    assert bos > 0, "le BOS ne se declenche jamais sur du vrai marche"
    part = 100.0 * double / bos
    assert part < 90.0, (
        f"{part:.1f} % des BOS sont AUSSI des breakouts — au-dela de 90 %, "
        "la cellule est un doublon et ne merite pas sa place")


def test_aucun_des_six_n_est_ARME():
    racine = Path(__file__).resolve().parents[2]
    nouveaux = ("bos_up", "bos_down", "choch_up", "choch_down",
                "fvg_inverse_up", "fvg_inverse_down")
    for f in (racine / "config" / "settings.py",
              racine / "backend" / "services" / "destinations_registry.py"):
        if not f.exists():
            continue
        texte = f.read_text(encoding="utf-8")
        for m in nouveaux:
            assert m not in texte, f"{m} est declare dans {f.name} — il serait ARME"
