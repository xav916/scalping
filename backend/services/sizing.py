"""Sizing dynamique du montant risque par trade.

Le bridge MT5 calcule les lots a partir de `risk_money` + specs du symbole
chez le broker (trade_tick_value, volume_step, etc.). Ce service calcule
ce `risk_money` en le modulant selon :

1. Capital actuel (realised PnL du jour inclus).
2. Base : `RISK_PER_TRADE_PCT` du capital.
3. Multiplicateur de confiance : un signal a 90/100 merite plus qu'un
   signal a 60/100. Echelle lineaire entre 0.5x et 1.5x sur la plage
   60→95 (au-dela, plafonne).
4. Drawdown-aware reducer : si le PnL realise sur les 7 derniers jours
   est negatif, on divise le risque par 2. Evite les "revenge trades"
   amplifies quand le modele sous-performe.
5. Session multiplier : l'overlap London/NY a un edge historique (60%
   du volume daily forex), la session asian est plus calme. On pondere
   0.7x-1.2x selon la fenetre, 0.0x le weekend.
6. Macro alignment : si le setup va contre le contexte macro (ex: long
   index en risk_off + VIX HIGH, short USD en DXY STRONG_UP), on
   reduit le risque. Si aligne, legere bonification.

Le but : faire travailler le capital plus fort quand le signal est fort
et le contexte favorable, et freiner quand on encaisse des pertes.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def confidence_multiplier(score: float | None) -> float:
    """Mappe un confidence_score 0-100 vers un multiplicateur de risque :
    - < 60  → 0.5x (clamp bas)
    - 60-95 → lineaire de 0.5x a 1.5x
    - >= 95 → 1.5x (clamp haut)

    Choix lineaire plutot que sigmoide : transparent, debuggable, et une
    relation plus complexe n'a pas de base statistique tant qu'on n'a
    pas 500+ trades pour calibrer."""
    if score is None:
        return 1.0
    if score < 60:
        return 0.5
    if score >= 95:
        return 1.5
    return _clamp(0.5 + (score - 60) / 35.0, 0.5, 1.5)


def recent_pnl_multiplier(days: int = 7) -> float:
    """1.0 si le PnL cumule des `days` derniers jours est >= 0,
    0.5 sinon. "Capital preservation mode" quand le modele est en
    perte recente."""
    try:
        from backend.services.trade_log_service import _DB_PATH
    except Exception:
        return 1.0

    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        with sqlite3.connect(_DB_PATH) as c:
            row = c.execute(
                "SELECT COALESCE(SUM(pnl), 0) FROM personal_trades "
                "WHERE status = 'CLOSED' AND closed_at >= ?",
                (since,),
            ).fetchone()
        pnl = float(row[0] or 0)
    except Exception as e:
        logger.debug(f"sizing: recent_pnl lookup failed: {e}")
        return 1.0
    return 1.0 if pnl >= 0 else 0.5


MAX_NOTIONAL_LEVERAGE = float(os.getenv("MAX_NOTIONAL_LEVERAGE", "5.0"))


def plafonner_notionnel(risk_money, setup, dest, capital):
    """Borne le notionnel d'une position. Retourne ``(risque, notionnel, plafond)``.

    Le dimensionnement vise un **risque** constant, pas une taille. Or le
    notionnel vaut ``risque × entrée / distance du stop`` — identité valable
    sur toutes les plateformes, la taille de contrat s'annulant entre le
    calcul du volume et celui du notionnel. Un stop serré produit donc
    mécaniquement une position énorme, sans que le risque affiché bouge.

    Le 2026-08-04, un ordre de 0,215 ETH est parti pour cette seule raison :
    403 USD de notionnel sur un compte de 103, soit 3,9×, alors que le risque
    visé n'était que de 0,66 USD.

    Le plafond est déclaré **par destination** (``max_notional_leverage``) :
    le forex MT5 à 0,1 lot atteint naturellement 3,8× sans que ce soit
    anormal, tandis que le même multiple sur un perpétuel crypto engage un
    actif d'une tout autre volatilité.

    Quand le plafond mord, c'est le **risque** qui est réduit — jamais la
    distance du stop, qui appartient au setup. Le trade est donc pris plus
    petit que visé, ce que le dict retourné rend visible.
    """
    entry = float(getattr(setup, "entry_price", 0) or 0)
    sl = float(getattr(setup, "stop_loss", 0) or 0)
    distance = abs(entry - sl)
    # `sl > 0` explicitement : un stop absent vaut 0, et `abs(entry - 0)`
    # donne une distance énorme mais non nulle. Le plafond se serait alors
    # calculé sur un stop qui n'existe pas.
    if risk_money <= 0 or entry <= 0 or sl <= 0 or distance <= 0 or not capital:
        return risk_money, None, None

    levier = MAX_NOTIONAL_LEVERAGE
    if dest is not None:
        from backend.services import destinations_registry as _reg
        d = _reg.get(getattr(dest, "destination_id", None))
        if d is not None and d.max_notional_leverage:
            levier = float(d.max_notional_leverage)

    plafond = float(capital) * levier
    notionnel = risk_money * entry / distance
    if notionnel <= plafond:
        return risk_money, round(notionnel, 2), round(plafond, 2)

    # Réduire le risque à proportion ramène le notionnel exactement au
    # plafond, la relation étant linéaire.
    reduit = round(risk_money * plafond / notionnel, 2)
    logger.warning(
        "sizing: notionnel plafonne %s -> %s (levier %sx sur capital %s) ; "
        "risque %s -> %s",
        round(notionnel, 2), round(plafond, 2), levier, round(float(capital), 2),
        risk_money, reduit,
    )
    return reduit, round(notionnel, 2), round(plafond, 2)


def compute_risk_money(setup, dest=None) -> dict:
    """Retourne un dict complet des multiplicateurs + risk_money final
    pour l'envoi au bridge et le logging.

    ``dest`` (2026-08-04) : le capital est résolu **par destination**, cf.
    ``destination_capital``. Sans ``dest``, comportement legacy inchangé
    (capital global).

    ⚠️ Si le capital d'une destination à solde interrogeable n'est pas
    disponible, ``risk_money`` vaut 0 : les clients de bridge rejettent alors
    l'ordre (``qty <= 0``). C'est délibéré — retomber sur le capital global
    reproduirait le défaut qui envoyait des ordres de 10 000 USD sur un
    compte de 103 USD.
    """
    from backend.services import destinations_registry as _registre
    from backend.services import macro_alignment, session_service
    from config.settings import RISK_PER_TRADE_PCT

    # Pourcentage propre a la destination, sinon global (2026-08-09). Kraken
    # est declare a 2 % : ses positions valaient 5,40 USD de notionnel pour un
    # plafond de 198, la ou monter le GLOBAL aurait aussi gonfle admin_live —
    # compte le plus contraint en marge, et deja sur-dimensionne sur l'or par
    # le lot minimum du courtier.
    #
    # ⚠️ Cantonne au sizing : `pair_admission_controller._r_unit_eur` garde le
    # global, car il s'en sert comme UNITE de normalisation et non comme
    # politique. L'y propager deplacerait retroactivement les seuils
    # d'admission de toutes les paires deja mesurees.
    propre = _registre.risque_par_trade_pct(getattr(dest, "destination_id", None))
    risk_pct = propre if propre is not None else RISK_PER_TRADE_PCT

    capital, capital_source = destination_capital(dest)
    if capital is None:
        return {
            "risk_money": 0.0, "base": 0.0,
            "notionnel": None, "plafond_notionnel": None,
            "notionnel_plafonne": False,
            "conf_mult": 0.0, "pnl_mult": 0.0, "session_mult": 0.0,
            "session": session_service.label(), "macro_mult": 0.0,
            "macro_reasons": [], "final_mult": 0.0,
            "capital": None, "capital_source": capital_source,
            "risk_pct": risk_pct,
        }
    base = capital * (risk_pct / 100.0)
    conf_mult = confidence_multiplier(getattr(setup, "confidence_score", None))
    pnl_mult = recent_pnl_multiplier()
    # La destination prime sur le symbole pour savoir si le marche cote 24/7 :
    # un instrument ajoute sans declaration dans ASSET_CLASS_OVERRIDES ne doit
    # pas voir son risque tombe a zero le weekend. Cf. `cote_en_continu`.
    from backend.services import destinations_registry as _reg
    session_mult = session_service.activity_multiplier(
        pair=getattr(setup, "pair", None),
        marche_continu=_reg.cote_en_continu(getattr(dest, "destination_id", None)),
    )
    session_label = session_service.label()
    direction = (
        setup.direction.value
        if hasattr(getattr(setup, "direction", None), "value")
        else str(getattr(setup, "direction", ""))
    )
    macro = macro_alignment.alignment_for(getattr(setup, "pair", ""), direction)
    macro_mult = macro["multiplier"]

    final_mult = conf_mult * pnl_mult * session_mult * macro_mult
    risk_money = round(base * final_mult, 2)

    # Plafond de notionnel : le dimensionnement vise un RISQUE constant, pas
    # une taille. Un stop serré produit donc mécaniquement une position
    # énorme. Voir `plafonner_notionnel`.
    risk_money, notionnel, plafond = plafonner_notionnel(
        risk_money, setup, dest, capital)

    return {
        "risk_money": risk_money,
        "notionnel": notionnel,
        "plafond_notionnel": plafond,
        "notionnel_plafonne": bool(
            plafond is not None and notionnel is not None
            and notionnel > plafond + 0.01),
        "base": round(base, 2),
        "conf_mult": round(conf_mult, 2),
        "pnl_mult": round(pnl_mult, 2),
        "session_mult": round(session_mult, 2),
        "session": session_label,
        "macro_mult": round(macro_mult, 2),
        "macro_reasons": macro["reasons"],
        "final_mult": round(final_mult, 2),
        "capital": capital,
        "capital_source": capital_source,
        "risk_pct": risk_pct,
    }


def raison_du_refus(sz: dict, setup) -> str:
    """Pourquoi la quantite envoyee serait nulle — nomme, jamais devine.

    Les clients crypto rejetaient sur ``qty <= 0`` avec un motif ecrit en
    dur : « qty<=0, likely sl==entry ». C'etait une conjecture, et elle etait
    fausse chaque fois que la cause venait du sizing — capital indisponible,
    ou multiplicateur de seance a zero.

    Un motif faux coute plus cher qu'un motif absent : il envoie chercher
    ailleurs. C'est exactement ce qui serait arrive a un instrument Kraken
    ajoute sans declaration dans ``ASSET_CLASS_OVERRIDES`` — on aurait cherche
    un stop colle a l'entree pendant que la cause etait la grille de seance.

    Les causes sont testees de la plus en amont a la plus en aval : sans
    capital il n'y a pas de base, sans base le multiplicateur n'explique rien.
    """
    if sz.get("capital") is None:
        return (f"capital indisponible pour la destination "
                f"({sz.get('capital_source', 'source inconnue')})")
    if not sz.get("session_mult"):
        return ("multiplicateur de séance nul — marché considéré fermé pour "
                "cette classe d'actif")
    entry = float(getattr(setup, "entry_price", 0) or 0)
    sl = float(getattr(setup, "stop_loss", 0) or 0)
    if entry <= 0 or sl <= 0 or abs(entry - sl) <= 0:
        return f"stop confondu avec l'entrée (entrée {entry}, stop {sl})"
    if not sz.get("risk_money"):
        return f"risque calculé nul (multiplicateur final {sz.get('final_mult')})"
    return "quantité nulle après arrondi du bridge"


# ─── Capital par destination (2026-08-04) ──────────────────────────────
#
# ⚠️ Jusqu'ici `compute_risk_money` sizait TOUJOURS sur le `TRADING_CAPITAL`
# global (3 000 €). Sur une destination dont le compte vaut 103 USD, cela
# produisait des ordres de ~10 000 USD de notionnel — vingt fois la capacité
# du compte. Kraken les rejetait en `invalidSize`, ce qui explique qu'aucun
# ordre n'y soit jamais passé.
#
# Les bridges MT5 s'en tiraient parce qu'ils ramènent le volume au minimum
# du broker côté bridge ; les bridges crypto, eux, envoient la quantité telle
# quelle.
#
# Principe retenu : **en cas de doute, refuser de trader**. Retomber sur le
# global reproduirait exactement le défaut — c'est la leçon de la journée,
# un repli qui élargit n'est pas un repli sûr.

_BALANCE_CACHE: dict[str, tuple[float, float]] = {}  # dest_id -> (capital, expire_at)
_BALANCE_TTL_SEC = 300.0

# Types de bridge dont le solde est interrogeable via /account. Les bridges
# MT5 gardent le capital global : leur sizing est reclampé côté bridge.
def _live_balance_types() -> frozenset[str]:
    """Dérivé du registre : `sizing="live_balance"` suffit à déclarer qu'un
    bridge doit être dimensionné sur son solde réel."""
    from backend.services.destinations_registry import bridge_types_with_live_balance
    return bridge_types_with_live_balance()


LIVE_BALANCE_BRIDGE_TYPES = _live_balance_types()

CAPITAL_UNAVAILABLE = "unavailable"


def _cache_get(dest_id: str) -> float | None:
    import time
    hit = _BALANCE_CACHE.get(dest_id)
    if hit and hit[1] > time.monotonic():
        return hit[0]
    return None


# Dernier solde connu, pour le PLAFOND DE PERTE JOURNALIERE seulement.
#
# Le cache de sizing perime en 5 min et n'est alimente que sur le chemin du
# dispatch. Mesure le 2026-09-03 juste apres deploiement : `capital_reel_connu`
# rendait `None` pour les trois comptes -- le plafond retombait donc toujours
# sur les 650 EUR de `TRADING_CAPITAL`, et le volet capital etait inerte.
#
# Une echeance SEPAREE et plus longue, parce que les deux usages n'ont pas les
# memes exigences : dimensionner un ordre demande un solde frais, opposer un
# plafond demande un solde STABLE. A 5 min, le seuil aurait oscille entre
# -19,50 et -21,58 EUR selon l'instant du signal -- un garde-fou de risque ne
# doit pas dependre de l'heure a laquelle on le regarde.
#
# ⚠️ Bornee quand meme : un solde de plusieurs heures peut ELARGIR le plafond
# a tort. Au-dela, on retombe sur la constante, qui est le seuil le plus serre.
_SOLDE_CONNU_TTL_SEC = 3600.0
_SOLDE_CONNU: dict[str, tuple[float, float]] = {}


def _cache_put(dest_id: str, capital: float) -> None:
    import time
    maintenant = time.monotonic()
    _BALANCE_CACHE[dest_id] = (capital, maintenant + _BALANCE_TTL_SEC)
    # Alimente aussi le plafond : les deux chemins (dispatch et job de fond)
    # passent ici, et aucun n'a besoin de le savoir.
    _SOLDE_CONNU[dest_id] = (capital, maintenant + _SOLDE_CONNU_TTL_SEC)


async def rafraichir_soldes_reels() -> dict[str, float | None]:
    """Interroge le solde des comptes REELS, hors du chemin du dispatch.

    Sans ce job, le solde n'etait connu que lorsqu'un setup allait jusqu'au
    dimensionnement -- donc jamais les jours ou toutes les portes refusent, et
    ce sont precisement les jours ou le plafond compte. Une logique correcte
    qu'aucun chemin n'atteint ne protege rien.

    ⚠️ La demo est ecartee : le plafond ne la vise pas, l'interroger ne
    servirait qu'a faire du bruit reseau.

    ⚠️ Ne leve jamais et n'abandonne jamais les autres comptes sur un compte
    muet : c'est le mode de defaillance qui avait bloque Kraken des mois.
    """
    resultats: dict[str, float | None] = {}
    try:
        from backend.services import bridge_destinations, destinations_registry
        cibles = [
            d for d in bridge_destinations.admin_destinations()
            if destinations_registry.is_real_money(
                getattr(d, "destination_id", None))
        ]
    except Exception as e:
        logger.warning(f"soldes reels: destinations illisibles ({e})")
        return {}

    for dest in cibles:
        dest_id = getattr(dest, "destination_id", "")
        try:
            resultats[dest_id] = await refresh_destination_capital(dest)
        except Exception as e:
            logger.warning(
                f"soldes reels[{dest_id}]: /account injoignable "
                f"({type(e).__name__}) — dernier solde connu conserve")
            resultats[dest_id] = None
    return resultats


def capital_reel_connu(dest_id: str) -> float | None:
    """Solde réel de cette destination, si le cache le connaît ENCORE.

    Exposé pour le plafond de perte journalière (2026-09-03), qui doit opposer
    la perte du jour au capital que le compte porte vraiment — pas à la
    constante `TRADING_CAPITAL`. Celle-ci valait 650 € pendant que le compte
    réel en portait 719,18 : le « 3 % » en valait 2,7, et se resserrait à
    chaque euro gagné.

    ⚠️ Retourne ``None`` quand le cache est froid ou périmé (TTL 5 min), et
    c'est volontaire : l'appelant doit alors retomber sur `TRADING_CAPITAL`,
    qui donne le seuil le plus SERRÉ. Ne pas savoir combien porte un compte ne
    doit jamais élargir son plafond.

    ⚠️ Lecture seule et sans réseau — ce plafond est interrogé à chaque signal
    et sur le chemin synchrone. Ce sont `refresh_destination_capital` (chemin
    du dispatch) et `rafraichir_soldes_reels` (job de fond) qui l'alimentent,
    tous deux via `_cache_put`.
    """
    import time
    hit = _SOLDE_CONNU.get(dest_id)
    if hit and hit[1] > time.monotonic():
        return hit[0]
    return None


async def refresh_destination_capital(dest) -> float | None:
    """Interroge ``/account`` du bridge et met le capital en cache.

    À appeler depuis le chemin async AVANT ``compute_risk_money``, qui lira
    ensuite le cache de façon synchrone. Évite un appel HTTP bloquant au
    milieu du calcul de sizing.

    Retourne le capital, ou ``None`` si indisponible (le sizing refusera
    alors de produire un ordre).
    """
    import httpx

    # Miroir de capital : c'est le solde de la destination REFLÉTÉE qu'il faut
    # rafraîchir, pas le sien. Sans ça le cache du miroir resterait vide et
    # `destination_capital` retomberait indéfiniment sur le global.
    miroir = getattr(dest, "capital_mirror", None)
    if miroir:
        from backend.services.bridge_destinations import admin_destinations

        cible = next(
            (d for d in admin_destinations()
             if getattr(d, "destination_id", None) == miroir), None
        )
        if cible is None:
            logger.warning(
                f"sizing[{getattr(dest, 'destination_id', '')}]: miroir "
                f"'{miroir}' introuvable — repli sur le capital global"
            )
            return None
        return await refresh_destination_capital(cible)

    dest_id = getattr(dest, "destination_id", "")
    cached = _cache_get(dest_id)
    if cached is not None:
        return cached
    url = (getattr(dest, "bridge_url", "") or "").rstrip("/")
    if not url:
        return None
    try:
        # Les bridges ne parlent pas le même dialecte (2026-08-06) : MT5
        # authentifie par `X-API-Key` et expose `equity`/`balance` en devise du
        # compte, là où les bridges crypto utilisent `X-Bridge-Key` et
        # `portfolio_value_usd`. Envoyer le mauvais en-tête donne un 401 lu
        # comme « solde indisponible » — donc un refus de sizing silencieux.
        est_mt5 = getattr(dest, "bridge_type", "mt5") == "mt5"
        entete = "X-API-Key" if est_mt5 else "X-Bridge-Key"
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(
                f"{url}/account",
                headers={entete: getattr(dest, "bridge_api_key", "") or ""},
            )
        if r.status_code != 200:
            logger.warning(
                f"sizing[{dest_id}]: /account HTTP {r.status_code} — sizing refusé"
            )
            return None
        corps = r.json() or {}
        if est_mt5:
            # `equity` plutôt que `balance` : c'est le capital réellement
            # disponible, positions ouvertes déduites. Dimensionner sur le
            # solde ignorerait une perte latente en cours.
            value = corps.get("equity")
            if value is None:
                value = corps.get("balance")
        elif getattr(dest, "bridge_type", "") == "ibkr":
            # ⚠️ Troisieme dialecte (2026-08-10). IBKR nomme le solde
            # `NetLiquidation` — ni `equity` (MT5), ni `portfolio_value_usd`
            # (Kraken/Binance). Lire la mauvaise cle rendrait `None`, donc un
            # refus de sizing SILENCIEUX : la route serait branchee et ne
            # traderait jamais, sans qu'aucune erreur ne le dise.
            #
            # `TotalCashValue` en repli : sur un compte cash sans position,
            # les deux coincident, mais `NetLiquidation` reste le bon concept
            # (positions ouvertes incluses).
            value = corps.get("NetLiquidation")
            if value is None:
                value = corps.get("TotalCashValue")
        else:
            # `portfolio_value_usd` est la clé commune aux bridges Kraken
            # Futures, Kraken Spot et Binance. On ne devine pas au-delà.
            value = corps.get("portfolio_value_usd")
        capital = float(value) if value is not None else 0.0
        if capital <= 0:
            logger.warning(f"sizing[{dest_id}]: solde nul ou absent — sizing refusé")
            return None
        _cache_put(dest_id, capital)
        return capital
    except Exception as e:
        logger.warning(f"sizing[{dest_id}]: /account injoignable ({type(e).__name__}) — sizing refusé")
        return None


def destination_capital(dest) -> tuple[float | None, str]:
    """Capital à utiliser pour cette destination, et sa provenance.

    Cascade :
      1. ``dest is None``            -> global (chemin legacy mono-tenant)
      2. ``dest.trading_capital``    -> surcharge explicite
      3. bridge à solde interrogeable -> cache alimenté par
         ``refresh_destination_capital``. Absent du cache -> ``None``,
         donc refus de trader.
      4. sinon                       -> global (bridges MT5)
    """
    from config.settings import TRADING_CAPITAL
    if dest is None:
        return TRADING_CAPITAL, "global"
    explicite = getattr(dest, "trading_capital", None)
    if explicite:
        return float(explicite), "destination"

    # Miroir de capital (2026-08-06) — le compte de démonstration dimensionne
    # sur le capital du compte RÉEL. Sa raison d'être est de refléter ce que le
    # réel ferait ; calculer sur son propre solde (652 € contre 415)
    # produirait des tailles différentes, donc des trades non comparables.
    #
    # Placé APRÈS la surcharge explicite (qui reste le dernier mot) et AVANT
    # toute lecture de solde propre.
    miroir = getattr(dest, "capital_mirror", None)
    if miroir:
        emprunte = _cache_get(miroir)
        if emprunte is not None:
            return emprunte, f"miroir:{miroir}"
        # Miroir indisponible : on retombe sur le global plutôt que de
        # dimensionner sur un solde qui n'est pas celui qu'on veut refléter.
        return TRADING_CAPITAL, "global"
    if getattr(dest, "bridge_type", "mt5") in LIVE_BALANCE_BRIDGE_TYPES:
        cached = _cache_get(getattr(dest, "destination_id", ""))
        if cached is None:
            return None, CAPITAL_UNAVAILABLE
        return cached, "live"

    # MT5 : solde réel si connu, global sinon (2026-08-06).
    #
    # ⚠️ Repli VOLONTAIRE, contrairement aux bridges crypto ci-dessus qui
    # refusent. La différence est de nature : pour un compte crypto, le solde
    # EST le capital et l'ignorer n'a pas de sens ; pour MT5 il existe un
    # capital configuré, historiquement utilisé, qui reste une réponse
    # acceptable. Refuser ici transformerait un `/account` momentanément
    # injoignable en arrêt total du trading — le mode de défaillance qui a
    # bloqué Kraken pendant des mois.
    #
    # Le sur-dimensionnement que ce repli peut produire est rattrapé en aval
    # par `_fit_volume_to_free_margin` côté bridge, qui réduit le volume à ce
    # que la marge autorise réellement.
    #
    # Motivation : `TRADING_CAPITAL` valait 3000 € quand le compte réel en
    # contenait 540 — le sizing calculait sur 5,5× le capital disponible.
    cached = _cache_get(getattr(dest, "destination_id", ""))
    if cached is not None:
        return cached, "live"
    return TRADING_CAPITAL, "global"
