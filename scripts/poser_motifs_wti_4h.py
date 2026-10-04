#!/usr/bin/env python3
"""Ouvre au WTI, a 4 h, les motifs que son propre detecteur produit.

    sudo python3 scripts/poser_motifs_wti_4h.py --essai   # montre, n'ecrit pas
    sudo python3 scripts/poser_motifs_wti_4h.py           # applique

## ⛔ Le defaut, mesure le 2026-10-04

Le flux long produit pour le WTI un systeme `V2_WTI_OPTIMAL_WTIUSD_4H` avec
trois motifs : `momentum_up`, `engulfing_bullish`, `range_bounce_up`.

Mais le WTI est **la seule paire du flux long sans derogation de motifs**.
Toutes les autres (AUD, EUR/USD, EUR/GBP, EUR/JPY, GBP/USD, GBP/JPY, USD/CAD,
USD/CHF, USD/JPY, XAG, XAU, BTC, ETH) en ont une a `4h`. Le WTI retombait donc
sur la liste GLOBALE — `range_bounce_up/down` — et ses deux autres motifs
etaient refuses en silence.

🔑 Ce n'est pas anodin : `momentum_up` a 4 h est le PREMIER producteur
d'ordres du compte reel (16 ordres sur 30 jours, devant tout le reste).

## ⛔ Ce que ce script REFUSE de faire

- **pas la liste generique des autres paires forex** : elle contient
  `breakout_up`, que la configuration du flux long qualifie elle-meme de
  « TOXIQUE sur WTI (fausses cassures news OPEC) ». On respecte cette analyse
  plutot que de l'ecraser par uniformite.
- **pas un mot sur le 5 min** : le banc y a mesure que le cout mange 8 % du
  risque, et n'a rien retenu sur 493 cellules.
- **pas le 1d** : `MT5_BRIDGE_LIVE_ALLOWED_HORIZONS=5min,4h` le refuse de
  toute facon ; l'ouvrir serait un reglage inerte qui ferait croire a une
  ouverture.

## ⚠️ Ce que Xavier sait en le demandant

Le banc WTI a rendu **0 retenu sur 493 cellules**. Cette porte s'ouvre sans
validation de la mesure, comme la reouverture du WTI elle-meme. C'est sa
decision, prise en connaissance de cause, et elle se retire en une ligne :

    sudo cp /opt/scalping/.env.bak-wti-4h /opt/scalping/.env
    sudo systemctl restart scalping
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ENV = Path("/opt/scalping/.env")
CLE = "MT5_BRIDGE_PATTERN_OVERRIDES"
PAIRE = "WTI/USD"
HORIZON = "4h"


def main() -> int:
    essai = "--essai" in sys.argv
    if not ENV.exists():
        print(f"⛔ {ENV} introuvable", file=sys.stderr)
        return 2

    # ⛔ La verite sur les motifs vient du DETECTEUR, pas d'une liste recopiee
    # a la main. Mais le `.env` vit sur l'HOTE et le detecteur dans le
    # CONTENEUR : on va donc le lui demander, plutot que de figer une liste qui
    # divergerait au premier changement.
    import subprocess
    lu = subprocess.run(
        ["docker", "exec", "scalping-radar", "python", "-c",
         "import json;from backend.services import shadow_v2_core_long as s;"
         f"c=s.SHADOW_CONFIG.get({PAIRE!r}) or {{}};"
         "print(json.dumps({'tf':c.get('tf'),"
         "'patterns':sorted(c.get('patterns') or []),"
         "'system_id':c.get('system_id')}))"],
        capture_output=True, text=True, timeout=60)
    if lu.returncode != 0:
        print(f"⛔ impossible d'interroger le détecteur : "
              f"{lu.stderr.strip()[:200]}", file=sys.stderr)
        return 2
    cfg = json.loads(lu.stdout.strip().splitlines()[-1])
    if cfg.get("tf") != HORIZON:
        print(f"⛔ {PAIRE} n'a pas de système {HORIZON} dans le flux long "
              f"(tf={cfg.get('tf')})", file=sys.stderr)
        return 2
    motifs = sorted(cfg.get("patterns") or ())
    if not motifs:
        print("⛔ le détecteur ne déclare aucun motif", file=sys.stderr)
        return 2
    if "breakout_up" in motifs:
        print("⛔ `breakout_up` est apparu dans le détecteur WTI — la config a "
              "changé, je m'arrête plutôt que d'ouvrir un motif jugé toxique",
              file=sys.stderr)
        return 2
    print(f"motifs déclarés par le détecteur {cfg.get('system_id')} : "
          f"{', '.join(motifs)}")

    lignes = ENV.read_text(encoding="utf-8").splitlines(keepends=True)
    cibles = [i for i, l in enumerate(lignes) if l.startswith(CLE + "=")]
    if len(cibles) != 1:
        print(f"⛔ {len(cibles)} ligne(s) `{CLE}`", file=sys.stderr)
        return 2
    i = cibles[0]
    conf = json.loads(lignes[i].split("=", 1)[1].strip())

    avant = len((conf.get(PAIRE) or {}).get(HORIZON) or [])
    conf.setdefault(PAIRE, {})[HORIZON] = motifs
    print(f"   {PAIRE} @ {HORIZON} : {avant} → {len(motifs)} motifs")

    if essai:
        print("\n(--essai : rien n'a été écrit)")
        return 0

    sauvegarde = ENV.with_name(ENV.name + ".bak-wti-4h")
    shutil.copy(ENV, sauvegarde)
    lignes[i] = f"{CLE}={json.dumps(conf, separators=(',', ':'), sort_keys=True)}\n"
    ENV.write_text("".join(lignes), encoding="utf-8")

    # ─── Relecture : on verifie ce qu'on a ECRIT, pas ce qu'on a voulu ecrire
    t = ENV.read_text(encoding="utf-8")
    probleme = None
    if not t.endswith("\n"):
        probleme = "le fichier ne finit pas par un saut de ligne"
    else:
        trouvees = [l for l in t.splitlines() if l.startswith(CLE + "=")]
        if len(trouvees) != 1:
            probleme = "la clé n'est plus seule sur sa ligne"
        else:
            relu = json.loads(trouvees[0].split("=", 1)[1])
            if sorted(relu[PAIRE][HORIZON]) != motifs:
                probleme = "la relecture ne rend pas les motifs attendus"
            elif "5min" in (relu.get(PAIRE) or {}):
                probleme = "une clé 5min est apparue sur le WTI — refusé"
    if probleme:
        print(f"⛔ {probleme} — RESTAURATION", file=sys.stderr)
        shutil.copy(sauvegarde, ENV)
        return 3

    print(f"\n✅ écrit et relu. Sauvegarde : {sauvegarde}")
    print("👉 sudo systemctl restart scalping")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
