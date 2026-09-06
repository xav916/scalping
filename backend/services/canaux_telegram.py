"""À quel fil Telegram appartient une notification — nommé PAR COMPTE.

Point ① de la rationalisation du 2026-09-06.

## Le constat

Quatre bots existent, et chacun écrit en privé à Xavier : le nom affiché dans
Telegram est celui du **bot**, pas d'un groupe. La séparation ne tient donc
qu'à une chose : le `channel` que passe l'appelant.

Or les canaux portaient des noms d'**usage** hérités, plus des noms de compte :

```
channel=sales   →  bot « IC MARKETS trades »
channel=trades  →  bot « KRAKEN Trades »
```

⛔ Un script qui notifie un trade IC Markets écrit naturellement
`channel=trades`… et atterrit chez Kraken. C'est ce qui s'est produit : `app.py`
poste les clôtures sur `trades`, si bien que « Position fermée — compte réel
13137475 » (le login IC Markets) s'affiche dans le fil Kraken. Symétriquement,
`notify-kraken-trade.sh` postait sur `sales`, donc chez IC Markets.

🔑 Le nom d'un canal doit dire **de quel compte il parle**, pas quel bot
l'a historiquement porté.

## Pourquoi une SEULE fonction

⛔ Chaque sonde décidait son canal dans son coin. Un correctif ne se propage
pas seul aux routes jumelles — déjà payé sur les stops Kraken, posés au prix du
signal alors que la route MT5 était corrigée. `canal_pour()` est donc le seul
endroit où un `destination_id` devient un fil.

⚠️ Les anciens noms restent acceptés : les couper casserait 25 appelants d'un
coup. Mais leur usage est JOURNALISÉ — un repli silencieux se lit comme une
absence de problème.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# canal → (variable jeton, variable chat, ce que le fil porte, picto)
#
# ⚠️ Le PICTO vit ici, avec le libellé, et pas dans une table à part : c'est
# la même information — « de quel compte parle-t-on » — sous deux formes. Une
# seconde table dériverait, comme les trois tables de canaux du 06/09.
#
# Couleurs choisies sur la marque du courtier : IC Markets bleu, Kraken
# violet, Pepperstone orange. L'œil reconnaît la section avant de lire.
CANAUX: dict[str, tuple[str, str, str, str]] = {
    "ic_markets": ("SALES_TELEGRAM_BOT_TOKEN", "SALES_TELEGRAM_CHAT_ID",
                   "[RÉEL · IC_MARKETS]", "🟦"),
    "kraken": ("TRADES_TELEGRAM_BOT_TOKEN", "TRADES_TELEGRAM_CHAT_ID",
               "[RÉEL · KRAKEN]", "🟪"),
    "demo": ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
             "[DÉMO · PEPPERSTONE]", "🟧"),
    "infra": ("INFRA_TELEGRAM_BOT_TOKEN", "INFRA_TELEGRAM_CHAT_ID",
              "[INFRA]", "⚙️"),
}

# ⚠️ Anciens noms. `trades` visait le bot Kraken et `sales` le bot IC Markets :
# on conserve EXACTEMENT ce routage, sans quoi la bascule déplacerait des
# messages en silence.
ALIAS: dict[str, str] = {"sales": "ic_markets", "trades": "kraken"}

# Le compte dont parle la notification → son fil.
#
# ⛔ IBKR n'a pas de fil : il est ÉTEINT, et son edge mesuré négatif. Ses rares
# messages d'état vont sur `infra` — les mêler aux trades donnerait à croire
# qu'il en passe.
_PAR_DESTINATION: dict[str, str] = {
    "admin_live": "ic_markets",
    "admin_kraken": "kraken",
    "admin_kraken_spot": "kraken",
    "admin_legacy": "demo",
    "admin_ibkr": "infra",
}


def canal_pour(destination_id: str | None) -> str:
    """Le fil d'un compte. ⛔ Un compte inconnu part sur `infra`, jamais sur un
    fil de trading : mieux vaut un message mal rangé qu'un message qui laisse
    croire qu'un compte a tradé."""
    if not destination_id:
        return "infra"
    canal = _PAR_DESTINATION.get(str(destination_id).strip().lower())
    if canal is None:
        logger.warning(
            "canal_pour: destination inconnue %r — repli sur infra", destination_id)
        return "infra"
    return canal


def normaliser(channel: str | None) -> tuple[str, bool]:
    """Rend `(canal_canonique, etait_un_alias)`. Lève `KeyError` si inconnu."""
    brut = (channel or "infra").strip().lower()
    if brut in ALIAS:
        return ALIAS[brut], True
    if brut in CANAUX:
        return brut, False
    raise KeyError(brut)


def libelle(canal: str) -> str:
    """Le préfixe de compte du fil — celui-là même qu'on emploie en session."""
    return CANAUX[canal][2]


def picto(canal: str) -> str:
    """Le picto du courtier. Couleur de sa marque, pour que l'œil trouve la
    section avant de lire."""
    return CANAUX[canal][3]


def libelle_avec_picto(canal: str) -> str:
    return f"{picto(canal)} {libelle(canal)}"


FILS_DE_TRADING = frozenset({"ic_markets", "kraken", "demo"})


def est_un_compte_de_trading(destination_id: str | None) -> bool:
    """Un de NOS comptes qui passe des ordres — réel ou démo.

    ⛔ Sert à décider qui reçoit une notification d'ouverture. Un `user:2` ou
    une destination inconnue n'en est pas un : lui en envoyer une la ferait
    atterrir sur `infra`, où elle se lirait comme un trade de la maison.

    ⚠️ IBKR en est exclu par construction : il est éteint, et son fil est
    `infra`.
    """
    return canal_pour(destination_id) in FILS_DE_TRADING


def jeton_et_chat(canal: str) -> tuple[str, str]:
    """``(jeton_bot, chat_id)`` d'un fil, lus dans la configuration.

    ⛔ Sert aux envois qui appellent l'API Telegram DIRECTEMENT, sans passer
    par l'endpoint — les notifications d'ouverture et de clôture. Sans cela
    ils redéfinissent leur propre table, et c'est très exactement ce qui a
    fait partir les ouvertures du compte réel IC Markets dans le fil Kraken.
    """
    from config import settings as _cfg
    var_token, var_chat, _lib, _picto = CANAUX[canal]
    return getattr(_cfg, var_token, ""), getattr(_cfg, var_chat, "")


if __name__ == "__main__":
    # Les scripts shell lisent la table ICI plutôt que d'en recopier une.
    #
    # ⛔ Une deuxième table serait une table qui dérive : c'est exactement ce
    # qui s'est produit entre le nom des bots côté Telegram et le nom des
    # canaux côté code. Sans argument : la table entière, une ligne par compte.
    import sys
    if len(sys.argv) > 1:
        print(canal_pour(sys.argv[1]))
    else:
        for dest, canal in sorted(_PAR_DESTINATION.items()):
            print(f"{dest}={canal}")
