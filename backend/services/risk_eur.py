"""Risque et gain d'un ordre, en euros, d'après le volume réellement exécuté.

⚠️ **Pourquoi ce module existe.** Le message « trade ouvert » annonçait un
montant calculé pour un lot fixe de 0,01, via une table statique par paire —
sans aucun lien avec le volume réellement envoyé au broker. Conséquences :

- MT5 à 0,02 lot : montant affiché deux fois trop petit ;
- Kraken : montant sans rapport avec la réalité. Le premier trade réel
  annonçait « Risque −0,01 € » pour un risque effectif d'environ 0,57 €.

Le bon calcul existait déjà — dans ``scripts/lib_calc_risk_eur.py``, utilisé
par un script shell. Deux arithmétiques du risque, dont la fausse était celle
que l'utilisateur lisait.

La grandeur qui compte n'est pas le lot mais le **notionnel** :

    risque = |entrée − stop| × volume × taille_du_contrat

``taille_du_contrat`` vaut 1 sur les exchanges crypto, où le volume est déjà
exprimé dans l'actif de base ; sur MT5 elle dépend de la classe d'actif
(100 onces par lot sur l'or, 100 000 unités sur le forex).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Taille de contrat par classe d'actif chez IC Markets (compte EUR).
TAILLE_CONTRAT_MT5: dict[str, int] = {
    "metal": 100,          # XAU/XAG : 100 onces par lot
    "energy": 100,         # WTI/XTIUSD : 100 barils par lot
    "forex": 100_000,      # lot standard
    "equity": 1,           # AAPL/TSLA/NVDA/MSFT .NAS : 1 action par lot
    "equity_index": 10,    # SPX/NDX : ~10 USD par point et par lot
    "crypto": 1,           # CFD crypto MT5
}

_ACTIONS = frozenset({"AAPL", "TSLA", "NVDA", "MSFT", "GOOGL", "AMZN", "META",
                      "AMD", "NFLX", "COIN", "HOOD", "MSTR", "SPY", "QQQ",
                      "PLTR", "SHOP"})
_INDICES = frozenset({"SPX", "NDX", "DAX", "CAC40", "FTSE", "US30", "US500",
                      "NAS100"})

EUR_USD_PAR_DEFAUT = 1.155


def classe_d_actif(pair: str) -> str:
    """Classe d'actif déduite du symbole, pour choisir la taille de contrat."""
    p = (pair or "").upper()
    if p.startswith(("XAU", "XAG")):
        return "metal"
    if p.startswith(("WTI", "BRENT", "XTI", "XBR", "NGAS", "NATGAS")):
        return "energy"
    if p in _ACTIONS:
        return "equity"
    if p in _INDICES:
        return "equity_index"
    if p.startswith(("BTC", "ETH", "LTC", "XRP", "SOL", "ADA", "DOGE", "BCH",
                     "DOT", "AVAX", "MATIC", "LINK")):
        return "crypto"
    return "forex"


def taille_contrat(pair: str, bridge_type: str) -> int:
    """Multiplicateur entre le volume envoyé et le notionnel.

    Sur les exchanges crypto le volume EST déjà la quantité de sous-jacent :
    le multiplicateur vaut 1. C'est la distinction que l'ancienne table par
    paire ne pouvait pas faire, puisqu'elle ignorait le broker.
    """
    if bridge_type in ("kraken", "kraken_spot", "binance"):
        return 1
    return TAILLE_CONTRAT_MT5.get(classe_d_actif(pair), 1)


def calculer(
    pair: str, entry: float, sl: float, tp: float, volume: float,
    bridge_type: str = "mt5", eur_usd: float = EUR_USD_PAR_DEFAUT,
) -> dict[str, float] | None:
    """Risque, gain visé et R:R en euros. ``None`` si indéterminable.

    Retourne ``None`` plutôt que des zéros : un montant faux est pire qu'un
    montant absent, puisqu'il sera lu comme vrai.
    """
    try:
        entry, sl, volume = float(entry or 0), float(sl or 0), float(volume or 0)
        tp = float(tp or 0)
        eur_usd = float(eur_usd or EUR_USD_PAR_DEFAUT)
    except (TypeError, ValueError):
        return None
    if entry <= 0 or sl <= 0 or volume <= 0 or eur_usd <= 0:
        return None

    cs = taille_contrat(pair, bridge_type)
    risque_usd = abs(entry - sl) * volume * cs
    gain_usd = abs(tp - entry) * volume * cs if tp > 0 else 0.0
    if risque_usd <= 0:
        return None

    return {
        "risque_eur": round(risque_usd / eur_usd, 2),
        "gain_eur": round(gain_usd / eur_usd, 2),
        "rr": round(gain_usd / risque_usd, 2),
        "taille_contrat": cs,
        "eur_usd": eur_usd,
    }


def taux_eur_usd() -> float:
    """Taux EUR/USD courant, avec repli sur une valeur figée.

    Le repli est volontairement silencieux : une notification de trade ne
    doit jamais échouer parce qu'un taux de change est indisponible. La
    borne de vraisemblance évite qu'une valeur aberrante en base produise
    un montant absurde présenté comme vrai.
    """
    try:
        from datetime import date

        from backend.services import macro_data
        obs = macro_data.get_close_at_or_before("EURUSD=X", date.today())
        v = float((obs or {}).get("close") or 0)
        if 0.5 < v < 2.0:
            return v
    except Exception as e:
        logger.debug(f"taux_eur_usd indisponible, repli : {e}")
    return EUR_USD_PAR_DEFAUT
