"""Corrélations simples entre paires forex (groupes statiques).

Permet de prevenir le user s'il a deja une position dans un groupe correle
quand un nouveau signal arrive (ex: long EUR/USD + signal sur GBP/USD dans
le meme sens = risque concentre sur USD).
"""

# Groupes de paires tres correles (positivement).
# Si deux paires sont dans le meme groupe et meme direction attendue -> risque cumule.
_GROUPS: list[set[str]] = [
    # Groupe USD (contre les autres) : toutes les XXX/USD bougent avec les news USD
    {"EUR/USD", "GBP/USD", "AUD/USD"},
    # JPY comme quote : toutes les XXX/JPY bougent avec les flux risk-on/off
    {"USD/JPY", "EUR/JPY", "GBP/JPY"},
    # USD en base : reagissent inverse des XXX/USD
    {"USD/CHF", "USD/CAD"},
    # Metaux / safe haven
    {"XAU/USD"},
]


def correlated_pairs(pair: str) -> set[str]:
    """Retourne les paires correlees a `pair` (exclut `pair` elle-meme)."""
    result: set[str] = set()
    for group in _GROUPS:
        if pair in group:
            result.update(group)
    result.discard(pair)
    return result


def has_open_correlation(pair: str, direction: str, open_trades: list[dict]) -> list[dict]:
    """Retourne les trades ouverts correles au signal (meme direction sur paire liee)."""
    corr = correlated_pairs(pair)
    return [
        t for t in open_trades
        if t.get("pair") in corr and t.get("direction") == direction
    ]
