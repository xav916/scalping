"""Restreint la population de signaux à celle qui a RÉELLEMENT été tradée.

Pourquoi ce module existe
-------------------------
L'audit du 2026-08-06 a montré que le backtest ne valide pas la population qui
trade : 48,2 % de ventes en simulation contre 90,5 % en production.

L'enquête a écarté deux explications et en a trouvé une troisième :

1. Ce n'est **pas** un filtre en aval qui déséquilibre — le déséquilibre est
   déjà dans les signaux qui atteignent le dispatch.
2. Ce n'est **pas** une inversion de sens du backtest — cette lecture venait
   d'une population marginale sans rapport.
3. C'est que ``verdict_action`` **n'est pas la décision d'auto-exécution**.
   489 des 524 ordres réels sur XAU/USD correspondent à des signaux étiquetés
   ``SKIP``. L'auto-exec est explicitement « décorrélé du verdict TAKE/WAIT/SKIP »
   (cf. l'en-tête de ``mt5_bridge.py`` et ``RESPECT_VERDICT=false``) : il a fallu
   l'en découpler parce que des SKIP massifs sur XAU/WTI/EUR coupaient tous les
   pushes.

⚠️ **Le verdict et l'auto-exec sont deux décisions différentes par construction,
et aucune ne peut être dérivée de l'autre.** Filtrer sur ``verdict_action='TAKE'``
sélectionne le produit consultatif destiné à l'humain — précisément ce qui NE
trade pas. C'est l'erreur que ce module rend impossible.

La seule vérité terrain est ``mt5_pushes`` : ce qui est réellement parti au
bridge. L'appariement est mesuré comme quasi parfait — 4 513 pushes sur 4 514
retrouvent leur signal à la paire, au sens et au prix à 5 décimales, tous à
moins d'une minute.

Ce module ne modifie rien et n'écrit rien : il ne fait que restreindre.
"""
from __future__ import annotations

import bisect
import sqlite3
from datetime import datetime, timedelta, timezone

# Un push est écrit juste après l'émission du signal. 120 s laisse de la marge
# pour la latence du cycle sans risquer d'attraper le signal du cycle suivant
# (les cycles sont bien plus espacés). Mesuré : 100 % des appariements tombent
# sous 60 s.
TOLERANCE_SECONDS = 120

# `mt5_pushes.entry_price_5dp` est déjà arrondi à 5 décimales — on aligne la
# clé des signaux dessus. C'est ce qui rend l'appariement quasi exact plutôt
# que temporel.
PRICE_DECIMALS = 5


def _parse(raw) -> datetime | None:
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d


def _signals_db() -> str:
    from backend.services.backtest_service import _DB_PATH
    return str(_DB_PATH)


def _pushes_db() -> str:
    from backend.services.trade_log_service import _DB_PATH
    return str(_DB_PATH)


def _index_signals(conn: sqlite3.Connection) -> dict:
    """(paire, sens, prix arrondi) -> liste triée de (instant, id)."""
    idx: dict = {}
    for sid, pair, direction, emitted_at, entry in conn.execute(
        "SELECT id, pair, direction, emitted_at, entry_price FROM signals "
        "WHERE entry_price IS NOT NULL"
    ):
        moment = _parse(emitted_at)
        if moment is None:
            continue
        cle = (pair, direction, round(float(entry), PRICE_DECIMALS))
        idx.setdefault(cle, []).append((moment, sid))
    for v in idx.values():
        v.sort()
    return idx


def traded_signal_ids(
    destination: str | None = None,
    tolerance_seconds: int = TOLERANCE_SECONDS,
) -> set[int]:
    """Identifiants des signaux réellement envoyés au bridge.

    ``destination`` restreint à une destination (``admin_live``, ``user:2``…).
    Un même signal peut donner plusieurs pushes (une par destination) : on rend
    un ensemble, donc il n'est compté qu'une fois.
    """
    with sqlite3.connect(_signals_db()) as sc:
        idx = _index_signals(sc)

    sql = "SELECT pair, direction, entry_price_5dp, pushed_at FROM mt5_pushes"
    params: tuple = ()
    if destination:
        sql += " WHERE destination_id = ?"
        params = (destination,)

    trouves: set[int] = set()
    limite = timedelta(seconds=tolerance_seconds)
    with sqlite3.connect(_pushes_db()) as pc:
        for pair, direction, prix, pushed_at in pc.execute(sql, params):
            moment = _parse(pushed_at)
            if moment is None or prix is None:
                continue
            candidats = idx.get((pair, direction, round(float(prix), PRICE_DECIMALS)))
            if not candidats:
                continue
            i = bisect.bisect_left(candidats, (moment, -1))
            meilleur_id, meilleur_ecart = None, None
            for j in (i - 1, i, i + 1):
                if 0 <= j < len(candidats):
                    ecart = abs(candidats[j][0] - moment)
                    if meilleur_ecart is None or ecart < meilleur_ecart:
                        meilleur_ecart, meilleur_id = ecart, candidats[j][1]
            if meilleur_id is not None and meilleur_ecart <= limite:
                trouves.add(meilleur_id)
    return trouves


def population_summary(destination: str | None = None) -> dict:
    """Compare la population complète des signaux à celle réellement tradée.

    Sert à répondre en une commande à « le backtest porte-t-il sur ce qui
    trade ? » — la question qui n'avait jamais été posée.
    """
    ids = traded_signal_ids(destination=destination)

    resume = {
        "destination": destination or "toutes",
        "signaux_total": 0,
        "signaux_trades": len(ids),
        "ventes_pct_total": None,
        "ventes_pct_trades": None,
        "take_pct_parmi_trades": None,
        "par_paire": {},
    }
    if not ids:
        return resume

    with sqlite3.connect(_signals_db()) as sc:
        lignes = sc.execute(
            "SELECT id, pair, direction, verdict_action FROM signals"
        ).fetchall()

    tot_n = tot_s = tr_n = tr_s = tr_take = 0
    par_paire: dict = {}
    for sid, pair, direction, verdict in lignes:
        est_vente = str(direction).lower().startswith("s")
        tot_n += 1
        tot_s += est_vente
        if sid in ids:
            tr_n += 1
            tr_s += est_vente
            tr_take += (verdict == "TAKE")
            e = par_paire.setdefault(pair, {"n": 0, "ventes": 0})
            e["n"] += 1
            e["ventes"] += est_vente

    resume["signaux_total"] = tot_n
    resume["ventes_pct_total"] = round(100 * tot_s / tot_n, 1) if tot_n else None
    resume["ventes_pct_trades"] = round(100 * tr_s / tr_n, 1) if tr_n else None
    resume["take_pct_parmi_trades"] = round(100 * tr_take / tr_n, 1) if tr_n else None
    resume["par_paire"] = {
        p: {"n": v["n"], "ventes_pct": round(100 * v["ventes"] / v["n"], 1)}
        for p, v in sorted(par_paire.items(), key=lambda kv: -kv[1]["n"])
    }
    return resume


if __name__ == "__main__":
    import json
    print(json.dumps(population_summary(), indent=2, ensure_ascii=False))
