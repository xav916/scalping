#!/usr/bin/env python3
"""Banc : l'esperance de l'horizon `1d`, contre un PLACEBO de 200 tirages.

PRE-INSCRIT `d3cd3fe` -- `docs/preinscriptions/2026-10-27-esperance-1d.md`.
Ce banc n'applique QUE les branches de ce bloc machine. Aucun seuil n'est
decide ici.

POURQUOI CE BANC EXISTE. Le precedent (`cf31258`, addendum `52747fd`) a rendu
ADMISSION sous la convention A, mais son seuil de 35,71 % suppose que chaque
issue vaut +1,8 R ou -1 R -- faux pour les 46,5 % de TIMEOUT, qui sortent au
marche pour une FRACTION de R. On mesure donc une ESPERANCE.

LE CŒUR EST LE PLACEBO. Sans lui, une esperance positive ne distinguerait pas
la geometrie du simple fait d'etre expose au marche pendant dix jours. Chaque
tirage garde du reel : les paires, le nombre de setups par paire, la periode, le
`risk_pct`, le R:R de 1,8, la fenetre de 240 h et LE SENS. Seul l'INSTANT
D'ENTREE est tire au hasard -- c'est donc lui, et lui seul, que ce banc teste.

⛔ LECTURE SEULE sur la base (`mode=ro`), et aucune ecriture nulle part.

⛔ LE MOTEUR VECTORISE EST VERIFIE CONTRE LA PRODUCTION. Rejouer 272 400
simulations avec `simulate_trade_forward` serait trop lent, donc la recherche
du premier franchissement est vectorisee en numpy. Un desaccord avec la
fonction de production, meme sur une seule ligne, ARRETE le banc : ce serait un
defaut d'implementation, pas un resultat.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import random
import re
import sqlite3
import statistics
import sys
from datetime import datetime, timedelta, timezone

import numpy as np

sys.path.insert(0, ".")

from backend.models.schemas import Candle  # noqa: E402
from backend.services import binance_klines_service as bks  # noqa: E402
from backend.services import price_service  # noqa: E402
from backend.services.backtest_engine import simulate_trade_forward  # noqa: E402
from backend.services.shadow_v2_core_long import DB_PATH  # noqa: E402

# ─── Les seuils viennent du FICHIER PRE-INSCRIT, lus PAR NOM DE CHAMP ──────
#
# ⛔ POURQUOI, ET CA VIENT D ETRE PAYE. Ce banc recopiait ses seuils en
# constantes. Un test verifiait qu ils COINCIDAIENT avec la pre-inscription --
# mais seulement les NOMBRES, pas les NOMS. Le 2026-10-27, sur le banc de la
# geometrie 1d, CINQ NOMS SUR CINQ divergeaient entre le critere engage et le
# resultat emis, et rien ne le signalait. Et des que DEUX criteres partagent
# un banc (1d puis 4h), des constantes ne peuvent plus servir les deux.
#
# ⛔ ET SURTOUT PAS PAR POSITION. Extraire « le 1er nombre, le 2e... » d une
# clause composite lierait silencieusement les mauvais seuils si la
# pre-inscription les ecrivait dans un autre ordre. On lit donc chaque clause
# par le NOM DU CHAMP qu elle compare.
#
# 🔑 Une cle absente est un ARRET, jamais un defaut : retomber sur une valeur
# de secours ferait mesurer autre chose que ce qui a ete souscrit.

_CL_SIMPLE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:<=|>=|<|>)\s*([-+]?\d+(?:[.,]\d+)?)\s*$")
# ⛔ LE PREMIER CHAMP INTERNE fait partie de la cle, et c est indispensable :
# la clause `indecidable` du critere porte DEUX `abs(...)`
# (`abs(esperance_reel - esperance_placebo) < 0,01 ET abs(t) < 2,00`). Une cle
# unique « abs » faisait ecraser 0,01 par 2,00 -- exactement la liaison
# silencieuse que ce lecteur existe pour empecher, et elle m a eu dans le
# lecteur lui-meme.
_CL_ABS = re.compile(
    r"^\s*abs\(\s*([A-Za-z_][A-Za-z0-9_]*)[^)]*\)"
    r"\s*(?:<=|>=|<|>)\s*([-+]?\d+(?:[.,]\d+)?)\s*$")


def seuils_par_champ(expression: str) -> dict:
    """`{nom_de_champ: seuil}` pour une expression multi-clauses.

    Les clauses `abs(a - b) <op> n` sont rangees sous la cle `"abs"`. Une
    clause sans seuil numerique (comparaison de deux champs) est ignoree :
    elle ne porte aucun nombre a lire.
    """
    out = {}
    for clause in re.split(r"\s+ET\s+", expression or ""):
        m = _CL_ABS.match(clause)
        if m:
            out["abs:" + m.group(1)] = float(m.group(2).replace(",", "."))
            continue
        m = _CL_SIMPLE.match(clause)
        if m:
            out[m.group(1)] = float(m.group(2).replace(",", "."))
    return out


def _exige(d: dict, cle: str, ou: str):
    if cle not in d:
        raise SystemExit(
            f"ARRET : le seuil [{cle}] manque a [{ou}] du bloc"
            f" CRITERE-MACHINE. Le banc REFUSE de retomber sur un defaut : il"
            f" mesurerait autre chose que ce qui a ete souscrit.")
    return d[cle]


class Criteres:
    """Les seuils ENGAGES, lus une fois et jamais devines."""

    def __init__(self, chemin: str):
        import pathlib
        sys.path.insert(0, ".claude/skills")
        from or_commun import sections

        bloc = sections.bloc_machine(
            pathlib.Path(chemin).read_text(encoding="utf-8"))
        if not bloc:
            raise SystemExit(f"ARRET : aucun bloc CRITERE-MACHINE dans {chemin}")
        self.source = chemin
        self.horizon = bloc.get("horizon", "1d")
        self.fenetre_h = int(float(bloc.get("fenetre_heures", 240)))
        self.tirages = int(float(bloc.get("tirages_placebo", 200)))

        v = seuils_par_champ(bloc.get("validite", ""))
        self.n_min = int(_exige(v, "n_reel", "validite"))
        self.couverture_min = _exige(v, "couverture_bougies_pct", "validite")
        self.ecart_risk_max = _exige(
            v, "abs:risk_pct_median_placebo", "validite")
        self.tirages_min = int(_exige(v, "tirages_aboutis", "validite"))

        a = seuils_par_champ(bloc.get("admission", ""))
        self.t_min = _exige(a, "t_contre_placebo", "admission")
        self.battus_min = _exige(a, "tirages_battus_pct", "admission")

        i = seuils_par_champ(bloc.get("indecidable", ""))
        self.indecidable_ecart = _exige(
            i, "abs:esperance_R_reel", "indecidable")

        # ⛔ LES PREDICTIONS SONT CHARGEES GENERIQUEMENT, et pour une raison
        # concrete : la pre-inscription 1d porte un `P4` sur les TIMEOUT, la
        # 4h un `P4` sur le COUT. Exiger un nom fixe aurait fait planter le
        # banc sur un critere parfaitement valide.
        #
        # 🔑 ET LE BANC REFUSE DE TOURNER s il rencontre une prediction qu il
        # ne sait pas evaluer : une prediction inscrite mais NON NOTEE serait
        # un critere applique en partie, sans que rien ne le dise.
        self.predictions = {k: float(v) for k, v in bloc.items()
                            if re.match(r"P\d+_", k)}
        if not self.predictions:
            raise SystemExit(
                "ARRET : aucune prediction `P<n>_...` dans le bloc machine")

# ─── Seuils PRE-INSCRITS (verifies contre le fichier par un test) ───────────
# Les deux seules constantes qui ne viennent PAS du critere : le R:R de la
# geometrie (`PATTERN_TP1_RR` de production) et le cout de spread du moteur de
# backtest. Ce sont des faits du systeme, pas des seuils de decision.
RR = 1.80
SPREAD_PCT = 0.0002

# ⛔ Graine FIXE et declaree. Un placebo non reproductible ne peut pas etre
# re-verifie, donc ne peut pas etre cru.
GRAINE = 20261027


# ─── Moteur vectorise ───────────────────────────────────────────────────────


class Serie:
    """Les bougies d'une paire, en tableaux, pour chercher vite."""

    def __init__(self, bougies: list[Candle]):
        self.ts = np.array([c.timestamp.timestamp() for c in bougies])
        self.high = np.array([c.high for c in bougies])
        self.low = np.array([c.low for c in bougies])
        self.close = np.array([c.close for c in bougies])
        self.open = np.array([c.open for c in bougies])

    def __len__(self) -> int:
        return len(self.ts)

    def index_apres(self, t: float) -> int:
        return int(np.searchsorted(self.ts, t, side="right"))

    def simule(self, i0: int, t_fin: float, achat: bool,
               sl: float, tp: float) -> tuple[str, float] | None:
        """Premiere borne franchie apres l'indice `i0`, jusqu'a `t_fin`.

        Reproduit EXACTEMENT la regle de `simulate_trade_forward` :
        - on ignore les bougies dont l'horodatage est <= l'entree ;
        - on s'arrete au-dela de `entree + fenetre` ;
        - ⛔ SL et TP touches dans la MEME bougie => SL (pire cas), et c'est
          ce detail qui fait la difference sur un stop large.
        Rend `(issue, prix_de_sortie)`, ou `None` si aucune bougie.
        """
        i1 = self.index_apres(t_fin)
        if i1 <= i0:
            return None
        h = self.high[i0:i1]
        b = self.low[i0:i1]
        touche_sl = (b <= sl) if achat else (h >= sl)
        touche_tp = (h >= tp) if achat else (b <= tp)
        premier_sl = int(np.argmax(touche_sl)) if touche_sl.any() else len(h)
        premier_tp = int(np.argmax(touche_tp)) if touche_tp.any() else len(h)
        if premier_sl == len(h) and premier_tp == len(h):
            return ("TIMEOUT", float(self.close[i1 - 1]))
        # <= et non < : a egalite d'indice, le SL gagne (pire cas).
        if premier_sl <= premier_tp:
            return ("SL", sl)
        return ("TP1", tp)


def esperance_R(resultats: list[tuple[float, float]]) -> float | None:
    """Moyenne des `pnl_pct / risk_pct`. `None` si vide."""
    rs = [p / r for p, r in resultats if r > 0]
    return (sum(rs) / len(rs)) if rs else None


def t_contre_placebo(reel: float, tirages: list[float]) -> float | None:
    """Ecart du reel a la distribution des tirages, en ecarts-types.

    ⛔ `None` si moins de deux tirages ou si la dispersion est nulle : rendre
    0,0 ferait passer une absence de reference pour une egalite mesuree.
    """
    if len(tirages) < 2:
        return None
    sigma = statistics.stdev(tirages)
    if sigma <= 0:
        return None
    return (reel - statistics.fmean(tirages)) / sigma


def part_battus_pct(reel: float, tirages: list[float]) -> float | None:
    if not tirages:
        return None
    return 100.0 * sum(1 for x in tirages if x < reel) / len(tirages)


def branche(esp_reel, esp_placebo, t, battus, cout_R, valide,
            cr: "Criteres") -> str:
    """Applique MECANIQUEMENT les branches pre-inscrites."""
    if not valide:
        return "NON_CONCLUANT_VALIDITE"
    if esp_reel is None or t is None or battus is None or esp_placebo is None:
        return "NON_CONCLUANT_MESURE_ABSENTE"
    if (abs(esp_reel - esp_placebo) < cr.indecidable_ecart
            and abs(t) < cr.t_min):
        return "INDECIDABLE_REEL_ET_PLACEBO_INDISCERNABLES"
    if (esp_reel > cout_R and t > cr.t_min
            and battus >= cr.battus_min):
        return "ADMISSION_information_a_l_entree"
    if esp_reel <= 0 and t < cr.t_min:
        return "REJET_horizon_1d_ECARTE"
    return "NON_CONCLUANT_BRANCHES_EN_DESACCORD"


# ─── Chargement ─────────────────────────────────────────────────────────────


def lire_reels(db: str, horizon: str) -> list[dict]:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    lignes = c.execute(
        "SELECT pair, bar_timestamp, direction, entry_price, stop_loss,"
        "       take_profit_1, outcome, pnl_pct_net"
        "  FROM shadow_setups"
        " WHERE resolved_backfill = 1 AND timeframe = ?"
        " ORDER BY pair, bar_timestamp", (horizon,)).fetchall()
    out = []
    for p, bt, sens, e, sl, tp, issue, pnl in lignes:
        d = datetime.fromisoformat(bt)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        out.append({
            "pair": p, "bar": d, "achat": sens == "buy",
            "entry": e, "sl": sl, "tp": tp,
            "issue": issue, "pnl": pnl,
            "risk_pct": 100.0 * abs(e - sl) / e if e > 0 else 0.0,
        })
    return out


async def charge(paires: dict[str, tuple[datetime, datetime]]) -> dict[str, Serie]:
    from scripts import rattrapage_commun as commun

    async def chargeur(paire, debut, fin):
        if bks.is_crypto_pair(paire):
            return await bks.fetch_klines_fenetre(paire, "5min", debut, fin)
        return await price_service.fetch_candles_fenetre(
            paire, "5min", debut, fin, pause_entre_tranches=4.0)

    blocs = await commun.charge_les_blocs(paires, chargeur)
    return {p: Serie(cs) for p, cs in blocs.items() if cs}


# ─── Le banc ────────────────────────────────────────────────────────────────


def controle_moteur(reels: list[dict], series: dict[str, Serie],
                    fenetre_h: int) -> tuple[int, int]:
    """Le moteur vectorise doit rendre EXACTEMENT ce que rend la production.

    Compare issue par issue sur les setups reels. Un desaccord est un DEFAUT,
    pas un resultat -- et il doit arreter le banc.
    """
    from backend.models.schemas import TradeDirection

    class _Stub:
        def __init__(self, d):
            self.pair = d["pair"]
            self.direction = (TradeDirection.BUY if d["achat"]
                              else TradeDirection.SELL)
            self.entry_price = d["entry"]
            self.stop_loss = d["sl"]
            self.take_profit_1 = d["tp"]

    accord = essais = 0
    for d in reels:
        s = series.get(d["pair"])
        if s is None or not len(s):
            continue
        bougies = [Candle(timestamp=datetime.fromtimestamp(t, tz=timezone.utc),
                          open=o, high=h, low=b, close=cl, volume=0)
                   for t, o, h, b, cl in zip(s.ts, s.open, s.high, s.low, s.close)]
        attendu = simulate_trade_forward(_Stub(d), bougies, d["bar"],
                                         timeout_hours=fenetre_h)
        obtenu = s.simule(s.index_apres(d["bar"].timestamp()),
                          d["bar"].timestamp() + fenetre_h * 3600,
                          d["achat"], d["sl"], d["tp"])
        essais += 1
        if obtenu is not None and obtenu[0] == attendu[0]:
            accord += 1
    return accord, essais


def pnl_pct(entry: float, sortie: float, achat: bool) -> float:
    brut = (sortie - entry) / entry if achat else (entry - sortie) / entry
    return 100.0 * (brut - SPREAD_PCT)


# ─── Notation des predictions, par le NOM de la cle engagee ────────────────
#
# ⛔ UNE PREDICTION INSCRITE MAIS NON NOTEE SERAIT UN CRITERE APPLIQUE EN
# PARTIE, sans que rien ne le dise. Ce banc REFUSE donc de tourner s il
# rencontre une cle `P<n>_...` qu il ne sait pas evaluer -- plutot que de
# l ignorer en silence.
#
# 🔑 Les deux criteres partagent P1, P2, P3 et P5, mais leur P4 DIFFERE : le 1d
# predit que les TIMEOUT valent une bribe, le 4h que le COUT est materiel
# (0,0537 R contre 0,0021 R, facteur 26). Une table par NOM absorbe cela ; des
# constantes, non.

_NOTATION = {
    "P1_esperance_R_reel_attendue_max": (
        "esperance reelle sous le seuil",
        lambda m, v: m["esperance_R_reel"] is not None
        and m["esperance_R_reel"] < v),
    "P2_esperance_R_placebo_abs_max": (
        "|placebo| sous le seuil",
        lambda m, v: m["esperance_R_placebo"] is not None
        and abs(m["esperance_R_placebo"]) < v),
    "P3_tirages_battus_pct_attendu_max": (
        "tirages battus sous le seuil",
        lambda m, v: m["tirages_battus_pct"] is not None
        and m["tirages_battus_pct"] < v),
    "P4_esperance_R_timeout_abs_max": (
        "|TIMEOUT| sous le seuil",
        lambda m, v: m["esperance_R_timeout"] is not None
        and abs(m["esperance_R_timeout"]) < v),
    "P4_cout_R_median_min": (
        "cout median AU-DESSUS du seuil",
        lambda m, v: m["cout_R_median"] is not None
        and m["cout_R_median"] > v),
    "P5_ecart_esperance_B_moins_A_max": (
        "B - A sous le seuil",
        lambda m, v: m["ecart_esperance_B_moins_A"] is not None
        and m["ecart_esperance_B_moins_A"] <= v),
}


def noter_predictions(cr: "Criteres", mesures: dict) -> dict:
    """`{cle: {seuil, passe, libelle}}`. Toute cle inconnue est un ARRET."""
    out = {}
    for cle, seuil in sorted(cr.predictions.items()):
        if cle not in _NOTATION:
            raise SystemExit(
                f"ARRET : la prediction [{cle}] est inscrite au critere mais"
                f" ce banc ne sait pas la noter. Une prediction non notee"
                f" serait un critere applique EN PARTIE. Ajouter son"
                f" evaluateur a `_NOTATION`, avec son test.")
        libelle, f = _NOTATION[cle]
        out[cle] = {"seuil": seuil, "libelle": libelle,
                    "passe": bool(f(mesures, seuil))}
    return out


def mesure(db: str, cr: "Criteres", tirages: int | None = None,
           controle: bool = True) -> dict:
    import asyncio

    logging.getLogger("banc").info("=== lecture des setups 1d rattrapes")
    tirages = cr.tirages if tirages is None else tirages
    reels = lire_reels(db, cr.horizon)
    if not reels:
        return {"erreur": "aucun setup 1d rattrape"}

    bornes: dict[str, tuple[datetime, datetime]] = {}
    for d in reels:
        mn, mx = bornes.get(d["pair"], (d["bar"], d["bar"]))
        bornes[d["pair"]] = (min(mn, d["bar"]), max(mx, d["bar"]))
    logging.getLogger("banc").info("=== chargement des bougies (cadence, peut prendre ~10 min)")
    series = asyncio.run(charge(bornes))

    couverts = [d for d in reels if d["pair"] in series]
    couverture = 100.0 * len(couverts) / len(reels)

    accord = essais = -1
    logging.getLogger("banc").info("=== controle du moteur vectorise contre la production")
    if controle:
        accord, essais = controle_moteur(couverts, series, cr.fenetre_h)
        if essais and accord != essais:
            return {
                "erreur": "LE MOTEUR VECTORISE DIVERGE DE LA PRODUCTION",
                "accord": accord, "essais": essais,
                "consigne": ("c'est un defaut d'implementation, pas un"
                             " resultat : le banc s'arrete"),
            }

    # ─── le reel ───
    reel_pts = [(d["pnl"], d["risk_pct"]) for d in couverts
                if d["pnl"] is not None and d["risk_pct"] > 0]
    esp_reel = esperance_R(reel_pts)
    esp_B = esperance_R([(d["pnl"], d["risk_pct"]) for d in couverts
                         if d["issue"] in ("TP1", "SL")
                         and d["pnl"] is not None and d["risk_pct"] > 0])
    esp_timeout = esperance_R([(d["pnl"], d["risk_pct"]) for d in couverts
                               if d["issue"] == "TIMEOUT"
                               and d["pnl"] is not None and d["risk_pct"] > 0])
    risk_med_reel = statistics.median([d["risk_pct"] for d in couverts])
    cout_R = (100.0 * SPREAD_PCT) / risk_med_reel

    # ─── le placebo ───
    logging.getLogger("banc").info("=== placebo : 200 tirages")
    alea = random.Random(GRAINE)
    esperances: list[float] = []
    risks_placebo: list[float] = []
    for _ in range(tirages):
        pts: list[tuple[float, float]] = []
        for d in couverts:
            s = series[d["pair"]]
            mn, mx = bornes[d["pair"]]
            # l'entree est tiree dans la MEME periode que les setups reels de
            # cette paire ; la fenetre de 240 h peut depasser, comme au reel.
            t0 = mn.timestamp()
            t1 = mx.timestamp()
            if t1 <= t0:
                continue
            t = alea.uniform(t0, t1)
            i0 = s.index_apres(t)
            if i0 >= len(s):
                continue
            entry = float(s.open[i0])
            if entry <= 0:
                continue
            # MEME geometrie que le setup reel apparie
            dist = entry * d["risk_pct"] / 100.0
            signe = 1 if d["achat"] else -1
            sl = entry - signe * dist
            tp = entry + signe * dist * RR
            r = s.simule(i0, t + cr.fenetre_h * 3600, d["achat"], sl, tp)
            if r is None:
                continue
            pts.append((pnl_pct(entry, r[1], d["achat"]), d["risk_pct"]))
            risks_placebo.append(d["risk_pct"])
        if (len(esperances) + 1) % 20 == 0:
            logging.getLogger("banc").info(
                "    tirage %d / %d", len(esperances) + 1, tirages)
        e = esperance_R(pts)
        if e is not None:
            esperances.append(e)

    esp_placebo = statistics.fmean(esperances) if esperances else None
    t_stat = (t_contre_placebo(esp_reel, esperances)
              if esp_reel is not None else None)
    battus = (part_battus_pct(esp_reel, esperances)
              if esp_reel is not None else None)
    risk_med_placebo = (statistics.median(risks_placebo)
                        if risks_placebo else None)

    valide = bool(
        len(couverts) >= cr.n_min
        and couverture > cr.couverture_min
        and risk_med_placebo is not None
        and abs(risk_med_placebo - risk_med_reel) < cr.ecart_risk_max
        and len(esperances) >= cr.tirages_min
    )

    ecart_B_moins_A = (esp_B - esp_reel
                       if (esp_B is not None and esp_reel is not None) else None)

    resultat = {
        # La FORME du banc, declaree et non devinee : `or-verdict` ne juge
        # pas un placebo comme un rejeu, et deviner la forme confondrait
        # « il n y a pas de rejeu » avec « le rejeu est casse ».
        "forme": "placebo",
        "preinscription": "docs/preinscriptions/2026-10-27-esperance-1d.md",
        "commit_preinscription": "d3cd3fe",
        "graine": GRAINE,
        "n": len(couverts),
        # `n_reel` est le nom employe par la clause de validite pre-inscrite.
        "n_reel": len(couverts),
        "n_reel_total": len(reels),
        "couverture_bougies_pct": couverture,
        "controle_moteur_accord": accord,
        "controle_moteur_essais": essais,
        "risk_pct_median_reel": risk_med_reel,
        "risk_pct_median_placebo": risk_med_placebo,
        "cout_R_median": cout_R,
        "esperance_R_reel": esp_reel,
        "esperance_R_placebo": esp_placebo,
        "esperance_R_convention_B": esp_B,
        "esperance_R_timeout": esp_timeout,
        "tirages_demandes": tirages,
        "tirages_aboutis": len(esperances),
        "t": t_stat,
        "t_contre_placebo": t_stat,
        "tirages_battus_pct": battus,
        "ecart_esperance_B_moins_A": ecart_B_moins_A,
        "predictions": None,  # renseigne juste apres
        "valide": valide,
        "verdict": branche(esp_reel, esp_placebo, t_stat, battus, cout_R,
                           valide, cr),
        # ⛔ Comme le banc precedent : il n'y a pas de REJEU a confronter a la
        # realite, donc pas d'ecart par trade. Emettre 0.0 ferait croire a une
        # fidelite parfaite.
        "ecart_par_trade": None,
        "placebo": f"{tirages}_TIRAGES_GRAINE_{GRAINE}",
        "horizon": cr.horizon,
        "fenetre_heures": cr.fenetre_h,
        "critere_lu_dans": cr.source,
    }
    # ⛔ Les predictions sont notees APRES coup, sur les mesures REELLEMENT
    # emises. Les noter dans le dict en construction obligerait a recopier
    # chaque valeur -- donc a pouvoir se tromper de valeur.
    resultat["predictions"] = noter_predictions(cr, resultat)
    return resultat


def rapport(r: dict) -> str:
    if "erreur" in r:
        return f"=== ARRET : {r['erreur']}\n    {r.get('consigne', '')}\n" \
               f"    accord {r.get('accord')} / {r.get('essais')}"
    out = []
    p = out.append
    p("=== BANC : l'esperance de l'horizon 1d, contre placebo")
    p(f"    pre-inscrit {r['commit_preinscription']} · graine {r['graine']}")
    p("")
    p(f"  n = {r['n']} sur {r['n_reel_total']}"
      f"   couverture {r['couverture_bougies_pct']:.2f} %")
    p(f"  controle du moteur vectorise : {r['controle_moteur_accord']}"
      f" / {r['controle_moteur_essais']} en accord avec la production")
    p("")
    p("  VALIDITE")
    p(f"    n >= {r['validite_n_min']} ................... {r['n']}")
    p(f"    couverture > 99 % ................. {r['couverture_bougies_pct']:.2f} %")
    p(f"    risk median reel / placebo ........ {r['risk_pct_median_reel']:.3f} %"
      f" / {_f(r['risk_pct_median_placebo'])} %")
    p(f"    tirages aboutis >= 190 ............ {r['tirages_aboutis']}"
      f" / {r['tirages_demandes']}")
    p(f"    => valide : {r['valide']}")
    p("")
    p("  ESPERANCES (en R par setup)")
    p(f"    reel (convention A) ............... {_f(r['esperance_R_reel'])}")
    p(f"    placebo ({r['tirages_aboutis']} tirages) ........... {_f(r['esperance_R_placebo'])}")
    p(f"    convention B (resolus seuls) ...... {_f(r['esperance_R_convention_B'])}")
    p(f"    TIMEOUT seuls ..................... {_f(r['esperance_R_timeout'])}")
    p(f"    cout median ....................... {_f(r['cout_R_median'])}")
    p("")
    p("  PREDICTIONS")
    for cle, d in (r.get("predictions") or {}).items():
        p(f"    {cle[:2]}  {d['libelle']:34s} seuil {d['seuil']:+7.3f}"
          f"   {_ok(d['passe'])}")
    p("")
    p(f"  t contre placebo : {_f(r['t_contre_placebo'])}"
      f"    tirages battus : {_f(r['tirages_battus_pct'])} %")
    p(f"  VERDICT : {r['verdict']}")
    return "\n".join(out)


def _f(v):
    return "   --  " if v is None else f"{v:+8.4f}"


def _ok(b):
    return "PASSE" if b else "echoue"


# `argv` injectable : un point d entree non testable n est pas teste, et
# c est par la que les deux NameError du 27/10 sont passees.
def main(argv: list[str] | None = None) -> int:
    # ⛔ UN TRAVAIL DE DIX MINUTES NE DOIT PAS ETRE MUET. Le 2026-10-27 ce
    # banc n imprimait rien avant la fin et n appelait pas `basicConfig` :
    # j en ai conclu qu il etait MORT alors qu il tournait. Un long silence
    # est indiscernable d une panne.
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__)
    # ⛔ OBLIGATOIRE : le banc ne porte aucun seuil de decision, il les LIT.
    p.add_argument("--preinscription", required=True,
                   help="le fichier dont le bloc CRITERE-MACHINE est engage")
    p.add_argument("--db", default=str(DB_PATH))
    p.add_argument("--tirages", type=int, default=None,
                   help="defaut : la valeur du bloc machine")
    p.add_argument("--json")
    p.add_argument("--sans-controle-moteur", action="store_true",
                   help="⛔ a n'utiliser que pour une mise au point")
    a = p.parse_args(argv)
    cr = Criteres(a.preinscription)
    r = mesure(a.db, cr, a.tirages,
               controle=not a.sans_controle_moteur)
    print(rapport(r))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(r, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n  resultat machine : {a.json}")
    return 1 if "erreur" in r else 0


if __name__ == "__main__":
    sys.exit(main())
