#!/usr/bin/env python3
"""L'execution est-elle ARMEE ? Si non, le dire — vite.

    python scripts/veilleur_interrupteur_execution.py
    python scripts/veilleur_interrupteur_execution.py --essai    # n'envoie rien
    python scripts/veilleur_interrupteur_execution.py --bilan    # dit l'etat quoi qu il arrive

## ⛔ POURQUOI IL EXISTE

Le 2026-10-07 a 22h14 UTC, un deploiement a change l'empreinte du code.
REM-002 a desarme l'execution — exactement ce qu'il doit faire. Personne ne l'a
lu. Resultat :

    456 refus `execution_globale_fermee` sur l'or en une heure, seul motif
    SIX HEURES de marche sans un ordre
    et c'est Xavier qui l'a remarque, en regardant ses bougies

Les signaux sortaient bien pendant tout ce temps (`engulfing_bullish` 15 min,
`order_block_up` 60 min a 06h45:31). Rien n'etait casse. Le garde-fou a
parfaitement fonctionne.

> 🔑 Ce qui a manque, ce n'est pas un garde-fou. C'est de le LIRE.

Consigne de Xavier le 2026-10-08 : « verifie l'interrupteur apres chaque
deploiement ». `deploy-v2.sh` le fait desormais — mais cela ne couvre que les
deploiements qui passent PAR lui. Ce veilleur couvre tout le reste : un
redemarrage, une derive de configuration, un desarmement manuel oublie.

## Mode EVENEMENT

Muet tant que l'execution est armee. Il ne parle que quand elle ne l'est pas,
et au plus une fois par `COOLDOWN_SEC` — une alerte repetee sans fin n'est plus
lue, c'est la lecon des 8 doublons du 07/10.

⛔ Un etat ILLISIBLE n'est PAS un etat arme : on alerte aussi. Se taire parce
qu'on n'a pas pu regarder est precisement la panne qu'on ne verrait pas.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, "/app")

# Assez long pour ne pas harceler, assez court pour qu'une fermeture ne passe
# pas une seance entiere inapercue.
COOLDOWN_SEC = int(os.environ.get("INTERRUPTEUR_COOLDOWN_SEC", "1800"))


def _etat() -> dict | None:
    """L'etat de l'interrupteur. ``None`` si on n'a pas pu le lire."""
    try:
        from backend.services import global_execution_switch as sw
        return sw.status()
    except Exception as e:  # noqa: BLE001
        print(f"etat ILLISIBLE ({type(e).__name__}: {e})")
        return None


def _prevenir(titre: str, corps: str, dedup: str) -> bool:
    from backend.services.canaux_telegram import canal_pour, notifier
    # `canal_pour(None)` -> le fil infra : c'est un fait d'INFRASTRUCTURE, pas
    # une position. Un ordre qui ne part pas n'appartient a aucun compte.
    return notifier(canal_pour(None), titre, corps, timeout=15,
                    dedup_key=dedup, cooldown_seconds=COOLDOWN_SEC)


def _corps(e: dict | None) -> str:
    if e is None:
        return ("⛔ Impossible de LIRE l'état de l'interrupteur d'exécution.\n\n"
                "Ce n'est pas « tout va bien » : c'est une absence de mesure. "
                "Aucune garantie qu'un ordre puisse partir.")
    lignes = [
        f"• Décision : **{e.get('decision')}** ({e.get('reason_code')})",
        f"• Exécution live : **{e.get('live_execution')}**",
        f"• Empreinte qui tourne : `{e.get('fingerprint_running')}`",
        f"• Empreinte armée : `{e.get('fingerprint_armed')}`",
    ]
    if e.get("configuration_drift"):
        lignes.append("• ⚠️ **dérive de configuration** entre l'armée et la "
                      "courante")
    if e.get("blocages"):
        lignes.append(f"• Blocages : {e.get('blocages')}")
    if e.get("armed_at"):
        lignes.append(f"• Armée le : {str(e.get('armed_at'))[:19]}")
    return "\n".join(lignes)


def main() -> int:
    essai = "--essai" in sys.argv
    bilan = "--bilan" in sys.argv

    e = _etat()
    arme = bool(e) and e.get("decision") == "ALLOW"
    print(f"interrupteur : {'ARME' if arme else 'DESARME ou illisible'}")
    if e:
        print(f"   {e.get('decision')} / {e.get('reason_code')} — "
              f"tourne {e.get('fingerprint_running')}, "
              f"armee {e.get('fingerprint_armed')}")

    if bilan:
        titre = ("✅ Exécution armée" if arme
                 else "🛑 Exécution DÉSARMÉE")
        ok = _prevenir(titre, _corps(e), dedup="interrupteur_bilan")
        print(f"   bilan envoyé : {'OK' if ok else 'ECHEC'}")
        return 0 if ok else 1

    if arme:
        print("   rien à dire")
        return 0

    if essai:
        print("   (--essai : rien envoyé)")
        return 0

    corps = (
        f"{_corps(e)}\n\n"
        "⛔ **Aucun ordre ne partira** tant que ce n'est pas réarmé.\n\n"
        "C'est le comportement attendu après un changement de code : REM-002 "
        "exige qu'un humain réarme. Mais il faut le faire — le 7 octobre, six "
        "heures de marché sont passées sans un ordre faute d'avoir lu cet "
        "état.\n\n"
        "Réponds-moi et je réarme sur l'empreinte courante.")
    ok = _prevenir("🛑 Exécution DÉSARMÉE — aucun ordre ne part", corps,
                   dedup="interrupteur_desarme")
    print(f"   ⛔ alerte {'OK' if ok else 'ECHEC'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
