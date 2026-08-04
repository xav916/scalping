"""Multi-tenant bridge routing — résolution des destinations pour un setup.

Pour chaque ``trade_setup`` généré par le scoring, ce module retourne la liste
des "destinations" (bridges MT5) vers lesquelles le pousser :

- ``admin_legacy`` : config depuis l'env (``MT5_BRIDGE_URL`` / ``KEY``), activée
  si ``MT5_BRIDGE_ENABLED=true``. Conserve le comportement actuel mono-tenant.
- ``user:{id}`` (Phase C, pas encore activé) : users Premium avec auto-exec
  activé et la pair dans leur watchlist.

V1 ne retourne qu'``admin_legacy``. La suite (multi-user) sera ajoutée en
Phase C en enrichissant ``_user_destinations()`` — sans toucher à
``mt5_bridge.send_setup()``.

Voir ``docs/superpowers/specs/2026-04-28-multi-tenant-bridge-routing.md``.

Note design : la résolution lit la config legacy via ``mt5_bridge`` (lazy
import) et non via ``config.settings`` directement, pour que les tests
existants qui patchent ``mt5_bridge.MT5_BRIDGE_*`` propagent leurs valeurs
ici sans modification. Pas de cycle d'import au chargement (lazy import
dans la fonction).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from backend.services.cost_model import CostModel


@dataclass(frozen=True)
class BridgeConfig:
    """Configuration d'une destination de bridge MT5.

    Attributes
    ----------
    destination_id : str
        Clé unique pour dedup et logs (``admin_legacy`` ou ``user:42``).
    user_id : int | None
        Id DB du user. ``None`` pour l'admin legacy env-based.
    bridge_url : str
        Base URL du bridge MT5 (sans trailing slash).
    bridge_api_key : str
        API key envoyée via header ``X-API-Key``.
    min_confidence : float
        Seuil ``confidence_score`` minimum pour pousser un setup vers cette
        destination. Override possible per-user en V2 (V1 = global).
    allowed_asset_classes : frozenset[str]
        Classes d'actifs supportées par le broker de cette destination.
    auto_exec_enabled : bool
        Master switch pour cette destination. ``False`` = court-circuite tous
        les pushes vers ce bridge sans toucher au reste du pipeline.
    symbol_map : dict[str, str] | None
        Mapping ``pair → broker_symbol`` propre au broker de cette destination.
        Permet d'injecter ``broker_symbol`` dans le payload pour que l'EA
        utilise le bon nom de symbole (ex: ``XAU/USD → GOLD`` pour Pepperstone
        UK). ``None`` = pas de mapping server-side, l'EA gère via son
        ``InpSymbolMap`` local. Cf. ``feedback_ea_symbol_map_pepperstone.md``.
    extra_pairs_allowed : frozenset[str]
        Pairs SUPPLÉMENTAIRES autorisées en plus de ``_STAR_PAIRS_SET`` pour
        cette destination. Permet d'élargir Live aux forex majors quand le
        capital est trop petit pour les stars métaux. Empty = stars-only.
        Cf. driver 2026-06-12 IC Markets €100.
    allowed_patterns : frozenset[str] | None
        Patterns autorisés à l'auto-exec pour cette destination.
        ``None`` = hérite du global ``MT5_BRIDGE_ALLOWED_PATTERNS``.
        ``frozenset()`` = aucun filtre pattern pour cette destination.
        Ajouté le 2026-08-04 : la whitelist était globale, donc impossible de
        garder `range_bounce` sur l'argent réel MT5 tout en l'ouvrant sur une
        destination d'observation. Cf. project_pattern_whitelist_dispatch.
    excluded_pairs : frozenset[str]
        Pairs explicitement BLOQUÉES pour cette destination, indépendamment du
        pair_admission_state global. Permet de mettre un client Premium en
        garde-fou sur les paires non-validées (ex: les 6 nouvelles cryptos
        promues manuellement par admin sans historique EV). Empty = aucune
        exclusion. Cf. memo profil Client Premium 2026-06-14.
    """

    destination_id: str
    user_id: int | None
    bridge_url: str
    bridge_api_key: str
    min_confidence: float
    allowed_asset_classes: frozenset[str]
    auto_exec_enabled: bool
    symbol_map: dict[str, str] | None = None
    extra_pairs_allowed: frozenset[str] = frozenset()
    excluded_pairs: frozenset[str] = frozenset()
    # None = hérite du global. frozenset() = pas de filtre pattern.
    allowed_patterns: frozenset[str] | None = None
    # Capital de CETTE destination pour le sizing. None = résolu par
    # sizing.destination_capital (solde live pour les bridges crypto,
    # TRADING_CAPITAL global pour les bridges MT5).
    trading_capital: float | None = None
    # bridge_type: "mt5" pour les bridges MT5 (admin_legacy, admin_live, user
    # premium), "binance" pour le bridge Binance Futures (USDⓈ-M perp).
    # Le dispatcher dans mt5_bridge._push_to_destination utilise ce flag pour
    # router vers le client approprié et adapter le payload.
    bridge_type: str = "mt5"
    # leverage pour les destinations Binance (ignoré côté MT5, broker fixe).
    leverage: int | None = None
    # ── Coût et edge (2026-08-04) ────────────────────────────────────
    # `cost_model` décrit ce que coûte un aller-retour sur cette route.
    # `expected_edge_r` est l'edge brut MESURÉ de la population admise, en
    # unités de risque. Les deux à None = route non mesurée : elle ne peut
    # pas prendre d'argent réel, mais reste observable en TELEGRAM.
    #
    # ⚠️ Ne jamais mettre 0.0 pour « on ne sait pas ». Un coût nul rendrait
    # n'importe quelle route éligible, un edge nul la condamnerait à tort.
    cost_model: CostModel | None = None
    expected_edge_r: float | None = None


def _admin_legacy_destination() -> BridgeConfig | None:
    """Retourne la config admin legacy depuis l'env, ou ``None`` si absente.

    Lit via ``mt5_bridge`` (lazy import) pour respecter les patches des
    tests existants qui font ``patch.object(mt5_bridge, "MT5_BRIDGE_URL", ...)``.

    Overrides opt-in via env vars ``MT5_BRIDGE_LEGACY_*`` (2026-07-29) —
    permet d'aligner Demo sur Live sans toucher aux globals partagés avec
    les user:N destinations. Fallback global si non défini.
    """
    from backend.services import mt5_bridge as mb

    if not (mb.MT5_BRIDGE_ENABLED and mb.MT5_BRIDGE_URL and mb.MT5_BRIDGE_API_KEY):
        return None

    legacy_min_conf_raw = os.getenv("MT5_BRIDGE_LEGACY_MIN_CONFIDENCE", "").strip()
    min_conf = (
        float(legacy_min_conf_raw)
        if legacy_min_conf_raw
        else float(mb.MT5_BRIDGE_MIN_CONFIDENCE)
    )

    legacy_classes_raw = os.getenv("MT5_BRIDGE_LEGACY_ALLOWED_ASSET_CLASSES", "").strip()
    if legacy_classes_raw:
        allowed_classes = frozenset(
            c.strip().lower() for c in legacy_classes_raw.split(",") if c.strip()
        )
    else:
        allowed_classes = frozenset(mb.MT5_BRIDGE_ALLOWED_ASSET_CLASSES)

    legacy_extras_raw = os.getenv("MT5_BRIDGE_LEGACY_EXTRA_PAIRS", "").strip()
    extra_pairs = (
        frozenset(
            p.strip().upper() for p in legacy_extras_raw.split(",") if p.strip()
        )
        if legacy_extras_raw
        else frozenset()
    )

    return BridgeConfig(
        destination_id="admin_legacy",
        user_id=None,
        bridge_url=mb.MT5_BRIDGE_URL.rstrip("/"),
        bridge_api_key=mb.MT5_BRIDGE_API_KEY,
        min_confidence=min_conf,
        allowed_asset_classes=allowed_classes,
        auto_exec_enabled=True,
        extra_pairs_allowed=extra_pairs,
    )


def _admin_live_destination() -> BridgeConfig | None:
    """Retourne la config admin LIVE (2e destination admin parallèle), ou ``None``.

    Permet de pousser les setups vers un second bridge admin en plus du Demo
    (admin_legacy). Pattern : Demo Pepperstone continue + Live IC Markets sur
    nouveau MT5 + bridge.py port 8788. Les deux destinations sont admin
    (user_id=None) donc HTTP synchrone, pas via la queue EA des Premium users.

    Driver 2026-06-12 : Pepperstone bloqué AMF (MT5 inaccessible retail FR),
    pivot IC Markets Cyprus en parallèle du Demo Pepperstone.

    Lit via ``config.settings`` directement (les env vars MT5_BRIDGE_LIVE_* sont
    indépendantes des patches mt5_bridge des tests existants).
    """
    from config import settings as st

    if not (
        getattr(st, "MT5_BRIDGE_LIVE_ENABLED", False)
        and getattr(st, "MT5_BRIDGE_LIVE_URL", "")
        and getattr(st, "MT5_BRIDGE_LIVE_API_KEY", "")
    ):
        return None
    live_symbol_map = getattr(st, "MT5_BRIDGE_LIVE_SYMBOL_MAP", None) or None
    return BridgeConfig(
        destination_id="admin_live",
        user_id=None,
        bridge_url=st.MT5_BRIDGE_LIVE_URL.rstrip("/"),
        bridge_api_key=st.MT5_BRIDGE_LIVE_API_KEY,
        min_confidence=float(st.MT5_BRIDGE_LIVE_MIN_CONFIDENCE),
        allowed_asset_classes=frozenset(st.MT5_BRIDGE_LIVE_ALLOWED_ASSET_CLASSES),
        auto_exec_enabled=True,
        symbol_map=live_symbol_map,
        extra_pairs_allowed=getattr(st, "MT5_BRIDGE_LIVE_EXTRA_PAIRS", frozenset()),
    )


def _admin_binance_destination() -> BridgeConfig | None:
    """Retourne la config Binance Futures (testnet ou live), ou ``None``.

    Lance Phase 2 du Palier 2 (migration vers vrais cryptos) : pousser les
    signaux crypto vers Binance USDⓈ-M en parallèle des destinations MT5.
    En testnet : zéro coût, validation comparative MT5 Demo vs Binance.

    Conditions activation :
    - BINANCE_BRIDGE_ENABLED=true
    - BINANCE_BRIDGE_URL set (typique http://127.0.0.1:8789)
    - bridge_type="binance" déclenche le dispatch vers binance_bridge_client
      au lieu du push MT5 standard.
    """
    from config import settings as st

    if not (
        getattr(st, "BINANCE_BRIDGE_ENABLED", False)
        and getattr(st, "BINANCE_BRIDGE_URL", "")
    ):
        return None
    return BridgeConfig(
        destination_id="admin_binance",
        user_id=None,
        bridge_url=st.BINANCE_BRIDGE_URL.rstrip("/"),
        bridge_api_key=getattr(st, "BINANCE_BRIDGE_API_KEY", "") or "",
        min_confidence=float(getattr(st, "BINANCE_BRIDGE_MIN_CONFIDENCE", 50)),
        allowed_asset_classes=frozenset({"crypto"}),
        auto_exec_enabled=True,
        bridge_type="binance",
        leverage=int(getattr(st, "BINANCE_BRIDGE_LEVERAGE", 5)),
    )


def _admin_kraken_spot_destination() -> BridgeConfig | None:
    """Retourne la config Kraken Spot LIVE (BTC/ETH achat réel), ou ``None`` si désactivé.

    Créé 2026-08-02 — fork du bridge Kraken Futures pour trading Spot sans levier.
    Long-only, pas d'OCO natif (watcher SL/TP émulé dans le bridge).
    Port 8791 par défaut (vs 8790 Futures).

    Conditions activation :
    - KRAKEN_SPOT_BRIDGE_ENABLED=true
    - KRAKEN_SPOT_BRIDGE_URL set (typique http://127.0.0.1:8791)
    - bridge_type="kraken_spot" déclenche le dispatch vers kraken_spot_bridge_client
    """
    from config import settings as st

    if not (
        getattr(st, "KRAKEN_SPOT_BRIDGE_ENABLED", False)
        and getattr(st, "KRAKEN_SPOT_BRIDGE_URL", "")
    ):
        return None
    return BridgeConfig(
        destination_id="admin_kraken_spot",
        user_id=None,
        bridge_url=st.KRAKEN_SPOT_BRIDGE_URL.rstrip("/"),
        bridge_api_key=getattr(st, "KRAKEN_SPOT_BRIDGE_API_KEY", "") or "",
        min_confidence=float(getattr(st, "KRAKEN_SPOT_BRIDGE_MIN_CONFIDENCE", 75)),
        allowed_asset_classes=frozenset({"crypto"}),
        auto_exec_enabled=True,
        bridge_type="kraken_spot",
        leverage=int(getattr(st, "KRAKEN_SPOT_BRIDGE_LEVERAGE", 1)),
        cost_model=CostModel(proportional_rate_per_leg=0.0005),
        # Le taux 0,0005 est celui des PERPÉTUELS. Le barème spot Kraken est
        # nettement plus élevé et n'a pas été mesuré. Edge à None : jamais
        # mesuré sur cette route, donc la porte bloque en exécution réelle.
        expected_edge_r=None,
    )


def _admin_kraken_stocks_destination() -> BridgeConfig | None:
    """Retourne la config Kraken xStocks LIVE (actions US tokenisées), ou ``None`` si désactivé.

    Créé 2026-08-02 (Voie A) après découverte que l'API Kraken Futures accepte
    les xStocks Backed Finance (PF_AAPLXUSD, PF_TSLAXUSD...) sur compte FR
    même si l'UI de recherche les cache. Route vers le MÊME bridge Kraken
    Futures (port 8790) que la destination admin_kraken crypto, mais avec
    filtre allowed_asset_classes={"equity"} pour séparer le tracking PnL.

    Risques connus :
    - Kraken pourrait bloquer l'accès API à tout moment (usage "non-intentionnel"
      pour compte FR)
    - Prix xStocks décorrélés des vrais marchés NYSE (pricing propre à Kraken)
    - Trading 24/7 avec levier ~10x auto = risque plus élevé

    Conditions activation :
    - KRAKEN_STOCKS_BRIDGE_ENABLED=true
    - KRAKEN_STOCKS_BRIDGE_URL set (typique http://127.0.0.1:8790 = même bridge)
    - bridge_type="kraken" déclenche le dispatch vers kraken_bridge_client
    """
    from config import settings as st

    if not (
        getattr(st, "KRAKEN_STOCKS_BRIDGE_ENABLED", False)
        and getattr(st, "KRAKEN_STOCKS_BRIDGE_URL", "")
    ):
        return None
    return BridgeConfig(
        destination_id="admin_kraken_stocks",
        user_id=None,
        bridge_url=st.KRAKEN_STOCKS_BRIDGE_URL.rstrip("/"),
        bridge_api_key=getattr(st, "KRAKEN_STOCKS_BRIDGE_API_KEY", "") or "",
        min_confidence=float(getattr(st, "KRAKEN_STOCKS_BRIDGE_MIN_CONFIDENCE", 75)),
        allowed_asset_classes=frozenset({"equity"}),
        auto_exec_enabled=True,
        bridge_type="kraken",
        leverage=int(getattr(st, "KRAKEN_STOCKS_BRIDGE_LEVERAGE", 5)),
        cost_model=CostModel(proportional_rate_per_leg=0.0005),
        # Edge jamais mesuré sur xStocks — la route n'a jamais tradé et ses prix
        # sont décorrélés du NYSE. Emprunter l'edge MT5 serait extrapoler hors
        # du domaine de mesure. À None, la porte bloque en exécution réelle.
        expected_edge_r=None,
    )


def _admin_kraken_destination() -> BridgeConfig | None:
    """Retourne la config Kraken Futures LIVE, ou ``None`` si désactivé.

    Créé 2026-08-02 après blocker AMF Binance Futures FR + Bybit UE Spot only
    + OKX EU MTF format non-standard. Kraken Futures régulé Ireland/EU,
    perpetuals USD-margined `PF_*` accessibles résidents FR.

    Conditions activation :
    - KRAKEN_BRIDGE_ENABLED=true
    - KRAKEN_BRIDGE_URL set (typique http://127.0.0.1:8790)
    - bridge_type="kraken" déclenche le dispatch vers kraken_bridge_client
    """
    from config import settings as st

    if not (
        getattr(st, "KRAKEN_BRIDGE_ENABLED", False)
        and getattr(st, "KRAKEN_BRIDGE_URL", "")
    ):
        return None
    return BridgeConfig(
        destination_id="admin_kraken",
        user_id=None,
        bridge_url=st.KRAKEN_BRIDGE_URL.rstrip("/"),
        bridge_api_key=getattr(st, "KRAKEN_BRIDGE_API_KEY", "") or "",
        min_confidence=float(getattr(st, "KRAKEN_BRIDGE_MIN_CONFIDENCE", 60)),
        allowed_asset_classes=frozenset({"crypto"}),
        auto_exec_enabled=True,
        bridge_type="kraken",
        leverage=int(getattr(st, "KRAKEN_BRIDGE_LEVERAGE", 5)),
        allowed_patterns=getattr(st, "KRAKEN_BRIDGE_ALLOWED_PATTERNS", None),
        # 0,05 % par jambe (taker). Donne 0,288 R au SL médian mesuré.
        cost_model=CostModel(proportional_rate_per_leg=0.0005),
        expected_edge_r=0.110,  # mesuré sur 876 trades réels le 2026-08-04
    )


def _user_destinations(setup: Any) -> list[BridgeConfig]:
    """Retourne les destinations users (Premium tier) pour ce setup.

    Phase C : interroge ``users_service.list_premium_auto_exec_users()``
    pour récupérer les users éligibles, puis filtre par
    ``setup.pair in user.watched_pairs``.

    V1 du multi-user : ``min_confidence`` et ``allowed_asset_classes`` sont
    hérités du global env (admin_legacy) — pas d'override per-user. À
    adresser en V2 si besoin.

    Best-effort : toute erreur (DB, parsing) est silencieuse et retourne
    ``[]`` pour la destination user fautive.
    """
    pair = getattr(setup, "pair", None)
    if not pair:
        return []

    # Lazy imports : évite cycle au chargement et permet aux tests de
    # patcher mt5_bridge.* / users_service.* sans setup top-level.
    from backend.services import mt5_bridge as mb
    from backend.services import users_service

    try:
        candidates = users_service.list_premium_auto_exec_users()
    except Exception:
        return []

    destinations: list[BridgeConfig] = []
    for user in candidates:
        if pair not in user["watched_pairs"]:
            continue
        cfg = user["broker_config"]
        raw_map = cfg.get("symbol_map")
        symbol_map = raw_map if isinstance(raw_map, dict) and raw_map else None
        # Per-user min_confidence override (defaults au global si absent)
        raw_min_conf = cfg.get("min_confidence")
        try:
            user_min_conf = float(raw_min_conf) if raw_min_conf is not None else float(mb.MT5_BRIDGE_MIN_CONFIDENCE)
        except (TypeError, ValueError):
            user_min_conf = float(mb.MT5_BRIDGE_MIN_CONFIDENCE)
        # Per-user excluded_pairs (paires explicitement bloquées pour ce user)
        raw_excluded = cfg.get("excluded_pairs") or []
        excluded_pairs = frozenset(p for p in raw_excluded if isinstance(p, str)) if isinstance(raw_excluded, list) else frozenset()
        try:
            destinations.append(
                BridgeConfig(
                    destination_id=f"user:{user['id']}",
                    user_id=int(user["id"]),
                    # bridge_url ignoré pour user destinations (path = EA queue,
                    # cf. mt5_bridge.send_setup user_id is not None branche).
                    # Conservé en str pour le dataclass, fallback "" si absent.
                    bridge_url=(cfg.get("bridge_url") or "").rstrip("/"),
                    bridge_api_key=cfg["bridge_api_key"],
                    min_confidence=user_min_conf,
                    allowed_asset_classes=frozenset(
                        mb.MT5_BRIDGE_ALLOWED_ASSET_CLASSES
                    ),
                    auto_exec_enabled=True,
                    symbol_map=symbol_map,
                    excluded_pairs=excluded_pairs,
                )
            )
        except (KeyError, TypeError, ValueError):
            # broker_config malformé pour ce user — skip silencieux
            continue
    return destinations


def admin_destinations() -> list[BridgeConfig]:
    """Destinations admin configurées, indépendamment de tout setup.

    ``resolve_destinations`` répond à « où pousser CE signal ? » et filtre
    donc selon la paire, le sens et les admissions. Les tâches de fond —
    réconciliation des clôtures, sondes de santé — ont besoin de l'autre
    question : « quels comptes existent ? ». Faute de cette fonction,
    ``kraken_sync`` aurait recopié la liste des constructeurs, soit
    exactement la duplication que le registre des destinations supprime.
    """
    constructeurs = (
        _admin_legacy_destination, _admin_live_destination,
        _admin_binance_destination, _admin_kraken_destination,
        _admin_kraken_spot_destination, _admin_kraken_stocks_destination,
    )
    return [d for d in (c() for c in constructeurs) if d is not None]


def resolve_destinations(setup: Any) -> list[BridgeConfig]:
    """Liste toutes les destinations vers lesquelles ce setup doit être poussé.

    Ordre : ``admin_legacy`` en premier (rétro-compat), puis ``admin_live`` (si
    configuré), puis users (Phase C). Liste possiblement vide — équivalent à
    l'ancien ``mt5_bridge.is_configured() == False``.
    """
    destinations: list[BridgeConfig] = []
    admin = _admin_legacy_destination()
    if admin is not None:
        destinations.append(admin)
    admin_live = _admin_live_destination()
    if admin_live is not None:
        destinations.append(admin_live)
    admin_binance = _admin_binance_destination()
    if admin_binance is not None:
        destinations.append(admin_binance)
    admin_kraken = _admin_kraken_destination()
    if admin_kraken is not None:
        destinations.append(admin_kraken)
    admin_kraken_spot = _admin_kraken_spot_destination()
    if admin_kraken_spot is not None:
        # Kraken Spot est long-only : le bridge rejette les shorts avec
        # `kraken_spot_short_rejected`. Filtrer ici évite de router ~30-40%
        # des signaux crypto (les SELL) pour rien, allège les logs et
        # rejections DB. Le bridge garde son check défensif au cas où.
        direction = getattr(getattr(setup, "direction", None), "value", "")
        if str(direction).lower() == "buy":
            destinations.append(admin_kraken_spot)
    admin_kraken_stocks = _admin_kraken_stocks_destination()
    if admin_kraken_stocks is not None:
        destinations.append(admin_kraken_stocks)
    destinations.extend(_user_destinations(setup))
    return destinations
