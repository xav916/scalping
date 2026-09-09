"""Le balayage de liquidité : la mèche prend les stops, le corps les rejette.

Concept déclaré dans `docs/concepts-trading.md` **avant** d'être codé — première
application de la recette `docs/ajouter-un-motif.md`.

## La règle, et pourquoi elle est falsifiable

Les stops s'accumulent juste au-delà d'un extrême récent. L'idée du concept est
que le prix va les chercher, puis repart **en sens inverse** :

    haut[derniere] > max(haut des 30 precedentes)   l'extreme est depasse
    ET cloture[derniere] < ce meme max              le prix est REVENU dessous

⇒ **Prédiction** : après un balayage des plus-hauts, le prix baisse. C'est un
signal de **retournement**, pas de continuation — donc réfutable par une simple
mesure de R moyen.

## Ce qui rend la mesure lisible

⛔ **J'avais écrit ici « exclusif de `breakout` par construction ». C'était
FAUX**, et c'est la leçon la plus utile de cette intégration. `_detect_breakout`
compare à `_find_level` — un niveau aggloméré — et non au maximum. Le prix peut
donc clôturer au-dessus de ce niveau tout en restant sous le plus-haut.

Mes données synthétiques ne pouvaient pas le montrer : sur un plateau plat,
`_find_level` et `max` coïncident. Sur **4 950 fenêtres réelles**, les deux
sortent ensemble **26 fois (0,53 %)**.

⇒ Aligner le sweep sur `_find_level` dénaturerait le concept — les stops
s'accumulent à l'**extrême**. On garde la règle fidèle et on **borne** le
recouvrement par un test sur du vrai marché.

⚠️ **Recouvrement attendu avec `pin_bar`**, en revanche : un balayage EST
souvent une pin bar. Deux cellules distinctes, mais **pas deux tests
indépendants**. À garder en tête si les deux ressortent ensemble.

⚠️ Les 30 bougies de référence sont **reprises de `_detect_breakout`** plutôt
que choisies : un réglage de plus serait un degré de liberté de plus.
"""
from datetime import datetime, timedelta, timezone

from backend.models.schemas import PatternType
from backend.services import pattern_detector as pd


def _c(o, h, l, c, i=0):
    from backend.services.pattern_detector import Candle
    return Candle(
        timestamp=datetime(2026, 9, 9, tzinfo=timezone.utc) + timedelta(minutes=5 * i),
        open=o, high=h, low=l, close=c, volume=0)


def _fond(n=35, prix=4000.0, amplitude=1.0):
    """Un plateau calme : plus-haut de référence à `prix + amplitude`."""
    return [_c(prix, prix + amplitude, prix - amplitude, prix, i) for i in range(n)]


def _motifs(candles):
    return {p.pattern for p in pd.detect_patterns(candles, "XAU/USD")}


# ─── Le balayage des HAUTS ⇒ signal baissier ─────────────────────────

def test_meche_au_dessus_puis_retour_dessous_donne_un_sweep_baissier():
    """Le cœur : le haut est dépassé, la clôture revient dessous."""
    c = _fond() + [_c(4000, 4008, 3999, 4000.5, 35)]   # haut 4008 > 4001, clot 4000,5
    assert PatternType.LIQUIDITY_SWEEP_DOWN in _motifs(c)


def test_une_CLOTURE_au_dessus_n_est_PAS_un_sweep():
    """Sans le retour sous le niveau, la liquidité n'a pas été rejetée — il ne
    reste qu'une cassure, qui est un autre concept."""
    c = _fond() + [_c(4000, 4008, 3999, 4007, 35)]     # clot 4007 > 4001
    m = _motifs(c)
    assert PatternType.LIQUIDITY_SWEEP_DOWN not in m


def test_sans_depassement_du_haut_aucun_sweep():
    """Sans prise de liquidité, il ne s'est rien passé."""
    c = _fond() + [_c(4000, 4000.5, 3999, 4000, 35)]
    assert PatternType.LIQUIDITY_SWEEP_DOWN not in _motifs(c)


# ─── Le miroir : balayage des BAS ⇒ signal haussier ──────────────────

def test_meche_en_dessous_puis_retour_au_dessus_donne_un_sweep_haussier():
    c = _fond() + [_c(4000, 4001, 3992, 3999.5, 35)]   # bas 3992 < 3999, clot 3999,5
    assert PatternType.LIQUIDITY_SWEEP_UP in _motifs(c)


def test_une_CLOTURE_en_dessous_n_est_PAS_un_sweep():
    c = _fond() + [_c(4000, 4001, 3992, 3993, 35)]
    assert PatternType.LIQUIDITY_SWEEP_UP not in _motifs(c)


# ─── Ce qui protège la mesure ────────────────────────────────────────

def test_le_recouvrement_avec_breakout_reste_MARGINAL():
    """⛔ J'avais ecrit « exclusifs par construction ». **C'ETAIT FAUX**, et mes
    donnees synthetiques ne pouvaient pas le montrer.

    `_detect_breakout` ne compare pas au MAXIMUM : il utilise `_find_level`, un
    niveau agglomere qui peut se situer SOUS le plus-haut. Le prix peut donc
    cloturer au-dessus de ce niveau (breakout_up) tout en restant sous le
    plus-haut (sweep_down). Les deux referencent des niveaux differents.

    🔑 Mon plateau de test etait plat : `_find_level` et `max` y coincidaient,
    et l'exclusivite paraissait tenir. Sur 4 950 fenetres REELLES, les deux
    sortent ensemble **26 fois**.

    ⇒ Aligner le sweep sur `_find_level` denaturerait le concept : les stops
    s'accumulent a l'EXTREME, pas sur un niveau agglomere. On garde la regle
    fidele et on BORNE le recouvrement, en le mesurant sur du vrai marche.
    """
    import json
    from pathlib import Path
    brut = json.loads(
        (Path(__file__).parent / "fixtures" / "bougies_xauusd_5min.json")
        .read_text(encoding="utf-8"))
    t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    from backend.services.pattern_detector import Candle
    bougies = [Candle(timestamp=t0 + timedelta(minutes=5 * i),
                      open=o, high=h, low=b, close=cl, volume=0)
               for i, (o, h, b, cl) in enumerate(brut)]

    ensemble = fenetres = 0
    for i in range(50, len(bougies)):
        fenetres += 1
        m = {p.pattern for p in pd.detect_patterns(bougies[i - 50:i], "XAU/USD")}
        if ({PatternType.LIQUIDITY_SWEEP_DOWN, PatternType.BREAKOUT_UP} <= m
                or {PatternType.LIQUIDITY_SWEEP_UP, PatternType.BREAKOUT_DOWN} <= m):
            ensemble += 1
    part = 100.0 * ensemble / fenetres
    assert part < 1.0, (
        f"recouvrement sweep/breakout a {part:.2f} % — au-dela de 1 %, leurs "
        "cellules ne sont plus deux tests distincts")


def test_un_fond_CALME_ne_produit_aucun_sweep():
    """Un détecteur qui mord sur du bruit remplit le laboratoire de cellules
    creuses et relève le plafond du hasard pour tous les autres."""
    m = _motifs(_fond(40))
    assert not (m & {PatternType.LIQUIDITY_SWEEP_UP,
                     PatternType.LIQUIDITY_SWEEP_DOWN})


def test_trop_peu_de_bougies_ne_leve_pas():
    """Le détecteur tourne à chaque cycle, y compris au démarrage à froid."""
    assert isinstance(pd.detect_patterns([_c(4000, 4001, 3999, 4000)], "XAU/USD"),
                      list)


def test_le_sweep_n_est_ARME_nulle_part():
    """⛔ L'invariant qui rend l'exercice sans risque : la whitelist de dispatch
    est fail-closed. Ces motifs ne doivent apparaître dans AUCUNE liste
    d'autorisation."""
    import pathlib
    racine = pathlib.Path(__file__).resolve().parents[2]
    for f in (racine / "config" / "settings.py",
              racine / "backend" / "services" / "destinations_registry.py"):
        if not f.exists():
            continue
        texte = f.read_text(encoding="utf-8")
        for m in ("liquidity_sweep_up", "liquidity_sweep_down"):
            assert m not in texte, f"{m} est declare dans {f.name} — il serait ARME"
