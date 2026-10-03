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

## Deux usages, selon ce que Xavier a sous la main

**Interactif** — s'il est devant un terminal :

    docker exec -it -w /app -e PYTHONPATH=/app scalping-radar \\
        python scripts/connexion_telegram.py

⚠️ `-it` est OBLIGATOIRE : sans terminal, impossible de taper le code. Le
script le dit au lieu d'echouer sans raison lisible.

**En DEUX TEMPS** — le 2026-10-03, Xavier n'avait que son telephone, donc
aucun terminal. La demande de code et la connexion sont alors separees, et
c'est Claude qui les lance :

    # 1. demander le code (le numero arrive par l'entree standard)
    echo "+33..." | python scripts/connexion_telegram.py --demander
    # 2. Xavier lit le code sur son telephone et le dicte ; puis :
    echo "12345" | python scripts/connexion_telegram.py --code

⛔ Le numero et le code passent par l'ENTREE STANDARD, jamais en argument :
sinon ils apparaitraient dans `argv` et dans la liste des processus.

⚠️ Entre les deux etapes, Telegram exige le `phone_code_hash` rendu par la
premiere. Il est donc garde dans `/app/data/veille_tg_attente.json` en `0600`,
et **efface des que la connexion aboutit**. Sans lui, le code serait refuse
avec un motif obscur.

Apres succes, la commande liste les canaux auxquels le compte est abonne, avec
leur identifiant exact — c'est ce qu'il faut mettre dans `VEILLE_CANAUX`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# L'attente entre les deux etapes. ⚠️ Dans le volume monte, en 0600, et effacee
# des que la connexion aboutit.
ATTENTE = Path("/app/data/veille_tg_attente.json")


def _lister_canaux(client) -> int:
    """Les canaux de DIFFUSION auxquels le compte est abonne."""
    print("\n=== canaux auxquels ce compte est abonne ===")
    print("   (ceux a brancher iront dans VEILLE_CANAUX, separes par des "
          "virgules)\n")
    n = 0
    for d in client.iter_dialogs():
        e = d.entity
        # ⚠️ Seuls les canaux de diffusion : ni conversations privees (ce
        # serait lire ses messages personnels), ni groupes.
        if not getattr(e, "broadcast", False):
            continue
        n += 1
        nom = getattr(e, "username", None)
        print(f"   {('@' + nom) if nom else ('id=' + str(e.id)):28s} {d.name}")
    if not n:
        print("   (aucun canal de diffusion — le compte n'est abonne a aucun)")
    return n


def _attente_ecrite(donnees: dict) -> None:
    ATTENTE.parent.mkdir(parents=True, exist_ok=True)
    ATTENTE.write_text(json.dumps(donnees))
    ATTENTE.chmod(0o600)


def _prerequis(ing) -> int | None:
    if not ing.API_ID or not ing.API_HASH:
        print("⛔ VEILLE_TG_API_ID et VEILLE_TG_API_HASH sont requis.\n"
              "   Obtenez-les sur https://my.telegram.org "
              "→ API development tools.", file=sys.stderr)
        return 2
    try:
        from telethon.sync import TelegramClient  # noqa: F401
    except ImportError:
        print("⛔ telethon absent de l'image. Redeployer apres l'ajout a "
              "requirements.txt.", file=sys.stderr)
        return 3
    return None


def demander() -> int:
    """Etape 1 : Telegram envoie un code sur le telephone de Xavier."""
    from backend.services import ingestion_telegram as ing
    if (code := _prerequis(ing)) is not None:
        return code

    numero = sys.stdin.read().strip()
    if not numero.startswith("+") or len(numero) < 8:
        print("⛔ numero attendu au format international, par exemple +33...",
              file=sys.stderr)
        return 5

    client = ing._client()
    client.connect()
    if client.is_user_authorized():
        print("✅ deja connecte — aucune demande de code necessaire.")
        _lister_canaux(client)
        client.disconnect()
        return 0
    envoi = client.send_code_request(numero)
    _attente_ecrite({"numero": numero,
                     "phone_code_hash": envoi.phone_code_hash})
    client.disconnect()
    ing._droits_session()
    print("✅ code demande. Telegram vient de l'envoyer — regarde dans "
          "l'application Telegram elle-meme, pas forcement en SMS.")
    print("   ⚠️ Il expire en quelques minutes.")
    return 0


def terminer() -> int:
    """Etape 2 : le code dicte par Xavier termine la connexion."""
    from backend.services import ingestion_telegram as ing
    if (c := _prerequis(ing)) is not None:
        return c
    if not ATTENTE.exists():
        print("⛔ aucune demande en attente : relancer --demander d'abord.\n"
              "   (Telegram exige le `phone_code_hash` rendu par la demande ; "
              "sans lui le code est refuse avec un motif obscur.)",
              file=sys.stderr)
        return 6

    attente = json.loads(ATTENTE.read_text())
    entree = sys.stdin.read().strip().split()
    code = entree[0] if entree else ""
    mot_de_passe = entree[1] if len(entree) > 1 else None
    if not code:
        print("⛔ code attendu sur l'entree standard.", file=sys.stderr)
        return 5

    client = ing._client()
    client.connect()
    try:
        client.sign_in(phone=attente["numero"], code=code,
                       phone_code_hash=attente["phone_code_hash"])
    except Exception as e:  # noqa: BLE001
        nom = type(e).__name__
        if "SessionPassword" in nom:
            # ⚠️ Verification en deux etapes active : il faut aussi le mot de
            # passe du compte. On ne le demande qu'ici, et seulement si c'est
            # indispensable.
            if not mot_de_passe:
                print("⛔ la verification en deux etapes est active sur ce "
                      "compte : le mot de passe Telegram est aussi requis.\n"
                      "   Relancer --code avec « CODE MOTDEPASSE ».",
                      file=sys.stderr)
                client.disconnect()
                return 7
            client.sign_in(password=mot_de_passe)
        else:
            print(f"⛔ connexion refusee : {nom}. "
                  "Si le code a expire, relancer --demander.", file=sys.stderr)
            client.disconnect()
            return 8

    ing._droits_session()
    try:
        ATTENTE.unlink()          # ⛔ l'attente ne survit pas au succes
    except OSError:
        pass
    moi = client.get_me()
    print(f"✅ connecte : {getattr(moi, 'username', None) or moi.id}")
    print("   session posee en 0600 dans le volume monte ; un deploiement ne "
          "l'efface pas,\n   ce code ne sera plus redemande.")
    _lister_canaux(client)
    client.disconnect()
    return 0


def main() -> int:
    from backend.services import ingestion_telegram as ing

    if "--demander" in sys.argv:
        return demander()
    if "--code" in sys.argv:
        return terminer()

    if (c := _prerequis(ing)) is not None:
        return c
    if not sys.stdin.isatty():
        print("⛔ Pas de terminal interactif : Telegram va demander un code "
              "et personne ne pourra le taper.\n"
              "   Relancez avec `docker exec -it`, ou utilisez les deux "
              "etapes `--demander` puis `--code`.", file=sys.stderr)
        return 4

    print(f"session : {ing.SESSION}")
    client = ing._client()
    client.start()
    ing._droits_session()
    moi = client.get_me()
    print(f"\n✅ connecte : {getattr(moi, 'username', None) or moi.id}")
    _lister_canaux(client)
    client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
