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
    """

    destination_id: str
    user_id: int | None
    bridge_url: str
    bridge_api_key: str
    min_confidence: float
    allowed_asset_classes: frozenset[str]
    auto_exec_enabled: bool


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
        try:
            destinations.append(
                BridgeConfig(
                    destination_id=f"user:{user['id']}",
                    user_id=int(user["id"]),
                    bridge_url=cfg["bridge_url"].rstrip("/"),
                    bridge_api_key=cfg["bridge_api_key"],
                    min_confidence=float(mb.MT5_BRIDGE_MIN_CONFIDENCE),
                    allowed_asset_classes=frozenset(
                        mb.MT5_BRIDGE_ALLOWED_ASSET_CLASSES
                    ),
                    auto_exec_enabled=True,
                )
            )
        except (KeyError, TypeError, ValueError):
            # broker_config malformé pour ce user — skip silencieux
            continue
    return destinations


def resolve_destinations(setup: Any) -> list[BridgeConfig]:
    """Liste toutes les destinations vers lesquelles ce setup doit être poussé.

    Ordre : ``admin_legacy`` en premier (rétro-compat), puis users (Phase C).
    Liste possiblement vide — équivalent à l'ancien
    ``mt5_bridge.is_configured() == False``.
    """
    destinations: list[BridgeConfig] = []
    admin = _admin_legacy_destination()
    if admin is not None:
        destinations.append(admin)
    destinations.extend(_user_destinations(setup))
    return destinations
