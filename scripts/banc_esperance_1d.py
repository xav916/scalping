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

# ─── Seuils PRE-INSCRITS (verifies contre le fichier par un test) ───────────
TIRAGES_PLACEBO = 200
RR = 1.80
FENETRE_H = 240
SPREAD_PCT = 0.0002
VALIDITE_N_MIN = 1000
VALIDITE_COUVERTURE_PCT = 99.0
VALIDITE_ECART_RISK_PCT = 1.0
VALIDITE_TIRAGES_MIN = 190
ADMISSION_T_MIN = 2.00
ADMISSION_BATTUS_PCT = 95.0
INDECIDABLE_ECART_R = 0.01
P2_PLACEBO_ABS_MAX = 0.05
P4_TIMEOUT_ABS_MAX = 0.20
P5_ECART_B_MOINS_A_MAX = -0.05

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


def branche(esp_reel, esp_placebo, t, battus, cout_R, valide) -> str:
    """Applique MECANIQUEMENT les branches pre-inscrites."""
    if not valide:
        return "NON_CONCLUANT_VALIDITE"
    if esp_reel is None or t is None or battus is None or esp_placebo is None:
        return "NON_CONCLUANT_MESURE_ABSENTE"
    if (abs(esp_reel - esp_placebo) < INDECIDABLE_ECART_R
            and abs(t) < ADMISSION_T_MIN):
        return "INDECIDABLE_REEL_ET_PLACEBO_INDISCERNABLES"
    if (esp_reel > cout_R and t > ADMISSION_T_MIN
            and battus >= ADMISSION_BATTUS_PCT):
        return "ADMISSION_information_a_l_entree"
    if esp_reel <= 0 and t < ADMISSION_T_MIN:
        return "REJET_horizon_1d_ECARTE"
    return "NON_CONCLUANT_BRANCHES_EN_DESACCORD"


# ─── Chargement ─────────────────────────────────────────────────────────────


def lire_reels(db: str) -> list[dict]:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    lignes = c.execute(
        "SELECT pair, bar_timestamp, direction, entry_price, stop_loss,"
        "       take_profit_1, outcome, pnl_pct_net"
        "  FROM shadow_setups"
        " WHERE resolved_backfill = 1 AND timeframe = '1d'"
        " ORDER BY pair, bar_timestamp").fetchall()
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


def controle_moteur(reels: list[dict], series: dict[str, Serie]) -> tuple[int, int]:
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
                                         timeout_hours=FENETRE_H)
        obtenu = s.simule(s.index_apres(d["bar"].timestamp()),
                          d["bar"].timestamp() + FENETRE_H * 3600,
                          d["achat"], d["sl"], d["tp"])
        essais += 1
        if obtenu is not None and obtenu[0] == attendu[0]:
            accord += 1
    return accord, essais


def pnl_pct(entry: float, sortie: float, achat: bool) -> float:
    brut = (sortie - entry) / entry if achat else (entry - sortie) / entry
    return 100.0 * (brut - SPREAD_PCT)


def mesure(db: str, tirages: int = TIRAGES_PLACEBO,
           controle: bool = True) -> dict:
    import asyncio

    logging.getLogger("banc").info("=== lecture des setups 1d rattrapes")
    reels = lire_reels(db)
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
        accord, essais = controle_moteur(couverts, series)
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
            r = s.simule(i0, t + FENETRE_H * 3600, d["achat"], sl, tp)
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
        len(couverts) >= VALIDITE_N_MIN
        and couverture > VALIDITE_COUVERTURE_PCT
        and risk_med_placebo is not None
        and abs(risk_med_placebo - risk_med_reel) < VALIDITE_ECART_RISK_PCT
        and len(esperances) >= VALIDITE_TIRAGES_MIN
    )

    ecart_B_moins_A = (esp_B - esp_reel
                       if (esp_B is not None and esp_reel is not None) else None)

    return {
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
        "P1_passe": (esp_reel is not None and esp_reel < 0.0),
        "P2_passe": (esp_placebo is not None
                     and abs(esp_placebo) < P2_PLACEBO_ABS_MAX),
        "P3_passe": (battus is not None and battus < ADMISSION_BATTUS_PCT),
        "P4_passe": (esp_timeout is not None
                     and abs(esp_timeout) < P4_TIMEOUT_ABS_MAX),
        "P5_passe": (ecart_B_moins_A is not None
                     and ecart_B_moins_A <= P5_ECART_B_MOINS_A_MAX),
        "valide": valide,
        "verdict": branche(esp_reel, esp_placebo, t_stat, battus, cout_R, valide),
        # ⛔ Comme le banc precedent : il n'y a pas de REJEU a confronter a la
        # realite, donc pas d'ecart par trade. Emettre 0.0 ferait croire a une
        # fidelite parfaite.
        "ecart_par_trade": None,
        "placebo": f"{TIRAGES_PLACEBO}_TIRAGES_GRAINE_{GRAINE}",
    }


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
    p(f"    n >= {VALIDITE_N_MIN} ................... {r['n']}")
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
    p(f"    P1  esperance reelle < 0 .......... {_f(r['esperance_R_reel'])}   {_ok(r['P1_passe'])}")
    p(f"    P2  |placebo| < 0,05 .............. {_f(r['esperance_R_placebo'])}   {_ok(r['P2_passe'])}")
    p(f"    P3  tirages battus < 95 % ......... {_f(r['tirages_battus_pct'])} %   {_ok(r['P3_passe'])}")
    p(f"    P4  |TIMEOUT| < 0,20 .............. {_f(r['esperance_R_timeout'])}   {_ok(r['P4_passe'])}")
    p(f"    P5  B - A <= -0,05 ................ {_f(r['ecart_esperance_B_moins_A'])}   {_ok(r['P5_passe'])}")
    p("")
    p(f"  t contre placebo : {_f(r['t_contre_placebo'])}"
      f"    tirages battus : {_f(r['tirages_battus_pct'])} %")
    p(f"  VERDICT : {r['verdict']}")
    return "\n".join(out)


def _f(v):
    return "   --  " if v is None else f"{v:+8.4f}"


def _ok(b):
    return "PASSE" if b else "echoue"


def main() -> int:
    # ⛔ UN TRAVAIL DE DIX MINUTES NE DOIT PAS ETRE MUET. Le 2026-10-27 ce
    # banc n imprimait rien avant la fin et n appelait pas `basicConfig` :
    # j en ai conclu qu il etait MORT alors qu il tournait. Un long silence
    # est indiscernable d une panne.
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=str(DB_PATH))
    p.add_argument("--tirages", type=int, default=TIRAGES_PLACEBO)
    p.add_argument("--json")
    p.add_argument("--sans-controle-moteur", action="store_true",
                   help="⛔ a n'utiliser que pour une mise au point")
    a = p.parse_args()
    r = mesure(a.db, a.tirages, controle=not a.sans_controle_moteur)
    print(rapport(r))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(r, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n  resultat machine : {a.json}")
    return 1 if "erreur" in r else 0


if __name__ == "__main__":
    sys.exit(main())
