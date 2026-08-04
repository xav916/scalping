"""Délai minimum entre deux ordres sur un même symbole (2026-08-04).

⚠️ **Pourquoi ce module existe.** Le 2026-08-04, six ordres ETH sont partis
en vingt-sept minutes sur le compte Kraken, dont deux de sens opposés à la
même seconde :

    17:50:47 sell · 17:56:42 sell · 17:59:41 sell
    18:14:38 buy  · 18:17:37 sell · 18:17:37 buy

Chaque ordre paie des frais, et sur crypto les frais valent 2,6× l'edge
mesuré. La déduplication existante ne l'empêche pas : elle porte sur
``(destination, jour, paire, sens, prix d'entrée)``, donc un prix d'entrée
qui bouge d'un centime rouvre la porte. Le plafond de notionnel borne la
taille d'un ordre, pas leur fréquence.

Le délai est déclaré **par destination**, et c'est essentiel
--------------------------------------------------------------
Mesure sur trente jours d'ordres réels, part des intervalles courts entre
deux ordres consécutifs sur un même symbole :

=================  =====  =======  ========  ==========
destination        <5min  <15min   médiane   verdict
=================  =====  =======  ========  ==========
``admin_kraken``     60%     100%    3 min   pathologique
``admin_live``        0%       0%  204 min   sain
``admin_legacy``      0%       0%  210 min   sain
``user:2``            3%      45%   18 min   **fréquent**
=================  =====  =======  ========  ==========

Un délai global de quinze minutes bloquerait **45 % des ordres de Cédric**.
D'où un réglage par destination, à zéro partout sauf là où le besoin est
démontré. Le compte d'un client ne change pas parce qu'on corrige le nôtre.

Ce que le délai compte
----------------------
Toute ligne de ``mt5_pushes``, confirmée ou non. Une réservation non
confirmée signifie qu'un ordre a **peut-être** atteint le marché : la
compter est le choix prudent. Les envois dont on sait qu'ils n'ont rien
atteint sont supprimés par ``PushLedger.release`` et ne comptent donc pas.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Garde-fou global, à zéro : le délai est un opt-in par destination. Un
# défaut non nul changerait le comportement de comptes qu'on n'a pas mesurés.
ORDER_COOLDOWN_SEC = int(os.getenv("ORDER_COOLDOWN_SEC", "0"))


def _db_path() -> str:
    from backend.services.trade_log_service import _DB_PATH
    return str(_DB_PATH)


def delai_requis(dest) -> int:
    """Délai minimum en secondes pour cette destination. ``0`` ⇒ désactivé."""
    if dest is None:
        return ORDER_COOLDOWN_SEC
    from backend.services import destinations_registry as _reg
    d = _reg.get(getattr(dest, "destination_id", None))
    if d is not None and d.order_cooldown_sec:
        return int(d.order_cooldown_sec)
    return ORDER_COOLDOWN_SEC


def secondes_depuis_dernier_ordre(destination_id: str, pair: str) -> float | None:
    """Âge du dernier ordre sur ce couple. ``None`` s'il n'y en a jamais eu.

    Best-effort : toute erreur de base retourne ``None``, ce qui autorise
    l'ordre. Un délai est une optimisation de coût, pas une protection —
    il ne doit pas bloquer le trading si la base est indisponible.
    """
    try:
        with sqlite3.connect(f"file:{_db_path()}?mode=ro", uri=True, timeout=5) as c:
            row = c.execute(
                "SELECT MAX(pushed_at) FROM mt5_pushes "
                " WHERE destination_id = ? AND pair = ?",
                (destination_id, pair),
            ).fetchone()
    except Exception as e:
        logger.debug(f"order_cooldown: lecture impossible : {e}")
        return None
    if not row or not row[0]:
        return None
    try:
        dernier = datetime.fromisoformat(str(row[0]))
    except ValueError:
        return None
    if dernier.tzinfo is None:
        dernier = dernier.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dernier).total_seconds()


def en_cooldown(dest, pair: str) -> tuple[bool, int]:
    """``(bloqué, secondes restantes)`` pour ce couple destination/symbole."""
    delai = delai_requis(dest)
    if delai <= 0 or dest is None:
        return False, 0
    age = secondes_depuis_dernier_ordre(
        getattr(dest, "destination_id", ""), pair)
    if age is None or age >= delai:
        return False, 0
    return True, int(delai - age)
