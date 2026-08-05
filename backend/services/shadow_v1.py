"""Shadow log V1 — persiste les signaux V1 pour les pairs OBSERVED.

Permet à `compute_promotion_score` (pair_admission_controller) d'évaluer
empiriquement les pairs en mode observation sans engager d'argent réel,
résolvant le chicken-and-egg de la promotion auto OBSERVED → AUTO_EXEC.

Architecture :
- À chaque cycle radar, pour chaque TradeSetup généré (passant
  filter_high_confidence_setups), on check si la (pair, direction) est
  en état OBSERVED via pair_admission_controller.
- Si oui, on INSERT une row dans `shadow_setups` avec
  `system_id='V1_SHADOW_<PAIR>_<DIR>'` (unique par pair-direction pour
  respecter la contrainte UNIQUE (system_id, bar_timestamp)).
- La reconciliation existante (`shadow_reconciliation.py`) résout ces
  shadows automatiquement — pas de filtre par system_id, donc V1 et V2
  sont traités uniformément.

Note : le système est en lecture seule côté V1 prod. Il ne déclenche
ni Telegram ni auto-exec. Sa seule sortie est d'alimenter le calcul
de `compute_promotion_score` pour les pairs OBSERVED.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.services.market_hours import is_market_open_for
from config.settings import CANDLE_INTERVAL

logger = logging.getLogger(__name__)

# Même fichier que shadow_v2_core_long
DB_PATH = Path("/app/data/trades.db") if Path("/app").exists() else Path("trades.db")

V1_SYSTEM_PREFIX = "V1_SHADOW"

# ── Horizon d'analyse ────────────────────────────────────────────────────
# L'étiquette écrite dans `shadow_setups.timeframe` doit dire sur quelles
# bougies le setup a été détecté. Jusqu'au 2026-08-04 elle valait "1h", avec
# un commentaire affirmant que « le radar V1 analyse des bougies 1h ».
#
# C'était faux. Le radar détecte sur `CANDLE_INTERVAL` (5 min en production)
# et ne récupère les bougies 1h que pour la confirmation multi-timeframe et
# le calcul d'ATR — cf. `scheduler.run_analysis_cycle`.
#
# L'étiquette est désormais **dérivée** plutôt que recopiée : elle ne peut
# plus diverger de l'intervalle réellement analysé si celui-ci change.
#
# ⚠️ Les rows V1 antérieures au 2026-08-04 portent "1h" et décrivent le même
# flux 5 min. Ne pas les agréger avec les nouvelles — de toute façon tout
# l'historique shadow antérieur à cette date est à écarter (bug de dédup).
V1_TIMEFRAME = CANDLE_INTERVAL

# Fenêtre de déduplication — distincte de l'horizon d'analyse, et c'est le
# point qui prêtait à confusion. Le cycle radar tourne toutes les 5 min, donc
# un setup qui persiste 40 min est revu huit fois alors qu'il ne représente
# qu'**une** opportunité de trade. Le regroupement horaire le compte une fois.
# Le ramener à l'intervalle des bougies réintroduirait l'inflation corrigée le
# 2026-08-04 (×960 sur SPX).
V1_DEDUP_WINDOW_HOURS = 1
DEFAULT_CAPITAL_EUR = 10000.0  # capital fictif pour sizing shadow
DEFAULT_RISK_PCT = 0.01        # 1% risque par trade, équivalent à V2


def system_id_for(pair: str, direction: str) -> str:
    """V1_SHADOW_<PAIR>_<DIR> — unique par pair+direction pour respecter
    UNIQUE (system_id, bar_timestamp) lors d'inserts multi-pairs au même cycle.

    Ex: 'V1_SHADOW_XAUUSD_buy', 'V1_SHADOW_EURUSD_sell'.
    """
    pair_clean = pair.replace("/", "")
    return f"{V1_SYSTEM_PREFIX}_{pair_clean}_{direction}"


def _bar_timestamp(cycle_at: datetime) -> str:
    """Début du bar H1 contenant ``cycle_at``, en ISO.

    ⚠️ C'est la clé de déduplication. Jusqu'au 2026-08-04, ``bar_timestamp``
    recevait ``cycle_at`` tel quel — donc une valeur différente à chaque
    cycle radar (~6 min), rendant la contrainte ``UNIQUE (system_id,
    bar_timestamp)`` **inopérante**. Une même idée de trade était persistée
    des centaines de fois : mesuré en prod à ×960 sur SPX, ×229 sur AAPL,
    ×2,5 en moyenne sur 19 928 rows.

    Toute statistique tirée du shadow était donc faussée — non pas
    légèrement, mais d'un facteur qui variait selon la paire, ce qui
    empêchait même de corriger a posteriori.

    Aligner sur le début de la fenêtre rétablit la sémantique annoncée par le
    docstring d'origine : **une opportunité comptée une fois**.

    ⚠️ Cette fenêtre n'est PAS l'horizon d'analyse (``V1_TIMEFRAME``, 5 min).
    Les deux ont longtemps tenu dans une seule constante, ce qui rendait
    l'étiquette d'horizon fausse. La troncature dérive de
    ``V1_DEDUP_WINDOW_HOURS`` pour qu'elle ne puisse pas non plus diverger.
    """
    heures = max(1, int(V1_DEDUP_WINDOW_HOURS))
    debut = (cycle_at.hour // heures) * heures
    return cycle_at.replace(hour=debut, minute=0, second=0, microsecond=0).isoformat()


def _persist_v1_shadow(
    setup: Any,
    pair: str,
    direction: str,
    cycle_at: datetime,
    funding_features: dict | None = None,
) -> bool:
    """INSERT shadow_setups V1_SHADOW. Idempotent via UNIQUE.

    Retourne True si une nouvelle row a été créée, False sinon (collision
    UNIQUE = même bar logué au cycle précédent, normal pendant warmup).

    ``funding_features`` : instantané funding Kraken (cf.
    ``shadow_v2_core_long._capture_funding_snapshot``), ``None`` pour une
    paire non-crypto ou si la capture a échoué. C'est la SEULE feature
    capturée par le flux V1 aujourd'hui — volontairement minimal, ce flux
    ne capture ni macro ni géopolitique (cf. docstring de module).
    """
    entry = float(setup.entry_price)
    sl = float(setup.stop_loss)
    tp1 = float(setup.take_profit_1)
    tp2 = getattr(setup, "take_profit_2", None)

    risk = abs(entry - sl)
    if entry <= 0 or risk <= 0:
        logger.debug(f"shadow_v1: skip {pair} {direction} — entry/risk invalide ({entry}/{risk})")
        return False
    risk_pct = risk / entry
    reward = abs(tp1 - entry)
    rr = reward / risk if risk > 0 else 0.0

    sizing_max_loss_eur = DEFAULT_CAPITAL_EUR * DEFAULT_RISK_PCT
    sizing_position_eur = sizing_max_loss_eur / risk_pct

    # Pattern name : compatibilité avec V2 schema
    pattern_name = "v1_signal"
    try:
        if hasattr(setup, "pattern") and hasattr(setup.pattern, "pattern"):
            pattern_name = setup.pattern.pattern.value
        elif hasattr(setup, "pattern"):
            pattern_name = str(setup.pattern)
    except Exception:
        pass

    # Marché fermé : le dernier cours ne bouge plus, donc le radar
    # régénérerait un setup identique à chaque cycle sur un prix figé. Une
    # action scannée 24h/24 alors que le NYSE n'ouvre que 6h30 produisait
    # ainsi ~230 rows/jour pour 1 idée de trade.
    # On interroge les horaires **au moment du cycle**, pas à l'instant présent :
    # un rejeu ou un backfill doit juger le passé avec le calendrier du passé.
    try:
        if not is_market_open_for(pair, cycle_at):
            return False
    except Exception as e:  # jamais bloquer le log sur une erreur d'horaires
        logger.debug(f"shadow_v1: market_hours indisponible pour {pair}: {e}")

    system_id = system_id_for(pair, direction)
    cycle_iso = cycle_at.isoformat()
    bar_iso = _bar_timestamp(cycle_at)
    funding_json = json.dumps(funding_features) if funding_features else None

    with sqlite3.connect(DB_PATH) as c:
        try:
            c.execute(
                """
                INSERT INTO shadow_setups (
                    cycle_at, bar_timestamp, system_id, pair, timeframe,
                    direction, pattern, entry_price, stop_loss,
                    take_profit_1, take_profit_2, risk_pct, rr,
                    sizing_capital_eur, sizing_risk_pct,
                    sizing_position_eur, sizing_max_loss_eur,
                    funding_features_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cycle_iso, bar_iso, system_id, pair, V1_TIMEFRAME,
                    direction, pattern_name,
                    entry, sl, tp1, tp2, risk_pct, rr,
                    DEFAULT_CAPITAL_EUR, DEFAULT_RISK_PCT,
                    sizing_position_eur, sizing_max_loss_eur,
                    funding_json,
                ),
            )
            return True
        except sqlite3.IntegrityError:
            # Collision UNIQUE — ce bar est déjà logué pour cette
            # (pair, direction). Comportement voulu : un setup par bar.
            return False


def log_v1_shadows_for_observed_pairs(setups: list, cycle_at: datetime) -> dict[str, int]:
    """Pour chaque TradeSetup, log un V1_SHADOW si (pair, direction) en OBSERVED.

    Appelé depuis scheduler.run_analysis_cycle après filter_high_confidence_setups.
    Idempotent et non-bloquant : log + counts d'erreurs sans propager d'exception.

    Returns:
        {"logged": int, "skipped_not_observed": int, "errors": int}
    """
    from backend.services import pair_admission_controller as pac
    from backend.services.shadow_v2_core_long import _capture_funding_snapshot

    counts = {"logged": 0, "skipped_not_observed": 0, "errors": 0}
    for setup in setups:
        try:
            pair = setup.pair
            direction = setup.direction.value if hasattr(setup.direction, "value") else str(setup.direction)

            current = pac.get_current_state(pair, direction)
            if current != pac.STATE_OBSERVED:
                counts["skipped_not_observed"] += 1
                continue

            # Funding Kraken — seule feature capturée par V1 (cf. docstring
            # module). None sur une paire non-crypto ; jamais bloquant.
            funding_features = None
            try:
                funding_features = _capture_funding_snapshot(pair, direction)
            except Exception as e:
                logger.debug(f"shadow_v1: funding capture failed pour {pair}: {e}")

            if _persist_v1_shadow(setup, pair, direction, cycle_at, funding_features=funding_features):
                counts["logged"] += 1
        except Exception as e:
            logger.warning(f"shadow_v1 log failed for {getattr(setup, 'pair', '?')}: {e}")
            counts["errors"] += 1
    return counts


def fetch_v1_shadow_pnls(pair: str, direction: str | None, window: int = 30) -> list[float]:
    """Récupère les pnl_eur des N derniers shadow_setups V1_SHADOW résolus.

    ⚠️ **Plus aucun appelant depuis le 2026-08-04.** `compute_promotion_score`
    s'alimentait ici ; il lit désormais `backtest.db.trades`. Motif : les rows
    antérieures au correctif de déduplication sont irrécupérablement
    dupliquées (×2,5 à ×960 selon la paire), et elles ont piloté de vraies
    rétrogradations automatiques.

    La fonction est conservée — pas supprimée — parce que le log shadow tourne
    à nouveau proprement : dans quelques semaines de séances réelles, cette
    table redeviendra exploitable. **Ne pas la rebrancher avant** d'avoir
    vérifié que les rows lues sont toutes postérieures au correctif.

    Si direction est None : agrège buy + sell (= scoring pair-level legacy).
    Sinon : restreint à ce sens.

    Returns:
        Liste de pnl_eur (float), exit-time desc, limité à `window`.
    """
    if direction:
        system_ids = [system_id_for(pair, direction)]
    else:
        system_ids = [system_id_for(pair, "buy"), system_id_for(pair, "sell")]

    placeholders = ",".join("?" * len(system_ids))
    sql = f"""
        SELECT pnl_eur FROM shadow_setups
         WHERE system_id IN ({placeholders})
           AND pair = ?
           AND outcome IS NOT NULL
           AND pnl_eur IS NOT NULL
         ORDER BY exit_at DESC
         LIMIT ?
    """
    pnls: list[float] = []
    with sqlite3.connect(DB_PATH) as c:
        rows = c.execute(sql, (*system_ids, pair, window)).fetchall()
    for r in rows:
        try:
            pnls.append(float(r[0]))
        except (TypeError, ValueError):
            continue
    return pnls
