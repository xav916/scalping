"""Une chaine mesuree au labo doit etre vue A L'IDENTIQUE en production.

⛔ **Le defaut que ce module previent.** Les 18 chaines n'existent aujourd'hui
que dans le rejeu du laboratoire : le radar ne sait pas les detecter. Les
porter en production en REECRIVANT la logique creerait deux implementations de
la meme regle — et ce depot sait ce que ca coute : `/opt/scalping/scripts`
divergent du depot une journee entiere, deux tables de sessions, deux plafonds
de chaines dans deux fichiers.

🔑 **Il n'y a donc qu'une implementation.** `detecter_chaines` convertit les
bougies de production au format du laboratoire et appelle **le meme code** :
memes declarations, memes predicats, meme fenetre de sequence. Le test central
compare les deux chemins sur les MEMES bougies et exige le meme resultat.

## ⛔ Ce qui ne doit PAS changer

`detect_patterns` continue de recevoir exactement `CANDLE_COUNT` bougies. Lui
en passer plus deplacerait les signaux EXISTANTS : `_detect_poc_return`
calcule son profil sur **toute** la liste recue, pas sur une fenetre fixe. Un
test le verrouille.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.models.schemas import Candle
from backend.services import chaines_production as cp
from backend.services import laboratoire_or as labo


def _dicts(n=200):
    """Des bougies qui montent et redescendent, format du pont."""
    t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    out, prix = [], 100.0
    for i in range(n):
        prix += 1.4 if (i // 7) % 2 == 0 else -1.1
        out.append({"t": (t0 + timedelta(minutes=5 * i)).isoformat(),
                    "o": prix, "h": prix + 0.9, "l": prix - 0.9,
                    "c": prix + (0.4 if i % 3 else -0.4), "tv": 500})
    return out


def _candles(ds):
    return [Candle(timestamp=datetime.fromisoformat(d["t"]), open=d["o"],
                   high=d["h"], low=d["l"], close=d["c"], volume=d["tv"])
            for d in ds]


def test_le_labo_et_la_PRODUCTION_voient_la_MEME_chose():
    """🔑 Le test qui donne son sens au module. Deux chemins, un seul verdict.

    ⛔ **Ma premiere version comparait le VIDE au VIDE.** Elle prenait la
    derniere bougie de la serie, ou aucune chaine ne se declenchait : les deux
    cotes rendaient `[]` et le test passait sans rien mesurer. Il compare
    desormais sur les indices ou le laboratoire voit REELLEMENT une chaine, et
    il echoue s'il n'y en a aucun.
    """
    ds = _dicts(200)
    releve = labo.detections(ds, "XAU/USD")
    sortie, _ = labo.chaines_detectees(releve, ds)
    indices = sorted(sortie)
    assert indices, (
        "aucune chaine dans la fixture : le test ne mesurerait rien")

    compares = 0
    for i in indices:
        au_labo = sorted(labo._nom_motif(s) for s in sortie[i])
        # ⚠️ La production voit la serie TRONQUEE a cet instant : elle ne
        # connait pas l'avenir, exactement comme en vrai.
        en_prod = sorted(c.pattern
                         for c in cp.detecter_chaines(_candles(ds[:i]), "XAU/USD"))
        assert en_prod == au_labo, (
            f"indice {i} : labo={au_labo} prod={en_prod}")
        compares += 1
    assert compares >= 1


def test_la_production_ne_rend_QUE_la_derniere_bougie():
    """Un signal qui appartient au passe n'est pas un signal."""
    ds = _dicts(200)
    for c in cp.detecter_chaines(_candles(ds), "XAU/USD"):
        assert c.indice == len(ds)


def test_sans_assez_d_HISTOIRE_on_ne_rend_RIEN():
    """Fail-closed : mieux vaut aucune chaine qu'une chaine amputee."""
    assert cp.detecter_chaines(_candles(_dicts(20)), "XAU/USD") == []


def test_une_chaine_n_est_JAMAIS_un_PatternType():
    """⛔ La liste blanche est fail-closed sur `PatternType`. Une chaine qui en
    deviendrait un pourrait partir sans passer par son propre registre."""
    from backend.models.schemas import PatternType
    valides = {p.value for p in PatternType}
    for c in cp.detecter_chaines(_candles(_dicts(200)), "XAU/USD"):
        assert c.pattern not in valides
        assert c.pattern.startswith("chaine:")


def test_detect_patterns_recoit_TOUJOURS_le_meme_nombre_de_bougies():
    """⛔ Le verrou qui protege les signaux EXISTANTS. `_detect_poc_return`
    calcule son profil sur TOUTE la liste recue : lui passer 450 bougies au
    lieu de 50 deplacerait des signaux qui tradent de l'argent reel."""
    import inspect
    from backend.services import scheduler
    src = inspect.getsource(scheduler)
    i = src.index("patterns = detect_patterns(")
    appel = src[i:i + 120]
    assert "candles" in appel, appel
    # la serie longue doit porter un AUTRE nom, jamais `candles`
    assert "candles_longues" not in appel, (
        "la serie longue est passee au detecteur : les signaux existants "
        "changeraient sans qu'aucun test ne le dise")


def test_l_instant_d_ENTREE_est_extrapole_quand_la_bougie_n_existe_pas():
    """⛔ Le defaut trouve en comparant les deux chemins. Le laboratoire lit
    `bougies[i]` — la bougie sur laquelle on ENTRE, une de plus que ce que le
    detecteur a vu. En rejeu elle existe ; en production elle n'est pas encore
    formee, et `None` rendait toutes les chaines de session MUETTES en silence.
    """
    ds = _dicts(60)
    pas = (datetime.fromisoformat(ds[1]["t"])
           - datetime.fromisoformat(ds[0]["t"]))
    attendu = datetime.fromisoformat(ds[-1]["t"]) + pas
    assert labo._instant(ds, len(ds)) == attendu


def test_le_LABORATOIRE_ne_passe_JAMAIS_par_l_extrapolation():
    """🔑 Ce qui garantit qu'aucune mesure existante ne bouge : la boucle du
    laboratoire s'arrete a `len - 1`."""
    ds = _dicts(80)
    releve = labo.detections(ds, "XAU/USD")
    assert releve, "releve vide : le test ne mesurerait rien"
    assert max(releve) <= len(ds) - 1
