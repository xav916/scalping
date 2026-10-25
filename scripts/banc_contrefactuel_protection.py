#!/usr/bin/env python3
"""Ce que la protection des pertes a VRAIMENT evite, sur les trades REELS du 12/10.

Pre-inscrit le 2026-10-13 (commit 6bcc600), AVANT ce code. Mesure le 2026-10-25.

Rejeu APPARIE des 165 trades automatiques du 12/10 sur les ticks reels :
  A  la protection telle qu'ARMEE (relevee dans la crontab, pas dans ma prose)
  B  sans elle : le stop initial ne bouge plus JAMAIS cote perte
Les deux gardent le trainage cote GAIN, puisque c'est l'etat du 12/10.

ON IMPORTE LES MODULES DE PRODUCTION. Reimplementer la regle, c'est la juger
avec sa paraphrase -- exactement la faute du 12/10 (sonde a 0,50 contre acteur
a 0,375). Si la production change, ce banc change avec elle.
"""
import os
import sys
import json
import bisect
import sqlite3
import statistics
from functools import lru_cache

# --- Les reglages ARMES, releves dans la crontab de l'hote le 25/10 ----------
#     * * * * * PROTECTION_PERTE_OR=1 PROTECTION_PERTE_FENETRE_SEC=60
#               PROTECTION_PERTE_PLANCHER_EUR=2
#               PROTECTION_PERTE_LARGEUR_MAX_EUR=9
#               PROTECTION_PERTE_PLANCHER_SPREAD_K=2
os.environ["PROTECTION_PERTE_OR"] = "1"
os.environ["PROTECTION_PERTE_FENETRE_SEC"] = "60"
os.environ["PROTECTION_PERTE_PLANCHER_EUR"] = "2"
os.environ["PROTECTION_PERTE_LARGEUR_MAX_EUR"] = "9"
os.environ["PROTECTION_PERTE_PLANCHER_SPREAD_K"] = "2"
# Le trainage etait ARME le 12/10 (desarme le 13/10) : on rejoue l'etat du jour.
os.environ["ECHELLE_STOP_OR"] = "1"
# ⛔ DEFAUT DU 2e REJEU : j'avais pris la configuration D'AUJOURD'HUI, qui indexe
# le trainage sur le spread (SPREAD_K=2 => ~0,34 EUR). Le commit du 12/10 est
# `59a93b3` : "Trainage indexe sur le SPREAD mesure -- livre DESARME". Donc ce
# jour-la le trainage valait 0,50 EUR FIXE. Un trainage plus serre sort plus
# souvent en TRAILING_SL et moins en SL : exactement l'ecart 135/30 contre
# 108/57 observe. On repose l'etat du jour.
os.environ.pop("ECHELLE_STOP_OR_TRAINAGE_SPREAD_K", None)
os.environ["ECHELLE_STOP_OR_TRAINAGE_EUR"] = "0.50"

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/scripts")
import protection_perte_or as P                      # noqa: E402
from backend.services import echelle_stop_or as E    # noqa: E402

# --- MEMOISATION, et seulement de fonctions PURES -----------------------------
# Un bras B peut faire vivre un trade jusqu'en fin de journee : a 1 appel par
# seconde simulee, les lecteurs d'environnement de l'echelle sont appeles des
# millions de fois et dominent le temps de calcul.
#
# On ne memoise QUE des fonctions dont la valeur ne peut pas changer pendant le
# rejeu : celles qui ne lisent que l'environnement (constant ici), et
# `trainage_eur` dont la cle est le spread EXACT, sans arrondi.
# Aucune regle n'est modifiee : c'est le meme code, appele moins souvent.
_echelle_brute = E.echelle
_trainage_brut = E.trainage_eur
E.echelle = lru_cache(maxsize=1)(_echelle_brute)
E.trainage_eur = lru_cache(maxsize=4096)(_trainage_brut)
if hasattr(E, "mode_trainage"):
    E.mode_trainage = lru_cache(maxsize=1)(E.mode_trainage)
if hasattr(E, "trainage_spread_k"):
    E.trainage_spread_k = lru_cache(maxsize=1)(E.trainage_spread_k)
if hasattr(E, "pas_mini_eur"):
    E.pas_mini_eur = lru_cache(maxsize=1)(E.pas_mini_eur)

# --- LE SPREAD DOIT VENIR DU 12/10, PAS DU PONT ------------------------------
# DEFAUT ATTRAPE LE 25/10 par la sortie du banc lui-meme :
#   "plancher au spread demande (k=2.0) mais spread illisible
#    — repli sur le plancher fixe"
# `stop_vise_prix` appelle `spread_eur()`, qui interroge le pont EN DIRECT.
# Pont mort => 10 s de timeout par appel, et surtout la protection aurait ete
# rejouee avec le plancher FIXE de 2 EUR au lieu de k=2 x spread : juger avec
# une autre regle que celle armee, exactement la faute du 12/10.
#
# On remplace donc la LECTURE du spread, jamais son USAGE : la regle recoit le
# spread qu'elle avait reellement a cet instant-la, lu dans le magasin de ticks.
_spread_du_tick = {"eur": None}
P.spread_eur = lambda pair, taux: _spread_du_tick["eur"]

JOUR = "2026-10-12"
MARKUP_USD = float(os.environ.get("BANC_MARKUP_USD", "0.10"))          # mesure du 12/10 : magasin + 10 points = cout reel
CADENCE_PROTECTION = 60    # crontab : * * * * *
CADENCE_TRAINAGE = 1       # ECHELLE_STOP_INTERVAL_SEC=1
# DEFAUT DU PREMIER REJEU (25/10) : je donnais a la protection une negativite
# PARFAITE, calculee a chaque tick. En production elle ne calcule rien : elle
# LIT la sonde (`_histoire()` -> table echelle_or_suivi), qui fixe
# `negatif_depuis` a sa PREMIERE observation negative et ne le rafraichit
# jamais. Sans enregistrement, `eligible` s'abstient (fail-closed).
#
# ⛔ ET MA PREMIERE CORRECTION ETAIT FAUSSE AUSSI : j'avais lu
#   2-59/5 * * * * .../sondes_p0.sh
# et conclu a une sonde toutes les 5 minutes. Mais `sondes_p0.sh` lance
# `sondes_p0.py` (la SURVEILLANCE). La sonde qui ecrit `echelle_or_suivi` a sa
# propre ligne de crontab :
#   * * * * * /opt/scalping/jobs/sonde_echelle_or.sh   => TOUTES LES MINUTES
# Ce qui concorde avec la mesure deja au depot (« la protection n'agit qu'a
# ~90 s ») -- une contradiction que j'aurais du voir tout de suite.
SONDE_MINUTE_MODULO = 1    # la sonde passe a CHAQUE minute
SONDE_MINUTE_RESTE = 0
TRADES = "/app/data/trades.db"
TICKS = "/app/data/ticks_courtier.db"


def charger_trades():
    c = sqlite3.connect("file:%s?mode=ro" % TRADES, uri=True)
    q = ("select id, direction, fill_price, entry_price, stop_loss, take_profit,"
         " created_at, closed_at, exit_price, pnl, close_reason, size_lot"
         " from personal_trades"
         " where date(created_at)=? and is_auto=1 and pair='XAU/USD'"
         "   and closed_at is not null and fill_price is not null"
         " order by created_at")
    champs = ("id", "sens", "fill", "entry", "sl", "tp", "ouvert",
              "ferme", "sortie", "pnl", "motif", "lot")
    return [dict(zip(champs, r)) for r in c.execute(q, (JOUR,))]


def taux_implique(trades):
    """Le taux EUR/USD du jour, DEDUIT de leurs propres chiffres.

    pnl = signe * (sortie - entree) / taux  pour 0,01 lot (1 once).
    On ne devine pas un taux : on lit celui que la production a utilise.
    """
    ech = []
    for t in trades:
        if not t["pnl"] or not t["sortie"] or not t["fill"]:
            continue
        signe = 1 if str(t["sens"]).lower().startswith("b") else -1
        usd = signe * (float(t["sortie"]) - float(t["fill"]))
        if abs(float(t["pnl"])) > 1e-9:
            ech.append(usd / float(t["pnl"]))
    return statistics.median(ech), len(ech)


def charger_ticks():
    c = sqlite3.connect("file:%s?mode=ro" % TICKS, uri=True)
    q = ("select ts_utc, ms, bid, ask from ticks"
         " where pair='XAU/USD' and ts_utc like ? order by ms")
    return [(ts, int(ms), float(b), float(a))
            for ts, ms, b, a in c.execute(q, (JOUR + "%",))]


def _mieux(nouveau, actuel, signe):
    """Un stop ne recule jamais : c'est le cliquet, et il vaut pour les 2 bras."""
    if actuel is None:
        return True
    return (nouveau > actuel) if signe > 0 else (nouveau < actuel)


def _trainage_vise(entree, sens, profit_eur, taux, spread_eur):
    """Le stop vise par le trainage cote GAIN, via le module de production."""
    try:
        return E.stop_vise(entree, sens, profit_eur, taux, spread_eur)
    except Exception:
        return None


def rejouer(trade, ticks, i0, taux, avec_protection):
    """Rejoue UN trade tick par tick. Rend (pnl_eur, motif, secondes_vecues)."""
    signe = 1 if str(trade["sens"]).lower().startswith("b") else -1
    sens = "buy" if signe > 0 else "sell"
    entree = float(trade["fill"])
    sl = float(trade["sl"])
    tp = float(trade["tp"]) if trade["tp"] else None
    t0 = ticks[i0][1]

    debut_negatif_ms = None       # quand la negativite a COMMENCE
    dernier_passage_protection = t0
    dernier_passage_trainage = t0
    derniere_empreinte_trainage = None
    derniere_minute_sonde = None  # etat de la sonde, cadencee a 5 min
    sonde_ouvert_ms = None       # None = position jamais observee

    for ts, ms, bid, ask in ticks[i0:]:
        # Cout reel : le magasin sous-estime le spread de 10 points (12/10).
        # L'ecart d'execution mesure valait la MOITIE du gap => split symetrique.
        bid_r = bid - MARKUP_USD / 2.0
        ask_r = ask + MARKUP_USD / 2.0
        # On sort toujours au prix defavorable : un achat se solde au bid.
        courant = bid_r if signe > 0 else ask_r
        age = (ms - t0) / 1000.0

        # --- le stop est-il touche ? (avant toute decision, comme le courtier)
        #
        # ⛔ DEFAUT DU 4e REJEU : je soldais au NIVEAU du stop (`sl`) alors que
        # je detectais le declenchement au prix REEL. Le cout du spread etait
        # donc paye une seule fois, au lieu de deux (entree ET sortie) -- et
        # l'ecart manquant valait 0,188 EUR/trade, soit presque exactement
        # 2 x le markup de 10 points mesure le 12/10.
        # Un stop se remplit au prix QUI L'A DECLENCHE, jamais a son niveau :
        # les ticks sautent, et le saut est toujours contre nous.
        if (signe > 0 and courant <= sl) or (signe < 0 and courant >= sl):
            gain = signe * (courant - entree)
            motif = "TRAILING_SL" if gain > 0 else "SL"
            return gain / taux, motif, age
        if tp is not None and ((signe > 0 and courant >= tp)
                               or (signe < 0 and courant <= tp)):
            return signe * (courant - entree) / taux, "TP", age

        perte_eur = signe * (entree - courant) / taux
        profit_eur = -perte_eur

        # --- LA SONDE, telle qu'elle passe vraiment : toutes les 5 minutes.
        # Elle n'enregistre que ce qu'elle VOIT a son passage, et ne rafraichit
        # jamais `negatif_depuis` tant que la position reste negative.
        minute_cle = ts[:16]          # "2026-10-12T HH:MM"
        if minute_cle != derniere_minute_sonde:
            mm = int(ts[14:16])
            if mm % SONDE_MINUTE_MODULO == SONDE_MINUTE_RESTE:
                derniere_minute_sonde = minute_cle
                sonde_ouvert_ms = t0           # la sonde connait l'ouverture
                if perte_eur > 0:
                    if debut_negatif_ms is None:
                        debut_negatif_ms = ms  # premiere observation negative
                else:
                    debut_negatif_ms = None    # remise a zero

        # Ce que la protection LIT : les horodatages de la sonde, ou rien.
        if sonde_ouvert_ms is None:
            age_vu, negatif_depuis = None, None      # jamais observee
        else:
            age_vu = (ms - sonde_ouvert_ms) / 1000.0
            negatif_depuis = None if debut_negatif_ms is None \
                else (ms - debut_negatif_ms) / 1000.0

        spread_eur = (ask_r - bid_r) / taux

        # --- TRAINAGE cote gain : actif dans LES DEUX bras (etat du 12/10)
        if (ms - dernier_passage_trainage) / 1000.0 >= CADENCE_TRAINAGE:
            dernier_passage_trainage = ms
            # `stop_vise` est PURE en (entree, sens, profit, taux, spread) ;
            # entree/sens/taux sont fixes. Si profit ET spread sont inchanges,
            # elle rendrait le MEME prix, que `_mieux` rejette deja. Sauter
            # l'appel est donc strictement equivalent, pas une approximation.
            empreinte = (profit_eur, spread_eur)
            if empreinte != derniere_empreinte_trainage:
                derniere_empreinte_trainage = empreinte
                vise = _trainage_vise(entree, sens, profit_eur, taux, spread_eur)
                if vise is not None and _mieux(vise, sl, signe):
                    sl = vise

        # --- PROTECTION cote perte : bras A seulement
        if avec_protection and \
           (ms - dernier_passage_protection) / 1000.0 >= CADENCE_PROTECTION:
            dernier_passage_protection = ms
            ok, _motif = P.eligible(age_vu, perte_eur, negatif_depuis)
            if ok:
                # le spread du 12/10 a CET instant, pas celui du pont
                _spread_du_tick["eur"] = spread_eur
                position = {"symbol": "XAUUSD", "type": sens,
                            "price_open": entree, "price_current": courant,
                            "sl": sl, "comment": E.MARQUE_RADAR,
                            "volume": 0.01}
                nv = P.stop_vise_prix(position, taux)
                if nv is not None and _mieux(nv, sl, signe):
                    sl = nv

    # fin de la journee de ticks : on solde au dernier prix connu
    ms = ticks[-1][1]
    courant = (ticks[-1][2] - MARKUP_USD / 2.0) if signe > 0 \
        else (ticks[-1][3] + MARKUP_USD / 2.0)
    return signe * (courant - entree) / taux, "FIN_DE_JOURNEE", (ms - t0) / 1000.0


def index_horodatages(ticks):
    """Les horodatages normalises, une seule fois, pour une recherche binaire."""
    return [ts.replace("T", " ") for ts, _ms, _b, _a in ticks]


def premier_tick(horodatages, horodatage):
    cible = str(horodatage)[:19].replace("T", " ")
    k = bisect.bisect_left(horodatages, cible)
    return k if k < len(horodatages) else None


def main():
    trades = charger_trades()
    taux, n_taux = taux_implique(trades)
    ticks = charger_ticks()
    print("trades rejoues      : %d" % len(trades))
    print("ticks du %s   : %d" % (JOUR, len(ticks)))
    print("taux EUR/USD DEDUIT : %.5f  (median sur %d trades)" % (taux, n_taux))
    print()

    horodatages = index_horodatages(ticks)
    lignes = []
    sautes = 0
    for t in trades:
        i0 = premier_tick(horodatages, t["ouvert"])
        if i0 is None or i0 >= len(ticks) - 1:
            sautes += 1
            continue
        a_pnl, a_motif, _a_age = rejouer(t, ticks, i0, taux, True)
        b_pnl, b_motif, _b_age = rejouer(t, ticks, i0, taux, False)
        lignes.append({"id": t["id"], "reel": float(t["pnl"] or 0),
                       "motif_reel": t["motif"], "a": a_pnl, "a_motif": a_motif,
                       "b": b_pnl, "b_motif": b_motif})

    if not lignes:
        print("AUCUN trade rejouable")
        return 1
    if sautes:
        print("%d trade(s) sans tick exploitable, ECARTES (et comptes ici)" % sautes)
        print()

    A = [x["a"] for x in lignes]
    B = [x["b"] for x in lignes]
    D = [b - a for a, b in zip(A, B)]
    n = len(D)
    moy = statistics.fmean(D)
    sd = statistics.stdev(D) if n > 1 else 0.0
    t_stat = moy / (sd / (n ** 0.5)) if sd > 0 else float("nan")

    reel = sum(x["reel"] for x in lignes)
    print("=== TOTAUX (EUR)")
    print("  reel observe le 12/10      : %+8.2f" % reel)
    print("  A  avec protection         : %+8.2f" % sum(A))
    print("  B  sans protection         : %+8.2f" % sum(B))
    print("  B - A (ce qu elle a evite) : %+8.2f" % (sum(B) - sum(A)))
    print()
    print("=== ECART APPARIE B - A, par trade")
    print("  n=%d   moyenne=%+.4f   ecart-type=%.4f   t=%+.2f"
          % (n, moy, sd, t_stat))
    print()
    gA = sum(1 for x in A if x > 0) / n * 100.0
    gB = sum(1 for x in B if x > 0) / n * 100.0
    print("=== REUSSITE")
    print("  A %.1f %%   B %.1f %%   (B - A = %+.1f points)" % (gA, gB, gB - gA))
    print()
    print("=== MOTIFS DE SORTIE")
    for bras, xs, cle in (("A", lignes, "a_motif"), ("B", lignes, "b_motif")):
        compte = {}
        for x in xs:
            compte[x[cle]] = compte.get(x[cle], 0) + 1
        print("  %s : %s" % (bras, ", ".join("%s=%d" % kv
                                             for kv in sorted(compte.items()))))
    print()
    print("=== CRITERE PRE-INSCRIT (6bcc600)")
    if t_stat > 2:
        print("  B - A positif avec t > +2  =>  LA PROTECTION COUTE,")
        print("  et ma recommandation de la garder etait FAUSSE")
    elif t_stat < -2:
        print("  B - A negatif avec t < -2  =>  LA PROTECTION GAGNE")
    else:
        print("  |t| <= 2  =>  INDECIDABLE SUR UN JOUR, et je le dis")
    print()
    print(json.dumps({"n": n, "total_reel": round(reel, 2),
                      "total_A": round(sum(A), 2), "total_B": round(sum(B), 2),
                      "evite": round(sum(B) - sum(A), 2),
                      "moy_appariee": round(moy, 4), "t": round(t_stat, 3),
                      "reussite_A": round(gA, 1), "reussite_B": round(gB, 1),
                      "taux_eur_usd": round(taux, 5)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
