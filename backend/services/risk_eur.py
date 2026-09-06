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
    # ⛔ Ce produit est libellé dans la DEVISE DE COTATION, pas en dollars. La
    # variable s'appelait `risque_usd` et l'hypothèse était fausse dès que la
    # paire ne se termine pas par USD :
    #
    #   USD/JPY, 0,01 lot, stop à 105 pips  ->  annoncé −909,09 €
    #                                           réel        −5,82 €   (×156)
    #
    # C'est le cours USD/JPY lui-même, jamais applique. Sur EUR/GBP le montant
    # etait sous-estimé de 30 %, sur USD/CAD surestimé de 40 %. Seules les
    # paires cotées en dollars étaient justes — dont l'or, l'argent et le WTI,
    # ce qui explique que le defaut ait vecu.
    montant_quote_risque = abs(entry - sl) * volume * cs
    montant_quote_gain = abs(tp - entry) * volume * cs if tp > 0 else 0.0
    if montant_quote_risque <= 0:
        return None

    # ⚠️ Le taux n'est cherché QUE si le prix d'entrée ne suffit pas — sur
    # USD/JPY ou EUR/JPY il porte déjà la conversion. Une lecture inutile
    # ferait dépendre un message de trade d'une base qui peut manquer.
    tq = None
    _base, _quote = devises(pair)
    if _quote not in ("USD", "EUR") and _base not in ("USD", "EUR"):
        tq = taux_quote_usd(_quote)
    risque_eur = convertir_en_eur(pair, entry, montant_quote_risque, eur_usd, tq)
    gain_eur = convertir_en_eur(pair, entry, montant_quote_gain, eur_usd, tq)

    return {
        # ⚠️ `None` quand la conversion est indécidable — jamais un montant
        # approché. Un montant faux est pire qu'un montant absent : il sera
        # lu comme vrai.
        "risque_eur": None if risque_eur is None else round(risque_eur, 2),
        "gain_eur": None if gain_eur is None else round(gain_eur, 2),
        # 🔑 Le R:R, lui, reste TOUJOURS juste : numérateur et dénominateur
        # sont dans la même devise, donc elle s'annule. C'est ce qui reste
        # à dire quand les euros manquent.
        "rr": round(montant_quote_gain / montant_quote_risque, 2),
        "taille_contrat": cs,
        "eur_usd": eur_usd,
        "devise_cotation": devises(pair)[1],
    }


def devises(pair: str) -> tuple[str, str]:
    """``(base, cotation)``. Un symbole sans barre est coté en dollars —
    SPX, NDX, WTI chez IC Markets."""
    p = (pair or "").upper().strip()
    if "/" in p:
        base, _, quote = p.partition("/")
        return base.strip(), quote.strip()
    return p, "USD"


def convertir_en_eur(pair: str, entry: float, montant_quote: float,
                     eur_usd: float, taux_quote_usd: float | None = None
                     ) -> float | None:
    """Convertit un montant exprimé dans la devise de cotation, vers l'euro.

    ⛔ Rend ``None`` sur une paire croisée dont on ne sait pas convertir la
    cotation — GBP/JPY, AUD/CAD… Le prix d'entrée ne suffit alors pas, et
    inventer un taux produirait le défaut qu'on répare.

    🔑 Dans les autres cas le PRIX D'ENTRÉE porte lui-même le taux :
    sur EUR/JPY il vaut des yens par euro, donc diviser par lui donne
    directement des euros. Aucune donnée externe n'est nécessaire.
    """
    if montant_quote == 0:
        return 0.0
    base, quote = devises(pair)
    try:
        entry = float(entry or 0)
        eur_usd = float(eur_usd or 0)
    except (TypeError, ValueError):
        return None
    if eur_usd <= 0:
        return None

    if quote == "EUR":
        return montant_quote                       # déjà en euros
    if base == "EUR":
        if entry <= 0:
            return None
        return montant_quote / entry               # cotation par euro
    if quote == "USD":
        return montant_quote / eur_usd
    if base == "USD":
        if entry <= 0:
            return None
        return (montant_quote / entry) / eur_usd   # entry = USD/cotation
    if taux_quote_usd and taux_quote_usd > 0:
        return (montant_quote * taux_quote_usd) / eur_usd
    return None


# Devise de cotation → série de taux et sens de la conversion vers le dollar.
# `True` : la série cote la devise EN dollars (GBP/USD) — on multiplie.
# `False` : elle cote le dollar dans cette devise (USD/JPY) — on divise.
_SERIE_PAR_DEVISE: dict[str, tuple[str, bool]] = {
    "JPY": ("usdjpy", False),
    "CHF": ("usdchf", False),
    "CAD": ("usdcad", False),
    "GBP": ("gbpusd", True),
    "AUD": ("audusd", True),
    "NZD": ("nzdusd", True),
    "EUR": ("eurusd", True),
}


def _close_macro(symbole: str) -> float | None:
    try:
        from datetime import date

        from backend.services import macro_data
        obs = macro_data.get_close_at_or_before(symbole, date.today())
        v = float((obs or {}).get("close") or 0)
        return v if v > 0 else None
    except Exception as e:  # noqa: BLE001
        logger.debug(f"taux {symbole} indisponible : {e}")
        return None


def taux_eur_usd() -> float:
    """Taux EUR/USD courant, avec repli sur une valeur figée.

    ⛔ Cette fonction cherchait « EURUSD=X », un symbole qui n'a JAMAIS existé
    dans `macro.db` — lequel ne porte que `btc`, `dxy`, `vix`, `spx`, `tnx`. Le
    taux de toutes les notifications était donc la constante 1,155 depuis
    toujours, et le repli « exceptionnel » était permanent. La série est
    désormais collectée sous `eurusd`.

    ⚠️ Le repli reste : une notification de trade ne doit jamais échouer parce
    qu'un taux manque. Mais il se JOURNALISE en avertissement — un repli
    silencieux se lit comme un taux vivant.
    """
    v = _close_macro("eurusd")
    if v is not None and 0.5 < v < 2.0:
        return v
    logger.warning("taux_eur_usd : série « eurusd » absente ou aberrante — "
                   "repli sur la constante %.3f", EUR_USD_PAR_DEFAUT)
    return EUR_USD_PAR_DEFAUT


def taux_quote_usd(devise: str) -> float | None:
    """Combien vaut UNE unité de `devise` en dollars. ``None`` si inconnu.

    🔑 Sert aux paires CROISÉES — GBP/JPY, AUD/CAD — où le prix d'entrée ne
    porte aucun taux exploitable. ⛔ Rendre une approximation ici recréerait
    exactement le défaut qu'on répare.
    """
    d = (devise or "").upper().strip()
    if d == "USD":
        return 1.0
    entree = _SERIE_PAR_DEVISE.get(d)
    if entree is None:
        return None
    serie, en_dollars = entree
    v = _close_macro(serie)
    if v is None or v <= 0:
        return None
    return v if en_dollars else 1.0 / v
