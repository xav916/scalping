#!/usr/bin/env python3
"""Importe l'historique calendrier exporte du terminal MT5.

    # 1. voir ce que dit la mesure du fuseau, SANS rien ecrire
    python scripts/importer_calendrier_mql5.py --fichier calendrier_export.tsv

    # 2. ecrire, au fuseau que la mesure a retenu
    python scripts/importer_calendrier_mql5.py --fichier ... --ecrire

    # 3. imposer le fuseau (⚠️ a n'utiliser que si la mesure est ambigue ET
    #    qu'on sait ce qu'on tranche — le choix impose est annonce)
    python scripts/importer_calendrier_mql5.py --fichier ... --ecrire \
        --fuseau Europe/Helsinki

⛔ Sans `--ecrire`, ce script ne touche RIEN. C'est voulu : le fuseau est le
piege central de cet import, et il se regarde avant de s'appliquer.

⚠️ UN FUSEAU, PAS UN DECALAGE. Un serveur MT5 typique tourne en EET/EEST :
UTC+2 en hiver, UTC+3 en ete. Un decalage fixe applique a cinq ans
d'historique se trompe d'une heure la moitie de l'annee.

🔑 L'import n'ecrit que ce qui est STRICTEMENT ANTERIEUR a la plus ancienne
ligne ForexFactory. ForexFactory possede sa fenetre et tout ce qui suit.

Chaine complete, de bout en bout :
  1. `mt5-bridge/CalendrierExport.mq5` tourne dans le terminal MT5 de DEMO
     (la base calendrier vient de MetaQuotes, elle est la meme quel que soit
     le compte — aucune raison de risquer la session du compte REEL) ;
  2. il ecrit `MQL5\\Files\\calendrier_export.tsv` ;
  3. ce fichier est rapatrie et passe ici.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services import import_calendrier_mql5 as imp  # noqa: E402


def _afficher_mesure(scores: dict[str, int], retenu: str) -> None:
    print("─── MESURE DU FUSEAU (appariement sur instant + devise) ───")
    for f in sorted(scores, key=lambda k: (-scores[k], k)):
        marque = "  ← retenu" if f == retenu else ""
        print(f"   {f:20s} {scores[f]:5d} lignes appariees{marque}")
    print(f"\n   fuseau retenu : {retenu}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fichier", required=True, help="l'export .tsv du terminal")
    p.add_argument("--db", default="data/scalping.db")
    p.add_argument("--ecrire", action="store_true",
                   help="sans ce drapeau, rien n'est ecrit")
    p.add_argument("--fuseau", default=None,
                   help="impose le fuseau au lieu de le mesurer "
                        "(ex. Europe/Helsinki)")
    a = p.parse_args()

    chemin = Path(a.fichier)
    if not chemin.exists():
        print(f"⛔ fichier introuvable : {chemin}", file=sys.stderr)
        return 2
    texte = chemin.read_text(encoding="utf-8", errors="replace")

    try:
        lignes = imp.lire_export(texte)
    except imp.ExportInvalide as e:
        print(f"⛔ export refuse : {e}", file=sys.stderr)
        return 2

    entete = imp.lire_entete(texte)
    print(f"export  : {len(lignes)} valeurs")
    print(f"terminal: gmt={entete.get('gmt')}  serveur={entete.get('serveur')}"
          f"  build={entete.get('build')}")
    if entete.get("gmt") and entete.get("serveur"):
        print("⚠️  ces deux instants ne donnent le decalage que d'UN instant :"
              " sur plusieurs annees il varie avec l'heure d'ete.")
    print()

    fuseau = a.fuseau
    if fuseau is not None:
        try:
            ZoneInfo(fuseau)
        except (ZoneInfoNotFoundError, ValueError):
            print(f"⛔ fuseau inconnu : {fuseau}", file=sys.stderr)
            return 2
        print(f"⚠️  fuseau IMPOSE : {fuseau} — la mesure est contournee.")
    else:
        try:
            fuseau, scores = imp.choisir_fuseau(texte, a.db)
            _afficher_mesure(scores, fuseau)
        except imp.RecouvrementInsuffisant as e:
            print(f"⛔ {e}", file=sys.stderr)
            return 3
        except imp.MesureAmbigue as e:
            print(f"⛔ {e}", file=sys.stderr)
            print("   relancer avec --fuseau une fois la raison comprise.",
                  file=sys.stderr)
            return 3

    if not a.ecrire:
        print("\n(rien n'a ete ecrit : ajouter --ecrire)")
        return 0

    n = imp.importer(texte, a.db, fuseau=fuseau)
    print(f"\n✅ {n} lignes ecrites (source « {imp.SOURCE} », fuseau {fuseau})")
    if n == 0:
        print("   ⚠️  zero ligne : tout l'export tombe DANS la fenetre que "
              "ForexFactory couvre deja, ou apres.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
