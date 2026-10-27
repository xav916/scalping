"""CONTROLE DE PROVENANCE, pas une cellule d hypothese.

Question : les issues STOCKEES des 4 280 lignes vecues correspondent-elles a ce
que donnent les bougies D AUJOURD HUI ? Si non, le bras reel et le bras placebo
ne reposent pas sur la meme donnee, et l ecart mesure est un ARTEFACT.
"""
import asyncio, sys
sys.path.insert(0, "/app")
sys.path.insert(0, "/tmp")
from datetime import datetime, timezone
import bh as banc

CR = banc.Criteres("/app/docs/preinscriptions/2026-10-28-hors-echantillon-5min.md")
reels = banc.lire_reels("/app/data/trades.db", CR.horizon, CR.population)
print(f"=== {len(reels)} lignes vecues relues")

bornes = {}
for d in reels:
    mn, mx = bornes.get(d["pair"], (d["bar"], d["bar"]))
    bornes[d["pair"]] = (min(mn, d["bar"]), max(mx, d["bar"]))
series = asyncio.run(banc.charge(bornes, CR.fin_chargement))

accord = desaccord = sans = 0
detail = {}
for d in reels:
    s = series.get(d["pair"])
    if s is None or not len(s):
        sans += 1
        continue
    r = s.simule(s.index_apres(d["bar"].timestamp()),
                 d["bar"].timestamp() + CR.fenetre_h * 3600,
                 d["achat"], d["sl"], d["tp"])
    obtenu = r[0] if r else None
    cle = (d["issue"], obtenu)
    detail[cle] = detail.get(cle, 0) + 1
    if obtenu == d["issue"]:
        accord += 1
    else:
        desaccord += 1

tot = accord + desaccord
print()
print("=== L ISSUE STOCKEE correspond-elle aux bougies D AUJOURD HUI ?")
print(f"   accord    : {accord:5d}  ({100*accord/tot:.1f} %)")
print(f"   DESACCORD : {desaccord:5d}  ({100*desaccord/tot:.1f} %)")
print(f"   sans serie: {sans}")
print()
print("   detail (stocke -> recalcule) :")
for (a, b), n in sorted(detail.items(), key=lambda kv: -kv[1])[:10]:
    marque = "" if a == b else "   <<< DESACCORD"
    print(f"     {str(a):9s} -> {str(b):9s} {n:5d}{marque}")
