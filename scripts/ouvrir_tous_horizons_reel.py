#!/usr/bin/env python3
"""Ouvre TOUS les horizons sur le compte reel, pour toutes les paires.

    sudo python3 scripts/ouvrir_tous_horizons_reel.py --essai
    sudo python3 scripts/ouvrir_tous_horizons_reel.py

Demande de Xavier le 2026-10-05 : « ouvrir tous les horizons sur toutes les
valeurs ».

## ⚠️ CE QUE CELA CHANGE VRAIMENT — mesure AVANT d'appliquer

    combinaisons (paire, horizon, motif) autorisees
      aujourd'hui  624   ->   apres  800     soit x1,3 seulement

🔑 Et c'est peu, pour une raison qui doit etre dite : pour **22 paires sur
25**, la liste de motifs n'en autorise que DEUX (`range_bounce_up/down`) a
chaque horizon. Ouvrir les horizons ne fait que recopier ces deux motifs sur
plus d'echelles.

⇒ Les 1 862 refus `horizon_not_allowed` deviendront surtout des refus
`pattern_not_allowed`. **Le verrou n'est pas l'horizon, c'est la liste de
motifs.** Le levier x9 serait d'ouvrir les 38 motifs partout — une autre
decision, et une bien plus grosse.

## Ce que ce script NE touche pas

- ⛔ **pas la liste de motifs** : un seul geste a la fois, sinon on ne saura
  pas lequel a produit l'effet.
- ⛔ **pas `MT5_ECHELLES_AGREGEES_ROUTES`** : les refus `horizon_not_allowed`
  deja enregistres sur `admin_live` prouvent que les setups agreges ATTEIGNENT
  sa porte. Si apres coup rien ne passe, ce sera le prochain suspect — et on le
  saura parce qu'on n'aura bouge qu'une chose.
- ⛔ **pas les derogations par paire** de XAU, BTC et ETH : elles restent, et
  restent plus larges que le defaut.

## ⚠️ Ce que Xavier sait en le demandant

Le banc a retenu **0 sur 4 580 cellules** pour l'or et **0 sur 493** pour le
WTI. Les echelles agregees n'ont ete mesurees que sur XAU et EUR/USD, n=19 a
24, et declarees « piste, pas conclusion ». La marge libre du compte est de
**225 €**.

🔑 Un point en faveur, mesure : le cout DIMINUE quand l'echelle grandit —
0,029 R en M5, 0,013 R en M30. Les echelles qu'on ouvre sont les moins cheres.

Retrait en une ligne :

    sudo cp /opt/scalping/.env.bak-horizons /opt/scalping/.env
    sudo systemctl restart scalping
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ENV = Path("/opt/scalping/.env")
CLE = "MT5_BRIDGE_LIVE_ALLOWED_HORIZONS"
# ⚠️ Les DEUX orthographes de l'heure : la porte d'horizon normalise, mais on
# ne compte pas dessus — c'est exactement le defaut qui a laisse l'or a deux
# motifs en 60 min pendant des jours.
VALEUR = "5min,15min,30min,1h,60min,4h,1d"


def main() -> int:
    essai = "--essai" in sys.argv
    if not ENV.exists():
        print(f"⛔ {ENV} introuvable", file=sys.stderr)
        return 2

    lignes = ENV.read_text(encoding="utf-8").splitlines(keepends=True)
    cibles = [i for i, l in enumerate(lignes) if l.startswith(CLE + "=")]
    if len(cibles) != 1:
        print(f"⛔ {len(cibles)} ligne(s) `{CLE}` — je n'y touche pas",
              file=sys.stderr)
        return 2
    i = cibles[0]
    avant = lignes[i].split("=", 1)[1].strip()
    print(f"avant : {CLE}={avant}")
    print(f"apres : {CLE}={VALEUR}")
    if avant == VALEUR:
        print("deja en place — rien a faire")
        return 0

    if essai:
        print("\n(--essai : rien n'a ete ecrit)")
        return 0

    sauvegarde = ENV.with_name(ENV.name + ".bak-horizons")
    shutil.copy(ENV, sauvegarde)
    lignes[i] = f"{CLE}={VALEUR}\n"
    ENV.write_text("".join(lignes), encoding="utf-8")

    # ─── Relecture : on verifie ce qu'on a ECRIT ────────────────────────────
    t = ENV.read_text(encoding="utf-8")
    probleme = None
    if not t.endswith("\n"):
        probleme = "le fichier ne finit pas par un saut de ligne"
    else:
        vues = [l for l in t.splitlines() if l.startswith(CLE + "=")]
        if len(vues) != 1:
            probleme = "la cle n'est plus seule sur sa ligne"
        elif vues[0].split("=", 1)[1] != VALEUR:
            probleme = "la relecture ne rend pas la valeur attendue"
    if probleme:
        print(f"⛔ {probleme} — RESTAURATION", file=sys.stderr)
        shutil.copy(sauvegarde, ENV)
        return 3

    print(f"\n✅ ecrit et relu. Sauvegarde : {sauvegarde}")
    print("👉 sudo systemctl restart scalping")
    print("⚠️ le tampon des echelles agregees se vide : ~50 min avant de "
          "reproduire du 15/30/60 min.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
