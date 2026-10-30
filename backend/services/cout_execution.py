"""Le cout d'execution REEL, en UN seul endroit.

## Le defaut que ce module ferme

Trois endroits facturaient trois couts differents pour le meme instrument, et
aucun ne facturait celui que l'execution paie :

| endroit | cout facture | verdict |
|---|---|---|
| `banc_esperance_horizon.SPREAD_PCT` | `0,0002` a plat, toute paire, tout instant | **4,4x TROP HAUT** pour l'or |
| `laboratoire_or` (route `/rates`) | ~5,0 points | **3,6x TROP BAS** |
| `ticks_courtier.db` (route `/ticks`) | ~8,2 points | trop bas de 10 points |

Mesure du 2026-10-30 sur 11 987 039 ticks (XAU/USD, 21/09 -> 30/10, zero
tick exclu) : spread median du magasin **0,0859 $**, markup inclus
**0,1859 $**, soit un relatif de **0,0000450**.

Une constante unique est fausse **dans les deux sens a la fois** : trop dure
la ou le spread est serre, trop douce la ou il s'ecarte. Elle ne peut donc pas
etre « prudente ».

## Le markup, et pourquoi il s'AJOUTE

Mesure du 2026-10-12 : 40 secondes appariees entre la route live et le
magasin, ecart median **+10,0 points**, ecart-type 1,2, **26/40 exactement
+10**. Confirme independamment par les prix d'execution reels, qui devient de
la MOITIE de l'ecart -- ce que predit un spread reel `= magasin + 10` (un
achat est rempli a `ask_magasin + 5`).

Verifie a nouveau le 2026-10-30 sur la route `/rates` : 3 312 bougies
appariees au magasin de ticks, ecart median **-2,4 points** et **0 %** a
+10 ==> `/rates` ne porte pas le markup non plus.

==> La route d'execution est `/tick`. **Tout cout lu dans un magasin doit se
voir ajouter `MARKUP_POINTS`.**

Ne PAS corriger une comparaison **appariee** : les deux bras paient le meme
cout manquant, donc leur difference est invariante. Corriger un seul bras est
la faute du 28/10. Ce module sert les **niveaux absolus**.

## La regle qui gouverne ce module

**Jamais de silence.** Tout cout rendu porte sa `source`. Un appelant qui
exige une mesure peut refuser une hypothese (`exiger_mesure`). C'est la lecon
des faux-surs du 28/10 et du 30/10 : « absent » n'est pas « vide ».
"""
from __future__ import annotations

import os
import sqlite3
from typing import NamedTuple

# --- Le markup du courtier, mesure ----------------------------------------
# Source : table `provenance` de ticks_courtier.db, cle `markup_live_points`.
# Mesure le 2026-10-12, 40 secondes appariees. NE PAS changer sans remesurer.
MARKUP_POINTS = 10.0
MARKUP_MESURE_LE = "2026-10-12"

# --- Taille du point, par paire. DECLAREE quand elle est connue ------------
# Une paire absente de cette table n'a pas de point connu : on ne devine pas.
# `cout_spread_relatif` rendra alors une hypothese de classe, marquee.
TAILLE_POINT: dict[str, float] = {
    "XAU/USD": 0.01,   # verifie par le pgcd de 870 valeurs de spread distinctes
}

# --- Hypotheses par CLASSE, pour les paires sans magasin de ticks ----------
# Ce sont des HYPOTHESES, pas des mesures. Aucun magasin courtier ne contient
# de bid/ask pour le forex, la crypto ou l'energie : la limite est dans les
# DONNEES, pas dans ce code. Toute valeur rendue depuis cette table porte la
# source `hypothese_classe` et doit etre refusee par un banc qui pretend
# mesurer un niveau absolu.
#
# Valeurs = spread relatif (fraction du prix). Le markup n'y est pas
# applicable : ce ne sont pas des lectures de magasin.
HYPOTHESE_CLASSE: dict[str, float] = {
    "metal":        0.0000450,   # ancre sur la mesure or (12 M de ticks)
    "forex_major":  0.0000200,   # borne HAUTE : spread_pts tronque a l'entier
    "forex_jpy":    0.0000200,
    "energy":       0.0002000,   # NON mesure : on garde l'ancienne constante
    "crypto":       0.0002000,   # NON mesure : on garde l'ancienne constante
    "equity_index": 0.0002000,   # NON mesure : on garde l'ancienne constante
}

_MAGASIN_DEFAUT = os.getenv("MAGASIN_TICKS", "/app/data/ticks_courtier.db")

# Tolerance de recherche d'un tick autour de l'instant demande.
TOLERANCE_SEC = 60

_FMT = "%Y-%m-%dT%H:%M:%S"


class Cout(NamedTuple):
    """Un cout de spread, et d'ou il vient.

    `relatif` est une FRACTION du prix (0,000045 = 0,0045 %), payee **une
    fois** par aller-retour. `source` dit si c'est une mesure ou une
    hypothese -- cette distinction est le coeur du module.
    """

    relatif: float
    source: str          # tick_instant | tick_moyen | hypothese_classe
    details: str

    @property
    def est_mesure(self) -> bool:
        return self.source.startswith("tick_")


def classe_de(pair: str) -> str:
    """La classe d'actif d'une paire, pour choisir une hypothese."""
    p = (pair or "").upper()
    base, _, quote = p.partition("/")
    if base in {"XAU", "XAG", "XPT", "XPD"}:
        return "metal"
    if base in {"WTI", "BRENT", "NATGAS"}:
        return "energy"
    if base in {"BTC", "ETH", "SOL", "ADA", "XRP", "LTC", "DOT", "BNB",
                "PAXG", "ALGO", "UNI", "DOGE", "LINK"}:
        return "crypto"
    if not quote or p in {"SPX", "NDX", "DAX", "CAC40", "US30", "NAS100"}:
        return "equity_index"
    if quote == "JPY":
        return "forex_jpy"
    return "forex_major"


def _hypothese(pair: str, pourquoi: str) -> Cout:
    cl = classe_de(pair)
    return Cout(HYPOTHESE_CLASSE[cl], "hypothese_classe",
                "classe=%s (%s) -- HYPOTHESE, pas une mesure" % (cl, pourquoi))


def cout_spread_relatif(pair: str, ts: str | None = None, *,
                        magasin: str | None = None) -> Cout:
    """Le cout du spread pour `pair`, a l'instant `ts` si on peut le lire.

    Cascade, du plus sur au moins sur -- et chaque etage DIT ce qu'il est :

    1. `tick_instant` : le tick le plus proche de `ts` (+/- TOLERANCE_SEC),
       markup ajoute. Le seul etage qui dit le cout de CE trade.
    2. `tick_moyen`   : la moyenne du magasin pour cette paire, markup
       ajoute. Un niveau juste, pas celui de l'instant.
    3. `hypothese_classe` : aucune donnee. Valeur declaree, marquee.

    Ne rend JAMAIS une valeur sans source. Un defaut substitue en silence a
    une absence est la faute que ce module existe pour empecher.
    """
    point = TAILLE_POINT.get((pair or "").upper())
    chemin = magasin or _MAGASIN_DEFAUT
    if point is None:
        return _hypothese(pair, "taille du point inconnue")
    if not os.path.exists(chemin):
        return _hypothese(pair, "magasin de ticks absent")

    markup = MARKUP_POINTS * point
    try:
        c = sqlite3.connect("file:%s?mode=ro" % chemin, uri=True)
    except sqlite3.Error as e:
        return _hypothese(pair, "magasin illisible : %s" % type(e).__name__)
    try:
        if ts:
            r = c.execute(
                "SELECT ask-bid, (ask+bid)/2.0 FROM ticks WHERE pair=?"
                "  AND ts_utc >= strftime(?, ?, ?)"
                "  AND ts_utc <= strftime(?, ?, ?)"
                "  AND ask > bid AND bid > 0"
                " ORDER BY abs(strftime('%s', ts_utc) - strftime('%s', ?))"
                " LIMIT 1",
                (pair, _FMT, ts, "-%d seconds" % TOLERANCE_SEC,
                 _FMT, ts, "+%d seconds" % TOLERANCE_SEC, ts)).fetchone()
            if r and r[1]:
                return Cout((r[0] + markup) / r[1], "tick_instant",
                            "tick a +/-%d s, markup %+.1f pt applique"
                            % (TOLERANCE_SEC, MARKUP_POINTS))
        r = c.execute(
            "SELECT AVG(ask-bid), AVG((ask+bid)/2.0) FROM ticks"
            " WHERE pair=? AND ask > bid AND bid > 0", (pair,)).fetchone()
        if r and r[0] and r[1]:
            return Cout((r[0] + markup) / r[1], "tick_moyen",
                        "moyenne du magasin, markup %+.1f pt applique"
                        % MARKUP_POINTS)
    except sqlite3.Error as e:
        return _hypothese(pair, "lecture impossible : %s" % type(e).__name__)
    finally:
        c.close()
    return _hypothese(pair, "aucun tick pour cette paire")


def exiger_mesure(cout: Cout) -> Cout:
    """Refuse une hypothese. A utiliser par tout banc qui publie un NIVEAU.

    Un banc qui annonce un P&L absolu sur une hypothese de classe annonce un
    nombre credible et faux. C'est exactement la faute du 13/10
    (« la protection a evite 642 EUR », fausse DE SIGNE).
    """
    if not cout.est_mesure:
        raise ValueError(
            "cout NON MESURE (%s) : %s. Un niveau absolu ne peut pas etre "
            "publie sur une hypothese -- mesurer, ou publier une comparaison "
            "APPARIEE, dont la difference est invariante au cout."
            % (cout.source, cout.details))
    return cout
