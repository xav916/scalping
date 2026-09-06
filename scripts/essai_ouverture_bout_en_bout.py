#!/usr/bin/env python3
"""Essai de bout en bout, PAR COMPTE et donc PAR FIL — ouverture ET clôture.

## Pourquoi

Le 06/09 a sorti, en une journée, trois tables de canaux divergentes et un
risque en euros faux d'un facteur 156. Aucun de ces défauts n'était visible
depuis un test unitaire : ils vivaient dans l'assemblage — quel bot reçoit
quoi, avec quels montants, sous quel libellé de compte.

🔑 Cet essai emprunte **exactement** le chemin d'un vrai trade :
`send_trade_opened()` / `send_close()` → `_canal_trade()` → `canaux_telegram`
→ le bot. Un chemin parallèle ne prouverait rien : c'est précisément
l'assemblage qu'on veut voir.

⛔ Il ne touche AUCUN courtier. Rien n'est envoyé à un bridge, aucun ordre
n'existe, aucune position n'est fermée. Le message porte un bandeau qui le
dit, sans quoi un essai relu dans trois semaines passerait pour une position
qu'on aurait vraiment prise.

⚠️ La clôture est éprouvée aussi, et pas par symétrie décorative : le fil démo
recevait des ouvertures qui ne se refermaient **jamais** — une demi-histoire,
pire que pas d'histoire — et c'est la clôture qui porte le RÉSULTAT.

## Les cas

Chaque trade fictif rejoue un défaut connu, pour que l'essai prouve quelque
chose plutôt que d'exercer du code au hasard :

| compte | paire | ce qu'il vérifie |
|---|---|---|
| `admin_live` | USD/JPY | annonçait **909,09 €** pour 5,82 € réels (×156) |
| `admin_kraken` | ETH/USD | taille de contrat 1 : annonçait « −0,01 € » pour 0,57 € |
| `admin_legacy` | EUR/GBP | cotation en GBP sous-estimée de 30 % ; fil muet jusqu'au 06/09 |

Le sens du 3ᵉ est `sell` **exprès** : c'est lui qui a révélé la pastille 🟢
codée en dur sur les ventes.

## Emploi

    python scripts/essai_ouverture_bout_en_bout.py            # montre, n'envoie pas
    python scripts/essai_ouverture_bout_en_bout.py --envoyer  # envoie pour de vrai
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass

sys.path.insert(0, "/app")

SEP = "=" * 68
SOUS_SEP = "-" * 68


@dataclass
class SetupFictif:
    """Le profil qu'un vrai setup présente au formateur de message.

    ⚠️ Les noms de champs sont ceux que `_format_trade_opened` et
    `_montants_du_trade` lisent réellement. Les inventer ferait un essai qui
    passe alors que la vraie chaîne casse.
    """
    pair: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit_1: float
    pattern: str = "rebond_support"
    confidence_score: int = 62


# R:R 1,80 partout — le ratio mesuré sur l'ensemble des trades réels.
CAS = [
    ("admin_live", "[RÉEL · IC_MARKETS]",
     SetupFictif("USD/JPY", "buy", 156.09700, 155.04700, 157.98700), 0.01,
     "annonçait 909,09 € pour 5,82 € réels"),
    ("admin_kraken", "[RÉEL · KRAKEN]",
     SetupFictif("ETH/USD", "buy", 4200.0, 4100.0, 4380.0), 0.05,
     "taille de contrat 1 : annonçait « −0,01 € »"),
    ("admin_legacy", "[DÉMO · PEPPERSTONE]",
     SetupFictif("EUR/GBP", "sell", 0.86500, 0.87000, 0.85600), 0.02,
     "cotation en GBP sous-estimée de 30 % ; fil muet jusqu'au 06/09"),
]


def _verifier(texte: str, montants) -> list[str]:
    """Ce qui doit être vrai du message. Rend la liste des ANOMALIES.

    ⛔ On vérifie ce qui a réellement cassé, pas des généralités.
    """
    anomalies = []
    if "None" in texte:
        anomalies.append("« None » apparaît dans le message")
    if "ESSAI" not in texte:
        anomalies.append("bandeau d'essai absent — confusion avec un vrai trade")
    if montants is None:
        anomalies.append("montants indéterminables")
        return anomalies
    r = montants.get("risque_eur")
    if r is None:
        anomalies.append("risque en euros absent")
    elif not (0.05 <= r <= 200.0):
        # ⛔ La borne qui aurait attrapé les 909,09 €. Large exprès : elle ne
        # juge pas le sizing, elle attrape l'absurde.
        anomalies.append(f"risque hors de toute vraisemblance : {r} €")
    if montants.get("rr") is not None and abs(montants["rr"] - 1.8) > 0.05:
        anomalies.append(f"R:R inattendu : {montants['rr']}")
    return anomalies


def _verifier_pastille(texte: str, sens: str) -> list[str]:
    """⛔ La pastille était 🟢 EN DUR : toute VENTE portait le signe de
    l'ACHAT. C'est ce que l'œil lit en PREMIER, avant tout chiffre — et aucun
    test unitaire ne le voyait, tous vérifiant le texte."""
    attendue = "🟢" if sens == "buy" else "🔴"
    ligne = next((l for l in texte.splitlines()
                  if "ACHAT" in l or "VENTE" in l), "")
    if attendue not in ligne:
        return [f"pastille incohérente avec le sens {sens} : {ligne[:40]}"]
    return []


def _montrer(texte: str, anomalies: list[str]) -> None:
    print("\n".join("  | " + l for l in texte.splitlines()))
    if anomalies:
        for a in anomalies:
            print(f"  ⛔ {a}")
    else:
        print("  ✅ aucune anomalie")


async def _ouverture(did, libelle, setup, volume, motif, envoyer):
    from backend.services import telegram_service as ts
    from backend.services.canaux_telegram import canal_pour, libelle as lib

    canal = canal_pour(did)
    jeton, destinataires = ts._canal_trade(did)
    montants = ts._montants_du_trade(setup, volume, did)
    texte = ts._format_trade_opened(
        setup, ticket="ESSAI", fill_price=setup.entry_price, volume=volume,
        mode="live", destination_id=did, essai=True)

    print(f"\n{SEP}")
    print(f"{libelle}  {setup.pair}  — OUVERTURE  ({motif})")
    print(f"  fil        {canal}   libellé {lib(canal)}")
    print(f"  bot        …{jeton[-6:] if jeton else 'AUCUN'}   "
          f"destinataires {len(destinataires)}")
    if montants:
        print(f"  risque     {montants.get('risque_eur')} €   "
              f"objectif {montants.get('gain_eur')} €   "
              f"R:R {montants.get('rr')}")

    anomalies = _verifier(texte, montants)
    anomalies += _verifier_pastille(texte, setup.direction)
    # ⛔ Le fil doit correspondre au compte : c'est LE défaut du jour.
    if lib(canal) != libelle:
        anomalies.append(f"fil {canal} ≠ compte attendu {libelle}")
    if not jeton:
        anomalies.append("aucun bot gréé pour ce fil")

    _montrer(texte, anomalies)
    if envoyer:
        await ts.send_trade_opened(
            setup, ticket="ESSAI", fill_price=setup.entry_price,
            volume=volume, mode="live", destination_id=did, essai=True)
        print("  → envoyé")
    return anomalies


def _cloture_depuis(setup, volume) -> dict:
    """La clôture de CE trade, gagnante à l'objectif.

    ⚠️ Les noms de champs sont ceux que `_format_close` et `_risque_annonce`
    lisent réellement — `take_profit` au singulier côté clôture, et
    `stop_loss` pour retrouver ce que l'ouverture avait annoncé.
    """
    brut = abs(setup.take_profit_1 - setup.entry_price)
    return {
        "pair": setup.pair,
        "direction": setup.direction,
        "entry_price": setup.entry_price,
        "exit_price": setup.take_profit_1,
        "stop_loss": setup.stop_loss,
        "take_profit": setup.take_profit_1,
        "size_lot": volume,
        "pnl": round(brut * volume, 2),
        "close_reason": "TP",
        "mt5_ticket": "ESSAI-" + setup.pair.replace("/", ""),
        "created_at": "2026-09-06T17:00:00+00:00",
        "closed_at": "2026-09-06T19:00:00+00:00",
        "signal_confidence": setup.confidence_score,
    }


async def _cloture(did, libelle, setup, volume, envoyer):
    """⛔ La clôture est la MOITIÉ manquante. Le fil démo recevait des
    ouvertures qui ne se refermaient jamais — une demi-histoire, pire que pas
    d'histoire — et c'est la clôture qui porte le RÉSULTAT."""
    from backend.services import telegram_service as ts
    from backend.services.canaux_telegram import canal_pour, libelle as lib

    trade = _cloture_depuis(setup, volume)
    canal = canal_pour(did)
    texte = ts._format_close(trade, did, essai=True)

    print(f"\n{SOUS_SEP}")
    print(f"{libelle}  {setup.pair}  — CLÔTURE")

    anomalies = []
    if "None" in texte:
        anomalies.append("« None » apparaît dans le message de clôture")
    if "ESSAI" not in texte:
        anomalies.append("bandeau d'essai absent")
    if "Prévu" not in texte:
        # ⛔ Ligne miroir de l'ouverture : sans elle, impossible de comparer
        # ce qu'on avait annoncé à ce qui est arrivé.
        anomalies.append("ligne « Prévu → Réalisé » absente")
    if lib(canal) != libelle:
        anomalies.append(f"fil {canal} ≠ compte attendu {libelle}")
    anomalies += _verifier_pastille(texte, setup.direction)

    _montrer(texte, anomalies)
    if envoyer:
        # ⚠️ Le dédoublonnage est en mémoire : sans ce retrait, un second
        # passage dans le même conteneur se tairait, et l'essai passerait pour
        # réussi alors qu'il n'aurait rien envoyé.
        ts._notified_closes.discard(str(trade["mt5_ticket"]))
        await ts.send_close(trade, destination_id=did, essai=True)
        print("  → envoyé")
    return anomalies


async def main(envoyer: bool) -> int:
    total = []
    for did, libelle, setup, volume, motif in CAS:
        total += await _ouverture(did, libelle, setup, volume, motif, envoyer)
        total += await _cloture(did, libelle, setup, volume, envoyer)

    print(f"\n{SEP}")
    if total:
        print(f"⛔ {len(total)} anomalie(s) — voir ci-dessus")
        return 1
    print("✅ 3 comptes × (ouverture + clôture) : fil correct, montants "
          "vraisemblables, R:R 1,80, pastille cohérente")
    if not envoyer:
        print("   (rien envoyé — relancer avec --envoyer pour poster)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--envoyer", action="store_true",
                    help="poste réellement sur les fils Telegram")
    sys.exit(asyncio.run(main(ap.parse_args().envoyer)))
