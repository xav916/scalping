#!/usr/bin/env python3
"""Relever à la main un appel de canal et le pousser dans le pipeline.

Écrit le 2026-09-24. Le canal MQL5 `Orvion` (« Trading XAUUSD ») n'est lisible
que depuis l'application MetaQuotes : pas de vue web publique, pas d'API, pas de
flux. Le relevé manuel n'est donc pas un pis-aller en attendant mieux — c'est,
aujourd'hui, la SEULE voie qui ne demande ni de déposer vos identifiants MQL5
dans un scraper, ni d'enfreindre les conditions du site.

🔑 Et c'est suffisant pour ce qui compte : trente appels relevés à la main
donnent le verdict du banc. Le parseur, lui, est l'actif durable — le jour où le
canal expose un flux, seul ce fichier devient inutile.

## Ce que le serveur fait ensuite, et qu'il ne faut pas refaire ici

Le signal part dans `send_setup()` et traverse TOUTES les portes : admission,
whitelist, confiance, horizon, motifs, coût, corrélation, plafond de risque,
banc. Un `200` dit « accepté à l'entrée », jamais « ordre passé ».

⛔ Et l'argent réel est hors d'atteinte : `resolve_destinations` écarte toute
destination réelle dès que `source` désigne un tiers. Orvion ira en démo, et
seulement en démo, tant que ce verrou n'est pas levé délibérément.

## Réglages

    export SCALPING_API_URL="https://app.scalping-radar.online"
    export ORVION_SIGNAL_TOKEN="<le jeton declare cote serveur>"

Côté serveur, dans le `.env` de l'EC2 :

    EXTERNAL_SIGNAL_TOKENS='{"orvion": "<le meme jeton>"}'

## Emploi

    # message brut — le parseur interprète, et refuse s'il n'est pas certain
    ./releve.py --message "XAUUSD SELL 3900 SL 3920 TP 3880"

    # champs explicites — aucune interprétation, le chemin sûr
    ./releve.py --paire XAU/USD --sens sell --entree 3900 --stop 3920 --objectif 3880

    # voir ce qui serait envoyé, sans rien envoyer
    ./releve.py --message "..." --essai
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parseur import Refus, construire, lire  # noqa: E402


def _arguments() -> argparse.Namespace:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--source", default="orvion", help="clé déclarée dans EXTERNAL_SIGNAL_TOKENS")
    a.add_argument("--message", help="le texte de l'appel, tel que publié")
    a.add_argument("--paire"); a.add_argument("--sens", choices=("buy", "sell"))
    a.add_argument("--entree", type=float); a.add_argument("--stop", type=float)
    a.add_argument("--objectif", type=float)
    a.add_argument("--ref", help="référence du message (horodatage) — prime sur "
                                 "l'identifiant déduit du contenu")
    a.add_argument("--essai", action="store_true", help="affiche sans envoyer")
    return a.parse_args()


def _signal(args):
    """⚠️ Les champs explicites PRIMENT sur le message. C'est ce qui permet de
    rattraper un refus — entrée en zone, sens ambigu — sans toucher au parseur.
    """
    if args.entree is not None and args.stop is not None:
        if not args.paire or not args.sens:
            raise Refus("--paire et --sens sont requis avec --entree/--stop")
        return construire(args.source, args.paire, args.sens, args.entree,
                          args.stop, args.objectif, args.ref)
    if args.message:
        return lire(args.message, args.source, args.ref)
    raise Refus("fournir --message, ou --paire --sens --entree --stop")


def main() -> int:
    args = _arguments()
    try:
        signal = _signal(args)
    except Refus as e:
        print(f"⛔ REFUSÉ : {e}", file=sys.stderr)
        print("   Rien n'a été envoyé. Précisez les champs à la main si l'appel "
              "est valide malgré tout.", file=sys.stderr)
        return 65

    charge = signal.charge()
    print(json.dumps(charge, indent=2, ensure_ascii=False))
    if args.essai:
        print("\n(essai — rien n'a été envoyé)")
        return 0

    jeton = os.getenv("ORVION_SIGNAL_TOKEN", "")
    if not jeton:
        print("⛔ ORVION_SIGNAL_TOKEN absent de l'environnement.", file=sys.stderr)
        return 78
    base = os.getenv("SCALPING_API_URL", "https://app.scalping-radar.online").rstrip("/")

    import httpx
    try:
        r = httpx.post(f"{base}/api/signals/external", json=charge,
                       headers={"X-Signal-Token": jeton}, timeout=15.0)
    except Exception as e:  # noqa: BLE001
        print(f"⛔ envoi impossible : {e}", file=sys.stderr)
        return 70

    try:
        verdict = r.json()
    except Exception:  # noqa: BLE001
        verdict = {"brut": r.text[:300]}
    print(f"\nHTTP {r.status_code}")
    print(json.dumps(verdict, indent=2, ensure_ascii=False))
    # ⚠️ Un doublon rend 200 avec `cause: doublon` : l'idempotence FONCTIONNE,
    # ce n'est pas un échec. Le code de sortie le reflète.
    return 0 if r.status_code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
