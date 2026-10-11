"""BATIR un magasin M5 de l'or DEPUIS LE COURTIER, en UTC vrai.

Demande de Xavier (2026-10-10) : reparer la donnee pour debloquer la piste du
calendrier (51 666 surprises, dont aucune n'est lisible aujourd'hui faute de
bougies fiables).

## 🔑 CE QUI REND CE CHANTIER POSSIBLE

Le decalage du pont est **DETERMINISTE** :

    decalage_a_appliquer = -decalage_serveur_sec / 60 + 180

Verifie le 2026-10-10 sur **21 jours sur 21** et **154 ancres d'execution**
(dont 75/75 le 09/10). Elle fait mieux que la recherche empirique, qui se
trompait les jours a une ou deux ancres (+930, -1933 au lieu de +1427).

⚠️ ET LE CHAMP DERIVE : il valait -69 256 a 20h, -74 831 a 21h — 93 minutes
d'ecart. Il faut donc le lire DANS LA MEME REPONSE que les bougies, jamais le
memoriser. C'est exactement ce que fait ce script.

## CE QU'IL ECRIT

Une base NEUVE, `/app/data/candles_courtier.db`, jamais celle que la recherche
lit deja. Aucune modification en place : si ce script se trompe, rien n'est
perdu.

    candles(pair, ts_utc, open, high, low, close, tick_volume, spread_pts)
    cle primaire (pair, ts_utc)  ⇒  INSERT OR REPLACE, donc idempotent et
    reprenable.

## ⛔ LES TROIS VERIFICATIONS, a la fin et non en option

1. **ancres d'execution** : les 154 prix d'execution reels doivent tomber DANS
   leur bougie. Seuil : 100 %.
2. **coupure hebdomadaire** : elle doit tomber au MEME endroit en UTC chaque
   annee. C'est le controle qui a fait tomber l'ancien magasin (samedi 06h55
   en 2023-2024 contre samedi 23h55 en 2025-2026).
3. **continuite** : part des minutes manquantes dans les heures de cotation.
"""
import json
import os
import sqlite3
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

PAIRE = os.getenv("MAGASIN_PAIRE", "XAU/USD")
# ⚠️ Parametre par l'environnement le 2026-10-11, pour batir un magasin M1 sans
# toucher au comportement M5 deja verifie. Sans variable, rien ne change.
TF = os.getenv("MAGASIN_TF", "M5")
PAS_MIN = int(os.getenv("MAGASIN_PAS_MIN", "5"))
# ⓘ Profondeur REELLE du courtier en M5, mesuree : 2025-05-16.
# Demander 2021 ne la rallonge pas, le pont rend ce qu'il a.
DEBUT = datetime.fromisoformat(
    os.getenv("MAGASIN_DEBUT", "2021-01-01")).replace(tzinfo=timezone.utc)
FIN = datetime.fromisoformat(
    os.getenv("MAGASIN_FIN", "2026-10-10")).replace(tzinfo=timezone.utc)
CIBLE = os.getenv("MAGASIN_CIBLE", "/app/data/candles_courtier.db")
SERVEUR_MIN = 180.0
PAUSE = 0.4

base = os.getenv("MT5_BRIDGE_LIVE_URL").rstrip("/")
cle = os.getenv("MT5_BRIDGE_LIVE_API_KEY")

db = sqlite3.connect(CIBLE)
db.execute("""CREATE TABLE IF NOT EXISTS candles (
    pair TEXT NOT NULL, ts_utc TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    tick_volume REAL, spread_pts REAL,
    PRIMARY KEY (pair, ts_utc))""")
db.execute("CREATE INDEX IF NOT EXISTS idx_ts ON candles(pair, ts_utc)")
db.execute("""CREATE TABLE IF NOT EXISTS provenance (
    cle TEXT PRIMARY KEY, valeur TEXT)""")
db.executemany("INSERT OR REPLACE INTO provenance VALUES (?,?)", [
    ("source", "pont MT5 IC Markets (/rates), PAS Twelve Data"),
    ("fuseau", "UTC vrai, corrige par -decalage_serveur_sec/60 + 180"),
    ("formule_verifiee", "21 jours sur 21, 154 ancres d'execution, 2026-10-10"),
    ("timeframe", TF),
    ("bati_le", "2026-10-10"),
])
db.commit()

print(f"cible : {CIBLE}")
print(f"demande : {PAIRE} {TF} de {DEBUT.date()} a {FIN.date()}")
print()

curseur, pages, ecrites, decalages = DEBUT, 0, 0, Counter()
t0 = time.time()
while pages < 400 and curseur < FIN:
    q = urllib.parse.urlencode({"pair": PAIRE, "timeframe": TF,
                                "from": curseur.isoformat(),
                                "to": FIN.isoformat()})
    try:
        rq = urllib.request.Request(f"{base}/rates?{q}",
                                    headers={"X-API-Key": cle})
        o = json.loads(urllib.request.urlopen(rq, timeout=600).read())
    except Exception as e:  # noqa: BLE001
        print(f"   page {pages+1} : {type(e).__name__} {e} — arret")
        break
    lot = o.get("bougies") or []
    ds = o.get("decalage_serveur_sec")
    if not lot or ds is None:
        print(f"   page {pages+1} : vide (n={o.get('n')}, "
              f"decalage={ds}) — arret")
        break
    # 🔑 LA CORRECTION, avec le decalage DE CETTE REPONSE
    # ⛔ DEUX DEFAUTS DU PREMIER JET, corriges ici.
    #
    # 1) LE SIGNE. Ce que j'ai verifie sur M1 (21 jours, 154 ancres) est : un
    #    trade a l'instant REEL T a sa bougie a l'etiquette BRUTE `T + 1427`.
    #    Donc **etiquette = reel + decalage**, et pour passer de l'etiquette au
    #    temps reel il faut **SOUSTRAIRE**. Mon premier jet ajoutait : 0 ancre
    #    sur 172, et la coupure hebdomadaire deplacee de DEUX JOURS
    #    (dimanche 20h30 -> mardi 21h35 au lieu de vendredi -> dimanche).
    #
    # 2) LES SECONDES. +1 428,7 min vaut 1 428 min 42 s : ajouter un decalage
    #    non entier REMET des secondes dans l'etiquette
    #    (`2025-05-16T22:30:33`), et toute recherche par egalite echoue. On
    #    arrondit donc a la MINUTE avant de l'appliquer.
    dec_min = int(round(-float(ds) / 60.0 + SERVEUR_MIN))
    dec = timedelta(minutes=dec_min)
    decalages[dec_min] += len(lot)
    rows = []
    for b in lot:
        t_brut = datetime.fromisoformat(b["t"]).replace(second=0,
                                                        microsecond=0)
        t_vrai = t_brut - dec          # ⛔ SOUSTRAIRE, cf. la note ci-dessus
        t_vrai = t_vrai.replace(minute=(t_vrai.minute // PAS_MIN) * PAS_MIN)
        rows.append((PAIRE, t_vrai.isoformat(), b["o"], b["h"], b["l"],
                     b["c"], float(b.get("tv") or 0),
                     float(b["s"]) if b.get("s") is not None else None))
    db.executemany("INSERT OR REPLACE INTO candles VALUES (?,?,?,?,?,?,?,?)",
                   rows)
    db.commit()
    ecrites += len(rows)
    pages += 1
    sf = o.get("suite_from")
    if pages % 10 == 0 or not o.get("tronque"):
        d0 = min(r[1] for r in rows)
        d1 = max(r[1] for r in rows)
        print(f"   page {pages:>3} : {len(lot):>5} bougies   corrigees de "
              f"{dec.total_seconds()/60:+.1f} min   {d0[:16]} -> {d1[:16]}"
              f"   cumul {ecrites}")
    if not o.get("tronque") or not sf:
        print(f"   page {pages} : fin de donnees (tronque={o.get('tronque')})")
        break
    nv = datetime.fromisoformat(sf)
    if nv <= curseur:
        print("   ⛔ le curseur n'avance pas — arret")
        break
    curseur = nv
    time.sleep(PAUSE)

print()
print(f"pages lues : {pages}   bougies ecrites : {ecrites}   "
      f"duree {time.time()-t0:.0f} s")
print(f"decalages appliques : {dict(decalages.most_common(6))}")
r = db.execute("SELECT COUNT(*), MIN(ts_utc), MAX(ts_utc) FROM candles "
               "WHERE pair=?", (PAIRE,)).fetchone()
print(f"en base : {r[0]} bougies distinctes, de {r[1]} a {r[2]}")

# ══════════════════ LES TROIS VERIFICATIONS ══════════════════
print()
print("=" * 94)
print("=== VERIFICATION 1 : les 154 prix d'EXECUTION reels tombent-ils dedans ?")
print("=" * 94)
ct = sqlite3.connect("file:/app/data/trades.db?mode=ro", uri=True)
ct.row_factory = sqlite3.Row
tr = [dict(x) for x in ct.execute(
    "SELECT created_at, entry_price FROM personal_trades WHERE pair=? "
    "AND destination_id='admin_live' AND entry_price > 0 ORDER BY created_at",
    (PAIRE,))]
dedans = dehors = absents = 0
for t in tr:
    tt = datetime.fromisoformat(str(t["created_at"]).replace("Z", "+00:00"))
    k = tt.replace(second=0, microsecond=0)
    k = k.replace(minute=(k.minute // PAS_MIN) * PAS_MIN)
    row = db.execute("SELECT low, high FROM candles WHERE pair=? AND ts_utc=?",
                     (PAIRE, k.isoformat())).fetchone()
    if not row:
        absents += 1
    elif row[0] - 0.6 <= float(t["entry_price"]) <= row[1] + 0.6:
        dedans += 1
    else:
        dehors += 1
tot = dedans + dehors
print(f"   trades d'or : {len(tr)}   bougie trouvee : {tot}   absente : "
      f"{absents}")
if tot:
    print(f"   ⇒ DEDANS : {dedans}/{tot} ({100*dedans/tot:.1f} %)"
          + ("   ✅" if dedans == tot else "   ⛔"))

print()
print("=" * 94)
print("=== VERIFICATION 2 : la coupure hebdomadaire est-elle au MEME endroit ?")
print("=" * 94)
JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi",
         "dimanche")
ts = [datetime.fromisoformat(x[0]) for x in db.execute(
    "SELECT ts_utc FROM candles WHERE pair=? ORDER BY ts_utc", (PAIRE,))]
deb, fin_, nb = defaultdict(Counter), defaultdict(Counter), Counter()
for a, b in zip(ts, ts[1:]):
    trou = (b - a).total_seconds() / 60.0
    if trou >= 8 * 60:
        an = str(a.year)
        nb[an] += 1
        deb[an][f"{JOURS[a.weekday()]} {a.hour:02d}h{a.minute:02d}"] += 1
        fin_[an][f"{JOURS[b.weekday()]} {b.hour:02d}h{b.minute:02d}"] += 1
print("   annee  coupures   derniere avant            premiere apres")
for an in sorted(deb):
    d = deb[an].most_common(1)[0]
    f = fin_[an].most_common(1)[0]
    print(f"   {an}    {nb[an]:>5}    {d[0]:<16} ({d[1]:>2}x)"
          f"    {f[0]:<16} ({f[1]:>2}x)")
uniq_d = {deb[a].most_common(1)[0][0] for a in deb}
uniq_f = {fin_[a].most_common(1)[0][0] for a in fin_}
print(f"   ⇒ debuts distincts : {sorted(uniq_d)}")
print(f"     fins distinctes  : {sorted(uniq_f)}")
print("   " + ("✅ UNE SEULE CONVENTION" if len(uniq_d) == 1 and len(uniq_f) == 1
               else "⛔ PLUSIEURS CONVENTIONS"))

print()
print("=" * 94)
print("=== VERIFICATION 3 : la continuite, annee par annee")
print("=" * 94)
print("   annee   bougies   attendu (~)   couverture   trous > 8h")
par_an = Counter(t.year for t in ts)
for an in sorted(par_an):
    # une annee de cotation ~ 5 j/7 x 24 h x 12 bougies = 74 880
    att = 74880
    print(f"   {an}    {par_an[an]:>7}      {att:>7}      "
          f"{100*par_an[an]/att:>5.1f} %        {nb[str(an)]:>3}")
db.close()
print()
print("=" * 94)
print("🔑 Ce magasin est NEUF : l'ancien `candles_5min.db` (Twelve Data) n'a")
print("   pas ete touche. Rien n'est perdu si ce script s'est trompe.")
print("=" * 94)
