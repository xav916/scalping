"""Auto-régulateur PnL par pair sur fenêtre glissante.

Complément de `stop_loss_alerts` qui détecte les rafales courtes (≥ 3 SL
en 1h). Ce module-ci capture le **saignement chronique diffus** invisible
au watchdog rafale : ex XAG/USD = 53 SL sur 6 semaines (~1.3 SL/jour)
qui n'a jamais déclenché 3 SL en 1h mais a accumulé -783€ (cf audit
2026-05-13).

## Mécanisme

Sur fenêtre glissante de N derniers trades (default 30) :
- Si `sum_pnl / capital < pause_threshold_pct` (default -3%) → pause 14j
- Si pair pausée et expires_at < now → resume (laisse re-trader, ré-évaluera)
- Sample minimum requis : MIN_SAMPLE trades (default 10) pour éviter
  faux positifs sur sample bias
- Plancher d'âge : un trade clôturé il y a plus de MAX_AGE_DAYS (default 90)
  ne compte plus. ⛔ Il n'y en avait AUCUN jusqu'au 29/08/2026 : l'argent était
  tenu en pause sur le compte réel IC Markets par 30 trades de MAI passés sur
  l'ancien compte démo MetaQuotes. Une paire dormante ne pouvait pas se défaire
  de son passé, faute de trader — le verdict et la donnée qui l'aurait révisé
  s'interdisaient mutuellement.
- Portée par DESTINATION : chaque compte est jugé sur ses propres clôtures, et
  une pause ne vaut que pour le sien. ⛔ Second volet du même défaut : le
  plancher borne le passé dans le temps, il ne dit pas de quel compte on parle.
  `destination` NULL = portée globale, et l'héritage va du particulier vers le
  global — jamais l'inverse, sans quoi séparer les comptes relâcherait des
  pauses en cours.

Auto-resume : pas de smart resume basé sur V1 quiet (cf stop_loss_alerts)
parce que le saignement chronique n'a pas de "rafale qui s'arrête" — on
laisse le pair re-trader après 14j et on observe.

## Hystérésis vs flapping

Pas de logique anti-flapping spéciale : sur 14 jours de cool-off,
même si le pair re-trade et perd 1-2 trades juste après resume,
il faut atteindre le seuil cumul -3% pour re-pause. Donc le cycle naturel
pause → 14j → resume → drift jusqu'à -3% → re-pause limite l'oscillation.

## Auto-pause vs MT5_BRIDGE_BLOCKED_PAIRS

Les deux co-existent. `MT5_BRIDGE_BLOCKED_PAIRS` = override manuel
permanent (env var). `auto_paused_pairs` = décisions auto révisées
toutes les heures. Le bridge check les deux en cascade ; n'importe lequel
qui bloque → "pair_blocked" ou "pair_auto_paused".
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _db_path() -> str:
    from backend.services.trade_log_service import _DB_PATH

    return str(_DB_PATH)


# ─── Schema ─────────────────────────────────────────────────────────────


_SCHEMA_ENSURED = False


def _ensure_schema() -> None:
    """Crée la table auto_paused_pairs si pas déjà là.

    Idempotent. Appelé au premier accès dans le process.
    """
    global _SCHEMA_ENSURED
    if _SCHEMA_ENSURED:
        return
    with sqlite3.connect(_db_path()) as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS auto_paused_pairs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT NOT NULL,
                paused_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                reason TEXT NOT NULL,
                pnl_pct REAL,
                trades_in_window INTEGER,
                resumed_at TEXT,
                resumed_reason TEXT,
                destination TEXT
            )
            """
        )
        # Migration des bases anterieures au 29/08/2026 : la colonne n'existait
        # pas. Les lignes deja posees restent a NULL, donc de portee GLOBALE —
        # elles continuent de bloquer toutes les destinations jusqu'a leur
        # terme. ⛔ Un correctif de mesure ne doit relacher aucune pause en
        # cours.
        colonnes = {r[1] for r in c.execute("PRAGMA table_info(auto_paused_pairs)")}
        if "destination" not in colonnes:
            c.execute("ALTER TABLE auto_paused_pairs ADD COLUMN destination TEXT")
        c.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_app_pair_active
              ON auto_paused_pairs(pair) WHERE resumed_at IS NULL
            """
        )
    _SCHEMA_ENSURED = True


# ─── Configuration ──────────────────────────────────────────────────────


def _config() -> dict[str, Any]:
    """Lit la config depuis settings (env vars overrides possibles)."""
    from config.settings import (
        PAIR_PNL_REGULATOR_ENABLED,
        PAIR_PNL_REGULATOR_WINDOW_TRADES,
        PAIR_PNL_REGULATOR_MIN_SAMPLE,
        PAIR_PNL_REGULATOR_PAUSE_THRESHOLD_PCT,
        PAIR_PNL_REGULATOR_PAUSE_DURATION_DAYS,
        PAIR_PNL_REGULATOR_MAX_AGE_DAYS,
        TRADING_CAPITAL,
    )
    return {
        "enabled": PAIR_PNL_REGULATOR_ENABLED,
        "window_trades": PAIR_PNL_REGULATOR_WINDOW_TRADES,
        "min_sample": PAIR_PNL_REGULATOR_MIN_SAMPLE,
        "pause_threshold_pct": PAIR_PNL_REGULATOR_PAUSE_THRESHOLD_PCT,
        "pause_duration_days": PAIR_PNL_REGULATOR_PAUSE_DURATION_DAYS,
        "max_age_days": PAIR_PNL_REGULATOR_MAX_AGE_DAYS,
        "capital": TRADING_CAPITAL,
    }


# ─── Core metrics ───────────────────────────────────────────────────────


def _plancher_age(max_age_days: int | None = None) -> str | None:
    """Date ISO avant laquelle un trade ne compte plus, ou ``None`` si desarme.

    ⛔ **Pourquoi ce plancher existe.** `compute_window_metrics` prenait les N
    derniers trades sans jamais regarder leur age. Le 29/08/2026, l'argent
    etait tenu en pause sur le compte reel IC Markets par 30 trades clotures
    entre le 7 et le 12 MAI sur l'ancien compte demo MetaQuotes (tickets a
    69 millions, `destination_id` NULL) — trois mois et demi, un autre
    courtier, et la periode que le systeme lui-meme a declaree contaminee par
    le bug de deduplication corrige le 04/08.

    🔑 Et le verrou etait circulaire : la paire ne pouvait pas trader a cause
    d'une mesure, et la mesure ne pouvait pas se rafraichir puisqu'elle ne
    tradait pas. **Un passe mort ne peut pas etre revise par les faits.**

    ⚠️ Ce que le plancher coute : une paire trop lente pour reunir
    `min_sample` clotures dans la fenetre d'age n'est plus jugee du tout —
    `keep_active` faute d'echantillon. C'est assume : « pas assez de preuves
    recentes » est une reponse plus honnete que « coupable sur des preuves
    perimees », et les rafales courtes restent couvertes par
    `stop_loss_alerts`, qui ne regarde que la derniere heure.
    """
    if max_age_days is None:
        max_age_days = _config()["max_age_days"]
    if not max_age_days or max_age_days <= 0:
        return None
    return (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()


def _somme_en_r(rows) -> tuple[float, int]:
    """``(somme des R, nombre de trades mesurables)``.

    🔑 **Pourquoi le R et non l'euro.** Mesuré le 2026-09-04 sur l'or de la
    démo : la même fenêtre de 30 trades vaut **−104,60 €** — soit −16 %, bien
    sous le seuil de pause — et **+0,31 R**, c'est-à-dire plate. Tous les lots
    y étaient à 0,01 ; ce qui variait, c'était la distance au stop, **d'un
    facteur 10,4** (8 à 84 points). Perdre 52 € sur un stop à 78 points, c'est
    perdre 1 R, exactement comme perdre 15 € sur un stop à 21 points.

    Sommer des euros sur des trades de risques incomparables ne mesure pas une
    espérance : ça mesure un mélange de largeurs de stop. La paire aux stops
    larges paraît coupable à talent égal — et c'est ainsi que l'or de la démo
    s'est retrouvé en pause jusqu'au 17/09, et l'argent du réel le 29/08.

    ⛔ Un trade dont le risque n'est pas lisible n'est PAS compté zéro : il est
    écarté et **dénombré**. `ea_closed_trades` ne porte ni `stop_loss` ni
    `size_lot` — aucun trade EA n'est donc mesurable. C'est sans effet sur le
    mode par destination, qui exclut déjà l'EA de la fenêtre.

    ⛔ **Le risque se convertit en EUROS avant la division.** Première version :
    `pnl / (entrée − stop)` — des euros divisés par une distance en PRIX. Ça ne
    tombe juste que pour l'or à 0,01 lot, par coïncidence (1 once, 1 $ ≈ 1 €).
    Sondée sur la production avant déploiement, elle rendait **−69 R sur 30
    trades de WTI** — soit 2,3 R perdus par trade, ce qui est impossible si le
    stop tient — parce qu'à 0,1 lot une distance de 2,25 $ vaut 225 $ de
    risque, pas 2,25. Elle aurait posé deux pauses fausses.

    `risk_eur.calculer` porte déjà les tailles de contrat (100 onces sur l'or,
    100 barils sur le WTI, 100 000 unités sur le forex) et le change. Une
    seconde arithmétique du risque serait l'endroit exact où les deux chiffres
    divergeraient sans que rien ne le dise.
    """
    from backend.services.risk_eur import calculer

    somme, n = 0.0, 0
    for r in rows:
        try:
            entree, stop, lot = r["entry_price"], r["stop_loss"], r["size_lot"]
        except (KeyError, IndexError):
            continue
        if entree is None or stop is None or not lot:
            continue
        mesure = calculer(r["pair_mesure"], entree, stop, 0.0, lot)
        if not mesure or mesure["risque_eur"] <= 0:
            continue
        somme += float(r["pnl"]) / mesure["risque_eur"]
        n += 1
    return somme, n


def _tickets_exclus() -> frozenset[int]:
    """Délègue à `tickets_exclus` — cf. ce module pour la raison d'être."""
    from backend.services.tickets_exclus import tickets_exclus
    return tickets_exclus()


def _filtre_exclusion(exclus: frozenset[int]) -> str:
    """Délègue à `tickets_exclus.filtre_sql`."""
    from backend.services.tickets_exclus import filtre_sql
    return filtre_sql(exclus)


def tickets_exclus_presents(pair: str) -> list[int]:
    """Tickets exclus qui existent RÉELLEMENT pour cette paire.

    Sert à inscrire l'exclusion dans le relevé. ⚠️ Sans cette trace, une
    fenêtre qui écarte en silence est indiscernable d'une fenêtre qui n'a rien
    écarté — et le chiffre affiché ne serait pas refaisable par un lecteur.
    """
    exclus = _tickets_exclus()
    if not exclus:
        return []
    _ensure_schema()
    from backend.services import ea_closed_trades_service as _eact
    _eact._ensure_schema()
    trous = ",".join("?" * len(exclus))
    ex = tuple(exclus)
    with sqlite3.connect(_db_path()) as c:
        rows = c.execute(
            f"""
            SELECT DISTINCT CAST(mt5_ticket AS INTEGER) FROM personal_trades
             WHERE pair = ? AND status = 'CLOSED' AND is_auto = 1
               AND pnl IS NOT NULL AND CAST(mt5_ticket AS INTEGER) IN ({trous})
            UNION
            SELECT DISTINCT CAST(mt5_ticket AS INTEGER) FROM ea_closed_trades
             WHERE pair = ? AND CAST(mt5_ticket AS INTEGER) IN ({trous})
            """,
            (pair,) + ex + (pair,) + ex,
        ).fetchall()
    return sorted(int(r[0]) for r in rows if r[0] is not None)


def compute_window_metrics(pair: str, window_trades: int,
                           max_age_days: int | None = None,
                           destination: str | None = None) -> dict[str, Any]:
    """Retourne PnL agrégé sur les N derniers trades fermés.

    Deux sources possibles :
    - ``personal_trades`` : trades admin Xavier (is_auto=1)
    - ``ea_closed_trades`` : trades reportés par l'EA des users Premium

    ``destination`` **restreint la fenêtre à un compte**. Sans lui, le
    comportement historique est conservé : union de toutes les sources et de
    toutes les destinations.

    ⛔ **Pourquoi cette restriction.** La fenêtre mélangeait démo, réel et
    anciens courtiers dans un seul verdict. Le 29/08/2026, l'argent était tenu
    en pause sur le compte **réel IC Markets** par 30 trades passés sur
    l'ancien compte démo MetaQuotes. Le plancher d'âge borne les dégâts dans le
    temps ; seule la séparation par destination répond à « ce compte-ci
    saigne-t-il ? ».

    ⚠️ Quand une destination est nommée, les trades de l'EA sont **écartés** :
    ils viennent des comptes des clients Premium, qui ne sont pas cette
    destination. Les agréger reviendrait à refaire, entre comptes, l'erreur
    qu'on corrige entre courtiers.
    """
    _ensure_schema()
    # ea_closed_trades schema ensure aussi (idempotent)
    from backend.services import ea_closed_trades_service as _eact
    _eact._ensure_schema()

    # ⛔ L'exclusion se fait EN SQL, avant le LIMIT. La faire en Python après
    # coup rendrait une fenêtre de moins de `window_trades` clôtures
    # comptables : on noterait la paire sur 29 trades en annonçant 30.
    exclus = _tickets_exclus()
    filtre = _filtre_exclusion(exclus)
    ex = tuple(exclus)

    # ⛔ Le plancher d'age s'applique EN SQL, avant le LIMIT — meme raison que
    # l'exclusion par ticket juste au-dessus. Filtrer apres coup rendrait une
    # fenetre plus courte que `window_trades` en pretendant l'inverse.
    plancher = _plancher_age(max_age_days)
    filtre_age = " AND closed_at >= ?" if plancher else ""
    age = (plancher,) if plancher else ()

    filtre_dest = " AND destination_id = ?" if destination else ""
    dest = (destination,) if destination else ()
    # ⛔ Nommer une destination écarte l'EA : voir la docstring. Le fragment
    # d'UNION disparaît alors entièrement — le laisser avec un filtre neutre
    # ferait rentrer par la fenêtre ce que la porte vient d'exclure.
    bloc_ea = "" if destination else f"""
            UNION ALL
            SELECT pnl, closed_at, entry_price, NULL AS stop_loss,
                   NULL AS size_lot, NULL AS pair_mesure,
                   'ea_' || user_id AS source FROM ea_closed_trades
             WHERE pair = ?{filtre}{filtre_age}"""
    params_ea = () if destination else (pair,) + ex + age
    # Le decompte "ecartes par l'age" suit exactement le meme perimetre que la
    # fenetre : meme destination, memes sources. Sinon il annoncerait des
    # trades qui n'auraient de toute facon jamais compte.
    bloc_ea_age = "" if destination else f"""
                    UNION ALL
                    SELECT closed_at FROM ea_closed_trades
                     WHERE pair = ?{filtre} AND closed_at < ?"""
    params_ea_age = () if destination else (pair,) + ex + (plancher,)

    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            f"""
            SELECT pnl, closed_at, entry_price, stop_loss, size_lot,
                   ? AS pair_mesure, 'admin' AS source FROM personal_trades
             WHERE pair = ? AND status = 'CLOSED'
               AND is_auto = 1 AND pnl IS NOT NULL{filtre}{filtre_age}{filtre_dest}{bloc_ea}
            ORDER BY closed_at DESC LIMIT ?
            """,
            (pair, pair) + ex + age + dest + params_ea + (window_trades,),
        ).fetchall()
        # ⚠️ Une fenetre qui ecarte en silence est indiscernable d'une fenetre
        # qui n'a rien ecarte, et le chiffre affiche ne serait pas refaisable
        # par un lecteur. Meme exigence que pour les tickets exclus.
        n_hors_age = 0
        if plancher:
            n_hors_age = c.execute(
                f"""
                SELECT COUNT(*) FROM (
                    SELECT closed_at FROM personal_trades
                     WHERE pair = ? AND status = 'CLOSED'
                       AND is_auto = 1 AND pnl IS NOT NULL{filtre}{filtre_dest}
                       AND closed_at < ?{bloc_ea_age}
                )
                """,
                (pair,) + ex + dest + (plancher,) + params_ea_age,
            ).fetchone()[0]
    ecartes = tickets_exclus_presents(pair)
    n = len(rows)
    if n == 0:
        return {
            "n": 0, "sum_pnl": 0.0, "wins": 0, "wr": 0.0,
            "somme_r": 0.0, "n_mesurables": 0, "n_non_mesurables": 0,
            "oldest_at": None, "newest_at": None,
            "by_source": {}, "excluded_tickets": ecartes,
            "plancher_age": plancher, "n_hors_age": n_hors_age,
            "destination": destination,
        }
    sum_pnl = sum(r["pnl"] for r in rows)
    wins = sum(1 for r in rows if r["pnl"] > 0)
    somme_r, n_mesurables = _somme_en_r(rows)
    # Breakdown par source (pour debug/dashboard : qui contribue combien)
    by_source: dict[str, dict[str, Any]] = {}
    for r in rows:
        src = r["source"]
        if src not in by_source:
            by_source[src] = {"n": 0, "sum_pnl": 0.0, "wins": 0}
        by_source[src]["n"] += 1
        by_source[src]["sum_pnl"] += r["pnl"]
        if r["pnl"] > 0:
            by_source[src]["wins"] += 1
    for src in by_source:
        by_source[src]["sum_pnl"] = round(by_source[src]["sum_pnl"], 2)
    return {
        "n": n,
        "sum_pnl": round(sum_pnl, 2),
        "somme_r": round(somme_r, 3),
        "n_mesurables": n_mesurables,
        "n_non_mesurables": n - n_mesurables,
        "wins": wins,
        "wr": round(100.0 * wins / n, 1),
        "oldest_at": rows[-1]["closed_at"],
        "newest_at": rows[0]["closed_at"],
        "by_source": by_source,
        "excluded_tickets": ecartes,
        "plancher_age": plancher,
        "n_hors_age": n_hors_age,
        "destination": destination,
    }


# ─── Pause state ────────────────────────────────────────────────────────


def get_active_pause(pair: str, destination: str | None = None) -> dict[str, Any] | None:
    """Retourne la pause active (resumed_at IS NULL) ou None.

    🔑 **Héritage, comme `pair_admission_state`.** Une pause dont la
    ``destination`` est NULL est de portée GLOBALE : elle vaut pour tous les
    comptes. Interrogée pour une destination précise, cette fonction rend
    d'abord la pause propre à ce compte, et à défaut la pause globale.

    ⛔ L'ordre compte, et il est fail-CLOSED : séparer les destinations ne doit
    relâcher aucune pause déjà posée. Toutes les lignes antérieures au
    29/08/2026 ont ``destination`` à NULL et continuent donc de tout bloquer.
    """
    _ensure_schema()
    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        if destination:
            row = c.execute(
                """
                SELECT * FROM auto_paused_pairs
                 WHERE pair = ? AND resumed_at IS NULL
                   AND (destination = ? OR destination IS NULL)
                 ORDER BY (destination IS NULL), id DESC LIMIT 1
                """,
                (pair, destination),
            ).fetchone()
        else:
            row = c.execute(
                """
                SELECT * FROM auto_paused_pairs
                 WHERE pair = ? AND resumed_at IS NULL AND destination IS NULL
                 ORDER BY id DESC LIMIT 1
                """,
                (pair,),
            ).fetchone()
    return dict(row) if row else None


def _pause_exacte(pair: str, destination: str | None) -> dict[str, Any] | None:
    """La pause de CETTE portée précise, sans héritage.

    ⛔ Sert à `apply_resume` : lever la pause d'un compte ne doit jamais lever
    par ricochet la pause globale, qui protège tous les autres.
    """
    _ensure_schema()
    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        if destination:
            row = c.execute(
                "SELECT * FROM auto_paused_pairs WHERE pair = ? AND resumed_at IS NULL"
                " AND destination = ? ORDER BY id DESC LIMIT 1",
                (pair, destination),
            ).fetchone()
        else:
            row = c.execute(
                "SELECT * FROM auto_paused_pairs WHERE pair = ? AND resumed_at IS NULL"
                " AND destination IS NULL ORDER BY id DESC LIMIT 1",
                (pair,),
            ).fetchone()
    return dict(row) if row else None


def is_paused(pair: str, destination: str | None = None) -> bool:
    """True si pair a une pause active non expirée sur cette destination."""
    pause = get_active_pause(pair, destination)
    if not pause:
        return False
    try:
        expires = datetime.fromisoformat(pause["expires_at"].replace("Z", "+00:00"))
        return expires > datetime.now(timezone.utc)
    except (ValueError, AttributeError, KeyError):
        return True  # safe default : si parsing foire, on garde paused


def list_active_pauses() -> list[dict[str, Any]]:
    """Liste les pauses actives pour le dashboard admin."""
    _ensure_schema()
    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT * FROM auto_paused_pairs WHERE resumed_at IS NULL ORDER BY paused_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def apply_pause(pair: str, reason: str, pnl_pct: float, trades_count: int,
                destination: str | None = None) -> int:
    """INSERT row pause. Idempotent : si déjà active, retourne l'id existant.

    ``destination=None`` pose une pause GLOBALE, opposable à tous les comptes.
    L'idempotence tient compte de l'héritage : si une pause globale court déjà,
    inutile d'en poser une par destination — le compte est déjà bloqué.
    """
    _ensure_schema()
    existing = get_active_pause(pair, destination)
    if existing:
        logger.debug(f"pair_pnl_regulator: {pair} already paused (id={existing['id']})")
        return existing["id"]
    cfg = _config()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=cfg["pause_duration_days"])
    with sqlite3.connect(_db_path()) as c:
        cur = c.execute(
            """
            INSERT INTO auto_paused_pairs
                (pair, paused_at, expires_at, reason, pnl_pct, trades_in_window,
                 destination)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (pair, now.isoformat(), expires.isoformat(), reason, pnl_pct,
             trades_count, destination),
        )
        new_id = cur.lastrowid
    logger.warning(
        f"pair_pnl_regulator: PAUSED {pair}@{destination or 'GLOBAL'} "
        f"pnl_pct={pnl_pct:.2f}% n={trades_count} until={expires.isoformat()}"
    )
    return new_id


def apply_resume(pair: str, reason: str, destination: str | None = None) -> bool:
    """UPDATE row active : resumed_at + resumed_reason. True si effectif.

    ⛔ Vise la portée EXACTE, sans héritage : lever la pause d'un compte ne
    doit pas lever la pause globale qui couvre tous les autres.
    """
    _ensure_schema()
    existing = _pause_exacte(pair, destination)
    if not existing:
        return False
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(_db_path()) as c:
        c.execute(
            """
            UPDATE auto_paused_pairs
               SET resumed_at = ?, resumed_reason = ?
             WHERE id = ?
            """,
            (now, reason, existing["id"]),
        )
    logger.warning(
        f"pair_pnl_regulator: RESUMED {pair}@{destination or 'GLOBAL'} "
        f"reason={reason} (was paused at {existing['paused_at']})"
    )
    return True


# ─── Decision logic ─────────────────────────────────────────────────────


def evaluate_pair(pair: str, destination: str | None = None) -> dict[str, Any]:
    """Décide pour un (pair, destination) : pause, resume, keep_paused, keep_active.

    Retourne {action, metrics, reason}. ``destination=None`` = portée globale,
    comportement d'avant le 29/08/2026.
    """
    cfg = _config()
    if not cfg["enabled"]:
        return {"action": "disabled", "metrics": {}, "reason": "regulator off"}

    metrics = compute_window_metrics(pair, cfg["window_trades"],
                                     destination=destination)

    # ⚠️ Le verdict se prend en R depuis le 2026-09-04, plus en euros.
    #
    # `pnl_pct` garde exactement son SENS — « combien de % du capital cette
    # paire aurait coûté » — mais chaque trade est ramené au risque prévu
    # (`RISK_PER_TRADE_PCT`) avant d'être somme. Le seuil de −10 % n'a donc pas
    # besoin d'être retraduit : c'est la mesure qui devient comparable, pas la
    # borne qui bouge.
    #
    #     pnl_pct = somme(R) × risque_par_trade_%
    #
    # ⛔ L'ancien chiffre en euros reste calculé et RENDU (`pnl_pct_euros`) :
    # c'est lui qui a servi de verdict pendant des semaines, et le faire
    # disparaître rendrait les pauses passées inexplicables.
    from config.settings import RISK_PER_TRADE_PCT

    pnl_pct_euros = (100.0 * metrics["sum_pnl"] / cfg["capital"]
                     if metrics["n"] > 0 else 0.0)
    metrics["pnl_pct_euros"] = round(pnl_pct_euros, 2)

    n_mes = metrics.get("n_mesurables", 0)
    pnl_pct = metrics.get("somme_r", 0.0) * RISK_PER_TRADE_PCT
    metrics["pnl_pct"] = round(pnl_pct, 2)

    # Pause active prioritaire sur tout autre check : un pair pausé sans
    # nouveaux trades doit rester pausé (cas froid). Le check no_data ne
    # s'applique que si pas de pause en cours.
    pause = get_active_pause(pair, destination)
    now = datetime.now(timezone.utc)

    if pause:
        try:
            expires = datetime.fromisoformat(pause["expires_at"].replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            expires = now  # parse fail → consider expired

        if expires <= now:
            # ⛔ On lève la portée de la pause TROUVÉE, pas celle qu'on
            # évaluait : une pause globale héritée doit être levée globalement,
            # sinon elle survivrait à son terme sans que rien ne la touche.
            apply_resume(pair, "expired_re_evaluate",
                         destination=pause.get("destination"))
            return {
                "action": "resume",
                "metrics": metrics,
                "reason": "pause expired, re-evaluate next cycle",
            }
        return {
            "action": "keep_paused",
            "metrics": metrics,
            "reason": f"paused until {pause['expires_at']}",
        }

    if metrics["n"] == 0:
        return {"action": "no_data", "metrics": metrics, "reason": "no trades"}

    # Pas paused : check si on devrait pause
    if metrics["n"] < cfg["min_sample"]:
        return {
            "action": "keep_active",
            "metrics": metrics,
            "reason": f"sample too small (n={metrics['n']} < {cfg['min_sample']})",
        }

    # ⛔ Le verdict se prend sur les trades MESURABLES en R. S'il n'y en a pas
    # assez, on ne juge pas — on ne retombe PAS sur la somme en euros, qui est
    # exactement la mesure qu'on vient de disqualifier.
    #
    # ⚠️ Ce que ça coûte, assumé : une paire dont les trades ne portent pas de
    # stop lisible n'est plus régulée du tout. C'est le même arbitrage que le
    # plancher d'âge — « pas assez de preuves exploitables » est une réponse
    # plus honnête que « coupable sur une mesure fausse » — et les rafales
    # courtes restent couvertes par `stop_loss_alerts`, qui ne regarde que la
    # dernière heure.
    if n_mes < cfg["min_sample"]:
        return {
            "action": "keep_active",
            "metrics": metrics,
            "reason": (f"risque non mesurable sur {metrics['n'] - n_mes} des "
                       f"{metrics['n']} trades (n_mesurables={n_mes} < "
                       f"{cfg['min_sample']}) — pas de verdict en R"),
        }

    if pnl_pct < cfg["pause_threshold_pct"]:
        apply_pause(pair, "ev_negative", pnl_pct, metrics["n"],
                    destination=destination)
        return {
            "action": "pause",
            "metrics": metrics,
            "reason": (f"pnl_pct {pnl_pct:.2f}% (en R : {metrics['somme_r']:+.2f} R "
                       f"sur {n_mes} trades) < seuil "
                       f"{cfg['pause_threshold_pct']:.2f}% "
                       f"[euros : {pnl_pct_euros:.2f}%]"),
        }

    return {"action": "keep_active", "metrics": metrics, "reason": "healthy"}


def _destinations_actives() -> list[str]:
    """Les comptes qui ont réellement des clôtures dans la fenêtre d'âge.

    Lues dans les données, pas dans le registre : une destination configurée
    mais jamais tradée n'a rien à juger, et une destination retirée du registre
    peut encore porter une pause à lever. On y ajoute donc les destinations des
    pauses en cours.
    """
    _ensure_schema()
    plancher = _plancher_age()
    filtre = " AND closed_at >= ?" if plancher else ""
    args = (plancher,) if plancher else ()
    with sqlite3.connect(_db_path()) as c:
        rows = c.execute(
            f"""
            SELECT DISTINCT destination_id FROM personal_trades
             WHERE status = 'CLOSED' AND is_auto = 1 AND pnl IS NOT NULL
               AND destination_id IS NOT NULL{filtre}
            UNION
            SELECT DISTINCT destination FROM auto_paused_pairs
             WHERE resumed_at IS NULL AND destination IS NOT NULL
            """,
            args,
        ).fetchall()
    return sorted(str(r[0]) for r in rows if r[0])


def check_and_regulate() -> dict[str, Any]:
    """Job scheduler + startup : évalue tous les pairs stars, applique.

    Retourne summary pour debug/tests.
    """
    cfg = _config()
    if not cfg["enabled"]:
        return {"enabled": False, "decisions": []}

    # On évalue les stars auto-exec + tous les pairs qui ont déjà été tradés
    # (pour gérer le cas où un pair est désactivé des stars mais a une pause
    # active à libérer après expiration).
    from backend.services.shadow_v2_core_long import SHADOW_PAIRS as _STAR_PAIRS

    pairs_to_check = set(_STAR_PAIRS)
    # Ajouter les pairs qui ont une pause active (au cas où retirés des stars)
    for p in list_active_pauses():
        pairs_to_check.add(p["pair"])

    # ⛔ Une paire est jugée PAR COMPTE, pas en bloc. La fenêtre mélangeait
    # démo, réel et anciens courtiers dans un seul verdict — c'est ainsi que
    # l'argent s'est retrouvé bloqué sur le compte réel par des trades passés
    # sur l'ancien compte démo.
    #
    # `None` reste dans la liste : c'est la portée GLOBALE, celle des pauses
    # posées avant le 29/08/2026. Sans elle, plus personne ne viendrait les
    # lever à leur terme.
    portees: list[str | None] = [None] + _destinations_actives()

    decisions = []
    for pair in sorted(pairs_to_check):
        for portee in portees:
            try:
                d = evaluate_pair(pair, destination=portee)
                d["pair"] = pair
                d["destination"] = portee
                decisions.append(d)
            except Exception:
                logger.exception(
                    f"pair_pnl_regulator: evaluate {pair}@{portee} failed")

    summary = {
        "enabled": True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "n_checked": len(decisions),
        "n_paused": sum(1 for d in decisions if d["action"] == "pause"),
        "n_resumed": sum(1 for d in decisions if d["action"] == "resume"),
        "n_keep_paused": sum(1 for d in decisions if d["action"] == "keep_paused"),
        "n_keep_active": sum(1 for d in decisions if d["action"] == "keep_active"),
        "decisions": decisions,
    }
    logger.info(
        f"pair_pnl_regulator: check_and_regulate n_checked={summary['n_checked']} "
        f"paused={summary['n_paused']} resumed={summary['n_resumed']} "
        f"keep_paused={summary['n_keep_paused']}"
    )
    return summary
