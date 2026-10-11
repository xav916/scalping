#!/usr/bin/env python3
"""Envoie le BILAN DU JOUR des messages differes — un seul message.

    python scripts/envoyer_digest_telegram.py --essai   # affiche, n'envoie rien
    python scripts/envoyer_digest_telegram.py           # envoie

Deuxieme moitie de la regle des trois etages (`etages_notification`). Les
messages classes DIGEST sont ranges par la route d'envoi ; ce script les
ramasse une fois par jour et en fait UN message.

## ⛔ DESARME PAR DEFAUT, comme le routage

Sans `ETAGES_NOTIFICATION`, rien n'est range, donc ce script ne trouve rien et
se taît. Il n'a pas besoin de son propre interrupteur : son travail n'existe
que si le routage est arme.

## 🔑 ON MARQUE APRES L'ENVOI, JAMAIS AVANT

Marquer avant, c'est perdre le bilan le jour ou Telegram refuse — exactement
le defaut repare le 2026-10-07 sur le cooldown de la route, ou la marque etait
posee avant l'appel et un echec consommait le silence.

## ⛔ UN BILAN VIDE N'ENVOIE RIEN

Envoyer << Bilan du jour — 0 message >> chaque soir serait exactement le bruit
qu'on retire.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, "/app")

CANAL = os.environ.get("DIGEST_CANAL", "ic_markets")


def main() -> int:
    essai = "--essai" in sys.argv

    from backend.services import digest_telegram as D

    lignes = D.en_attente(CANAL)
    if not lignes:
        print("bilan du jour : rien a dire (0 message differe) — on se tait")
        return 0

    texte = D.formater(lignes)
    print("bilan du jour : %d message(s) differe(s)" % len(lignes))
    print("-" * 60)
    print(texte)
    print("-" * 60)

    if essai:
        print("[ESSAI] rien envoye, rien marque")
        return 0

    import httpx
    from backend.services import canaux_telegram as ct
    from config import settings as cfg

    var_token, var_chat, libelle, picto = ct.CANAUX[CANAL]
    jeton = getattr(cfg, var_token, "")
    salon = getattr(cfg, var_chat, "")
    if not jeton or not salon:
        print("⛔ fil %s non configure (%s/%s) — rien envoye, rien marque : "
              "le bilan repartira demain" % (CANAL, var_token, var_chat))
        return 1

    # ⛔ TEXTE BRUT. `parse_mode` absent exprès : les `dedup_key` sont en
    # snake_case et Telegram lit un underscore comme une italique OUVERTE —
    # 400, message jamais livre. Defaut paye le 2026-10-10 sur `/trade`.
    corps = "%s %s Bilan du jour\n\n%s" % (picto, libelle, texte)
    try:
        r = httpx.post(
            "https://api.telegram.org/bot%s/sendMessage" % jeton,
            json={"chat_id": salon, "text": corps[:4000],
                  "disable_web_page_preview": True},
            timeout=20.0)
    except Exception as e:  # noqa: BLE001
        print("⛔ envoi impossible (%s) — rien marque, le bilan repartira "
              "demain" % e)
        return 1

    if r.status_code != 200:
        print("⛔ Telegram a refuse (%s : %s) — rien marque, le bilan "
              "repartira demain" % (r.status_code, r.text[:200]))
        return 1

    n = D.marquer_envoyes([l["id"] for l in lignes])
    print("✅ envoye, et %d ligne(s) marquee(s)" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
