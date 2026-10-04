#!/usr/bin/env python3
"""Pose les cles `60min` et `1h` manquantes dans la derogation de motifs de l'or.

    sudo python3 scripts/poser_motifs_60min_or.py           # applique
    sudo python3 scripts/poser_motifs_60min_or.py --essai   # montre, n'ecrit pas

⛔ LE DEFAUT, trouve le 2026-10-04 par `scripts/verifier_derogations.py`.

L'or a recu une derogation d'HORIZON pour les six echelles, avec la cle `1h`.
Elle fonctionne : cette porte-la NORMALISE les noms. Mais la derogation de
MOTIFS lit la chaine BRUTE (`par_paire.get(horizon)` dans `mt5_bridge`), et la
production estampille `60min`. Les cles de l'or sont `5min`, `15min`, `30min`,
`4h`, `1d` — ni `1h`, ni `60min`.

L'or franchissait donc la porte d'horizon a 60 min, puis retombait sur la
liste GLOBALE : **deux motifs** (`range_bounce_up/down`) au lieu de huit. Sans
un message, sans une trace.

🔑 BTC et ETH portent deja les DEUX cles. La lecon avait ete apprise une fois
sans etre appliquee a l'or.

⛔ ON NE RECOPIE PAS LA LISTE DU 30 MIN. Elle contient `pin_bar_down`, la
chaine ARMEE apres mesure sur CET horizon precis. L'etendre au 60 min
l'armerait sans mesure — exactement ce que le banc interdit, et ce que
[[project_chaine_autres_echelles_2026_09_15]] a deja refuse sur 365 jours.
La reference est donc le 5 min, qui porte les huit motifs de base.

⚠️ PIEGE DU `.env` : un fichier sans saut de ligne final a deja mange deux
reglages (`ECHELLES_MEMOIRE_M5=520EXPECTED_GIT_COMMIT=...`), fermant trois
echelles pendant dix minutes pour un seul avertissement. Ce script verifie
donc la forme APRES ecriture, et relit ce qu'il a ecrit.

⚠️ Il faut REDEMARRER le conteneur pour que le `.env` soit relu. Un
redemarrage ne declenche PAS de reconstruction, donc REM-002 reste arme.
Le tampon des echelles agregees se vide et se reremplit par prechauffage.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ENV = Path("/opt/scalping/.env")
CLE = "MT5_BRIDGE_PATTERN_OVERRIDES"
PAIRE = "XAU/USD"
REFERENCE = "5min"       # les huit motifs de base, SANS le pin_bar_down du 30 min
A_POSER = ("60min", "1h")


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

    try:
        cfg = json.loads(lignes[i].split("=", 1)[1].strip())
    except json.JSONDecodeError as e:
        print(f"⛔ JSON illisible : {e}", file=sys.stderr)
        return 2

    par_paire = cfg.get(PAIRE)
    if not isinstance(par_paire, dict) or REFERENCE not in par_paire:
        print(f"⛔ pas de référence `{REFERENCE}` pour {PAIRE}", file=sys.stderr)
        return 2

    base = list(par_paire[REFERENCE])
    print(f"référence « {REFERENCE} » : {len(base)} motifs")
    if len(base) != 8:
        print(f"⛔ {len(base)} motifs au lieu de 8 — la configuration a changé, "
              f"je m'arrête plutôt que de deviner", file=sys.stderr)
        return 2

    for cle in A_POSER:
        avant = len(par_paire.get(cle) or [])
        par_paire[cle] = base
        print(f"   {cle:6s} : {avant} → {len(base)} motifs")

    if essai:
        print("\n(--essai : rien n'a été écrit)")
        return 0

    sauvegarde = ENV.with_name(ENV.name + ".bak-60min-or")
    shutil.copy(ENV, sauvegarde)
    lignes[i] = f"{CLE}={json.dumps(cfg, separators=(',', ':'), sort_keys=True)}\n"
    ENV.write_text("".join(lignes), encoding="utf-8")

    # ─── Relecture : on verifie ce qu'on a ecrit, pas ce qu'on a voulu ecrire
    t = ENV.read_text(encoding="utf-8")
    if not t.endswith("\n"):
        print("⛔ le fichier ne finit pas par un saut de ligne — RESTAURATION",
              file=sys.stderr)
        shutil.copy(sauvegarde, ENV)
        return 3
    cibles2 = [l for l in t.splitlines() if l.startswith(CLE + "=")]
    if len(cibles2) != 1:
        print("⛔ la clé n'est plus seule sur sa ligne — RESTAURATION",
              file=sys.stderr)
        shutil.copy(sauvegarde, ENV)
        return 3
    relu = json.loads(cibles2[0].split("=", 1)[1])[PAIRE]
    if relu.get("30min") == relu.get("60min"):
        print("⛔ le 60 min a hérité du `pin_bar_down` du 30 min — RESTAURATION",
              file=sys.stderr)
        shutil.copy(sauvegarde, ENV)
        return 3

    print(f"\n✅ écrit et relu. Sauvegarde : {sauvegarde}")
    print(f"   horizons de l'or : {', '.join(sorted(relu))}")
    print("\n👉 Redémarrer pour relire le .env (PAS de reconstruction, "
          "REM-002 reste armé) :")
    print("   sudo systemctl restart scalping")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
