"""Réconciliation des clôtures Kraken → ``personal_trades`` + notification.

⚠️ **Pourquoi ce module existe.** ``send_close`` n'était appelé que depuis
``mt5_sync``. Aucune réconciliation n'existait pour Kraken : le 2026-08-04,
quatre positions réelles ont touché leur stop — quatre pertes encaissées —
sans la moindre notification ni ligne de clôture. Le côté qui coûte de
l'argent était précisément celui qui n'était pas couvert.

Ce que Kraken donne, et que MT5 ne donne pas
--------------------------------------------
Chaque exécution porte deux champs qui suppriment toute heuristique :

``order_id``      l'ordre à l'origine de l'exécution. Pour une clôture c'est
                  le SL ou le TP posés à l'ouverture, dont les identifiants
                  sont déjà stockés dans ``mt5_pushes.bridge_response``. La
                  cause de sortie est donc **connue**, là où ``mt5_sync``
                  doit la deviner par proximité du prix de sortie.
``realized_pnl``  en USD, calculé par Kraken. On ne recalcule rien.

Vérifié sur les données réelles du 2026-08-04 : les treize exécutions issues
d'ordres du radar se raccrochent toutes à leur push. Les non reliées sont
des ordres passés à la main le 2026-08-02, ce qui est le comportement voulu.

La difficulté propre à Kraken : le nettage
-------------------------------------------
Kraken **nette les positions par symbole**. Trois ventes ETH successives ne
forment qu'une position, et un ordre d'achat pendant qu'on est vendeur ne
crée pas une position acheteuse : il réduit la vente. Le radar, lui, raisonne
par ordre.

D'où deux causes de clôture distinctes, et jamais confondues :

``SL`` / ``TP``   attribution exacte par ``order_id``. Cas dominant.
``NET``           la position a disparu sans qu'aucun SL/TP du push n'ait été
                  exécuté : un ordre opposé l'a absorbée. Le P&L est alors
                  celui que Kraken a réalisé sur cet ordre opposé.

Quand le P&L n'est pas attribuable sans ambiguïté, il reste ``None`` et la
clôture est enregistrée sans montant. Un chiffre inventé serait lu comme vrai.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TIMEOUT_SEC = 10.0

# Causes de sortie, dans le vocabulaire déjà utilisé par `personal_trades`.
CAUSE_SL = "SL"
CAUSE_TP = "TP1"
CAUSE_NET = "NET"


def _db_path() -> str:
    from backend.services.mt5_sync import _db_path as p
    return p()


# ─── Lecture des exécutions ────────────────────────────────────────────

async def fetch_fills(dest) -> list[dict[str, Any]]:
    """Exécutions récentes du compte Kraken. Liste vide si indisponible.

    Best-effort : la réconciliation ne doit jamais faire tomber le cycle.
    """
    url = f"{dest.bridge_url.rstrip('/')}/fills"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SEC) as c:
            r = await c.get(url, headers={"X-Bridge-Key": dest.bridge_api_key}
                            if dest.bridge_api_key else {})
        if r.status_code != 200:
            logger.warning(f"kraken_sync: /fills a repondu {r.status_code}")
            return []
        return r.json().get("fills") or []
    except Exception as e:
        logger.warning(f"kraken_sync: /fills injoignable ({url}) : {e}")
        return []


async def fetch_positions(dest) -> dict[str, float]:
    """Taille ouverte par symbole. ``{}`` si indisponible.

    Sert à distinguer « toujours ouvert » de « fermé par nettage ».
    """
    url = f"{dest.bridge_url.rstrip('/')}/positions"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SEC) as c:
            r = await c.get(url, headers={"X-Bridge-Key": dest.bridge_api_key}
                            if dest.bridge_api_key else {})
        if r.status_code != 200:
            return {}
        return {p["symbol"]: float(p.get("size") or 0)
                for p in (r.json().get("positions") or []) if p.get("symbol")}
    except Exception as e:
        logger.warning(f"kraken_sync: /positions injoignable : {e}")
        return {}


# ─── Les ordres poussés par le radar ───────────────────────────────────

def pushes_kraken() -> list[dict[str, Any]]:
    """Ordres Kraken confirmés, avec les identifiants de leurs SL/TP.

    Source : ``mt5_pushes``, la seule table qui relie un ordre broker au
    setup qui l'a produit.
    """
    sortie: list[dict[str, Any]] = []
    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute("""
            SELECT id, destination_id, pair, direction, pushed_at, bridge_response
              FROM mt5_pushes
             WHERE destination_id LIKE '%kraken%' AND ok = 1
             ORDER BY id
        """).fetchall()
    for r in rows:
        try:
            b = json.loads(r["bridge_response"] or "{}")
        except Exception:
            continue
        if not b.get("market_order_id"):
            continue
        sortie.append({
            "push_id": r["id"],
            "destination_id": r["destination_id"],
            "pair": r["pair"],
            "direction": r["direction"],
            "pushed_at": r["pushed_at"],
            "symbol": b.get("symbol"),
            "order_id": b.get("market_order_id"),
            "sl_order_id": b.get("sl_order_id"),
            "tp_order_id": b.get("tp_order_id"),
            "volume": float(b.get("volume") or 0),
            "entry_price": float(b.get("avg_price") or 0),
            "sl": b.get("sl"),
            "tp": b.get("tp"),
        })
    return sortie


# ─── Attribution des clôtures ──────────────────────────────────────────

def attribuer_clotures(pushes, fills) -> list[dict[str, Any]]:
    """Associe à chaque ordre sa clôture, quand elle est identifiable.

    L'attribution par ``order_id`` est exacte : un fill dont l'``order_id``
    est le SL d'un push ferme ce push, et la cause est connue. Aucun
    rapprochement par prix ou par horodatage n'est tenté.
    """
    par_sl = {p["sl_order_id"]: p for p in pushes if p.get("sl_order_id")}
    par_tp = {p["tp_order_id"]: p for p in pushes if p.get("tp_order_id")}

    clotures: dict[int, dict[str, Any]] = {}
    for f in fills:
        oid = f.get("order_id")
        push = par_sl.get(oid) or par_tp.get(oid)
        if push is None:
            continue
        cause = CAUSE_SL if oid in par_sl else CAUSE_TP
        c = clotures.setdefault(push["push_id"], {
            "push": push, "cause": cause, "taille": 0.0,
            "pnl_usd": 0.0, "notionnel": 0.0, "closed_at": None,
        })
        taille = float(f.get("size") or 0)
        c["taille"] += taille
        c["pnl_usd"] += float(f.get("realized_pnl") or 0)
        c["notionnel"] += taille * float(f.get("price") or 0)
        # La date retenue est celle de la dernière exécution : une clôture
        # peut arriver en plusieurs morceaux.
        t = f.get("fill_time")
        if t and (c["closed_at"] is None or t > c["closed_at"]):
            c["closed_at"] = t

    # Un ordre dont la PROPRE exécution porte un P&L réalisé n'a pas ouvert de
    # position : il a réduit celle qui existait déjà, Kraken nettant par
    # symbole. Le 2026-08-04, deux achats ETH ont ainsi été comptés comme des
    # positions ouvertes alors qu'ils fermaient un short — le garde-fou de
    # corrélation voyait donc ETH ouvert dans les deux sens et bloquait tout.
    #
    # Le montant réalisé appartient en toute rigueur à la position réduite,
    # pas à cet ordre. L'attribuer ici reste une approximation, mais elle
    # préserve la propriété qui compte : chaque P&L est compté une fois et
    # une seule, aucun n'est inventé.
    par_ordre = {p["order_id"]: p for p in pushes}
    for f in fills:
        push = par_ordre.get(f.get("order_id"))
        if push is None or not float(f.get("realized_pnl") or 0):
            continue
        if push["push_id"] in clotures:
            continue
        clotures[push["push_id"]] = {
            "push": push, "cause": CAUSE_NET, "taille": float(f.get("size") or 0),
            "pnl_usd": float(f.get("realized_pnl") or 0),
            "notionnel": float(f.get("size") or 0) * float(f.get("price") or 0),
            "closed_at": f.get("fill_time"),
        }

    for c in clotures.values():
        c["exit_price"] = (c["notionnel"] / c["taille"]) if c["taille"] else 0.0
        # Clôture partielle : on ne déclare fermé que ce qui l'est vraiment.
        c["complete"] = c["taille"] >= c["push"]["volume"] * 0.999
    return list(clotures.values())


def clotures_par_nettage(pushes, fills, positions, deja_closes) -> list[dict[str, Any]]:
    """Ordres dont la position a disparu sans exécution de leur SL/TP.

    Kraken nette par symbole : un ordre opposé peut absorber la position. Le
    P&L réalisé apparaît alors sur l'ordre opposé, pas sur le SL/TP — d'où
    une attribution qui ne peut pas être exacte. On enregistre la clôture,
    et le montant reste ``None`` plutôt que d'être deviné.
    """
    sortie = []
    for p in pushes:
        if p["push_id"] in deja_closes:
            continue
        sym = p.get("symbol")
        if sym and positions.get(sym, 0.0) > 0:
            continue  # encore de l'exposition sur ce symbole : rien à conclure
        if not positions:
            continue  # positions indisponibles : ne rien affirmer
        sortie.append({
            "push": p, "cause": CAUSE_NET, "taille": p["volume"],
            "pnl_usd": None, "exit_price": None, "complete": True,
            "closed_at": datetime.now(timezone.utc).isoformat(),
        })
    return sortie


# ─── Écriture et notification ──────────────────────────────────────────

def _ligne_existante(order_id: str) -> tuple[bool, bool]:
    """``(la ligne existe, elle est deja close)`` pour cet ordre.

    ``personal_trades.mt5_ticket`` ne porte qu'un index simple, **pas** de
    contrainte ``UNIQUE`` : un ``ON CONFLICT`` y échouerait. La dédup est
    donc explicite.
    """
    with sqlite3.connect(_db_path()) as c:
        r = c.execute(
            "SELECT status FROM personal_trades WHERE mt5_ticket = ?",
            (str(order_id),),
        ).fetchone()
    return (r is not None, bool(r and r[0] == "CLOSED"))


def materialiser_ouvertures(pushes) -> int:
    """Inscrit en ``personal_trades`` les ordres Kraken encore sans ligne.

    Les positions Kraken n'existaient nulle part tant qu'elles n'étaient pas
    fermées : ``personal_trades`` est pourtant la source unique de
    « qu'est-ce qui est ouvert » pour tout le système — cap par paire,
    garde-fou de corrélation, cockpit. Une position Kraken ouverte était donc
    invisible à ces trois mécanismes.

    Idempotent : une ligne existante n'est jamais réécrite.
    """
    ecrits = 0
    with sqlite3.connect(_db_path()) as c:
        for p in pushes:
            order_id = str(p["order_id"])
            deja = c.execute(
                "SELECT 1 FROM personal_trades WHERE mt5_ticket = ?",
                (order_id,),
            ).fetchone()
            if deja:
                continue
            c.execute("""
                INSERT INTO personal_trades
                    (user, pair, direction, entry_price, stop_loss, take_profit,
                     size_lot, status, created_at, mt5_ticket, is_auto)
                VALUES (?,?,?,?,?,?,?, 'OPEN', ?,?, 1)
            """, ("auto", p["pair"], p["direction"], p["entry_price"],
                  p.get("sl") or 0.0, p.get("tp") or 0.0, p["volume"],
                  p["pushed_at"], order_id))
            ecrits += 1
    if ecrits:
        logger.info(f"kraken_sync: {ecrits} position(s) ouverte(s) materialisee(s)")
    return ecrits


def enregistrer_cloture(cloture: dict[str, Any], eur_usd: float) -> dict | None:
    """Écrit la clôture dans ``personal_trades``. ``None`` si déjà connue.

    La ligne est créée si elle n'existe pas : les ordres Kraken n'étaient
    enregistrés nulle part jusqu'ici, l'historique doit donc être rattrapé.
    """
    p = cloture["push"]
    order_id = str(p["order_id"])
    existe, close = _ligne_existante(order_id)
    if close:
        return None

    pnl_eur = (round(cloture["pnl_usd"] / eur_usd, 2)
               if cloture.get("pnl_usd") is not None and eur_usd > 0 else None)
    closed_at = cloture.get("closed_at") or datetime.now(timezone.utc).isoformat()
    trade = {
        "pair": p["pair"], "direction": p["direction"],
        "entry_price": p["entry_price"], "exit_price": cloture.get("exit_price"),
        "pnl": pnl_eur, "close_reason": cloture["cause"],
        "mt5_ticket": order_id, "size_lot": p["volume"],
        "created_at": p["pushed_at"], "closed_at": closed_at,
        "signal_pattern": None, "signal_confidence": None,
    }
    with sqlite3.connect(_db_path()) as c:
        if existe:
            c.execute("""
                UPDATE personal_trades
                   SET status = 'CLOSED',
                       exit_price = COALESCE(?, exit_price),
                       pnl = COALESCE(?, pnl),
                       closed_at = COALESCE(closed_at, ?),
                       close_reason = COALESCE(close_reason, ?)
                 WHERE mt5_ticket = ?
            """, (cloture.get("exit_price"), pnl_eur, closed_at,
                  cloture["cause"], order_id))
        else:
            # `stop_loss` et `take_profit` sont NOT NULL. Le bridge ne
            # renvoyait que les identifiants des ordres SL/TP, pas leurs
            # niveaux : ils valent 0 pour les trades antérieurs au correctif,
            # ce que le message de clôture n'affiche de toute façon pas.
            c.execute("""
                INSERT INTO personal_trades
                    (user, pair, direction, entry_price, stop_loss,
                     take_profit, size_lot, status, exit_price, pnl,
                     created_at, closed_at, close_reason, mt5_ticket, is_auto)
                VALUES (?,?,?,?,?,?,?, 'CLOSED', ?,?,?,?,?,?, 1)
            """, ("auto", p["pair"], p["direction"], p["entry_price"],
                  p.get("sl") or 0.0, p.get("tp") or 0.0, p["volume"],
                  cloture.get("exit_price"), pnl_eur, p["pushed_at"],
                  closed_at, cloture["cause"], order_id))
    return trade


async def reconcile() -> int:
    """Détecte les clôtures Kraken, les enregistre et les notifie.

    Retourne le nombre de clôtures nouvellement traitées. Best-effort de
    bout en bout : aucune exception ne remonte au planificateur.
    """
    from backend.services import bridge_destinations as bd, risk_eur

    try:
        dests = [d for d in bd.admin_destinations()
                 if d.bridge_type in ("kraken", "kraken_spot")]
    except Exception as e:
        logger.warning(f"kraken_sync: destinations indisponibles : {e}")
        return 0

    total = 0
    eur_usd = risk_eur.taux_eur_usd()
    for dest in dests:
        fills = await fetch_fills(dest)
        if not fills:
            continue
        positions = await fetch_positions(dest)
        pushes = [p for p in pushes_kraken()
                  if p["destination_id"] == dest.destination_id]
        if not pushes:
            continue

        # Les ouvertures d'abord : une position invisible échappe au cap par
        # paire et au garde-fou de corrélation.
        materialiser_ouvertures(pushes)

        clotures = [c for c in attribuer_clotures(pushes, fills) if c["complete"]]
        vus = {c["push"]["push_id"] for c in clotures}
        clotures += clotures_par_nettage(pushes, fills, positions, vus)

        for c in clotures:
            trade = enregistrer_cloture(c, eur_usd)
            if trade is None:
                continue
            total += 1
            logger.warning(
                f"kraken_sync: cloture {trade['pair']} {trade['direction']} "
                f"cause={trade['close_reason']} pnl={trade['pnl']} EUR "
                f"(push #{c['push']['push_id']})"
            )
            try:
                from backend.services.telegram_service import send_close
                await send_close(trade)
            except Exception as e:
                logger.warning(f"kraken_sync: notification de cloture echouee : {e}")
    return total
