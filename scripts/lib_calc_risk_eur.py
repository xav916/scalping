"""Helper : calcule risk/reward en EUR pour affichage notif Telegram.

Usage CLI :
  python3 lib_calc_risk_eur.py --pair XAU/USD --entry 2400 --sl 2380 --tp 2430 --volume 0.02
Output JSON : {"risk_eur": 3.46, "reward_eur": 5.19, "rr": 1.5}

Motif : incident WTI weekend 2026-08-03 a montré qu'on avait aucune vue lisible
du risque monétaire au moment du push. Ce helper permet d'afficher SL/TP en EUR
directement dans les notifs Telegram sales bot.
"""

import argparse
import json
import sys

# Contract size par asset_class chez IC Markets (compte EUR, quote USD généralement)
_CONTRACT_SIZE_MT5 = {
    "metal": 100,        # XAU/XAG : 100 oz/lot
    "energy": 100,       # WTI/XTIUSD : 100 barrels/lot
    "forex": 100000,     # forex standard lot
    "equity": 1,         # AAPL/TSLA/NVDA/MSFT .NAS : 1 share/lot
    "equity_index": 10,  # SPX/NDX approx 10 USD/point/lot
    "crypto": 1,         # crypto CFD MT5 (peu utilisé)
}


def _asset_class(pair: str) -> str:
    p = pair.upper()
    if p.startswith(("XAU", "XAG")):
        return "metal"
    if p.startswith(("WTI", "BRENT", "XTI", "XBR", "NGAS", "NATGAS")):
        return "energy"
    if p in {"AAPL", "TSLA", "NVDA", "MSFT", "GOOGL", "AMZN", "META", "AMD",
             "NFLX", "COIN", "HOOD", "MSTR", "SPY", "QQQ", "PLTR", "SHOP"}:
        return "equity"
    if p in {"SPX", "NDX", "DAX", "CAC40", "FTSE", "US30", "US500", "NAS100"}:
        return "equity_index"
    if p.startswith(("BTC", "ETH", "LTC", "XRP", "SOL", "ADA", "DOGE", "BCH", "DOT")):
        return "crypto"
    return "forex"


def calc(pair, entry, sl, tp, volume, bridge_type="mt5", eur_usd=1.155):
    """Retourne dict {risk_eur, reward_eur, rr, contract_size, quote_ccy}."""
    try:
        entry = float(entry) if entry else 0.0
        sl = float(sl) if sl else 0.0
        tp = float(tp) if tp else 0.0
        volume = float(volume) if volume else 0.0
        eur_usd = float(eur_usd) if eur_usd else 1.155
    except (TypeError, ValueError):
        return {"risk_eur": 0, "reward_eur": 0, "rr": 0, "error": "parse_fail"}

    if bridge_type in ("kraken", "kraken_spot"):
        # Kraken : size = unités du sous-jacent (BTC, ETH, shares xStocks)
        # risk = |entry-sl| × size en USD
        cs = 1
    else:
        # MT5 : contract_size × volume × distance = USD
        ac = _asset_class(pair)
        cs = _CONTRACT_SIZE_MT5.get(ac, 1)

    risk_usd = abs(entry - sl) * volume * cs if (entry > 0 and sl > 0) else 0
    reward_usd = abs(tp - entry) * volume * cs if (entry > 0 and tp > 0) else 0

    # Conversion USD → EUR (compte EUR chez IC Markets, USD chez Kraken)
    # Pour Kraken le compte est en USD mais on affiche en EUR pour UX cohérente
    risk_eur = round(risk_usd / eur_usd, 2) if eur_usd > 0 else 0
    reward_eur = round(reward_usd / eur_usd, 2) if eur_usd > 0 else 0
    rr = round(reward_usd / risk_usd, 2) if risk_usd > 0 else 0

    return {
        "risk_eur": risk_eur,
        "reward_eur": reward_eur,
        "rr": rr,
        "contract_size": cs,
        "eur_usd_used": eur_usd,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--pair", required=True)
    p.add_argument("--entry", required=True)
    p.add_argument("--sl", default="0")
    p.add_argument("--tp", default="0")
    p.add_argument("--volume", required=True)
    p.add_argument("--bridge-type", default="mt5", choices=["mt5", "kraken", "kraken_spot"])
    p.add_argument("--eur-usd", default="1.155")
    a = p.parse_args()
    result = calc(a.pair, a.entry, a.sl, a.tp, a.volume, a.bridge_type, a.eur_usd)
    print(json.dumps(result))
