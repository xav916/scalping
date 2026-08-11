#!/usr/bin/env python3
"""Rodage de l'or en 4h — vérifier la plomberie, PAS chercher un edge.

Lancé le 2026-08-11, à relire vers le 2026-09-01.

## ⛔ Ce que ce rodage NE PEUT PAS conclure

Débit attendu : **~2,5 setups/jour**. En trois semaines, ~50 trades.

```
effet detectable a 80 % de puissance :  n=30 -> 0,72 R · n=50 -> 0,55 R
seuil de VIABILITE economique        :               0,073 R
pour detecter 0,073 R                :  n = 2 884  ->  ~3 ANS a ce debit
```

**On ne distinguera pas +0,05 de −0,05.** Toute lecture de ces trades comme
« l'or en 4h marche / ne marche pas » serait une surinterprétation. Le contrôle
aléatoire a déjà tranché ce qu'il pouvait sur 2 188 trades de métaux 4h :
**−0,045 R, intervalle [−0,100 ; +0,012], non tranché**. Trois semaines de plus
ne bougeront pas cet intervalle.

## ✅ Ce qu'il PEUT établir

1. **Le flux existe** — l'or produisait 0 setup dispatchable sur 76. On attend
   maintenant ~2,5/jour. Zéro au bout d'une semaine = la surcharge de patterns
   ne fonctionne pas.
2. **Mes projections tiennent** — distance au stop projetée 1,808 %, spread
   1,2 % de R, risque réel ~68,75 EUR au lot minimum. Chacune est vérifiable.
3. **Rien de catastrophique** — une espérance de −0,5 R serait visible sur
   30 trades. C'est le seul verdict que la puissance autorise.
4. **Le miroir se comporte comme prévu** — le réel doit REFUSER ces trades en
   `risque_realise_trop_eleve` (27x le voulu, plafond à 5x), et les accepter
   sur le 5 min.

Usage :
    python3 scripts/rodage_or_4h.py
"""
import sqlite3
import statistics
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEBUT = "2026-08-11"
ATTENDU_PAR_JOUR = 2.5
PROJECTIONS = {
    "distance au stop (% du prix)": 1.808,
    "risque reel au lot mini (EUR)": 68.75,
    "cout du spread (% de R)": 1.2,
}


def main() -> int:
    c = sqlite3.connect("/app/data/trades.db")
    c.row_factory = sqlite3.Row
    jours = max((date.today() - date.fromisoformat(DEBUT)).days, 1)

    setups = c.execute(
        "SELECT entry_price, stop_loss, pattern, outcome, pnl_pct_net "
        "  FROM shadow_setups "
        " WHERE pair = 'XAU/USD' AND timeframe = '4h' AND detected_at >= ?",
        (DEBUT,),
    ).fetchall()

    print(f"rodage de l'or en 4h — {jours} jour(s) depuis le {DEBUT}")
    print()
    print("=== 1. le flux existe-t-il ? ===")
    print(f"  setups detectes  : {len(setups)}  ({len(setups)/jours:.2f}/jour)")
    print(f"  attendu          : ~{ATTENDU_PAR_JOUR}/jour")
    if jours >= 7 and len(setups) == 0:
        print("  ⛔ ZERO apres une semaine : la surcharge de patterns ne marche pas")
    elif len(setups) / jours < ATTENDU_PAR_JOUR * 0.4:
        print("  ⚠️ debit tres inferieur a l'attendu — chercher une porte en amont")
    else:
        print("  ✅ debit coherent")

    print()
    print("=== 2. mes projections tiennent-elles ? ===")
    stops = [abs(s["entry_price"] - s["stop_loss"]) / s["entry_price"] * 100
             for s in setups if s["entry_price"] and s["stop_loss"]]
    if stops:
        m = statistics.median(stops)
        ecart = (m - PROJECTIONS["distance au stop (% du prix)"]) / \
            PROJECTIONS["distance au stop (% du prix)"] * 100
        print(f"  distance au stop mesuree : {m:.3f} %  "
              f"(projete {PROJECTIONS['distance au stop (% du prix)']:.3f} %, "
              f"ecart {ecart:+.0f} %)")
        print(f"  risque au lot mini       : {m/100*4390*0.866:.2f} EUR")
    else:
        print("  pas encore de setup mesurable")

    print()
    print("=== 3. rien de catastrophique ? ===")
    clos = [s for s in setups if s["outcome"] and s["outcome"] != "OPEN"
            and s["pnl_pct_net"] is not None]
    if len(clos) < 10:
        print(f"  {len(clos)} trades clos — trop peu pour lire quoi que ce soit")
    else:
        rs = [s["pnl_pct_net"] for s in clos]
        moy = statistics.mean(rs)
        seuil = 2.8 * (statistics.stdev(rs) if len(rs) > 1 else 1.4) / (len(rs) ** 0.5)
        print(f"  n={len(clos)}  moyenne {moy:+.4f}  "
              f"(detectable a cette taille : {seuil:.3f})")
        if moy < -0.5:
            print("  ⛔ CATASTROPHE VISIBLE — refermer la surcharge de patterns")
        else:
            print("  ✅ rien de catastrophique ; ⚠️ et rien de CONCLUANT non plus")

    print()
    print("=== 4. le miroir se comporte-t-il comme prevu ? ===")
    for r in c.execute(
        "SELECT reason_code, COUNT(*) n FROM signal_rejections "
        " WHERE destination_id = 'admin_live' AND pair = 'XAU/USD' "
        "   AND created_at >= ? GROUP BY 1 ORDER BY n DESC LIMIT 5", (DEBUT,)
    ):
        print(f"  {r['reason_code']:34s} {r['n']:4d}")
    print("  attendu : `risque_realise_trop_eleve` sur les 4h (27x le voulu),")
    print("  et RIEN sur le 5 min, qui doit passer a 2,3x.")

    print()
    print("⛔ RAPPEL : ce rodage ne peut PAS conclure sur l'edge. Detecter")
    print("   0,073 R demanderait 2 884 trades, soit ~3 ans a ce debit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
