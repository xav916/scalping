"""Intégration avec le bridge MT5 local (tourne sur le PC Windows de l'user).

Le bridge tourne en loopback sur le PC et est joignable depuis l'EC2 via
Tailscale (ex: http://100.122.188.8:8787). Tant que le bridge tourne en
PAPER_MODE, AUCUN ordre réel n'est envoyé à MT5 — cet appel sert juste
à tracer les setups côté utilisateur.

Sécurité
- Filtre strict : confidence_score ≥ MT5_BRIDGE_MIN_CONFIDENCE (barrière numérique
  dédiée à l'auto-exec, décorrélée du verdict TAKE/WAIT/SKIP utilisé par
  Telegram/UI). Le gate TAKE historique filtrait trop — le scoring de base
  atteint rarement 75, ce qui produisait 0 auto-exec en pratique.
- Dedup in-memory (date, pair, direction, entry arrondi)
- Timeout court (5s) pour ne pas bloquer le cycle d'analyse si le bridge
  est down (PC éteint, Tailscale coupé)
- Best-effort : toute erreur est loggée et ignorée, jamais propagée
"""

import asyncio
import logging
import os
import time
from datetime import date, datetime, timezone

import httpx

# Toggle (2026-06-29) — calque sur BINANCE_RESPECT_VERDICT.
# Quand `MT5_BRIDGE_LIVE_RESPECT_VERDICT=false`, le bridge admin_live ignore
# les verdict_blockers / geopolitical_veto / macro_veto et laisse passer
# le setup vers les autres checks (min_confidence, market hours, sl_too_close…).
# Découvert post-audit : la stack soft veto met massivement XAU/WTI en SKIP,
# ce qui privait admin_live (IC Markets Live) de ses paires gagnantes.
# Les autres destinations (admin_legacy, user:N) continuent à respecter le verdict.
RESPECT_VERDICT_LIVE = os.getenv(
    "MT5_BRIDGE_LIVE_RESPECT_VERDICT", "true"
).strip().lower() in ("true", "1", "yes")

# Toggle (2026-07-03) — même pattern que LIVE, appliqué à toutes les destinations
# user:N (Premium multi-tenant). Quand `MT5_BRIDGE_USER_RESPECT_VERDICT=false`,
# les user destinations ignorent verdict_blockers / geopolitical_veto / macro_veto.
# Motivé par le constat 2026-07-03 : Cédric (user:2) recevait 100+ pushes/jour
# avant 30/06, puis 0 push depuis à cause des verdict SKIP massifs sur XAU/WTI/EUR.
# admin_legacy garde le comportement strict (mais il est off en prod).
RESPECT_VERDICT_USER = os.getenv(
    "MT5_BRIDGE_USER_RESPECT_VERDICT", "true"
).strip().lower() in ("true", "1", "yes")

# Whitelist par destination (2026-06-30) — opt-in restrictif.
# Quand l'env var `MT5_BRIDGE_LIVE_WHITELIST_PAIRS` est non-vide, seules les
# pairs listées peuvent être pushees vers admin_live. Toute autre pair est
# rejetee avec reason_code "pair_not_whitelisted".
# Inversion de paradigme : opt-in plutot qu'opt-out. Empeche toute activation
# manuelle imprudente de nouvelles pairs en Live.
LIVE_WHITELIST_PAIRS = frozenset(
    p.strip().upper()
    for p in os.getenv("MT5_BRIDGE_LIVE_WHITELIST_PAIRS", "").split(",")
    if p.strip()
)

# Whitelist par destination (2026-07-29) — même pattern que LIVE_WHITELIST_PAIRS,
# étendu à admin_legacy (Demo). Permet d'aligner Demo sur Live comme miroir
# pour tester des variantes avant promotion vers l'argent réel. Vide = pas de
# whitelist (comportement stars-only historique de admin_legacy).
LEGACY_WHITELIST_PAIRS = frozenset(
    p.strip().upper()
    for p in os.getenv("MT5_BRIDGE_LEGACY_WHITELIST_PAIRS", "").split(",")
    if p.strip()
)

from backend.services.market_hours import is_market_open_for_destination
from backend.services.shadow_v2_core_long import SHADOW_PAIRS as _STAR_PAIRS
from config.settings import (
    MT5_BRIDGE_ENABLED,
    MT5_BRIDGE_URL,
    MT5_BRIDGE_API_KEY,
    MT5_BRIDGE_MIN_CONFIDENCE,
    MT5_BRIDGE_LOTS,
    MT5_BRIDGE_ALLOWED_ASSET_CLASSES,
    MT5_BRIDGE_MIN_SL_DISTANCE_PCT,
    MT5_BRIDGE_MIN_SL_DISTANCE_PCT_PER_CLASS,
    MT5_BRIDGE_MAX_POSITIONS_PER_PAIR,
    MT5_BRIDGE_BLOCKED_DIRECTIONS,
    MT5_BRIDGE_BLOCKED_PAIRS,
    MT5_BRIDGE_AVOID_HOURS_UTC,
    MT5_BRIDGE_ALLOWED_PATTERNS,
    SILENT_DROPS_LOG_ENABLED,
    TRADING_CAPITAL,
    RISK_PER_TRADE_PCT,
    asset_class_for,
)

logger = logging.getLogger(__name__)

# Dedup in-memory : même setup dans la journée = pas de re-push.
# Clé : (date_iso, pair, direction, entry_arrondi_5dp).
_sent_setups_today: set[tuple[str, str, str, str]] = set()

# Filtre auto-exec : on n'envoie au bridge MT5 que les setups dont la paire
# fait partie du portefeuille stars Phase 4 (XAU/XAG/WTI/ETH/XLI/XLK).
# Cohérent avec le filtre Telegram. XLI/XLK ne sont pas dans WATCHED_PAIRS
# côté V1 et n'apparaîtront jamais ici en pratique.
_STAR_PAIRS_SET: frozenset[str] = frozenset(_STAR_PAIRS)


def is_configured() -> bool:
    return bool(MT5_BRIDGE_ENABLED and MT5_BRIDGE_URL and MT5_BRIDGE_API_KEY)


def _direction_value(setup) -> str:
    d = setup.direction
    return d.value if hasattr(d, "value") else str(d)


def _pattern_value(setup) -> str | None:
    """Nom du pattern détecté, en lowercase, ou None si indéterminable.

    Le setup porte un ``PatternDetection`` dont le champ ``pattern`` est un
    ``PatternType``. Les deux niveaux sont optionnels selon la provenance du
    setup (tests, replays), d'où les gardes.
    """
    try:
        detection = getattr(setup, "pattern", None)
        if detection is None:
            return None
        p = getattr(detection, "pattern", detection)
        value = p.value if hasattr(p, "value") else str(p)
        return value.lower() if value else None
    except Exception:
        return None


def _dedup_key(setup, dest_id: str = "admin_legacy") -> tuple[str, str, str, str, str]:
    """Clé de dedup étendue avec ``dest_id`` pour le multi-tenant routing.

    L'ordre est ``(date, pair, direction, entry, dest_id)`` — pair en
    position [1] est figé pour ne pas casser les tests legacy qui font
    ``k[0]==today and k[1]==pair``. ``dest_id`` en queue permet à plusieurs
    destinations de pousser le même setup sans collision.
    """
    return (
        date.today().isoformat(),
        setup.pair,
        _direction_value(setup),
        f"{setup.entry_price:.5f}",
        dest_id,
    )


def _cleanup_old_keys() -> None:
    """Purge les entrées des jours précédents."""
    today = date.today().isoformat()
    for key in list(_sent_setups_today):
        if key[0] != today:
            _sent_setups_today.discard(key)


def _min_sl_distance_pct_for(pair: str) -> float:
    """Retourne le seuil min SL distance % applicable à cette pair.

    Priorité : dict per-class (avec cas spécial `forex_jpy` pour les pairs
    avec JPY comme quote/base) > fallback legacy MT5_BRIDGE_MIN_SL_DISTANCE_PCT.
    """
    cfg = MT5_BRIDGE_MIN_SL_DISTANCE_PCT_PER_CLASS or {}
    upper = (pair or "").upper()
    # Pairs JPY ont un pip size 10x plus grand → seuil dédié
    if "JPY" in upper:
        if "forex_jpy" in cfg:
            return float(cfg["forex_jpy"])
    asset_class = asset_class_for(pair)
    # Mapping asset_class → clé du dict. 'forex' → 'forex_major' pour
    # différencier des JPY pairs déjà traitées au-dessus.
    key_map = {
        "forex": "forex_major",
        "metal": "metal",
        "equity_index": "equity_index",
        "crypto": "crypto",
        "energy": "energy",
    }
    key = key_map.get(asset_class)
    if key and key in cfg:
        return float(cfg[key])
    return MT5_BRIDGE_MIN_SL_DISTANCE_PCT


def _max_positions_for_pair(pair: str) -> int:
    """Cap de positions simultanées pour cette pair, via asset class."""
    cfg = MT5_BRIDGE_MAX_POSITIONS_PER_PAIR or {}
    asset_class = asset_class_for(pair)
    if asset_class in cfg:
        return int(cfg[asset_class])
    return 2  # défaut générique


def _count_open_trades_for_pair(pair: str) -> int:
    """Compte les trades auto encore OPEN pour cette pair (source : DB
    locale personal_trades). Évite un round-trip bridge."""
    try:
        import sqlite3
        from backend.services.trade_log_service import _DB_PATH
        with sqlite3.connect(_DB_PATH) as c:
            row = c.execute(
                """
                SELECT COUNT(*) FROM personal_trades
                 WHERE is_auto = 1 AND status = 'OPEN' AND pair = ?
                """,
                (pair,),
            ).fetchone()
        return int(row[0]) if row else 0
    except Exception as e:
        logger.debug(f"mt5_bridge: count_open_trades_for_pair({pair}) failed: {e}")
        return 0


def _duree_detention_pire_cas() -> float | None:
    """Borne supérieure de la durée de détention, en heures.

    Utilisée pour le coût de portage tant qu'aucune médiane n'est mesurable.
    La détention ne peut pas dépasser le délai de sortie du système, donc cette
    valeur majore le portage réel — un trade qui passe la porte de coût ici
    passerait *a fortiori* avec la vraie médiane.

    ⚠️ Ne JAMAIS mettre une valeur inférieure au délai de sortie : ce serait
    sous-estimer les frais et laisser passer des trades non rentables, soit
    exactement ce que la porte de coût existe pour empêcher.

    Rendre `None` restaure l'ancien comportement — portage incalculable, donc
    refus de tout argent réel sur les routes à funding.
    """
    try:
        from config.settings import HOLDING_WORST_CASE_HOURS
        return float(HOLDING_WORST_CASE_HOURS) if HOLDING_WORST_CASE_HOURS else None
    except Exception:
        return 96.0


def _cost_rejection(setup, dest) -> str | None:
    """Refuse un signal dont les frais consomment plus de 30 % de l'edge brut.

    Extraite de `_check_rejection` pour être testable sans base ni réseau :
    les portes d'admission et de whitelist qui la précèdent lisent la base,
    et un test unitaire ne les atteindrait jamais.

    Une destination qui ne déclare ni `cost_model` ni `expected_edge_r`
    garde exactement son comportement d'avant le 2026-08-04. En revanche,
    `exceeds_edge` garantit qu'un edge mesuré à zéro ou négatif bloque
    TOUJOURS : une destination qui déclare `expected_edge_r=0.0` sans
    `cost_model` ne doit donc pas s'échapper ici — c'est exactement le cas
    que cette porte existe pour attraper.
    """
    if dest is None:
        return None
    modele = getattr(dest, "cost_model", None)
    edge = getattr(dest, "expected_edge_r", None)
    if modele is None and edge is None:
        return None

    # Jeton de dérogation (2026-08-06) — cf. `_jeton_derogation_restant`.
    # Restreint aux routes MT5 : la porte de coût de Kraken repose sur des
    # frais 10× supérieurs et sur un portage, l'ouvrir par effet de bord
    # ferait passer des trades crypto non rentables.
    if getattr(dest, "bridge_type", "mt5") == "mt5" and _jeton_derogation_restant():
        return None

    from backend.services.cost_model import cost_in_r, exceeds_edge

    risk_money = None
    try:
        from backend.services.sizing import compute_risk_money

        risk_money = compute_risk_money(setup, dest).get("risk_money")
    except Exception as e:
        # Sizing indisponible : `risk_money` reste None. `cost_in_r` renverra
        # None si une composante fixe est déclarée, et `exceeds_edge` bloquera
        # l'argent réel — jamais l'inverse.
        logger.debug(
            f"_cost_rejection: sizing indisponible pour {getattr(setup, 'pair', '?')} — {e}"
        )
        risk_money = None

    cout_r = None
    if modele is not None:
        cout_r = cost_in_r(
            entry=getattr(setup, "entry_price", 0) or 0,
            stop_loss=getattr(setup, "stop_loss", 0) or 0,
            model=modele,
            risk_money=risk_money,
        )

    # Coût de portage (2026-08-05). N'existe qu'à horizon long : une position
    # de scalping ne traverse aucune échéance de funding.
    #
    # La durée de détention attendue n'est pas connue tant qu'aucun
    # échantillon propre postérieur au 2026-08-04 n'existe. Elle vaut donc
    # `None`, ce qui rend le coût total non calculable — et `exceeds_edge`
    # bloque alors l'argent réel sans bloquer l'observation. C'est le
    # comportement voulu : ces routes restent en état TELEGRAM.
    if modele is not None and getattr(modele, "funding_interval_hours", 0.0) > 0:
        from backend.services.horizon import is_long as _is_long

        if _is_long(getattr(setup, "horizon", None)):
            from backend.services.cost_model import (
                holding_cost_in_r, median_holding_hours,
            )
            from backend.services.kraken_funding_scoring import (
                get_funding_rate_for_pair,
            )

            systeme = getattr(setup, "shadow_system_id", None)
            duree = median_holding_hours(systeme) if systeme else None

            # Repli PIRE CAS (2026-08-06) — remplace « incalculable donc refus ».
            #
            # La médiane exige 30 setups résolus depuis le 2026-08-05. Mesuré
            # ce jour-là : XAU 4h en avait 2, WTI 4h 1, et les systèmes crypto
            # journaliers ZÉRO. À un setup par jour, chacun mettant des jours à
            # se résoudre, la route Kraken restait fermée **un à deux mois**.
            #
            # Or la borne supérieure suffit à trancher : la détention ne peut
            # pas dépasser le délai de sortie. Surestimer le portage ne peut
            # que **refuser** un trade marginal, jamais en laisser passer un
            # mauvais — c'est fail-SAFE, là où l'ancien comportement était
            # fail-closed-à-vie.
            #
            # Vérifié le 2026-08-06 aux taux de funding réels : au pire cas
            # (96 h), un setup crypto journalier à 7,69 % de stop — la médiane
            # observée — consomme 24,8 % de l'edge sur BTC et 19,1 % sur ETH,
            # sous le plafond de 30 %. Ce qui échoue même au pire cas mérite
            # d'être refusé.
            if duree is None:
                duree = _duree_detention_pire_cas()

            portage = holding_cost_in_r(
                entry=getattr(setup, "entry_price", 0) or 0,
                stop_loss=getattr(setup, "stop_loss", 0) or 0,
                rate_per_interval=get_funding_rate_for_pair(getattr(setup, "pair", "")),
                interval_hours=float(modele.funding_interval_hours),
                holding_hours=duree,
            )
            # Un coût partiellement calculable rend le coût TOTAL non
            # calculable, jamais la seule composante connue : ni un portage
            # non calculable (`portage is None`) ne doit ignorer un coût de
            # base connu, ni un coût de base non calculable (`cout_r is
            # None` — composante fixe déclarée mais risque en devise
            # inconnu) ne doit se voir remplacé par zéro et ne facturer que
            # le portage.
            cout_r = None if (portage is None or cout_r is None) else cout_r + portage

    if exceeds_edge(
        cout_r,
        edge,
        auto_exec=bool(getattr(dest, "auto_exec_enabled", False)),
    ):
        return "fees_exceed_edge"
    return None


def _horizon_rejection(setup, dest) -> str | None:
    """Refuse un setup dont l'horizon d'analyse n'est pas servi par la route.

    Extraite comme `_cost_rejection` pour être testable sans base ni réseau.

    Une route dimensionnée pour le scalping et une route dimensionnée pour la
    détention n'ont ni le même sizing, ni les mêmes stops, ni les mêmes frais.
    Router un setup 4h vers MT5 enverrait un ordre pensé pour une autre
    échelle de temps.

    `dest.allowed_horizons is None` ⇒ aucun filtre, comportement d'avant le
    2026-08-05. Sinon **fail-closed** : horizon absent ou inconnu = refus.
    """
    if dest is None:
        return None
    admis = getattr(dest, "allowed_horizons", None)
    if not admis:
        return None

    from backend.services.horizon import normalize as _normalize_horizon

    h = _normalize_horizon(getattr(setup, "horizon", None))
    if h is None or h not in admis:
        return "horizon_not_allowed"
    return None


def _now_utc():
    """Horloge isolée pour que les portes temporelles soient testables."""
    from datetime import datetime as _dt, timezone as _tz

    return _dt.now(_tz.utc)


def _event_rejection(setup, dest) -> str | None:
    """Refuse une détention longue qui traverserait un événement connu.

    Principe : à horizon long, un veto qui réduit la taille ne suffit plus.
    Un événement connu à l'avance et tombant pendant la détention doit
    empêcher l'ouverture, puisqu'on ne peut plus sortir avant.

    Ne s'applique qu'aux horizons longs : en scalping la position se ferme
    avant l'événement, et les vetos doux existants continuent de jouer au
    scoring.
    """
    from backend.services.horizon import is_long as _is_long

    if not _is_long(getattr(setup, "horizon", None)):
        return None
    pair = getattr(setup, "pair", "") or ""

    # 1. Earnings — la publication tombe pendant la détention.
    try:
        from backend.services import earnings_veto

        if earnings_veto.blocks_at_long_horizon(pair, now=_now_utc()):
            return "earnings_blackout"
    except Exception as e:
        logger.debug(f"_event_rejection earnings {pair}: {e}")

    # 2. Gap de week-end — généralisation du gel énergie du vendredi
    #    (incident 2026-08-03 : 2 positions WTI tenues 3 nuits, SL à 83,15
    #    exécuté à 79,57 au gap de réouverture, −20,75 € au lieu de −4 à −5).
    #    Une détention ouverte vendredi soir franchit la clôture par
    #    construction, quelle que soit la classe d'actif qui ferme.
    #    Interrupteur dédié (WEEKEND_HOLD_BLOCK_ENABLED), indépendant du
    #    NO_FRIDAY_LATE_OPEN_ENERGY_ENABLED du gel énergie préexistant — les
    #    deux règles coexistent et se coupent séparément.
    try:
        from config.settings import (
            WEEKEND_HOLD_BLOCK_ENABLED,
            NO_FRIDAY_LATE_OPEN_ENERGY_HOUR_UTC,
            asset_class_for as _acf,
        )
    except Exception as e:
        # Classification indisponible : impossible de distinguer la crypto
        # (jamais gelée) du reste. Deviner une classe bloquerait des
        # positions crypto à tort — on ne bloque pas plutôt que de deviner.
        logger.debug(f"_event_rejection weekend gate indisponible {pair}: {e}")
        return None

    if not WEEKEND_HOLD_BLOCK_ENABLED:
        return None

    if _acf(pair) != "crypto":
        # Le marché crypto ne ferme pas : pas de gap de réouverture.
        maintenant = _now_utc()
        if maintenant.weekday() == 4 and maintenant.hour >= NO_FRIDAY_LATE_OPEN_ENERGY_HOUR_UTC:
            return "weekend_hold_blocked"
    return None


def _check_rejection(setup, dest=None) -> str | None:
    """Retourne None si le setup peut être pushé, sinon un reason_code parmi
    ceux définis dans `rejection_service.REASON_LABELS_FR`. Seuls les cas qui
    représentent un "ordre perdu" sont loggés — pas les early-returns purement
    techniques (bridge non configuré, dedup, etc.).

    Si ``dest`` (``BridgeConfig``) est fourni, utilise ``dest.min_confidence``
    en remplacement du ``MT5_BRIDGE_MIN_CONFIDENCE`` global et skip le check
    ``is_configured()`` (la résolution garantit déjà la config). Sans ``dest``,
    comportement legacy mono-tenant inchangé.
    """
    if dest is None and not is_configured():
        return "_not_configured"  # privé, non enregistré
    # Per-user excluded_pairs (Cédric & futurs clients Premium avec garde-fou
    # sur les paires non-validées). Court-circuit avant tous les autres checks
    # car c'est une décision policy explicite, pas un état système.
    if dest is not None:
        excluded = getattr(dest, "excluded_pairs", None) or frozenset()
        if setup.pair in excluded:
            return "_user_excluded_pair"  # privé, non enregistré
    # Source de vérité pour l'éligibilité auto-exec : pair_admission_controller
    # (= state machine pair × direction). Migration douce : si (pair, direction)
    # n'a JAMAIS été enregistrée dans le controller (= row absente, pré-backfill
    # ou test patch), fallback sur la liste hardcodée _STAR_PAIRS_SET legacy.
    setup_direction = getattr(setup, "direction", None)
    if hasattr(setup_direction, "value"):
        setup_direction = setup_direction.value
    # Pour le filtre stars-only fallback, on inclut aussi les extras de cette
    # destination (cas Live IC Markets €100 : EUR/USD permis en plus des stars).
    extras = getattr(dest, "extra_pairs_allowed", None) or frozenset() if dest else frozenset()
    allowed_pairs_for_dest = _STAR_PAIRS_SET | extras
    # Destination-aware admission (2026-07-29) : chaque destination peut
    # avoir son propre état par (pair, direction). Ex : XAU/USD sell peut
    # être AUTO_EXEC sur admin_legacy et TELEGRAM sur admin_live pendant
    # une phase de validation Demo avant promotion Live.
    dest_id_for_pac = getattr(dest, "destination_id", None) if dest else None
    try:
        from backend.services import pair_admission_controller
        if pair_admission_controller.has_explicit_state(setup.pair, setup_direction, dest_id_for_pac):
            if not pair_admission_controller.is_auto_exec_eligible(setup.pair, setup_direction, dest_id_for_pac):
                return "_not_admitted"
        else:
            if setup.pair not in allowed_pairs_for_dest:
                return "_not_a_star"
    except Exception as e:
        logger.debug(f"mt5_bridge: pair_admission_controller fallback: {e}")
        if setup.pair not in allowed_pairs_for_dest:
            return "_not_a_star"  # privé : filtre auto-exec stars-only legacy
    # Blocklist surgical : retire un pair sans toucher au scoring/Telegram.
    # Cf. MT5_BRIDGE_BLOCKED_PAIRS dans config/settings.py.
    #
    # ⚠️ Restreinte aux bridges MT5 depuis le 2026-08-08. Elle bloquait TOUTES
    # les destinations, Kraken compris — alors que son motif est purement
    # Pepperstone : `INVALID_VOLUME` (retcode 10014) sur SOL/ADA dont le
    # `volume_step` vaut 0,1 chez ce courtier, contre 0,01 pour BTC/ETH.
    #
    # Chez Kraken les specs n'ont rien à voir : `contractValueTradePrecision`
    # vaut 2 pour PF_SOLUSD et 0 pour PF_XRPUSD, et le dimensionnement a été
    # vérifié valide le 2026-08-08. **Un garde-fou d'un courtier interdisait
    # un autre courtier** — 61 refus XRP et 48 SOL le seul 2026-08-08, dont
    # l'unique setup journalier produit ce jour-là.
    #
    # Le correctif était déjà annoncé dans la fiche de juin : « pause par
    # bridge plutôt que globale ». Le nom même de la variable le disait.
    if (getattr(dest, "bridge_type", "mt5") == "mt5"
            and setup.pair.upper() in MT5_BRIDGE_BLOCKED_PAIRS):
        return "pair_blocked"
    # Whitelist par destination (2026-06-30 admin_live, 2026-07-29 admin_legacy).
    # Opt-in strict : si WHITELIST_PAIRS non-vide pour la destination, seules ces
    # pairs passent. Reasoning : empêche activation involontaire de nouvelles
    # pairs en argent réel (Live) ou en shadow test (Legacy aligné Live).
    if dest is not None:
        dest_id_wl = getattr(dest, "destination_id", None)
        if (
            LIVE_WHITELIST_PAIRS
            and dest_id_wl == "admin_live"
            and setup.pair.upper() not in LIVE_WHITELIST_PAIRS
        ):
            return "pair_not_whitelisted"
        if (
            LEGACY_WHITELIST_PAIRS
            and dest_id_wl == "admin_legacy"
            and setup.pair.upper() not in LEGACY_WHITELIST_PAIRS
        ):
            return "pair_not_whitelisted"
    # Auto-régulateur PnL : pause auto par pair quand sum_pnl < seuil sur
    # fenêtre glissante. Couvre le saignement chronique (cas XAG diffus).
    try:
        from backend.services import pair_pnl_regulator
        if pair_pnl_regulator.is_paused(setup.pair):
            return "pair_auto_paused"
    except Exception as e:
        logger.debug(f"mt5_bridge: pair_pnl_regulator check failed: {e}")
    try:
        from backend.services import kill_switch
        # Passe le pair pour que les pauses per-pair (rafale chirurgicale)
        # soient prises en compte en plus des triggers globaux.
        if kill_switch.is_active(pair=setup.pair):
            # Sub-typing pour traçabilité dans les logs/rejections
            if kill_switch.is_pair_rafale_paused(setup.pair)[0]:
                return "kill_switch_pair_paused"
            return "kill_switch"
    except Exception as e:
        logger.debug(f"mt5_bridge: kill_switch check failed: {e}")
    try:
        from backend.services import event_blackout
        bo = event_blackout.is_blackout_for(setup.pair)
        if bo["active"]:
            logger.info(
                f"mt5_bridge: blackout event pour {setup.pair} — {bo['reason']}"
            )
            return "event_blackout"
    except Exception as e:
        logger.debug(f"mt5_bridge: event_blackout check failed: {e}")
    if getattr(setup, "is_simulated", False):
        return "simulated_data"
    blockers = getattr(setup, "verdict_blockers", None)
    if blockers:
        # Distinction par type de veto pour observabilité dashboard.
        # L'ordre des prefix est stable car les hooks scoring ajoutent
        # toujours le même libellé : "Macro veto:" / "Geopolitical veto:".
        first = blockers[0] if blockers else ""
        if first.startswith("Geopolitical veto:"):
            rejection_code = "geopolitical_veto"
        elif first.startswith("Macro veto:"):
            rejection_code = "macro_veto"
        else:
            rejection_code = "verdict_blocker"
        # Bypass conditionnel selon la destination :
        #   admin_live → MT5_BRIDGE_LIVE_RESPECT_VERDICT
        #   user:N     → MT5_BRIDGE_USER_RESPECT_VERDICT
        # admin_legacy garde toujours le comportement strict.
        dest_id = getattr(dest, "destination_id", "") if dest is not None else ""
        bypass = (
            (dest_id == "admin_live" and not RESPECT_VERDICT_LIVE)
            or (dest_id.startswith("user:") and not RESPECT_VERDICT_USER)
        )
        if dest is not None and bypass:
            toggle_name = (
                "MT5_BRIDGE_LIVE_RESPECT_VERDICT"
                if dest_id == "admin_live"
                else "MT5_BRIDGE_USER_RESPECT_VERDICT"
            )
            logger.info(
                f"mt5_bridge[{dest_id}]: bypass {rejection_code} pour {setup.pair} "
                f"({toggle_name}=false, blockers={blockers[:2]})"
            )
        else:
            return rejection_code
    dest_id_for_hours = getattr(dest, "destination_id", "") if dest is not None else ""
    if not is_market_open_for_destination(setup.pair, dest_id_for_hours):
        return "market_closed"
    # No-weekend-hold energy : bloque les nouveaux pushes energy (WTI/Brent/NatGas)
    # vendredi après NO_FRIDAY_LATE_OPEN_ENERGY_HOUR_UTC (défaut 18h UTC = 20h Paris).
    # Motif : incident 2026-08-03 → 2 positions WTI Live tenues 3 nuits weekend, SL
    # défini à 83.15/83.67 mais gap réouverture dimanche a exécuté à 79.57/79.59
    # (slippage -4 USD/ticket, perte totale €20.75 au lieu de €4-5 attendus).
    try:
        from config.settings import (
            NO_FRIDAY_LATE_OPEN_ENERGY_ENABLED,
            NO_FRIDAY_LATE_OPEN_ENERGY_HOUR_UTC,
            asset_class_for as _acf,
        )
    except Exception:
        NO_FRIDAY_LATE_OPEN_ENERGY_ENABLED = False
        NO_FRIDAY_LATE_OPEN_ENERGY_HOUR_UTC = 18
    if NO_FRIDAY_LATE_OPEN_ENERGY_ENABLED and _acf(setup.pair) == "energy":
        from datetime import datetime as _dt, timezone as _tz
        _now = _dt.now(_tz.utc)
        if _now.weekday() == 4 and _now.hour >= NO_FRIDAY_LATE_OPEN_ENERGY_HOUR_UTC:
            return "energy_pre_weekend_freeze"
    # Validation tick pre-push : fraîcheur + spread + cohérence prix.
    # Best-effort : si le bridge n'a pas /tick ou est injoignable, None → on continue.
    # Uniquement pour les destinations admin avec bridge_url (pas les EA queue users).
    if dest is not None and getattr(dest, "bridge_url", "") and getattr(dest, "user_id", -1) is None:
        from backend.services.bridge_tick_validator import validate_tick_pre_push
        tick_rejection = validate_tick_pre_push(dest, setup)
        if tick_rejection:
            return tick_rejection
    entry = getattr(setup, "entry_price", 0) or 0
    sl = getattr(setup, "stop_loss", 0) or 0
    if entry > 0 and sl > 0:
        sl_pct = abs(entry - sl) / entry * 100
        min_pct = _min_sl_distance_pct_for(setup.pair)
        if sl_pct < min_pct:
            return "sl_too_close"
    score = getattr(setup, "confidence_score", None) or 0
    min_conf = dest.min_confidence if dest is not None else MT5_BRIDGE_MIN_CONFIDENCE
    if score < min_conf:
        return "below_confidence"
    # Porte d'horizon (2026-08-05). Placée TÔT, à l'inverse de la porte de
    # coût qui est en dernier : une appartenance à un frozenset ne coûte
    # rien, là où la porte de coût appelle le sizing, qui peut interroger le
    # solde du bridge en HTTP. Inutile de payer ce prix pour un signal qui
    # n'est de toute façon pas à la bonne échelle de temps.
    horizon_reason = _horizon_rejection(setup, dest)
    if horizon_reason:
        return horizon_reason
    # Portes événementielles (2026-08-05). Après l'horizon — inutile
    # d'interroger le calendrier earnings pour un setup que la route ne sert
    # pas — et avant la porte de coût, qui est la plus chère.
    event_reason = _event_rejection(setup, dest)
    if event_reason:
        return event_reason
    # Whitelist de patterns (2026-08-04). S'ajoute au seuil de confidence,
    # ne le remplace pas — cf. MT5_BRIDGE_ALLOWED_PATTERNS dans settings.
    # Sur 100 657 trades suivis, `range_bounce_up/down` fait +0,129 R/trade
    # là où le seuil de confidence seul fait +0,030 pour 64 % du flux écarté.
    #
    # Pattern indéterminable alors que la whitelist est active ⇒ on bloque.
    # Fail-closed volontaire : la whitelist est un opt-in explicite, et
    # `signal_pattern` est porté dans les details de la rejection, donc une
    # vague de blocages à `None` reste diagnosticable au dashboard.
    # Per-destination depuis le 2026-08-04 : `dest.allowed_patterns` à None
    # hérite du global, à frozenset() désactive le filtre pour cette seule
    # destination. Permet de garder `range_bounce` sur l'argent réel MT5 tout
    # en ouvrant une destination d'observation.
    allowed_patterns = MT5_BRIDGE_ALLOWED_PATTERNS
    if dest is not None and getattr(dest, "allowed_patterns", None) is not None:
        allowed_patterns = dest.allowed_patterns
    if allowed_patterns and not _jeton_derogation_restant():
        if _pattern_value(setup) not in allowed_patterns:
            return "pattern_not_allowed"
    # Filtre direction par pair (diagnostic 2026-04-24 : les BUY ont 18%
    # winrate vs 42% pour les SELL sur notre dataset post-fix pipeline).
    # Env `MT5_BRIDGE_BLOCKED_DIRECTIONS=PAIR:dir,*:dir,...`.
    direction = _direction_value(setup).lower()
    pair_upper = setup.pair.upper()
    if (pair_upper, direction) in MT5_BRIDGE_BLOCKED_DIRECTIONS:
        return "direction_blocked_for_pair"
    if ("*", direction) in MT5_BRIDGE_BLOCKED_DIRECTIONS:
        return "direction_blocked_global"
    # Filtre session : skip les heures UTC qui saignent (diag : session
    # NY pm 17-21 UTC = 23% winrate, -186€ sur 17 trades).
    if MT5_BRIDGE_AVOID_HOURS_UTC:
        current_hour_utc = datetime.now(timezone.utc).hour
        if current_hour_utc in MT5_BRIDGE_AVOID_HOURS_UTC:
            return "hour_in_avoid_list"
    # Cap par pair : forcer la diversification. Le backtest a montré qu'on
    # peut avoir jusqu'à 5-7 trades XAU simultanés sur un même régime, ce
    # qui transforme 1 pari macro en 5-7 pertes corrélées si le régime
    # tourne. Limite configurable par asset class.
    open_count = _count_open_trades_for_pair(setup.pair)
    max_allowed = _max_positions_for_pair(setup.pair)
    if open_count >= max_allowed:
        return "max_positions_per_pair"
    # Délai minimum entre deux ordres sur un même symbole. Le cap ci-dessus
    # borne les positions SIMULTANÉES ; il ne dit rien du rythme quand elles
    # se ferment vite. Le 2026-08-04, six ordres ETH en vingt-sept minutes,
    # dont deux de sens opposés à la même seconde. Réglé par destination :
    # cf. `order_cooldown`, un délai global casserait le compte de Cédric.
    from backend.services.order_cooldown import en_cooldown
    bloque, restant = en_cooldown(dest, setup.pair)
    if bloque:
        logger.info(
            f"cooldown[{getattr(dest, 'destination_id', '?')}] {setup.pair} : "
            f"encore {restant}s avant un nouvel ordre"
        )
        return "cooldown_symbole"
    # Corrélation : le cap par paire compte les positions sur LA MÊME paire.
    # Un short BTC et un short ETH y échappent, alors qu'ils corrèlent à 0,81
    # — un seul pari, pris deux fois. Réglé par destination, cf.
    # `correlation_guard` : le compte principal en compte 281 sur 568 trades,
    # l'activer partout changerait massivement un comportement en place.
    from backend.services.correlation_guard import pari_deja_pris
    pris, en_cause = pari_deja_pris(dest, setup.pair, direction)
    if pris:
        logger.info(
            f"correlation[{getattr(dest, 'destination_id', '?')}] {setup.pair} "
            f"{direction} : meme pari que {', '.join(en_cause)}"
        )
        return "correlated_exposure"
    # Porte de coût (2026-08-04). Placée en DERNIER, après tous les filtres
    # bon marché : elle appelle le sizing, qui peut interroger le solde du
    # bridge par HTTP. Inutile de payer ce coût pour un signal qu'un filtre
    # gratuit allait écarter.
    cost_reason = _cost_rejection(setup, dest)
    if cost_reason:
        return cost_reason
    return None


_FIRST_LIVE_PUSH_MARKER = "/app/data/.first_live_push_notified"


def _notify_first_live_push(setup, bridge_response: dict) -> None:
    """Alerte infra one-shot : 1er push Live réussi depuis activation IC Markets.

    Marker fichier sur disque (`/app/data/.first_live_push_notified`) pour
    idempotence à travers les restarts container. Idempotent : une fois le
    marker créé, retourne immédiatement.

    Pour reset l'alerte (re-déclencher au prochain push admin_live) :
    ``rm /app/data/.first_live_push_notified`` côté container.

    Best-effort : toute exception laisse le marker non créé (next push
    re-tentera) et ne propage pas l'erreur au pipeline de push.
    """
    import os
    if os.path.exists(_FIRST_LIVE_PUSH_MARKER):
        return
    try:
        # Crée le marker AVANT l'envoi pour éviter race condition multi-thread.
        with open(_FIRST_LIVE_PUSH_MARKER, "w") as f:
            f.write(datetime.now(timezone.utc).isoformat())
    except Exception as e:
        logger.warning(f"first_live_push marker write failed: {e}")
        return  # ne notifie pas si on ne peut pas marker (sinon spam au cycle suivant)

    pair = getattr(setup, "pair", "?")
    direction = _direction_value(setup)
    ticket = bridge_response.get("ticket")
    fill_price = bridge_response.get("price") or getattr(setup, "entry_price", 0)
    volume = bridge_response.get("volume") or 0
    confidence = getattr(setup, "confidence_score", None)

    msg = (
        "🚀 <b>Premier push LIVE détecté</b>\n"
        f"Compte : <b>IC Markets €100</b> (admin_live)\n"
        f"Pair : <code>{pair}</code> {direction.upper()}\n"
        f"Ticket : <code>{ticket}</code>\n"
        f"Fill : <code>{fill_price}</code> · Volume : <code>{volume}</code>\n"
        f"Confidence : <code>{confidence}</code>\n"
        f"\nL'auto-exec parallèle Demo+Live tourne. Surveiller :"
        f"\n• <code>/v2/admin</code> pour positions Live"
        f"\n• <code>SELECT * FROM mt5_pushes WHERE destination_id='admin_live'</code>"
    )
    try:
        from backend.services import telegram_service as _tg
        import asyncio as _asyncio
        _asyncio.create_task(_tg.send_infra_text(msg, parse_mode="HTML"))
    except Exception as e:
        logger.warning(f"first_live_push send_infra_text failed: {e}")


def _jeton_derogation_restant() -> bool:
    """Reste-t-il un jeton de dérogation, et lesquelles portes il lève.

    Mécanisme **à usage unique et auto-réarmant** (2026-08-06). UN seul jeton
    lève DEUX portes à la fois — le filtre de patterns et la porte de coût —
    pour qu'un trade d'observation en consomme un, pas deux.

    ⚠️ **Réservé aux routes MT5.** La porte de coût de Kraken n'est pas levée :
    elle repose sur des frais 10× supérieurs et sur un portage, et l'ouvrir
    par effet de bord ferait passer des trades crypto non rentables.

    Le jeton est disponible tant que le nombre de pushes `admin_legacy` depuis
    l'armement reste sous `TRADE_DEROGATION_PUSHES`. Dès le quota atteint,
    les deux portes se remettent seules — sans dépendre de quiconque.

    **Pourquoi ce mécanisme plutôt qu'un simple réglage à vider.** Retirer la
    whitelist « le temps de voir » laisse toujours une fenêtre ouverte plus
    longtemps que prévu : personne ne revient la refermer. Le quota rend
    l'expérience bornée par construction.

    **Pourquoi compter `admin_legacy` seulement.** C'est le compte qui pilote
    (cf. `_mirror_fill_to_live`). Sa copie vers le réel ne passe pas par cette
    porte, donc elle partira même après le réarmement : un trade consomme bien
    un seul jeton, pas deux.

    ⚠️ Le quota compte les **pushes**, pas les fills. Un push refusé par le
    courtier consomme quand même le jeton — c'est voulu : on veut borner
    l'ouverture, pas garantir un résultat.

    Défaut `0` = filtre toujours actif, comportement d'avant.
    """
    try:
        from config.settings import TRADE_DEROGATION_PUSHES
        quota = int(TRADE_DEROGATION_PUSHES)
    except Exception:
        return False
    if quota <= 0:
        return False
    # Compte depuis l'instant d'ARMEMENT, pas depuis minuit.
    #
    # ⚠️ Corrigé le 2026-08-06 avant mise en service : compter par jour
    # calendaire faisait consommer le quota par les pushes DÉJÀ passés le
    # matin — et, pire, le remettait à zéro à minuit, ce qui aurait rouvert
    # la vanne en grand pendant la nuit sans que personne le demande.
    try:
        from config.settings import TRADE_DEROGATION_SINCE
        depuis = str(TRADE_DEROGATION_SINCE or "").strip()
    except Exception:
        depuis = ""
    if not depuis:
        # Sans instant d'armement, on ne sait pas depuis quand compter :
        # filtre maintenu plutôt qu'ouvert sur une base inconnue.
        return False

    try:
        import sqlite3
        from backend.services.trade_log_service import _DB_PATH

        with sqlite3.connect(str(_DB_PATH)) as c:
            n = c.execute(
                "SELECT COUNT(*) FROM mt5_pushes "
                "WHERE destination_id = 'admin_legacy' AND pushed_at >= ?",
                (depuis,),
            ).fetchone()[0]
        return int(n) < quota
    except Exception as e:
        # Compteur illisible ⇒ filtre ACTIF. Un doute ne doit pas ouvrir la
        # vanne : c'est le sens prudent de l'incertitude ici.
        logger.warning(f"dérogation: compteur illisible ({e}) — portes maintenues")
        return False


def _mirror_active() -> bool:
    """Le compte de démonstration pilote-t-il le compte réel ?

    Relu à chaque appel pour rester coupable sans redémarrage.
    """
    try:
        from config.settings import MIRROR_DEMO_TO_LIVE_ENABLED
        return bool(MIRROR_DEMO_TO_LIVE_ENABLED)
    except Exception:
        return False


async def _mirror_fill_to_live(setup, sz: dict, fill: dict, source_id: str) -> None:
    """Réplique sur le compte RÉEL un ordre qui vient d'être rempli en démo.

    Demandé le 2026-08-06 : le compte de démonstration **pilote** le compte
    réel, plutôt que les deux décidant en parallèle depuis le même signal.

    ⚠️ Les portes de DÉCISION du backend ne sont pas rejouées ici — le démo
    vient de décider, et les rejouer reproduirait la divergence qu'on cherche
    à supprimer. Les garde-fous de SÉCURITÉ restent tous en place, côté bridge
    et côté courtier : plafonds de lot par classe, nombre de positions,
    perte journalière maximale, ajustement à la marge disponible, et le refus
    du courtier lui-même. La copie ne peut donc pas ouvrir ce que le compte
    réel ne peut pas porter.

    ⚠️ **Le volume copié est celui réellement rempli en démo**, pas celui
    calculé : c'est ce qui rend la copie fidèle. Le bridge le réduira s'il
    dépasse ce que la marge du compte réel autorise.

    ⚠️ Ce que la copie ne peut PAS transporter (mesuré le 2026-08-06) : la
    marge. Sur les 8 fills du démo ce jour-là, **zéro** aurait pu être copié —
    le compte réel avait une marge libre négative toute la journée. Le miroir
    supprime la divergence de décision, jamais celle de capacité.
    """
    if source_id != "admin_legacy" or not _mirror_active():
        return

    from backend.services import bridge_destinations as _bd
    from backend.services import mt5_pushes_service
    # Importé ici comme partout ailleurs dans ce module : `record_rejection`
    # n'existe pas au niveau module, et l'appeler sans cet import n'aurait
    # explosé qu'au PREMIER refus du courtier réel — donc en production.
    from backend.services.rejection_service import record_rejection

    cible = _bd._admin_live_destination()
    if cible is None:
        return

    # La copie ne rejoue PAS les portes de décision (cf. docstring). La porte
    # d'HORIZON n'en est pas une : elle ne dit pas si le trade est bon, elle dit
    # quels horizons cette route *sert*. Copier un setup 4h vers une route qui
    # ne sert que le scalping n'est donc pas la divergence de décision qu'on
    # cherche à supprimer — c'est une erreur d'aiguillage.
    #
    # Ce que ça coûterait sans ce garde-fou, mesuré le 2026-08-07 : un stop
    # médian de 1,81 % sur `XAU/USD 4h` fait perdre 77,87 USD au lot minimum,
    # soit 20 % de l'``equity`` réelle du jour (350,68 EUR) — et 50 % au pire
    # stop observé. Le bridge ne peut pas rattraper ça : il sait réduire un
    # volume à la marge disponible, pas descendre sous 0,01 lot.
    #
    # Conséquence voulue : `MT5_LONG_HORIZON_ROUTES` reste le seul
    # interrupteur. Y ajouter `admin_live` ouvrira la copie des horizons longs
    # vers le réel sans qu'une ligne de ce fichier ne bouge.
    motif_horizon = _horizon_rejection(setup, cible)
    if motif_horizon:
        record_rejection(
            pair=setup.pair,
            direction=_direction_value(setup),
            confidence=getattr(setup, "confidence_score", None),
            reason_code=motif_horizon,
            details={"horizon": getattr(setup, "horizon", None), "miroir": True},
            user_id=None,
            destination_id=cible.destination_id,
        )
        return

    # Même découpage que `_dedup_key` : (date, pair, direction, entry, dest).
    push_date, _, direction, entry_5dp, _ = _dedup_key(setup, cible.destination_id)
    # Dedup par la base, comme un push normal : un fill démo rejoué ne doit
    # pas ouvrir deux positions réelles.
    if not mt5_pushes_service.try_register_push(
        cible.destination_id, push_date, setup.pair, direction, entry_5dp
    ):
        return

    # Payload construit POUR la destination réelle : son `symbol_map` diffère
    # (WTI_N6 chez IC Markets contre SpotCrude chez Pepperstone). Réutiliser
    # celui du démo enverrait un symbole que le courtier ne connaît pas.
    payload = _build_order_payload(setup, sz, dest=cible)
    volume = fill.get("volume")
    if volume:
        payload["lots"] = float(volume)

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(
                cible.bridge_url + "/order",
                json=payload,
                headers={"X-API-Key": cible.bridge_api_key,
                         "Content-Type": "application/json"},
            )
        data = r.json() if r.status_code == 200 else {}
        ok = bool(data.get("ok"))
        mt5_pushes_service.update_push_result(
            cible.destination_id, push_date, setup.pair, direction, entry_5dp,
            ok=ok, response=data or {"status": r.status_code, "body": r.text[:200]},
        )
        if ok:
            logger.info(
                f"MIROIR démo→réel : {setup.pair} {direction} "
                f"lot={payload.get('lots')} ticket={data.get('ticket')}"
            )
        else:
            logger.warning(
                f"MIROIR démo→réel REFUSÉ : {setup.pair} {direction} — "
                f"{data.get('message') or r.status_code}"
            )
            record_rejection(
                pair=setup.pair, direction=direction,
                confidence=getattr(setup, "confidence_score", None),
                reason_code="bridge_error",
                details={"miroir": True, "reponse": str(data or r.text)[:200]},
                user_id=None, destination_id=cible.destination_id,
            )
    except Exception as e:
        logger.warning(f"MIROIR démo→réel échoué ({type(e).__name__}): {e}")
        mt5_pushes_service.discard_push(
            cible.destination_id, push_date, setup.pair, direction, entry_5dp
        )


def _build_order_payload(setup, sz: dict, dest=None) -> dict:
    """Construit le dict envoyé à l'EA MQL5 / bridge.py.

    Contient à la fois les **prix absolus** (sl/tp) pour compat ascendante
    avec EA v≤1.04 et les **distances relatives** (sl_dist/tp_dist/tp2_dist)
    pour permettre à l'EA v1.05+ de recalculer SL/TP à partir du fill price
    effectif. Sans ça, le slippage entre signal et exécution dégrade le R:R
    réel (mesuré 0.7-1.3 au lieu de 1.8 sur ETH/USD le 2026-05-18).

    Si ``dest`` est fourni et que sa ``symbol_map`` contient la pair du setup,
    injecte ``broker_symbol`` dans le payload. L'EA v1.06+ utilisera cette
    valeur prioritairement sur son ``InpSymbolMap`` local. Permet le mapping
    multi-tenant server-side (un Premium peut être sur Pepperstone UK avec
    XAU/USD=GOLD, un autre sur Razor avec XAU/USD=XAUUSD).
    """
    entry = setup.entry_price
    sl = setup.stop_loss
    tp1 = setup.take_profit_1
    tp2 = getattr(setup, "take_profit_2", None)
    payload = {
        "pair": setup.pair,
        "direction": _direction_value(setup),
        "entry": entry,
        # Prix absolus (legacy EA v≤1.04, bridge.py admin).
        "sl": sl,
        "tp": tp1,
        "tp2": tp2,
        # Distances relatives (EA v1.05+). Positives en unités de prix.
        # L'EA calculera : SL = fill_price ± sl_dist, TP = fill_price ± tp_dist.
        "sl_dist": abs(entry - sl),
        "tp_dist": abs(entry - tp1),
        "tp2_dist": abs(entry - tp2) if tp2 is not None else None,
        "risk_money": sz["risk_money"],
        "comment": f"scalping-radar-{date.today().isoformat()}",
        # Le pourcentage EFFECTIF de la destination, pas le global : depuis le
        # 2026-08-09 il se declare par destination, et annoncer 1 % pour un
        # ordre calcule a 2 % ferait mentir le payload et les logs du bridge.
        # Informatif — le bridge dimensionne sur `risk_money`.
        "risk_pct": sz.get("risk_pct", RISK_PER_TRADE_PCT),
        "confidence": getattr(setup, "confidence_score", None),
        "sizing_detail": sz,
    }
    if dest is not None and getattr(dest, "symbol_map", None):
        broker_sym = dest.symbol_map.get(setup.pair)
        if broker_sym:
            payload["broker_symbol"] = broker_sym
    return payload


def _should_push(setup) -> bool:
    """Backward-compat : True si OK, False si rejeté."""
    return _check_rejection(setup) is None


async def _push_to_destination(setup, dest) -> None:
    """Push un setup vers UNE destination (``BridgeConfig``).

    Tous les filtres / dedup / HTTP sont paramétrés par ``dest``. Cette
    fonction est l'évolution V2 du corps historique de ``send_setup`` —
    cf. `docs/superpowers/specs/2026-04-28-multi-tenant-bridge-routing.md`.
    """
    from backend.services.rejection_service import record_rejection, record_silent_drop

    rejection = _check_rejection(setup, dest)
    if rejection is not None:
        # Les reason codes privés (commencent par "_") n'ont longtemps laissé
        # AUCUNE trace : pas de push, pas de rejet, rien. C'est ainsi que
        # `_not_admitted` a bloqué 85 % des signaux Kraken et que `_not_a_star`
        # a empêché les Voies A/B de trader une seule action, sans que rien ne
        # l'indique. On les compte désormais, agrégés par jour pour ne pas
        # noyer la table — cf. `record_silent_drop`.
        if rejection.startswith("_"):
            if SILENT_DROPS_LOG_ENABLED:
                record_silent_drop(
                    pair=setup.pair,
                    direction=_direction_value(setup),
                    reason_code=rejection,
                    destination_id=dest.destination_id,
                )
        else:
            # Inclut signal_pattern dans details pour les rejections
            # kill_switch_pair_paused : le watchdog stop_loss_alerts s'en
            # sert pour détecter si V1 essaie encore le pattern défaillant
            # (smart resume). Inutile pour les autres reason_codes mais
            # peu cher à porter, donc on log universellement.
            #
            # `horizon` (2026-08-05) : même logique pour `horizon_not_allowed`
            # — sans lui, une vague de refus d'horizon n'est pas
            # diagnosticable (quel horizon le signal portait-il vraiment ?).
            # Universel comme `signal_pattern`, et pour la même raison.
            details = {
                "signal_pattern": _pattern_value(setup),
                "horizon": getattr(setup, "horizon", None),
            }
            # Persister les blockers en clair pour les dashboards
            # (geopolitical_veto en particulier — sinon on perd la règle
            # qui a déclenché et le détail prob/jours).
            _blockers = getattr(setup, "verdict_blockers", None)
            if _blockers:
                details["blockers"] = list(_blockers)
            record_rejection(
                pair=setup.pair,
                direction=_direction_value(setup),
                confidence=getattr(setup, "confidence_score", None),
                reason_code=rejection,
                details=details,
                user_id=dest.user_id,
                destination_id=dest.destination_id,
            )
        return
    # Guard asset class : broker de cette destination ne supporte pas
    # toutes les classes. Per-destination en V2 (avant : global env).
    asset_class = asset_class_for(setup.pair)
    if asset_class not in dest.allowed_asset_classes:
        logger.debug(
            f"mt5_bridge[{dest.destination_id}]: skipping {setup.pair} "
            f"({asset_class}) — broker supports only {sorted(dest.allowed_asset_classes)}"
        )
        record_rejection(
            pair=setup.pair,
            direction=_direction_value(setup),
            confidence=getattr(setup, "confidence_score", None),
            reason_code="asset_class_blocked",
            details={"asset_class": asset_class, "allowed": sorted(dest.allowed_asset_classes)},
            user_id=dest.user_id,
            destination_id=dest.destination_id,
        )
        return
    _cleanup_old_keys()
    key = _dedup_key(setup, dest.destination_id)
    if key in _sent_setups_today:
        return
    # ─── Dispatch Binance bridge (Phase 2 R&D — 2026-06-17) ──────────
    # Quand la destination est de type "binance", déléguer au client dédié
    # qui formate le payload (qty au lieu de lots, leverage, isolated) et
    # gère la réponse Binance-shaped. Le client persiste dans mt5_pushes
    # (même destination_id="admin_binance") pour comparaison MT5 vs Binance.
    if getattr(dest, "bridge_type", "mt5") == "binance":
        _sent_setups_today.add(key)
        from backend.services import sizing
        from backend.services import binance_bridge_client
        # Capital réel de CETTE destination, pas le global : cf.
        # sizing.destination_capital. Le refresh est async pour ne pas
        # bloquer la boucle au milieu du calcul.
        await sizing.refresh_destination_capital(dest)
        sz = sizing.compute_risk_money(setup, dest)
        await binance_bridge_client.push_to_binance(setup, sz, dest)
        return

    # ─── Dispatch Kraken Futures bridge (2026-08-02) ──────────────────
    # Miroir du pattern binance. Cible = crypto perpetuals régulés EU
    # après blocker AMF Binance Futures FR.
    if getattr(dest, "bridge_type", "mt5") == "kraken":
        _sent_setups_today.add(key)
        from backend.services import sizing
        from backend.services import kraken_bridge_client
        # Capital réel de CETTE destination, pas le global : cf.
        # sizing.destination_capital. Le refresh est async pour ne pas
        # bloquer la boucle au milieu du calcul.
        await sizing.refresh_destination_capital(dest)
        sz = sizing.compute_risk_money(setup, dest)
        await kraken_bridge_client.push_to_kraken(setup, sz, dest)
        return

    # ─── Dispatch IBKR actions US (2026-08-10) ────────────────────────
    # Compte CASH, achat seul, quantite en nombre ENTIER d'actions. Le
    # sizing lit `NetLiquidation` (troisieme dialecte de solde du systeme).
    if getattr(dest, "bridge_type", "mt5") == "ibkr":
        _sent_setups_today.add(key)
        from backend.services import ibkr_bridge_client, sizing
        await sizing.refresh_destination_capital(dest)
        sz = sizing.compute_risk_money(setup, dest)
        await ibkr_bridge_client.push_to_ibkr(setup, sz, dest)
        return

    # ─── Dispatch Kraken Spot bridge (2026-08-02) ─────────────────────
    # Long-only, pas de levier, achat réel BTC/ETH. Watcher SL/TP émulé
    # côté bridge (pas d'OCO natif Kraken Spot). Paires: BTC/USD, ETH/USD.
    if getattr(dest, "bridge_type", "mt5") == "kraken_spot":
        _sent_setups_today.add(key)
        from backend.services import sizing
        from backend.services import kraken_spot_bridge_client
        # Capital réel de CETTE destination, pas le global : cf.
        # sizing.destination_capital. Le refresh est async pour ne pas
        # bloquer la boucle au milieu du calcul.
        await sizing.refresh_destination_capital(dest)
        sz = sizing.compute_risk_money(setup, dest)
        await kraken_spot_bridge_client.push_to_kraken_spot(setup, sz, dest)
        return
    # Dedup atomique en DB (UNIQUE constraint INSERT OR IGNORE) — source de
    # vérité partagée multi-process. Le set in-memory reste en parallèle pour
    # rétro-compat des tests existants. Best-effort : si la DB est
    # inaccessible, le service retourne True (fallback safe).
    from backend.services import mt5_pushes_service

    push_date = key[0]
    direction = _direction_value(setup)
    entry_5dp = f"{setup.entry_price:.5f}"
    if not mt5_pushes_service.try_register_push(
        dest.destination_id, push_date, setup.pair, direction, entry_5dp
    ):
        return
    _sent_setups_today.add(key)
    # Sizing dynamique : base = RISK_PER_TRADE_PCT du capital, module par
    # la confiance du signal (0.5x a 1.5x) et par le PnL recent (0.5x si
    # en drawdown sur 7j, sinon 1.0x). Voir sizing.compute_risk_money.
    # Note V1 : sizing reste global (pas per-user). À adresser en V2.
    from backend.services import sizing
    # Capital réel de CETTE destination (2026-08-06). `TRADING_CAPITAL` valait
    # 3000 € quand le compte réel en contenait 540 : le sizing calculait sur
    # 5,5× le capital disponible, et seuls les plafonds de lot puis
    # l'ajustement à la marge rattrapaient l'erreur — par accident, pas par
    # conception.
    #
    # Réservé aux destinations admin : une destination `user:N` passe par la
    # file de l'EA et n'expose pas de bridge à interroger.
    #
    # Le refus n'est jamais possible ici : `destination_capital` retombe sur le
    # global si le solde est indisponible (cf. sa docstring).
    if dest.user_id is None:
        await sizing.refresh_destination_capital(dest)
    sz = sizing.compute_risk_money(setup, dest)
    risk_money = sz["risk_money"]
    payload = _build_order_payload(setup, sz, dest=dest)

    # ─── Routing dispatch (Phase MQL.C) ──────────────────────────────
    # admin_legacy (user_id=None) : push HTTP synchrone vers le bridge admin.
    # user destinations (user_id=int) : enqueue dans mt5_pending_orders.
    # L'EA MQL5 du user récupère via GET /api/ea/pending toutes les ~30s.
    if dest.user_id is not None:
        from backend.services import mt5_pending_orders_service

        try:
            order_id = mt5_pending_orders_service.enqueue(
                user_id=dest.user_id,
                api_key=dest.bridge_api_key,
                payload=payload,
            )
            mt5_pushes_service.update_push_result(
                dest.destination_id, push_date, setup.pair, direction, entry_5dp,
                ok=True,
                response={"enqueued_order_id": order_id, "via": "ea_queue"},
            )
            logger.info(
                f"MT5 ea_queue[{dest.destination_id}] enqueued "
                f"order_id={order_id} {setup.pair} {direction} risk=${risk_money}"
            )
        except Exception as e:
            logger.warning(
                f"MT5 ea_queue[{dest.destination_id}] enqueue failed for "
                f"{setup.pair}: {e}"
            )
            record_rejection(
                pair=setup.pair,
                direction=direction,
                confidence=getattr(setup, "confidence_score", None),
                reason_code="bridge_error",
                details={"exception": str(e)[:200]},
                user_id=dest.user_id,
                destination_id=dest.destination_id,
            )
            _sent_setups_today.discard(key)
            mt5_pushes_service.discard_push(
                dest.destination_id, push_date, setup.pair, direction, entry_5dp
            )
        return

    # admin_legacy : path HTTP synchrone, comportement V1 inchangé.
    url = dest.bridge_url + "/order"
    headers = {
        "X-API-Key": dest.bridge_api_key,
        "Content-Type": "application/json",
    }

    # Mesure de latence end-to-end push admin_legacy : couvre RTT HTTP +
    # bridge.py processing (symbol_resolve + sizing + audit DB) + MT5 fill.
    # Le log `latency_ms=N` permet de surveiller le SLA (typique 700-2000ms,
    # bottleneck = exec broker côté Pepperstone Demo).
    push_start = time.perf_counter()

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(url, json=payload, headers=headers)
            latency_ms = int((time.perf_counter() - push_start) * 1000)
            if r.status_code == 200:
                data = r.json()
                mt5_pushes_service.update_push_result(
                    dest.destination_id, push_date, setup.pair, direction, entry_5dp,
                    ok=True, response=data,
                )
                logger.info(
                    f"MT5 bridge[{dest.destination_id}] → {setup.pair} {direction} "
                    f"risk=${risk_money} latency_ms={latency_ms} "
                    f"(conf={sz['conf_mult']}x pnl={sz['pnl_mult']}x "
                    f"session={sz['session']}:{sz['session_mult']}x "
                    f"macro={sz['macro_mult']}x"
                    + (f" {sz['macro_reasons']}" if sz.get('macro_reasons') else "")
                    + ") "
                    f"mode={data.get('mode', '?')}"
                )
                # Miroir démo → réel (2026-08-06) : déclenché sur un fill
                # CONFIRMÉ, jamais sur un simple push accepté. Le compte de
                # démonstration pilote le réel — cf. `_mirror_fill_to_live`.
                if data.get("ok") and data.get("ticket"):
                    try:
                        await _mirror_fill_to_live(
                            setup, sz, data, dest.destination_id
                        )
                    except Exception as _e:
                        logger.warning(f"miroir démo→réel: {_e}")

                # Notif user "Trade OUVERT" si le bridge a vraiment fillé
                # (ticket présent, mode='live'). Best-effort, non bloquant.
                if data.get("ok") and data.get("ticket"):
                    try:
                        from backend.services import telegram_service as _tg
                        await _tg.send_trade_opened(
                            setup,
                            ticket=int(data.get("ticket")),
                            fill_price=float(data.get("price") or setup.entry_price),
                            volume=float(data.get("volume") or 0),
                            mode=str(data.get("mode") or "?"),
                            destination_id=dest.destination_id,
                        )
                    except Exception as _e:
                        logger.warning(f"send_trade_opened hook error: {_e}")
                    # Alerte immédiate si le bridge dit explicitement que la
                    # position n'est PAS protégée (incident 2026-08-05 :
                    # position XAU/USD ouverte sans SL/TP, découverte 7h
                    # après par un cron qui ne pollait qu'à l'heure). `protected`
                    # n'existe que depuis le fix bridge-side du 2026-08-06 ;
                    # son absence (bridge pas encore mis à jour) ne déclenche
                    # rien — on ne peut pas distinguer "non protégé" de
                    # "bridge pas encore patché" sans le champ, donc on ne
                    # suppose rien dans ce cas (`.get(...) is False`, pas
                    # `not .get(...)`).
                    if data.get("protected") is False:
                        try:
                            from backend.services import telegram_service as _tg
                            await _tg.send_infra_text(
                                "🚨 <b>Position LIVE ouverte SANS stop</b>\n"
                                f"Destination : <code>{dest.destination_id}</code>\n"
                                f"Pair : <code>{setup.pair}</code> {direction.upper()}\n"
                                f"Ticket : <code>{data.get('ticket')}</code>\n"
                                f"SL error : <code>{data.get('sl_error') or '?'}</code>\n"
                                "\n👉 Vérifier immédiatement côté MT5 — la position "
                                "n'a pas de stop-loss confirmé.",
                                parse_mode="HTML",
                            )
                        except Exception as _e:
                            logger.warning(f"protected=False alert failed: {_e}")
                    # Alerte infra one-shot : premier push Live (admin_live)
                    # réussi depuis l'activation 2026-06-12. Marker fichier sur
                    # disque pour idempotence à travers les restarts container.
                    if dest.destination_id == "admin_live":
                        try:
                            _notify_first_live_push(setup, data)
                        except Exception as _e:
                            logger.warning(f"first_live_push notif error: {_e}")
            else:
                logger.warning(
                    f"MT5 bridge[{dest.destination_id}] a répondu {r.status_code} "
                    f"pour {setup.pair} (latency_ms={latency_ms}): {r.text[:200]}"
                )
                # Catégorise la rejection bridge pour la viz dédiée
                body_text = r.text or ""
                if r.status_code == 429 or "Max open positions" in body_text:
                    reason = "bridge_max_positions"
                elif "10016" in body_text or "INVALID_STOPS" in body_text:
                    reason = "bridge_invalid_stops"
                else:
                    reason = "bridge_error"
                record_rejection(
                    pair=setup.pair,
                    direction=direction,
                    confidence=getattr(setup, "confidence_score", None),
                    reason_code=reason,
                    details={"status": r.status_code, "body": body_text[:200]},
                    user_id=dest.user_id,
                    destination_id=dest.destination_id,
                )
                # Si l'ordre a été rejeté par le bridge, on retire de la dedup
                # (mémoire + DB) pour qu'un cycle suivant puisse retenter.
                _sent_setups_today.discard(key)
                mt5_pushes_service.discard_push(
                    dest.destination_id, push_date, setup.pair, direction, entry_5dp
                )
    except httpx.TimeoutException:
        logger.info(
            f"MT5 bridge[{dest.destination_id}] timeout — skip {setup.pair}"
        )
        record_rejection(
            pair=setup.pair,
            direction=direction,
            confidence=getattr(setup, "confidence_score", None),
            reason_code="bridge_timeout",
            user_id=dest.user_id,
            destination_id=dest.destination_id,
        )
        _sent_setups_today.discard(key)  # retente au cycle suivant
        mt5_pushes_service.discard_push(
            dest.destination_id, push_date, setup.pair, direction, entry_5dp
        )
    except Exception as e:
        logger.warning(
            f"MT5 bridge[{dest.destination_id}] exception pour {setup.pair}: {e}"
        )
        record_rejection(
            pair=setup.pair,
            direction=direction,
            confidence=getattr(setup, "confidence_score", None),
            reason_code="bridge_error",
            details={"exception": str(e)[:200]},
            user_id=dest.user_id,
            destination_id=dest.destination_id,
        )
        _sent_setups_today.discard(key)
        mt5_pushes_service.discard_push(
            dest.destination_id, push_date, setup.pair, direction, entry_5dp
        )


async def send_setup(setup) -> None:
    """Push un trade_setup vers chaque destination active.

    V1 : 1 destination max (``admin_legacy`` depuis l'env). Phase C
    élargira pour inclure les users Premium auto-exec via
    ``bridge_destinations.resolve_destinations()``.
    """
    from backend.services.bridge_destinations import resolve_destinations

    destinations = resolve_destinations(setup)
    if not destinations:
        return
    await asyncio.gather(
        *(_push_to_destination(setup, dest) for dest in destinations),
        return_exceptions=True,
    )


async def send_setups(setups: list) -> None:
    """Push plusieurs setups en parallèle. No-op si bridge pas configuré."""
    if not is_configured() or not setups:
        return
    # Pré-filtre 1 : stars du portefeuille Phase 4 + extras autorisés sur
    # admin_live (cas €100 cap insuffisant pour XAU/ETH → ouverture aux forex
    # majors EUR/USD, GBP/USD, USD/JPY uniquement côté Live, cf. driver
    # 2026-06-12 IC Markets). Demo continue de filtrer stars-only via le
    # per-destination check dans _push_to_destination → _check_rejection.
    try:
        from config.settings import MT5_BRIDGE_LIVE_EXTRA_PAIRS as _live_extras
    except Exception:
        _live_extras = frozenset()
    try:
        from config.settings import MT5_BRIDGE_EXTRA_PAIRS_GLOBAL as _global_extras
    except Exception:
        _global_extras = frozenset()
    allowed_pairs = _STAR_PAIRS_SET | _live_extras | _global_extras
    setups = [s for s in setups if s.pair in allowed_pairs]
    if not setups:
        return
    # Pré-filtre 2 : asset class supportée par le broker courant.
    setups = [
        s for s in setups
        if asset_class_for(s.pair) in MT5_BRIDGE_ALLOWED_ASSET_CLASSES
    ]
    if not setups:
        return
    await asyncio.gather(*(send_setup(s) for s in setups), return_exceptions=True)


async def get_account() -> dict:
    """Récupère l'état du compte broker via bridge /account.

    Retourne un dict enrichi avec `margin_level_pct` (équity / margin × 100).
    Si bridge pas configuré ou injoignable, retourne
    `{configured: bool, reachable: False, error: str}`.
    """
    if not is_configured():
        return {"configured": False, "reachable": False}
    url = MT5_BRIDGE_URL.rstrip("/") + "/account"
    headers = {"X-API-Key": MT5_BRIDGE_API_KEY}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url, headers=headers)
            if r.status_code != 200:
                return {
                    "configured": True,
                    "reachable": False,
                    "status": r.status_code,
                }
            data = r.json()
            margin = float(data.get("margin") or 0)
            equity = float(data.get("equity") or 0)
            # Margin level = equity / margin × 100. Indéfini si margin=0
            # (aucune position ouverte) → convention broker: "Infinity",
            # on renvoie None pour que l'UI affiche "—".
            margin_level_pct = (equity / margin * 100) if margin > 0 else None
            return {
                "configured": True,
                "reachable": True,
                **data,
                "margin_level_pct": margin_level_pct,
            }
    except httpx.TimeoutException:
        return {"configured": True, "reachable": False, "error": "timeout"}
    except Exception as e:
        return {"configured": True, "reachable": False, "error": str(e)[:120]}


async def health_check(bridge_url: str | None = None) -> dict:
    """Retourne l'état d'un bridge MT5 depuis le point de vue du backend.

    Par défaut ping `MT5_BRIDGE_URL` (bridge legacy / Demo Pepperstone).
    Si `bridge_url` est fourni (ex: `MT5_BRIDGE_LIVE_URL` pour IC Markets Live),
    ping cet URL à la place — utile pour un endpoint multi-bridges-health.
    """
    target = (bridge_url or MT5_BRIDGE_URL or "").strip()
    if not target:
        return {"configured": False}
    url = target.rstrip("/") + "/health"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(url)
            if r.status_code == 200:
                return {"configured": True, "reachable": True, **r.json()}
            return {"configured": True, "reachable": False, "status": r.status_code}
    except Exception as e:
        return {"configured": True, "reachable": False, "error": str(e)[:100]}
