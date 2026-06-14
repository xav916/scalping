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

from dataclasses import dataclass
from typing import Any


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


def _admin_legacy_destination() -> BridgeConfig | None:
    """Retourne la config admin legacy depuis l'env, ou ``None`` si absente.

    Lit via ``mt5_bridge`` (lazy import) pour respecter les patches des
    tests existants qui font ``patch.object(mt5_bridge, "MT5_BRIDGE_URL", ...)``.
    """
    from backend.services import mt5_bridge as mb

    if not (mb.MT5_BRIDGE_ENABLED and mb.MT5_BRIDGE_URL and mb.MT5_BRIDGE_API_KEY):
        return None
    return BridgeConfig(
        destination_id="admin_legacy",
        user_id=None,
        bridge_url=mb.MT5_BRIDGE_URL.rstrip("/"),
        bridge_api_key=mb.MT5_BRIDGE_API_KEY,
        min_confidence=float(mb.MT5_BRIDGE_MIN_CONFIDENCE),
        allowed_asset_classes=frozenset(mb.MT5_BRIDGE_ALLOWED_ASSET_CLASSES),
        auto_exec_enabled=True,
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
    return BridgeConfig(
        destination_id="admin_live",
        user_id=None,
        bridge_url=st.MT5_BRIDGE_LIVE_URL.rstrip("/"),
        bridge_api_key=st.MT5_BRIDGE_LIVE_API_KEY,
        min_confidence=float(st.MT5_BRIDGE_LIVE_MIN_CONFIDENCE),
        allowed_asset_classes=frozenset(st.MT5_BRIDGE_LIVE_ALLOWED_ASSET_CLASSES),
        auto_exec_enabled=True,
        extra_pairs_allowed=getattr(st, "MT5_BRIDGE_LIVE_EXTRA_PAIRS", frozenset()),
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
    destinations.extend(_user_destinations(setup))
    return destinations
