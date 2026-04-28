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
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config.settings import (
    MT5_BRIDGE_ALLOWED_ASSET_CLASSES,
    MT5_BRIDGE_API_KEY,
    MT5_BRIDGE_ENABLED,
    MT5_BRIDGE_MIN_CONFIDENCE,
    MT5_BRIDGE_URL,
)


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
    """Retourne la config admin legacy depuis l'env, ou ``None`` si absente."""
    if not (MT5_BRIDGE_ENABLED and MT5_BRIDGE_URL and MT5_BRIDGE_API_KEY):
        return None
    return BridgeConfig(
        destination_id="admin_legacy",
        user_id=None,
        bridge_url=MT5_BRIDGE_URL.rstrip("/"),
        bridge_api_key=MT5_BRIDGE_API_KEY,
        min_confidence=float(MT5_BRIDGE_MIN_CONFIDENCE),
        allowed_asset_classes=frozenset(MT5_BRIDGE_ALLOWED_ASSET_CLASSES),
        auto_exec_enabled=True,
    )


def _user_destinations(setup: Any) -> list[BridgeConfig]:
    """Retourne les destinations users (Premium tier) pour ce setup.

    V1 retourne ``[]``. Phase C élargira en interrogeant ``users_service``
    pour lister les Premium avec auto-exec activé et la pair dans leur
    watchlist.
    """
    return []


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
