"""Deux définitions du « gap », mises face à face pour être départagées.

Demandé par Xavier le 2026-09-09. Sa thèse : le *Fair Value Gap* et le
*breakaway gap* se distinguent **sur la troisième bougie** — si elle clôture
DANS la deuxième, le prix retracera dans la zone avant de repartir ; si elle
clôture AU-DELÀ, la tendance est trop forte et il repart sans retracer.

⛔ **Ce ne sont pas deux noms pour la même chose** — ils viennent de deux
traditions :

| | tradition | définition |
|---|---|---|
| Fair Value Gap | ICT / Smart Money | **bas[3] > haut[1]** — un trou non recouvert sur 3 bougies. Aucun vrai gap requis. |
| Breakaway gap | classique (Edwards & Magee) | un **vrai saut de prix**, à la sortie d'une consolidation. Pensé pour les actions en journalier. |

⚠️ Et la règle de Xavier n'est **ni l'une ni l'autre** : le FVG standard ne
regarde pas où clôture la 3ᵉ bougie. Les deux détecteurs sélectionnent donc des
événements différents. On code **les deux** et on laisse la mesure trancher —
répondre par la définition serait répondre à côté.

## Mesuré avant d'écrire (1 000 bougies XAU/USD 5 min)

```
open != cloture precedente     999/999 = 100 %   <- « vrai gap » n'est PAS une
   ecart median 0,24 USD                            categorie ici : tout ouvre
                                                    a cote. Un breakaway gap au
                                                    sens classique exigerait un
                                                    SEUIL arbitraire.
FVG haussier standard          10,1 %            <- defini sans aucun seuil
FVG baissier standard           9,6 %
```

⇒ C'est pourquoi le second détecteur classe **par la 3ᵉ bougie** (la règle de
Xavier) et non par la taille d'un saut : un seuil choisi à la main serait un
degré de liberté de plus, donc de l'edge fabriqué.

⚠️ **Aucun de ces motifs n'est armé.** La whitelist de dispatch est
fail-closed : un motif absent rend `pattern_not_allowed`. Ils ne servent qu'à
être mesurés par le laboratoire, contre un tirage au hasard.

⚠️ Le prior honnête : **sept motifs mesurés, aucun ne bat le hasard**
(Δ = +0,004 R sur 29 000 trades). Ceux-ci sont les huitième et neuvième.
"""
from datetime import datetime, timedelta, timezone

import pytest

from backend.models.schemas import PatternType
from backend.services import pattern_detector as pd


def _c(o, h, l, c, i=0):
    """Une bougie, minute i."""
    from backend.services.pattern_detector import Candle
    return Candle(
        timestamp=datetime(2026, 9, 9, tzinfo=timezone.utc) + timedelta(minutes=5 * i),
        open=o, high=h, low=l, close=c, volume=0)


def _fond(n=20, prix=4000.0):
    """Un fond calme, pour que l'ATR existe sans créer de motif."""
    return [_c(prix, prix + 1, prix - 1, prix, i) for i in range(n)]


def _motifs(candles):
    return {p.pattern for p in pd.detect_patterns(candles, "XAU/USD")}


# ─── FVG standard (ICT) : bas[3] > haut[1] ───────────────────────────

def test_fvg_haussier_standard_detecte():
    """Le trou entre le haut de la 1re et le bas de la 3e."""
    c = _fond() + [
        _c(4000, 4002, 3999, 4001, 20),      # 1re : haut = 4002
        _c(4001, 4020, 4001, 4019, 21),      # 2e  : impulsion
        _c(4019, 4022, 4010, 4021, 22),      # 3e  : bas 4010 > 4002
    ]
    assert PatternType.FVG_UP in _motifs(c)


def test_fvg_baissier_standard_detecte():
    c = _fond() + [
        _c(4000, 4001, 3998, 3999, 20),      # 1re : bas = 3998
        _c(3999, 3999, 3980, 3981, 21),
        _c(3981, 3990, 3978, 3979, 22),      # 3e  : haut 3990 < 3998 ? non
    ]
    c[-1] = _c(3981, 3995, 3978, 3979, 22)   # haut 3995 < 3998 -> FVG
    assert PatternType.FVG_DOWN in _motifs(c)


def test_pas_de_FVG_quand_le_trou_est_RECOUVERT():
    """⛔ Le cœur de la définition : si la 3e bougie redescend dans la 1re,
    il n'y a pas de déséquilibre — donc pas de FVG."""
    c = _fond() + [
        _c(4000, 4002, 3999, 4001, 20),
        _c(4001, 4020, 4001, 4019, 21),
        _c(4019, 4022, 4000, 4021, 22),      # bas 4000 < haut 4002 : recouvert
    ]
    assert PatternType.FVG_UP not in _motifs(c)


# ─── La règle de Xavier : où clôture la 3e bougie ────────────────────

def test_cloture_DANS_la_2e_donne_un_retracement_attendu():
    """« Le prix va retracer dans la zone puis repartir. »"""
    c = _fond() + [
        _c(4000, 4002, 3999, 4001, 20),
        _c(4001, 4020, 4001, 4019, 21),      # 2e : impulsion, haut 4020
        _c(4019, 4021, 4008, 4012, 22),      # 3e : cloture 4012, DANS la 2e
    ]
    m = _motifs(c)
    assert PatternType.GAP_RETRACE_UP in m
    assert PatternType.GAP_BREAKAWAY_UP not in m


def test_cloture_AU_DESSUS_de_la_2e_donne_un_breakaway():
    """« La tendance est si forte que le prix continue sans retracer. »"""
    c = _fond() + [
        _c(4000, 4002, 3999, 4001, 20),
        _c(4001, 4020, 4001, 4019, 21),      # 2e : haut 4020
        _c(4019, 4030, 4018, 4028, 22),      # 3e : cloture 4028 > 4020
    ]
    m = _motifs(c)
    assert PatternType.GAP_BREAKAWAY_UP in m
    assert PatternType.GAP_RETRACE_UP not in m


def test_les_deux_verdicts_sont_EXCLUSIFS():
    """⛔ S'ils pouvaient coexister, la mesure ne départagerait rien : chaque
    fenêtre alimenterait les deux cellules et l'écart serait un artefact."""
    for close3 in (4012, 4028):
        c = _fond() + [
            _c(4000, 4002, 3999, 4001, 20),
            _c(4001, 4020, 4001, 4019, 21),
            _c(4019, 4030, 4008, close3, 22),
        ]
        m = _motifs(c)
        assert not (PatternType.GAP_RETRACE_UP in m
                    and PatternType.GAP_BREAKAWAY_UP in m)


def test_sans_IMPULSION_aucun_des_deux_ne_sort():
    """⚠️ Sans une 2e bougie qui déplace vraiment, « clôturer au-dessus »
    arriverait une fois sur deux — le motif ne dirait rien."""
    c = _fond() + [
        _c(4000, 4001, 3999, 4000, 20),
        _c(4000, 4001, 3999, 4000, 21),      # 2e : corps nul
        _c(4000, 4002, 3999, 4001, 22),
    ]
    m = _motifs(c)
    assert PatternType.GAP_RETRACE_UP not in m
    assert PatternType.GAP_BREAKAWAY_UP not in m


def test_le_sens_BAISSIER_existe_aussi():
    c = _fond() + [
        _c(4000, 4001, 3998, 3999, 20),
        _c(3999, 3999, 3980, 3981, 21),      # 2e : impulsion baissiere
        _c(3981, 3982, 3970, 3972, 22),      # 3e : cloture sous le bas 3980
    ]
    assert PatternType.GAP_BREAKAWAY_DOWN in _motifs(c)


# ─── Ce qui protège le reste ─────────────────────────────────────────

def test_un_fond_CALME_ne_produit_aucun_de_ces_motifs():
    """Un détecteur qui se déclenche sur du bruit remplit le laboratoire de
    cellules vides et dilue le plafond du hasard pour tous les autres."""
    m = _motifs(_fond(30))
    assert not (m & {PatternType.FVG_UP, PatternType.FVG_DOWN,
                     PatternType.GAP_RETRACE_UP, PatternType.GAP_RETRACE_DOWN,
                     PatternType.GAP_BREAKAWAY_UP, PatternType.GAP_BREAKAWAY_DOWN})


def test_moins_de_TROIS_bougies_ne_leve_pas():
    """Le détecteur tourne sur chaque cycle, y compris au démarrage à froid."""
    assert isinstance(pd.detect_patterns([_c(4000, 4001, 3999, 4000)], "XAU/USD"), list)


def test_aucun_de_ces_motifs_n_est_ARME():
    """⛔ L'invariant qui rend ce travail sans risque : la whitelist de
    dispatch est fail-closed, un motif absent rend `pattern_not_allowed`.
    Ces six motifs ne doivent apparaître dans AUCUNE liste d'autorisation."""
    import pathlib
    racine = pathlib.Path(__file__).resolve().parents[2]
    nouveaux = {"fvg_up", "fvg_down", "gap_retrace_up", "gap_retrace_down",
                "gap_breakaway_up", "gap_breakaway_down"}
    for f in [racine / "config" / "settings.py",
              racine / "backend" / "services" / "destinations_registry.py"]:
        if not f.exists():
            continue
        texte = f.read_text(encoding="utf-8")
        for m in nouveaux:
            assert m not in texte, f"{m} est declare dans {f.name} — il serait ARME"
