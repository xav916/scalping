"""Order Block : la zone d'où l'impulsion est partie, retestée et tenue.

Concept déclaré dans `docs/concepts-trading.md` **avant** d'être codé —
deuxième application de la recette `docs/ajouter-un-motif.md`.

## La règle

1. une bougie d'**impulsion** haussière (corps > 0,5 × ATR) ;
2. la dernière bougie **rouge avant elle** est l'*order block* — zone `[bas, haut]` ;
3. la bougie courante **redescend dans la zone** (`bas ≤ haut_OB`) ;
4. **et clôture au-dessus** (`clôture > haut_OB`) — la zone a tenu.

⇒ **Prédiction falsifiable** : après ce retest tenu, le prix repart dans le sens
de l'impulsion. R moyen nul ⇒ concept réfuté.

## Ce que j'ai appris de l'intégration précédente

⛔ Pour le *liquidity sweep*, j'avais affirmé « exclusif de `breakout` par
construction ». Un test synthétique le confirmait — et **4 950 fenêtres réelles
l'ont démenti** (26 co-occurrences). Sur un plateau plat, `_find_level` et `max`
coïncidaient ; le vrai marché, non.

⇒ Ici, **aucune exclusivité n'est déclarée**. Le recouvrement avec
`range_bounce` et `fvg` est **attendu**, et il est **mesuré sur du vrai marché**
plutôt que supposé. Une propriété qu'on affirme sans la mesurer sur des données
réelles est une propriété qu'on ne connaît pas.

⚠️ Aucun seuil neuf : `_IMPULSION_MIN_ATR` est repris du détecteur de gap.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.models.schemas import PatternType
from backend.services import pattern_detector as pd
from backend.services.pattern_detector import Candle


def _c(o, h, l, c, i=0):
    return Candle(
        timestamp=datetime(2026, 9, 9, tzinfo=timezone.utc) + timedelta(minutes=5 * i),
        open=o, high=h, low=l, close=c, volume=0)


def _fond(n=30, prix=4000.0):
    """Fond calme : ATR ≈ 2, donc l'impulsion doit dépasser ~1 point de corps."""
    return [_c(prix, prix + 1, prix - 1, prix, i) for i in range(n)]


def _motifs(candles):
    return {p.pattern for p in pd.detect_patterns(candles, "XAU/USD")}


def _scenario_haussier(close_final):
    """OB rouge, impulsion verte, puis retest de la zone."""
    return _fond() + [
        _c(4000, 4001, 3996, 3997, 30),      # OB rouge : zone [3996, 4001]
        _c(3997, 4020, 3997, 4018, 31),      # impulsion verte, corps 21
        _c(4018, 4019, 3999, close_final, 32),  # redescend dans la zone
    ]


# ─── Le cas nominal ──────────────────────────────────────────────────

def test_retest_TENU_donne_un_order_block_haussier():
    """Le cœur : la zone est touchée et la clôture repasse au-dessus."""
    assert PatternType.ORDER_BLOCK_UP in _motifs(_scenario_haussier(4010))


def test_retest_PERDU_ne_donne_rien():
    """⛔ Clôturer DANS la zone, c'est qu'elle n'a pas tenu — le concept ne dit
    rien de ce cas, et inventer un signal serait fabriquer de l'edge."""
    assert PatternType.ORDER_BLOCK_UP not in _motifs(_scenario_haussier(3998))


def test_zone_jamais_TOUCHEE_ne_donne_rien():
    """Sans retour dans la zone, il n'y a rien à confirmer."""
    c = _fond() + [
        _c(4000, 4001, 3996, 3997, 30),
        _c(3997, 4020, 3997, 4018, 31),
        _c(4018, 4022, 4015, 4020, 32),      # reste loin au-dessus
    ]
    assert PatternType.ORDER_BLOCK_UP not in _motifs(c)


def test_sans_IMPULSION_aucun_order_block():
    """⚠️ Sans déplacement franc, « la dernière bougie opposée » n'est qu'une
    bougie parmi d'autres."""
    c = _fond() + [
        _c(4000, 4001, 3996, 3997, 30),
        _c(3997, 3999, 3997, 3998, 31),      # corps 1, sous le seuil
        _c(3998, 3999, 3996, 3999, 32),
    ]
    assert PatternType.ORDER_BLOCK_UP not in _motifs(c)


def test_le_sens_BAISSIER_existe_aussi():
    c = _fond() + [
        _c(4000, 4004, 3999, 4003, 30),      # OB vert : zone [3999, 4004]
        _c(4003, 4003, 3980, 3982, 31),      # impulsion rouge
        _c(3982, 4001, 3981, 3990, 32),      # remonte dans la zone, clot dessous
    ]
    assert PatternType.ORDER_BLOCK_DOWN in _motifs(c)


# ─── Ce qui protège la mesure ────────────────────────────────────────

def test_un_fond_CALME_ne_produit_aucun_order_block():
    m = _motifs(_fond(40))
    assert not (m & {PatternType.ORDER_BLOCK_UP, PatternType.ORDER_BLOCK_DOWN})


def test_trop_peu_de_bougies_ne_leve_pas():
    assert isinstance(pd.detect_patterns([_c(4000, 4001, 3999, 4000)], "XAU/USD"),
                      list)


def test_le_recouvrement_est_MESURE_et_non_suppose():
    """⛔ La leçon du *liquidity sweep* : une propriété affirmée sans mesure sur
    du vrai marché est une propriété qu'on ne connaît pas.

    On ne déclare aucune exclusivité ici. On **borne** le recouvrement, et on
    l'affiche — s'il dépassait la moitié des occurrences, la cellule de l'order
    block ne serait plus un test distinct de celle de `range_bounce`.
    """
    brut = json.loads(
        (Path(__file__).parent / "fixtures" / "bougies_xauusd_5min.json")
        .read_text(encoding="utf-8"))
    t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    bougies = [Candle(timestamp=t0 + timedelta(minutes=5 * i),
                      open=o, high=h, low=b, close=cl, volume=0)
               for i, (o, h, b, cl) in enumerate(brut)]

    ob = collision = 0
    for i in range(50, len(bougies)):
        m = {p.pattern for p in pd.detect_patterns(bougies[i - 50:i], "XAU/USD")}
        if PatternType.ORDER_BLOCK_UP in m:
            ob += 1
            if m & {PatternType.RANGE_BOUNCE_UP, PatternType.FVG_UP}:
                collision += 1
    assert ob > 0, "l'order block ne se declenche jamais sur du vrai marche"
    part = 100.0 * collision / ob
    assert part < 50.0, (
        f"{part:.1f} % des order blocks coincident avec range_bounce ou fvg — "
        "au-dela de la moitie, ce n'est plus un test distinct")


def test_l_order_block_n_est_ARME_nulle_part():
    """⛔ Whitelist fail-closed : ces motifs ne doivent figurer dans AUCUNE
    liste d'autorisation."""
    racine = Path(__file__).resolve().parents[2]
    for f in (racine / "config" / "settings.py",
              racine / "backend" / "services" / "destinations_registry.py"):
        if not f.exists():
            continue
        texte = f.read_text(encoding="utf-8")
        for m in ("order_block_up", "order_block_down"):
            assert m not in texte, f"{m} est declare dans {f.name} — il serait ARME"
