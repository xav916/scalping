"""Un détecteur mal calibré pollue le laboratoire — et il doit être arrêté AVANT.

⛔ **Pourquoi cette porte existe** (2026-09-09). En intégrant le FVG et la règle
du gap, j'ai bricolé **deux fois** le même script jetable pour répondre à une
question qui revient à chaque nouveau motif : *est-ce qu'il se déclenche assez
pour être mesurable, et pas trop pour être du bruit ?*

Les deux extrêmes coûtent cher, et aucun ne produit d'erreur :

| | conséquence |
|---|---|
| **> 25 %** des fenêtres | ce n'est plus un motif, c'est un état permanent du marché déguisé en signal |

⚠️ **Et une cellule inutile n'est pas gratuite.** Le plafond du hasard croît
avec le nombre de cellules — mesuré : 56 → 2,549 · 80 → 2,669. Chaque détecteur
qui ne dira jamais rien **relève la barre pour tous les autres**.

## Pourquoi une fixture et pas le réseau

Les bougies sont de **vraies** bougies XAU/USD 5 min, relevées le 2026-09-09 et
figées. Aucun appel réseau.

⛔ La raison n'est pas le confort : `test_phase4_e2e` appelle Twelve Data, se
fait jeter en 429 selon l'ordre de la batterie, et **m'a fait accuser mon propre
code deux fois dans la même journée**. Un test qui dépend du réseau mesure le
voisinage, pas le code.

⚠️ Des données synthétiques ne conviendraient pas non plus : un détecteur se
calibre sur la structure réelle du marché, et un bruit gaussien fabriquerait des
fréquences qui ne veulent rien dire.

Cf. [[feedback_test_reseau_bisection_trompeuse]] · [[project_laboratoire_or_2026_09_08]]
"""
import collections
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.models.schemas import PatternType
from backend.services.pattern_detector import Candle, detect_patterns

_FIXTURE = Path(__file__).parent / "fixtures" / "bougies_xauusd_5min.json"

# ⛔ CE QUE CETTE PORTE PEUT — ET NE PEUT PAS — JUGER.
#
# Ma première version imposait un plancher à 1 % des fenêtres. Elle a
# immédiatement recalé quatre motifs EXISTANTS et légitimes :
#
#     mean_reversion_up 0,31 %   ·   poc_return_up 0,00 %
#
# Or le laboratoire leur trouve n=53 et n=86. Le seuil n'était pas trop
# strict : il était mal SPÉCIFIÉ. La fixture couvrait 3,5 jours quand le
# laboratoire en rejoue 90 — un facteur 26. Un motif à 0,1 % ici donne une
# vingtaine d'occurrences là-bas, ce qui n'a rien de « jamais mesurable ».
#
# 🔑 Cette porte ne peut donc PAS juger de la rareté utile : c'est le travail
# du laboratoire, qui dispose de la fenêtre longue. Elle juge les deux façons
# dont un détecteur est STRUCTURELLEMENT casse, et elles seules :
#
#     ne se declenche JAMAIS   -> condition impossible, faute de frappe
#     se declenche TOUJOURS    -> condition trop lache, du bruit
#
# ⚠️ La fixture a ete portee a 5 000 bougies (17 jours) pour que « jamais »
# veuille dire quelque chose. Elargir les bornes jusqu'a ce qu'un detecteur
# entre serait supprimer la porte en gardant l'apparence d'en avoir une —
# corriger une specification fausse est autre chose, et c'est ce qui est fait
# ici.
MAXI_PCT = 25.0


# ⛔ LA PRODUCTION TRAVAILLE SUR UNE FENETRE FIXE. `CANDLE_COUNT` vaut 50 :
# `detect_patterns` ne voit JAMAIS plus de 50 bougies. Ma premiere mesure lui
# passait un prefixe qui grandissait jusqu'a 5 000 — elle rendait
# `poc_return_down` a 48 % alors que le POC, calcule sur un historique de plus
# en plus long, se figeait et laissait le prix « revenir » en permanence.
#
# 🔑 Un banc d'essai qui ne reproduit pas la fenetre de production mesure un
# autre systeme. C'est le meme piege que le rejeu hors production qui rendait
# des scores a 0,0 le 08/09.
FENETRE = 50


@pytest.fixture(scope="module")
def frequences() -> dict[str, float]:
    """`{motif: % des fenêtres}`, en glissant une fenêtre de 50 bougies —
    exactement ce que voit la production."""
    brut = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    bougies = [
        Candle(timestamp=t0 + timedelta(minutes=5 * i),
               open=o, high=h, low=b, close=c, volume=0)
        for i, (o, h, b, c) in enumerate(brut)
    ]
    n = collections.Counter()
    fenetres = 0
    for i in range(FENETRE, len(bougies)):
        fenetres += 1
        for p in detect_patterns(bougies[i - FENETRE:i], "XAU/USD"):
            n[p.pattern.value] += 1
    return {m: 100.0 * v / fenetres for m, v in n.items()}


def test_la_fixture_est_bien_du_MARCHE_reel(frequences):
    """Garde-fou du garde-fou : une fixture abîmée rendrait 0 partout et les
    tests suivants passeraient en ne mesurant rien."""
    brut = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert len(brut) >= 5000
    assert all(len(b) == 4 and b[1] >= b[2] for b in brut), "haut < bas quelque part"
    assert len({b[3] for b in brut}) > 500, "trop de clotures identiques — pas du reel"


def test_la_fixture_couvre_assez_de_JOURS_pour_que_jamais_ait_un_sens(frequences):
    """⛔ Le garde-fou de la porte elle-même. Sur 3,5 jours, « zéro fois » ne
    distingue pas un détecteur cassé d'un motif rare — et la porte recalait
    des motifs parfaitement sains."""
    brut = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    jours = len(brut) * 5 / 60 / 24
    assert jours >= 14, f"fixture de {jours:.1f} jours — trop courte pour juger"


def test_aucun_motif_n_est_TROP_FREQUENT(frequences):
    """⛔ Au-delà de 25 %, ce n'est plus un motif mais un état permanent du
    marché — il « prédira » la moyenne et rien d'autre."""
    trop_frequents = {m: f for m, f in frequences.items() if f > MAXI_PCT}
    assert not trop_frequents, (
        f"motifs au-dessus de {MAXI_PCT} % des fenetres, du bruit deguise : "
        f"{ {m: round(f, 2) for m, f in trop_frequents.items()} }")


def test_TOUT_motif_declare_se_declenche_au_moins_une_fois(frequences):
    """⛔ Un `PatternType` qu'aucune bougie ne produit est du code mort qui se
    fait passer pour une couverture. Le detecteur peut avoir ete ecrit,
    branche, teste unitairement — et ne jamais mordre sur du vrai marche."""
    jamais = [p.value for p in PatternType if p.value not in frequences]
    assert not jamais, (
        f"declares mais JAMAIS detectes sur toute la fixture : {jamais}")


def test_la_porte_a_bien_des_BORNES(frequences):
    """Une porte dont les bornes sont si larges qu'elles n'excluent rien n'est
    pas une porte. On verifie qu'elle contraint vraiment."""
    assert 0 < MAXI_PCT < 50
    assert frequences, "aucun motif detecte : la mesure elle-meme est cassee"
