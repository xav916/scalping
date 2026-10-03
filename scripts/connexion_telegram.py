#!/usr/bin/env python3
"""La connexion Telegram, UNE fois. ⛔ A lancer par Xavier, pas par Claude.

Telegram envoie un code par SMS ou dans l'application. Il faut le taper. Aucun
automate ne peut le faire a sa place, et c'est une bonne chose : cette etape est
la preuve que le compte appartient bien a quelqu'un.

## ⚠️ Ce que cette commande cree, et ce que ca engage

Un fichier de session dans `/app/data/`, qui **vaut le compte Telegram** :
quiconque l'obtient lit toutes les conversations de Xavier. Il est donc ecrit
avec des droits `0600`, il vit dans le volume monte (un deploiement ne l'efface
pas), et il n'est jamais copie ailleurs.

⛔ Ni `api_hash`, ni le code recu, ni le contenu de la session ne sont affiches
ni journalises.

## Usage

    # 1. Obtenir api_id et api_hash sur https://my.telegram.org
    #    → API development tools → create application
    # 2. Les poser dans l'environnement du conteneur, puis :

    docker exec -it -w /app -e PYTHONPATH=/app scalping-radar \\
        python scripts/connexion_telegram.py

⚠️ `-it` est OBLIGATOIRE : sans terminal interactif, impossible de taper le
code, et la commande echouerait sans dire pourquoi.

Apres succes, la commande liste les canaux auxquels le compte est abonne, avec
leur identifiant exact — c'est ce qu'il faut mettre dans `VEILLE_CANAUX`.
"""
from __future__ import annotations

import sys


def main() -> int:
    from backend.services import ingestion_telegram as ing

    if not ing.API_ID or not ing.API_HASH:
        print("⛔ VEILLE_TG_API_ID et VEILLE_TG_API_HASH sont requis.\n"
              "   Obtenez-les sur https://my.telegram.org "
              "→ API development tools.", file=sys.stderr)
        return 2
    try:
        from telethon.sync import TelegramClient  # noqa: F401
    except ImportError:
        print("⛔ telethon absent de l'image. Il faut redeployer apres l'ajout "
              "a requirements.txt.", file=sys.stderr)
        return 3

    if not sys.stdin.isatty():
        print("⛔ Pas de terminal interactif : Telegram va demander un code "
              "et personne ne pourra le taper.\n"
              "   Relancez avec `docker exec -it`.", file=sys.stderr)
        return 4

    print(f"session : {ing.SESSION}")
    client = ing._client()
    client.start()                      # demande le telephone puis le code
    ing._droits_session()

    moi = client.get_me()
    print(f"\n✅ connecte : {getattr(moi, 'username', None) or moi.id}")
    print("   la session est posee avec des droits 0600 dans le volume monte ;"
          "\n   un deploiement ne l'efface pas, ce code ne sera pas redemande.")

    print("\n=== canaux auxquels ce compte est abonne ===")
    print("   (copiez les identifiants voulus dans VEILLE_CANAUX, "
          "separes par des virgules)\n")
    n = 0
    for d in client.iter_dialogs():
        e = d.entity
        # Seuls les canaux de diffusion : ni conversations privees, ni groupes.
        if not getattr(e, "broadcast", False):
            continue
        n += 1
        nom = getattr(e, "username", None)
        print(f"   {'@' + nom if nom else f'id={e.id}':30s} {d.name}")
    if not n:
        print("   (aucun canal de diffusion — le compte n'est abonne a aucun)")
    client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
