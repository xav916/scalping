#!/usr/bin/env python3
"""Essai de bout en bout d'une ouverture, PAR COMPTE et donc PAR FIL.

## Pourquoi

Le 06/09 a sorti, en une journée, trois tables de canaux divergentes et un
risque en euros faux d'un facteur 156. Aucun de ces défauts n'était visible
depuis un test unitaire : ils vivaient dans l'assemblage — quel bot reçoit
quoi, avec quels montants, sous quel libellé de compte.

🔑 Cet essai emprunte **exactement** le chemin d'un vrai trade :
`send_trade_opened()` → `_canal_trade()` → `canaux_telegram` → le bot. Un
chemin parallèle ne prouverait rien : c'est précisément l'assemblage qu'on
veut voir.

⛔ Il ne touche AUCUN courtier. Rien n'est envoyé à un bridge, aucun ordre
n'existe. Le message porte un bandeau qui le dit, sans quoi un essai relu
dans trois semaines passerait pour une position qu'on aurait vraiment prise.

## Les cas

Chaque trade fictif rejoue un défaut connu, pour que l'essai prouve quelque
chose plutôt que d'exercer du code au hasard :

| compte | paire | ce qu'il vérifie |
|---|---|---|
| `admin_live` | USD/JPY | annonçait **909,09 €** pour 5,82 € réels (×156) |
| `admin_kraken` | ETH/USD | taille de contrat 1 : annonçait « −0,01 € » pour 0,57 € |
| `admin_legacy` | EUR/GBP | cotation en GBP, sous-estimée de 30 % ; fil muet jusqu'au 06/09 |

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
     "cotation en GBP, sous-estimée de 30 % ; fil muet jusqu'au 06/09"),
]


def _verifier(texte: str, libelle_attendu: str, montants) -> list[str]:
    """Ce qui doit être vrai du message. Rend la liste des ANOMALIES.

    ⛔ On vérifie ce qui a réellement cassé aujourd'hui, pas des généralités.
    """
    anomalies = []
    if "None" in texte:
        anomalies.append("« None » apparaît dans le message")
    if montants is None:
        anomalies.append("montants indéterminables")
    else:
        r = montants.get("risque_eur")
        if r is None:
            anomalies.append("risque en euros absent")
        elif not (0.05 <= r <= 200.0):
            # ⛔ La borne qui aurait attrapé les 909,09 €. Elle est large
            # exprès : elle ne juge pas le sizing, elle attrape l'absurde.
            anomalies.append(f"risque hors de toute vraisemblance : {r} €")
        if montants.get("rr") is not None and abs(montants["rr"] - 1.8) > 0.05:
            anomalies.append(f"R:R inattendu : {montants['rr']}")
    if "ESSAI" not in texte:
        anomalies.append("bandeau d'essai absent — confusion possible avec un vrai trade")
    return anomalies


async def _un_cas(did, libelle, setup, volume, motif, envoyer):
    from backend.services import telegram_service as ts
    from backend.services.canaux_telegram import canal_pour, libelle as lib

    canal = canal_pour(did)
    jeton, destinataires = ts._canal_trade(did)
    montants = ts._montants_du_trade(setup, volume, did)
    texte = ts._format_trade_opened(
        setup, ticket="ESSAI", fill_price=setup.entry_price, volume=volume,
        mode="live", destination_id=did, essai=True)

    print(f"\n{'=' * 68}\n{libelle}  {setup.pair}  ({motif})")
    print(f"  fil        {canal}   libellé {lib(canal)}")
    print(f"  bot        …{jeton[-6:] if jeton else 'AUCUN'}   "
          f"destinataires {len(destinataires)}")
    if montants:
        print(f"  risque     {montants.get('risque_eur')} €   "
              f"objectif {montants.get('gain_eur')} €   "
              f"R:R {montants.get('rr')}")

    anomalies = _verifier(texte, libelle, montants)
    # ⛔ Le fil doit correspondre au compte : c'est LE defaut du jour.
    if lib(canal) != libelle:
        anomalies.append(f"fil {canal} ≠ compte attendu {libelle}")
    if not jeton:
        anomalies.append("aucun bot gréé pour ce fil")

    print("  ---- message ----")
    print("\n".join("  | " + l for l in texte.split("\n")))

    if anomalies:
        for a in anomalies:
            print(f"  ⛔ {a}")
    else:
        print("  ✅ aucune anomalie")

    if envoyer:
        await ts.send_trade_opened(
            setup, ticket="ESSAI", fill_price=setup.entry_price,
            volume=volume, mode="live", destination_id=did, essai=True)
        print("  → envoyé")
    return anomalies


async def main(envoyer: bool) -> int:
    total = []
    for did, libelle, setup, volume, motif in CAS:
        total += await _un_cas(did, libelle, setup, volume, motif, envoyer)
    print(f"\n{'=' * 68}")
    if total:
        print(f"⛔ {len(total)} anomalie(s) — voir ci-dessus")
        return 1
    print("✅ les 3 comptes : fil correct, montants vraisemblables, R:R 1,80")
    if not envoyer:
        print("   (rien envoyé — relancer avec --envoyer pour poster)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--envoyer", action="store_true",
                    help="poste réellement sur les fils Telegram")
    sys.exit(asyncio.run(main(ap.parse_args().envoyer)))
