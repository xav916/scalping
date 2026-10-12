#!/usr/bin/env python3
"""Les bancs refaits au COUT REEL : +10 points de markup sur le magasin.

Pre-inscrit dans docs/predictions/2026-10-12_bancs_refaits_au_cout_reel.md
AVANT d'ecrire ce fichier (commit 34d6315).

⛔ POURQUOI. La route historique `/ticks`, dont est bati `ticks_courtier.db`,
rend un spread INFERIEUR DE 10 POINTS a la route `/tick` que l'execution
utilise. Tous mes bancs sur ticks ont donc sous-estime le cout de
0,089 EUR/trade.

🔑 Le modele : le milieu est juste, la marge est symetrique.
      bid_reel = bid_magasin - 5 pts      ask_reel = ask_magasin + 5 pts

⛔ ET CE BANC S'ARRETE SI L'ETAPE ① NE CONFIRME PAS ~5 POINTS PAR COTE. Un
banc qui corrige d'une constante non verifiee remplacerait une erreur par une
autre, en se donnant l'air rigoureux.
"""
from __future__ import annotations

import collections
import datetime as dt
import math
import os
import sqlite3
import statistics as st
import sys

MAGASIN = os.getenv("TICKS", "/app/data/ticks_courtier.db")
EUR_USD = 1.1198

# Le markup MESURE, en prix (points / 100). 10 points au total, 5 par cote.
MARKUP_PTS = float(os.getenv("MARKUP_PTS", "10"))
DEMI = MARKUP_PTS / 200.0        # en USD, par cote

SL_DEPART_EUR = 13.0
PAS_MINI = 0.10
PLAFOND_EUR = 9.0
AGE_MINI_SEC = 60
CADENCE_SEC = 60
NEG_REQUIS_SEC = 30
CAP_SEC = 14400
REPOS_SEC = 300


# ─────────────────────────────────────────────────────────────────────────
# ① VALIDATION : le markup vaut-il bien ~5 points par cote ?
# ─────────────────────────────────────────────────────────────────────────

def valider_markup(ts_index) -> tuple[bool, str]:
    """Compare les prix d'EXECUTION reels au bid/ask du magasin, a la SECONDE.

    ⚠️ Mon premier essai appariait a +/- 2 s et la dispersion allait de -48 a
    +126 points : le marche bouge dans l'intervalle. Ici on exige la MEME
    seconde, et on ecarte les trades dont la seconde n'est pas couverte.
    """
    from backend.services.mt5_sync import _db_path
    t = sqlite3.connect(_db_path())
    t.row_factory = sqlite3.Row
    q = ("SELECT created_at q, lower(direction) s, entry_price p"
         " FROM personal_trades WHERE pair LIKE '%XAU%'"
         " AND destination_id='admin_live' AND entry_price IS NOT NULL"
         " AND replace(created_at,'T',' ') >= '2026-10-11 22:00'")
    ecarts_a, ecarts_v = [], []
    for r in t.execute(q):
        sec = str(r["q"]).replace("T", " ")[:19].replace(" ", "T")
        v = ts_index.get(sec)
        if not v:
            continue
        bid, ask = st.median([x[0] for x in v]), st.median([x[1] for x in v])
        p = float(r["p"])
        if r["s"] == "buy":
            ecarts_a.append((p - ask) * 100)
        else:
            ecarts_v.append((bid - p) * 100)

    lignes = []
    for nom, e in (("ACHATS  execute - ask magasin", ecarts_a),
                   ("VENTES  bid magasin - execute", ecarts_v)):
        if not e:
            lignes.append("   %-32s aucun trade apparie" % nom)
            continue
        s = sorted(e)
        lignes.append("   %-32s n=%-3d median %+6.1f pts   p25 %+6.1f  p75 %+6.1f"
                      % (nom, len(e), st.median(s),
                         s[int(.25 * len(s))], s[int(.75 * len(s))]))
    print("\n".join(lignes))

    tous = ecarts_a + ecarts_v
    if len(tous) < 20:
        return False, "moins de 20 trades apparies a la seconde (%d)" % len(tous)
    m = st.median(tous)
    attendu = MARKUP_PTS / 2.0
    print()
    print("   markup MEDIAN par cote : %+.1f pts   (attendu %.1f)" % (m, attendu))
    # ⛔ La porte. On accepte une moitie de markup entre 2,5 et 7,5 points,
    # soit un markup total entre 5 et 15. Hors de la, le modele est faux et on
    # ne corrige rien.
    if not (attendu * 0.5 <= m <= attendu * 1.5):
        return False, ("markup mesure %+.1f pts par cote, hors de la plage "
                       "[%.1f ; %.1f] : LE MODELE EST FAUX"
                       % (m, attendu * 0.5, attendu * 1.5))
    return True, "markup confirme a %+.1f pts par cote" % m


# ─────────────────────────────────────────────────────────────────────────

def charger():
    c = sqlite3.connect("file:%s?mode=ro" % MAGASIN, uri=True)
    rows = c.execute("SELECT ts_utc, ms, bid, ask FROM ticks "
                     "WHERE pair = 'XAU/USD' ORDER BY ts_utc, ms").fetchall()
    ts, bid, ask, index = [], [], [], collections.defaultdict(list)
    for t, ms, b, a in rows:
        if ms and ms > 1e12:
            ts.append(ms / 1000.0)
        else:
            d = dt.datetime.fromisoformat(t).replace(tzinfo=dt.timezone.utc)
            ts.append(d.timestamp() + (ms or 0) / 1000.0)
        bid.append(b)
        ask.append(a)
        index[str(t)[:19]].append((b, a))
    return ts, bid, ask, index


def rejouer(ts, bid, ask, i, achat, *, plancher_fixe, k_plancher,
            trainage_fixe, k_trainage, markup: bool):
    """Rend (pnl, stop_touche).

    `markup=True` elargit le bid/ask de DEMI de chaque cote : c'est tout ce
    qui separe ce banc de ses predecesseurs.
    """
    k = 1.0 / EUR_USD
    d = DEMI if markup else 0.0
    entree = (ask[i] + d) if achat else (bid[i] - d)
    t0 = ts[i]
    stop = -SL_DEPART_EUR
    neg_depuis = None
    vu_trainage = -1e18
    vu_prot = -1e18
    n = len(ts)
    j = i + 1

    while j < n and ts[j] - t0 <= CAP_SEC:
        b, a = bid[j] - d, ask[j] + d
        sortie = b if achat else a
        pnl = (sortie - entree) * k if achat else (entree - sortie) * k
        if pnl <= stop + 1e-12:
            return stop, True

        spread = (a - b) * k

        if ts[j] - vu_trainage >= 1:
            vu_trainage = ts[j]
            larg = trainage_fixe if trainage_fixe is not None else k_trainage * spread
            if pnl >= larg - 1e-9:
                c2 = pnl - larg
                if c2 > stop + PAS_MINI - 1e-9 and c2 < pnl - spread:
                    stop = c2

        if pnl < 0:
            if neg_depuis is None:
                neg_depuis = ts[j]
        else:
            neg_depuis = None

        if ts[j] - vu_prot >= CADENCE_SEC:
            vu_prot = ts[j]
            perte = -pnl
            if (ts[j] - t0 >= AGE_MINI_SEC and perte > 0
                    and neg_depuis is not None
                    and ts[j] - neg_depuis >= NEG_REQUIS_SEC):
                largeur = -stop
                pl = (plancher_fixe if plancher_fixe is not None
                      else k_plancher * spread)
                if largeur > pl:
                    vise = (largeur + perte) / 2.0
                    if vise < pl:
                        vise = pl
                    vise = min(vise, max(PLAFOND_EUR, perte + pl))
                    if vise < perte:
                        vise = perte + pl
                    if vise < largeur:
                        stop = -vise
        j += 1

    fin = min(j, n - 1)
    b, a = bid[fin] - d, ask[fin] + d
    sortie = b if achat else a
    return ((sortie - entree) * k if achat else (entree - sortie) * k), False


def tableau(ts, bid, ask, entrees, jours, cellules, markup):
    res = {}
    for nom, pf, kp, tf, kt in cellules:
        par_jour = collections.defaultdict(list)
        touches = 0
        for i, achat in entrees:
            p, t = rejouer(ts, bid, ask, i, achat, plancher_fixe=pf,
                           k_plancher=kp, trainage_fixe=tf, k_trainage=kt,
                           markup=markup)
            par_jour[jours[i]].append(p)
            touches += 1 if t else 0
        tous = [x for v in par_jour.values() for x in v]
        moy = [st.fmean(v) for _, v in sorted(par_jour.items())]
        res[nom] = {
            "moyennes": moy, "moyenne": st.fmean(tous), "pire": min(moy),
            "reussite": 100.0 * sum(1 for x in tous if x > 0) / len(tous),
            "nuls": 100.0 * sum(1 for x in tous if abs(x) < 0.05) / len(tous),
            "stop": 100.0 * touches / len(tous),
            "gains": st.fmean([x for x in tous if x > 0] or [0]),
            "pertes": st.fmean([x for x in tous if x < 0] or [0]),
        }
    return res


def ecart(res, nom, ref):
    e = [x - y for x, y in zip(res[nom]["moyennes"], res[ref]["moyennes"])]
    m = st.fmean(e)
    s = st.stdev(e) if len(e) > 1 else 0.0
    return m, (m / (s / math.sqrt(len(e))) if s else 0.0)


def main() -> int:
    ts, bid, ask, index = charger()
    jours = [dt.datetime.fromtimestamp(t, dt.timezone.utc).date() for t in ts]
    sp = [(a - b) / EUR_USD for a, b in zip(ask, bid)]
    print("=" * 78)
    print("MAGASIN : %d ticks, %d jours, spread median %.0f points"
          % (len(ts), len(set(jours)), st.median(sp) * EUR_USD * 100))
    print("=" * 78)
    print()

    print("=" * 78)
    print("① VALIDATION DU MARKUP — le banc s'arrete si elle echoue")
    print("=" * 78)
    ok, motif = valider_markup(index)
    print()
    if not ok:
        print("   ⛔ %s" % motif)
        print("   ⛔ ON NE CORRIGE RIEN. Un banc qui corrige d'une constante")
        print("      non verifiee remplace une erreur par une autre en se")
        print("      donnant l'air rigoureux.")
        return 1
    print("   ✅ %s" % motif)
    print()

    entrees, dernier = [], -1e18
    for i in range(1, len(ts) - 1):
        if ts[i] - dernier < REPOS_SEC:
            continue
        entrees.append((i, len(entrees) % 2 == 0))
        dernier = ts[i]
    print("%d positions par cellule\n" % len(entrees))

    # ② le plancher au spread, et ③ le trainage — memes cellules qu'a l'origine
    CELL = (
        ("A production",      2.0,  None, 0.50, None),
        ("B plancher k=2",    None, 2.0,  0.50, None),
        ("X regle de Xavier", None, 2.0,  None, 2.0),
    )
    sans = tableau(ts, bid, ask, entrees, jours, CELL, markup=False)
    avec = tableau(ts, bid, ask, entrees, jours, CELL, markup=True)

    print("=" * 78)
    print("② et ③  LES CELLULES, AU COUT DU MAGASIN puis AU COUT REEL")
    print("=" * 78)
    print("   %-18s %9s %9s %9s %7s %7s %7s"
          % ("cellule", "moyenne", "pire jour", "reussite", "nuls", "au SL", "gain moy"))
    for nom, *_ in CELL:
        for lib, r in (("magasin", sans[nom]), ("REEL   ", avec[nom])):
            print("   %-18s %+9.4f %+9.3f %8.1f %% %6.1f %% %6.1f %% %+7.3f"
                  % (("%s %s" % (nom[:11], lib))[:18], r["moyenne"], r["pire"],
                     r["reussite"], r["nuls"], r["stop"], r["gains"]))
    print()

    print("=" * 78)
    print("🔑 PREDICTION n°1 : LES ECARTS APPARIES SURVIVENT-ILS ?")
    print("=" * 78)
    print("   %-20s %12s %8s   %12s %8s   %10s"
          % ("ecart contre A", "au magasin", "t", "au cout REEL", "t", "DELTA"))
    verdicts = []
    for nom in ("B plancher k=2", "X regle de Xavier"):
        m1, t1 = ecart(sans, nom, "A production")
        m2, t2 = ecart(avec, nom, "A production")
        d = m2 - m1
        verdicts.append((nom, m1, t1, m2, t2, d))
        print("   %-20s %+12.4f %+8.2f   %+12.4f %+8.2f   %+10.4f"
              % (nom, m1, t1, m2, t2, d))
    print()
    pire = max(abs(v[5]) for v in verdicts)
    print("   plus grand deplacement d'ecart : %+.4f EUR/trade" % pire)
    if pire < 0.005:
        print("   ✅ PREDICTION n°1 TENUE (< 0,005) : mon affirmation du matin")
        print("      -- << les comparaisons appariees survivent >> -- se verifie.")
    elif pire < 0.02:
        print("   ⚠️ PREDICTION n°1 partiellement tenue : l'ecart bouge de")
        print("      %+.4f, au-dela de mes 0,005 mais sous les 0,02 qui" % pire)
        print("      m'auraient fait RETIRER mon affirmation.")
    else:
        print("   ⛔ PREDICTION n°1 FAUSSE (> 0,02) : JE RETIRE mon affirmation")
        print("      du matin. Les comparaisons appariees NE survivent PAS.")
    print()

    print("=" * 78)
    print("④ L'AUDIT DE COUT — ce que la configuration ACTUELLE rend vraiment")
    print("=" * 78)
    a1, a2 = sans["A production"], avec["A production"]
    print("   par trade        au magasin %+8.4f   au cout REEL %+8.4f   soit %+8.4f"
          % (a1["moyenne"], a2["moyenne"], a2["moyenne"] - a1["moyenne"]))
    print("   le markup theorique vaut %.4f EUR/trade (%.0f points)"
          % (MARKUP_PTS / 100.0 / EUR_USD, MARKUP_PTS))
    print()
    print("   gain moyen       %+8.3f -> %+8.3f" % (a1["gains"], a2["gains"]))
    print("   perte moyenne    %+8.3f -> %+8.3f" % (a1["pertes"], a2["pertes"]))
    print("   reussite         %8.2f %% -> %8.2f %%" % (a1["reussite"], a2["reussite"]))
    print("   stop touche      %8.2f %% -> %8.2f %%" % (a1["stop"], a2["stop"]))
    print()
    # 🔑 La reussite REQUISE pour l'equilibre, a geometrie donnee :
    #       p x gain = (1-p) x |perte|   =>   p = |perte| / (gain + |perte|)
    for lib, r in (("au magasin", a1), ("au cout REEL", a2)):
        g, pe = r["gains"], abs(r["pertes"])
        if g + pe <= 0:
            continue
        req = 100.0 * pe / (g + pe)
        print("   %-14s reussite REQUISE %6.2f %%   OBTENUE %6.2f %%   manque %+6.2f pt"
              % (lib, req, r["reussite"], r["reussite"] - req))
    g1, p1 = a1["gains"], abs(a1["pertes"])
    g2, p2 = a2["gains"], abs(a2["pertes"])
    if (g1 + p1) > 0 and (g2 + p2) > 0:
        d = 100.0 * p2 / (g2 + p2) - 100.0 * p1 / (g1 + p1)
        print()
        print("   🔑 le markup releve la reussite REQUISE de %+.2f point" % d)
        print("      (a comparer aux 0,72 point qui manquaient en production)")
    print()
    print("   ⛔ ET JE L'AI PRE-INSCRIT (prediction n°6) : ON NE PEUT PAS")
    print("      CONCLURE d'ici que le markup explique l'echec de la geometrie.")
    print("      Les entrees de ce banc sont SYNTHETIQUES (toutes les 300 s),")
    print("      pas les setups reels. Le chiffre ci-dessus est un ordre de")
    print("      grandeur, pas une attribution.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
