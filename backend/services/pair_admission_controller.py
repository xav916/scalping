"""Pair Admission Controller — état des pairs dans le pipeline auto-exec.

Généralisation du pair_pnl_regulator. Au lieu d'une simple liste hardcodée
de "stars" + un mécanisme de pause, on a une vraie state machine par pair :

  OBSERVED ──(score promotion OK)──► TELEGRAM ──(admin valide)──► AUTO_EXEC
  AUTO_EXEC ──(sum_pnl < -3% sur 30 trades)──► PAUSED
  PAUSED ──(cool-off PAC_PAUSE_COOLOFF_DAYS + bat la moyenne des pairs comparables)──► AUTO_EXEC
  PAUSED ──(2× re-pause sur 60j)──► DEMOTED
  DEMOTED ──(manuel)──► OBSERVED

## États

- **OBSERVED** : pair scannée par V1, signaux générés en interne, AUCUN
  push Telegram, AUCUN auto-exec. Source de scoring = shadow_setups
  (backtest live Track A V2) + historique personal_trades / ea_closed_trades
  pour pairs qui ont été AUTO_EXEC dans le passé.
- **TELEGRAM** : niveau intermédiaire, le user reçoit les signaux sur
  Telegram avec verdict TAKE/SKIP/WAIT mais l'auto-exec bridge MT5 NE
  s'enclenche PAS. Permet à l'humain de valider avant d'accorder l'auto-
  exec — passage à AUTO_EXEC = manuel par défaut.
- **AUTO_EXEC** : signaux Telegram + envoi auto au bridge MT5 pour tous
  les users Premium éligibles.
- **PAUSED** : équivalent au pair_pnl_regulator actuel. Push Telegram en
  mode "info" (verdict forcé SKIP), bridge bloqué. Auto-revue après le
  cool-off (`config.settings.PAC_PAUSE_COOLOFF_DAYS`, 14j par défaut) — le
  retour à AUTO_EXEC exige EN PLUS que le contrôle par comparaison
  inter-paires (`peer_control_for_pair`, cf. section dédiée plus bas)
  établisse que les signaux de la pair font mieux que la moyenne des autres
  pairs de la MÊME CLASSE D'ACTIF, sur `shadow_setups` récent. Le délai seul
  ne suffit plus depuis le 2026-08-05.
  ⚠️ Condition NÉCESSAIRE, jamais SUFFISANTE : ce contrôle établit seulement
  que la pair n'est pas pire que ses semblables. Il ne dit rien sur la
  question systémique « les patterns battent-ils une VRAIE entrée
  aléatoire ? » — mesurable seulement hors ligne par backtest, et déjà
  répondue négativement pour au moins un système testé (cf. section dédiée
  plus bas).
- **DEMOTED** : pair sortie de la plateforme après 2 pauses répétées.
  Plus de push Telegram, plus d'exec. Seul un admin manuel peut la
  remettre en OBSERVED.

## Auto-promote vs manuel

Promotion auto : OBSERVED → TELEGRAM (humain peut voir et valider)
Promotion manuelle : TELEGRAM → AUTO_EXEC (entrée d'argent réel = humain
dans la boucle, philosophie loss-averse asymétrique)

Demotion auto : tout le reste (AUTO_EXEC → PAUSED, PAUSED → DEMOTED).

## Source de vérité

Table `pair_admission_state` (historique des transitions, l'état courant
= la row la plus récente pour chaque pair). Permet l'audit du chemin de
chaque pair dans la plateforme.
"""

from __future__ import annotations

import json
import re
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# États valides (cohérent avec le CHECK contrainte SQL)
STATE_OBSERVED = "OBSERVED"
STATE_TELEGRAM = "TELEGRAM"
STATE_AUTO_EXEC = "AUTO_EXEC"
STATE_PAUSED = "PAUSED"
STATE_DEMOTED = "DEMOTED"

VALID_STATES = frozenset([
    STATE_OBSERVED, STATE_TELEGRAM, STATE_AUTO_EXEC, STATE_PAUSED, STATE_DEMOTED
])

# « Indécidable » — classification de `compute_promotion_score()["eligible_for"]`,
# PAS un état de la state machine (absent de VALID_STATES, n'apparaît jamais
# dans la colonne `pair_admission_state.state`). Distingue explicitement
# « on ne sait pas » (échantillon réel insuffisant) de « on sait que c'est
# mauvais » (STATE_OBSERVED avec échantillon réel suffisant) — cf. garde-fou
# `PAC_MIN_REAL_TRADES` 2026-08-05. Inconnu ≠ 0 / négatif : cette valeur est
# le pendant de ce principe au niveau de la décision d'admission.
STATE_INDETERMINATE = "INDETERMINATE"

# Default si pair n'a jamais été vue par le controller : on observe par défaut
# (= ne pas envoyer Telegram ni auto-exec sans décision explicite)
DEFAULT_STATE = STATE_OBSERVED

# Cible de la promotion automatique quand tous les critères statistiques sont validés.
# Défaut TELEGRAM = conservateur (admin valide ensuite AUTO_EXEC manuellement).
# Surcharge env AUTO_PROMOTE_TARGET=AUTO_EXEC pour activer le full-auto (saut TELEGRAM).
# ⚠️ AUTO_EXEC engage de l'argent réel sans validation humaine — accepter le risque
# d'oscillation OBSERVED→AUTO_EXEC→PAUSED (cap downside ≈ -3% capital par pair via
# pair_pnl_regulator).
import os as _os
_raw_target = _os.getenv("AUTO_PROMOTE_TARGET", STATE_TELEGRAM).upper()
AUTO_PROMOTE_TARGET = _raw_target if _raw_target in (STATE_TELEGRAM, STATE_AUTO_EXEC) else STATE_TELEGRAM

_SCHEMA_ENSURED = False


def _db_path() -> str:
    from backend.services.trade_log_service import _DB_PATH
    return str(_DB_PATH)


# ─── Circuit breaker auto-demotes ─────────────────────────────────────
# Anti-cascade : si > THRESHOLD demotions auto sur fenêtre glissante,
# bloque les nouvelles demotions auto. Le PAUSED reste, l'humain peut
# intervenir. Cf. 2026-06-07/08 : 17 demotions en 48h.


def _breaker_window() -> int:
    try:
        from config.settings import PAC_CIRCUIT_BREAKER_WINDOW_DAYS
        return int(PAC_CIRCUIT_BREAKER_WINDOW_DAYS)
    except Exception:
        return 7


def _breaker_threshold() -> int:
    try:
        from config.settings import PAC_CIRCUIT_BREAKER_THRESHOLD
        return int(PAC_CIRCUIT_BREAKER_THRESHOLD)
    except Exception:
        return 5


def _count_recent_auto_demotions(window_days: int = 7) -> int:
    """Compte les DEMOTED auto sur fenêtre glissante."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
    try:
        with sqlite3.connect(_db_path()) as c:
            row = c.execute(
                """SELECT COUNT(*) FROM pair_admission_state
                   WHERE state = ? AND state_since >= ?
                     AND transitioned_by LIKE 'auto%'""",
                ("DEMOTED", cutoff),
            ).fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def _promotions_recentes_vers_auto_exec(jours: int = 7) -> int:
    """Nombre de promotions AUTOMATIQUES vers AUTO_EXEC sur la fenêtre glissante.

    Les promotions **manuelles** ne sont pas comptées : une décision humaine
    explicite n'a pas à consommer un budget conçu pour brider l'automatisme.
    """
    # `timedelta` n'est pas importé au niveau module dans ce fichier.
    from datetime import timedelta as _timedelta

    depuis = (datetime.now(timezone.utc) - _timedelta(days=jours)).isoformat()
    try:
        _ensure_schema()
        with sqlite3.connect(_db_path()) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM pair_admission_state "
                "WHERE state = ? AND state_since >= ? AND transitioned_by LIKE 'auto%'",
                (STATE_AUTO_EXEC, depuis),
            ).fetchone()
            return int(row[0]) if row else 0
    except Exception as e:
        logger.warning(f"budget de promotion illisible: {e}")
        # Fail-closed : sans compteur fiable, on ne promeut pas. Une promotion
        # de trop engage de l'argent ; une promotion retardée ne coûte rien.
        return 10**6


def _budget_promotions_hebdo() -> int:
    """Combien de promotions automatiques vers l'argent réel par semaine ?

    ⚠️ Ce plafond existe à cause d'une vague mesurée : au moment de corriger la
    porte à sens unique (2026-08-06), **37 couples** étaient bloqués en
    `OBSERVED`. Sans débit maximal, ils seraient tous entrés en `TELEGRAM` le
    même cycle, donc tous arrivés à maturité **le même jour** — l'exposition
    serait passée de 11 à 47 couples d'un coup, sur un système dont aucun
    avantage n'est démontré.

    Réparer une porte bloquée ne doit pas revenir à l'arracher. Le débit rend
    l'élargissement progressif et observable : un couple promu, une semaine
    pour en voir l'effet.
    """
    try:
        from config.settings import PAC_MAX_AUTO_PROMOTIONS_PER_WEEK
        return int(PAC_MAX_AUTO_PROMOTIONS_PER_WEEK)
    except Exception:
        return 2


def _promotion_indetermine_autorisee() -> bool:
    """Une paire « indécidable » peut-elle franchir TELEGRAM → AUTO_EXEC ?

    Relu à chaque appel (jamais figé en constante de module) pour rester
    monkeypatchable et modifiable sans redémarrage.

    ⚠️ Par défaut **oui**, et c'est délibéré. `INDETERMINATE` veut dire « pas
    assez de trades RÉELS », or seule une paire en `AUTO_EXEC` en produit :
    exiger cette preuve avant d'accorder l'exécution est une condition
    insatisfaisable, qui a fermé l'admission dans un seul sens.

    Mettre ce drapeau à `false` rétablit la porte à sens unique. Ne le faire
    qu'en connaissance de cause, et de préférence en promouvant à la main les
    paires souhaitées.
    """
    try:
        from config.settings import PAC_ALLOW_INDETERMINATE_PROMOTION
        return bool(PAC_ALLOW_INDETERMINATE_PROMOTION)
    except Exception:
        return True


def _min_real_trades() -> int:
    """Plancher de trades RÉELS requis pour qu'une décision d'admission auto
    (promotion OU rétrogradation) soit prise. Cf. `config.settings.PAC_MIN_REAL_TRADES`.

    ⚠️ Import différé, relu à *chaque* appel (jamais mis en cache dans une
    constante de module) : c'est ce qui permet à un test de monkeypatcher
    `config.settings.PAC_MIN_REAL_TRADES` et de voir l'effet immédiatement,
    sans reload de module. Même schéma que `_breaker_window` / `_breaker_threshold`
    ci-dessus — un monkeypatch sur autre chose que `config.settings` ne serait
    lu par personne.
    """
    try:
        from config.settings import PAC_MIN_REAL_TRADES
        return int(PAC_MIN_REAL_TRADES)
    except Exception:
        return 30


def is_demotion_blocked() -> bool:
    """True si le circuit breaker bloque les auto-demotes (anti-cascade)."""
    try:
        from config.settings import PAC_CIRCUIT_BREAKER_ENABLED
    except ImportError:
        return False
    if not PAC_CIRCUIT_BREAKER_ENABLED:
        return False
    return _count_recent_auto_demotions(_breaker_window()) >= _breaker_threshold()


_breaker_notified_window: set[str] = set()  # dedup notif par jour


def _notify_circuit_breaker_block(pair: str, direction: str | None, n_recent: int) -> None:
    """Push Telegram (user+infra) à chaque blocage. Dedup 1× par (date, pair, direction)
    pour éviter le spam si le breaker déclenche sur plusieurs paires en cascade.
    """
    try:
        today = datetime.now(timezone.utc).date().isoformat()
        key = f"{today}|{pair}|{direction or ''}"
        if key in _breaker_notified_window:
            return
        _breaker_notified_window.add(key)
        # Reset si jour change
        if len(_breaker_notified_window) > 50:
            _breaker_notified_window.clear()
            _breaker_notified_window.add(key)

        import asyncio
        from backend.services.telegram_service import send_text
        # Mapping FR vulgarisé 2026-06-14 (cohérent avec autres msg ScalpingRadar)
        _PAIR_FR_LOCAL = {
            "XAU/USD": "Or",
            "XAG/USD": "Argent",
            "WTI/USD": "Pétrole",
            "BTC/USD": "Bitcoin",
            "ETH/USD": "Ethereum",
            "SOL/USD": "Solana",
            "ADA/USD": "Cardano",
            "XRP/USD": "XRP",
            "LTC/USD": "Litecoin",
            "BCH/USD": "Bitcoin Cash",
            "DOT/USD": "Polkadot",
            "SPX": "S&P 500",
            "NDX": "Nasdaq",
        }
        pair_fr = _PAIR_FR_LOCAL.get(pair, pair)
        dir_label = ""
        if direction == "buy":
            dir_label = " (sens achat)"
        elif direction == "sell":
            dir_label = " (sens vente)"
        msg = (
            f"🚨 *Sécurité activée — paire à problème*\n"
            f"\n"
            f"⚠️ La paire *{pair_fr}* ({pair}){dir_label} a déjà été rétrogradée "
            f"*{n_recent} fois* par le système sur les {_breaker_window()} derniers jours.\n"
            f"\n"
            f"ℹ️ *Pourquoi ce message ?*\n"
            f"Quand une paire se fait rétrograder à répétition, le radar arrête "
            f"de la faire passer d'un mode à l'autre automatiquement et te "
            f"demande de vérifier manuellement. C'est un garde-fou anti-yoyo "
            f"pour éviter d'enchaîner les ajustements pendant que tu dors.\n"
            f"\n"
            f"🛠️ *À faire de ton côté*\n"
            f"Décide si tu veux désactiver complètement la paire (mode pause) "
            f"ou si tu acceptes qu'elle reste dans son état actuel. Va sur "
            f"`/v2/cockpit` → section Admission paires pour agir."
        )
        coro = send_text(msg)
        try:
            loop = asyncio.get_running_loop()
            asyncio.ensure_future(coro)
        except RuntimeError:
            asyncio.run(coro)
    except Exception as e:
        logger.debug(f"_notify_circuit_breaker_block error: {e}")


def _ensure_schema() -> None:
    """Crée pair_admission_state si pas déjà là. Idempotent.

    Évolution 2026-05-13 : ajout colonne ``direction`` (NULL pour les rows
    pair-level legacy, 'buy' ou 'sell' pour les rows direction-specific).
    Migration douce : les rows existantes restent direction IS NULL et
    s'appliquent à toutes les directions.

    Évolution 2026-07-29 : ajout colonne ``destination`` (NULL = s'applique
    à toutes les destinations, 'admin_legacy' / 'admin_live' = specific).
    Permet le workflow test-then-promote Demo → Live : une pair peut être
    AUTO_EXEC sur admin_legacy tout en restant TELEGRAM sur admin_live.
    Résolution en cascade : destination-specific first, fallback destination
    IS NULL, fallback direction IS NULL.
    """
    global _SCHEMA_ENSURED
    if _SCHEMA_ENSURED:
        return
    with sqlite3.connect(_db_path()) as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS pair_admission_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN
                    ('OBSERVED', 'TELEGRAM', 'AUTO_EXEC', 'PAUSED', 'DEMOTED')),
                state_since TEXT NOT NULL,
                reason TEXT,
                score_snapshot TEXT,
                transitioned_by TEXT NOT NULL DEFAULT 'auto'
            )
            """
        )
        # Migration : ajoute la colonne direction si absente (idempotent via try)
        try:
            c.execute("ALTER TABLE pair_admission_state ADD COLUMN direction TEXT")
        except sqlite3.OperationalError:
            pass  # colonne déjà présente
        # Migration 2026-07-29 : ajoute la colonne destination (idempotent)
        try:
            c.execute("ALTER TABLE pair_admission_state ADD COLUMN destination TEXT")
        except sqlite3.OperationalError:
            pass  # colonne déjà présente
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_pas_pair_since ON pair_admission_state(pair, state_since DESC)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_pas_pair_dir_since ON pair_admission_state(pair, direction, state_since DESC)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_pas_pair_dir_dest_since ON pair_admission_state(pair, direction, destination, state_since DESC)"
        )
    _SCHEMA_ENSURED = True


# Destinations valides (miroir de bridge_destinations.BridgeConfig.destination_id)
# Dérivé du registre : ajouter une plateforme là-bas suffit. Cette liste
# était maintenue à la main et ne connaissait que 2 destinations sur 7 —
# cf. destinations_registry pour l'incident du 2026-08-04.
from backend.services.destinations_registry import (  # noqa: E402
    USER_DESTINATION_RE as _USER_DESTINATION_RE,
    ids as _registry_ids,
)

VALID_DESTINATIONS = _registry_ids()


def is_valid_destination(destination: str) -> bool:
    """True si la chaîne désigne une destination connue (admin ou user:N)."""
    d = str(destination).strip().lower()
    return d in VALID_DESTINATIONS or bool(_USER_DESTINATION_RE.match(d))


def _normalize_destination(
    destination: Optional[str], *, strict: bool = False
) -> Optional[str]:
    """Normalise une destination, ou None pour « toutes les destinations ».

    ⚠️ **Corrigé le 2026-08-04.** ``VALID_DESTINATIONS`` ne listait que
    ``admin_legacy`` et ``admin_live`` — soit 2 destinations sur 7 — et toute
    valeur non listée était repliée en ``None``. Or ``None`` signifie *« toutes
    les destinations »* : le repli **élargissait** donc les permissions au lieu
    de les restreindre, silencieusement et sans erreur.

    Constaté : ``set_state(..., destination='admin_kraken')`` rendait le couple
    éligible à l'auto-exec sur **toutes** les destinations, y compris ``user:2``
    dont les classes autorisées incluent la crypto.

    Effet miroir en lecture : une row stockée avec une destination non listée
    devenait inatteignable, la cascade retombant sur la row globale. La
    promotion ``BTC/USD buy @admin_kraken_spot`` du 2026-08-03 n'a ainsi jamais
    rien fait.

    ``strict=True`` (chemins d'écriture) : lève sur destination inconnue plutôt
    que d'élargir la portée. En cas de doute, restreindre.
    """
    if destination is None:
        return None
    d = str(destination).strip().lower()
    if is_valid_destination(d):
        return d
    if strict:
        raise ValueError(
            f"Destination inconnue : {destination!r}. "
            f"Attendu : {sorted(VALID_DESTINATIONS)} ou 'user:<id>'. "
            "Refusé plutôt que replié en portée globale."
        )
    logger.warning(
        f"pair_admission: destination inconnue en lecture {destination!r} — "
        "repli sur la cascade globale. Vérifier VALID_DESTINATIONS."
    )
    return None


# ─── Read API ───────────────────────────────────────────────────────────


def _normalize_direction(direction: Optional[str]) -> Optional[str]:
    """Normalise direction en 'buy'/'sell' ou None. Valide les entrées."""
    if direction is None:
        return None
    d = str(direction).strip().lower()
    if d in ("buy", "long", "b"):
        return "buy"
    if d in ("sell", "short", "s"):
        return "sell"
    return None  # entrée invalide → fallback pair-level


def get_current_state(
    pair: str,
    direction: Optional[str] = None,
    destination: Optional[str] = None,
) -> str:
    """Retourne l'état courant pour (pair, direction, destination).

    Résolution en cascade (spécifique → legacy) :
    1. (pair, direction, destination) — most specific
    2. (pair, direction, destination IS NULL) — direction-specific, all destinations
    3. (pair, direction IS NULL, destination IS NULL) — pair-level legacy
    4. DEFAULT_STATE

    Migration douce : les rows existantes (direction IS NULL, destination IS NULL)
    restent honorées tant qu'aucune row plus spécifique n'override.
    """
    _ensure_schema()
    direction = _normalize_direction(direction)
    destination = _normalize_destination(destination)
    with sqlite3.connect(_db_path()) as c:
        # 1. Row (pair, direction, destination) — most specific
        if direction is not None and destination is not None:
            row = c.execute(
                """
                SELECT state FROM pair_admission_state
                 WHERE pair = ? AND direction = ? AND destination = ?
                 ORDER BY state_since DESC LIMIT 1
                """,
                (pair, direction, destination),
            ).fetchone()
            if row:
                return row[0]
        # 2. Row (pair, direction, destination IS NULL) — direction-specific legacy
        if direction is not None:
            row = c.execute(
                """
                SELECT state FROM pair_admission_state
                 WHERE pair = ? AND direction = ? AND destination IS NULL
                 ORDER BY state_since DESC LIMIT 1
                """,
                (pair, direction),
            ).fetchone()
            if row:
                return row[0]
        # 3. Row (pair, direction IS NULL, destination IS NULL) — pair-level legacy
        row = c.execute(
            """
            SELECT state FROM pair_admission_state
             WHERE pair = ? AND direction IS NULL AND destination IS NULL
             ORDER BY state_since DESC LIMIT 1
            """,
            (pair,),
        ).fetchone()
    return row[0] if row else DEFAULT_STATE


def get_full_state(
    pair: str,
    direction: Optional[str] = None,
    destination: Optional[str] = None,
) -> dict[str, Any]:
    """Retourne l'état + métadonnées (state_since, reason, score, destination).

    Même cascade que get_current_state : (pair, dir, dest) → (pair, dir, dest NULL)
    → (pair, dir NULL, dest NULL) → default.
    """
    _ensure_schema()
    direction = _normalize_direction(direction)
    destination = _normalize_destination(destination)
    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        row = None
        # 1. (pair, direction, destination)
        if direction is not None and destination is not None:
            row = c.execute(
                """
                SELECT * FROM pair_admission_state
                 WHERE pair = ? AND direction = ? AND destination = ?
                 ORDER BY state_since DESC LIMIT 1
                """,
                (pair, direction, destination),
            ).fetchone()
        # 2. (pair, direction, destination IS NULL)
        if not row and direction is not None:
            row = c.execute(
                """
                SELECT * FROM pair_admission_state
                 WHERE pair = ? AND direction = ? AND destination IS NULL
                 ORDER BY state_since DESC LIMIT 1
                """,
                (pair, direction),
            ).fetchone()
        # 3. (pair, direction IS NULL, destination IS NULL)
        if not row:
            row = c.execute(
                """
                SELECT * FROM pair_admission_state
                 WHERE pair = ? AND direction IS NULL AND destination IS NULL
                 ORDER BY state_since DESC LIMIT 1
                """,
                (pair,),
            ).fetchone()
    if not row:
        return {"pair": pair, "direction": direction, "destination": destination,
                "state": DEFAULT_STATE, "state_since": None, "reason": None,
                "score_snapshot": None, "transitioned_by": None}
    d = dict(row)
    if d.get("score_snapshot"):
        try:
            d["score_snapshot"] = json.loads(d["score_snapshot"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d


def list_all_states() -> list[dict[str, Any]]:
    """Retourne l'état courant de tous les (pair × direction) qui ont une row.

    Une row par bucket (pair, direction) — ex: 3 rows possibles par pair
    (pair-level NULL + buy + sell). Le caller peut filtrer/grouper selon ses
    besoins. Pour l'univers complet, inclure WATCHED_PAIRS (default OBSERVED).
    """
    _ensure_schema()
    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        # On groupe par (pair, direction) avec IS NULL bien traité via COALESCE
        rows = c.execute(
            """
            SELECT pas.* FROM pair_admission_state pas
             INNER JOIN (
                SELECT pair, COALESCE(direction, '__null__') AS dir_key,
                       MAX(state_since) AS max_since
                  FROM pair_admission_state
                 GROUP BY pair, dir_key
             ) latest
               ON pas.pair = latest.pair
              AND COALESCE(pas.direction, '__null__') = latest.dir_key
              AND pas.state_since = latest.max_since
             ORDER BY pas.pair, pas.direction
            """
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if d.get("score_snapshot"):
            try:
                d["score_snapshot"] = json.loads(d["score_snapshot"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result


# ─── Eligibility helpers (utilisés par mt5_bridge + telegram_service) ───


def _has_explicit_state(
    pair: str,
    direction: Optional[str] = None,
    destination: Optional[str] = None,
) -> bool:
    """True si une row matche (pair, direction, destination) avec cascade.

    Match si au moins l'un des 3 niveaux existe : (dir, dest) spec, (dir, dest NULL),
    (dir NULL, dest NULL). Retour True = get_current_state renverra une valeur
    de la DB (pas DEFAULT_STATE), donc le callsite doit honorer l'état.
    """
    _ensure_schema()
    direction = _normalize_direction(direction)
    destination = _normalize_destination(destination)
    with sqlite3.connect(_db_path()) as c:
        # Le OR ci-dessous couvre les 3 niveaux de cascade en une seule query.
        # destination IS NULL matche toujours (destination-agnostic legacy row).
        if direction is not None:
            if destination is not None:
                row = c.execute(
                    """
                    SELECT 1 FROM pair_admission_state
                     WHERE pair = ?
                       AND (direction = ? OR direction IS NULL)
                       AND (destination = ? OR destination IS NULL)
                     LIMIT 1
                    """,
                    (pair, direction, destination),
                ).fetchone()
            else:
                row = c.execute(
                    """
                    SELECT 1 FROM pair_admission_state
                     WHERE pair = ?
                       AND (direction = ? OR direction IS NULL)
                       AND destination IS NULL
                     LIMIT 1
                    """,
                    (pair, direction),
                ).fetchone()
        else:
            row = c.execute(
                "SELECT 1 FROM pair_admission_state WHERE pair = ? LIMIT 1",
                (pair,),
            ).fetchone()
    return bool(row)


def is_auto_exec_eligible(
    pair: str,
    direction: Optional[str] = None,
    destination: Optional[str] = None,
) -> bool:
    """True si (pair, direction, destination) peut être pushée vers son bridge.

    Migration douce : si pas de row matchant la cascade, retourne False et
    le callsite fait son fallback _STAR_PAIRS_SET legacy.
    """
    if not _has_explicit_state(pair, direction, destination):
        return False  # callsite doit faire son fallback
    return get_current_state(pair, direction, destination) == STATE_AUTO_EXEC


def is_telegram_eligible(
    pair: str,
    direction: Optional[str] = None,
    destination: Optional[str] = None,
) -> bool:
    """True si (pair, direction, destination) peut générer un push Telegram.

    PAUSED inclus : on continue à informer le user mais avec verdict SKIP
    forcé côté setup (= signal info, pas trade reco).
    """
    if not _has_explicit_state(pair, direction, destination):
        return False  # callsite doit faire son fallback
    return get_current_state(pair, direction, destination) in (
        STATE_TELEGRAM, STATE_AUTO_EXEC, STATE_PAUSED
    )


def has_explicit_state(
    pair: str,
    direction: Optional[str] = None,
    destination: Optional[str] = None,
) -> bool:
    """API publique de _has_explicit_state pour les callers qui veulent
    décider eux-mêmes du fallback legacy."""
    return _has_explicit_state(pair, direction, destination)


# ─── Write API ──────────────────────────────────────────────────────────


def set_state(
    pair: str,
    new_state: str,
    reason: str,
    direction: Optional[str] = None,
    score_snapshot: Optional[dict] = None,
    transitioned_by: str = "auto",
    destination: Optional[str] = None,
) -> int:
    """Transitionne (pair, direction, destination) vers un nouvel état. Idempotent.

    Si destination=None : row destination-agnostic (s'applique aux 2 bridges).
    Si destination='admin_legacy'/'admin_live' : override pour cette destination.

    Si direction=None : row pair-level (tous les sens).
    Si direction='buy'/'sell' : row direction-specific.
    """
    if new_state not in VALID_STATES:
        raise ValueError(f"État invalide : {new_state}. Doit être dans {VALID_STATES}")
    # Porte du banc d'essai : promouvoir en AUTO_EXEC sur de l'argent réel exige un
    # essai pré-enregistré et passé. Désarmée par défaut, et sans effet sur les
    # autres états ni sur les destinations fictives.
    # ⛔ Placée AVANT toute normalisation : `destination=None` doit arriver tel quel
    # à la porte, qui le traite comme de l'argent réel — un `None` signifie « toutes
    # les destinations », donc `admin_live` en fait partie.
    try:
        from backend.services import research_bench
        _ok, _motif = research_bench.gate_promotion(
            pair, new_state, direction=direction, destination=destination,
            transitioned_by=transitioned_by)
    except ImportError:  # banc absent du déploiement : ne gèle personne
        _ok, _motif = True, "banc absent"
    if not _ok:
        raise PermissionError(f"banc d'essai : {_motif}")
    _ensure_schema()
    direction = _normalize_direction(direction)
    # strict : une destination inconnue doit échouer, jamais devenir globale.
    destination = _normalize_destination(destination, strict=True)

    current = get_current_state(pair, direction, destination)
    if current == new_state:
        logger.debug(
            f"pair_admission: {pair}/{direction}/{destination} déjà {new_state}, no-op"
        )
        return -1

    now = datetime.now(timezone.utc).isoformat()
    score_json = json.dumps(score_snapshot) if score_snapshot else None
    with sqlite3.connect(_db_path()) as c:
        cur = c.execute(
            """
            INSERT INTO pair_admission_state
                (pair, direction, destination, state, state_since, reason, score_snapshot, transitioned_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (pair, direction, destination, new_state, now, reason, score_json, transitioned_by),
        )
        new_id = cur.lastrowid
    dir_label = f"/{direction}" if direction else ""
    dest_label = f"@{destination}" if destination else ""
    logger.warning(
        f"pair_admission: {pair}{dir_label}{dest_label} {current} → {new_state} "
        f"by={transitioned_by} reason={reason}"
    )

    # Notification Telegram infra des transitions, sauf le backfill initial
    # (= silencieux pour ne pas spammer ~30 messages au déploiement). Best-effort :
    # toute erreur Telegram est swallowée pour ne jamais bloquer l'écriture DB.
    if not transitioned_by.startswith("auto:backfill"):
        try:
            _notify_transition(pair, direction, current, new_state, reason, score_snapshot, transitioned_by)
        except Exception as e:
            logger.debug(f"pair_admission: telegram notify failed: {e}")

    return new_id


def _notify_transition(
    pair: str,
    direction: Optional[str],
    from_state: str,
    to_state: str,
    reason: str,
    score: Optional[dict],
    transitioned_by: str,
) -> None:
    """Pousse une alerte HTML sur le canal Telegram infra @xav_scalping_infra_bot.

    Format compact : pair/direction, transition, raison + métriques score si dispo.
    Best-effort fire-and-forget. Si l'event loop n'a pas de session async dispo,
    on lance la coroutine dans un thread isolé pour ne pas bloquer le caller.
    """
    import asyncio
    import html
    from backend.services.telegram_service import send_infra_text

    dir_label = direction.upper() if direction else "pair-level"
    safe_reason = html.escape((reason or "").strip())[:200]

    # Emoji selon transition pour scanability
    arrow = {
        ("OBSERVED", "TELEGRAM"): "📈",
        ("TELEGRAM", "OBSERVED"): "📉",
        ("AUTO_EXEC", "PAUSED"): "⏸",
        ("PAUSED", "AUTO_EXEC"): "▶️",
        ("PAUSED", "DEMOTED"): "❌",
        ("OBSERVED", "AUTO_EXEC"): "📈",
    }.get((from_state, to_state), "🔄")

    lines = [
        f"{arrow} <b>Pair admission</b> · <code>{html.escape(pair)}</code> · {dir_label}",
        f"<b>{from_state}</b> → <b>{to_state}</b>",
        f"Raison : {safe_reason}",
    ]
    if score and isinstance(score, dict) and score.get("sample"):
        lines.append(
            f"Score : n={score.get('sample')} pnl%={score.get('pnl_pct')} "
            f"WR%={score.get('wr')} PF={score.get('pf')} maxDD%={score.get('max_dd_pct')}"
        )
    if transitioned_by and transitioned_by != "auto":
        lines.append(f"By : {html.escape(transitioned_by)}")
    text = "\n".join(lines)

    # Run la coroutine send_infra_text dans le contexte approprié
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    coro = send_infra_text(text, parse_mode="HTML")
    if loop and loop.is_running():
        # Schedule sans bloquer (fire-and-forget)
        asyncio.ensure_future(coro)
    else:
        # Pas de loop actif (test ou contexte sync) → run sync
        asyncio.run(coro)

    # Notif user-facing en plus de l'infra (refonte 2026-06-10).
    # Best-effort, fire-and-forget. Évite spam : déjà filtré côté caller
    # par `transitioned_by != "auto:backfill"`.
    try:
        from backend.services.telegram_service import send_pac_transition_user
        coro_user = send_pac_transition_user(pair, direction, from_state, to_state, reason or "")
        if loop and loop.is_running():
            asyncio.ensure_future(coro_user)
        else:
            asyncio.run(coro_user)
    except Exception as e:
        logger.debug(f"pair_admission: telegram user notify failed: {e}")


# ─── Score composite + transitions auto ─────────────────────────────────

# Seuils par défaut (overridables via env). On garde des seuils prudents
# côté promotion (asymétrique avec demotion) — philosophie loss-averse.
PROMOTE_MIN_SAMPLE = 30           # nb minimum de setups pour évaluer une pair
PROMOTE_MIN_PNL_PCT = 2.0         # +2% sur le capital sur la fenêtre
PROMOTE_MIN_WR_PCT = 45.0         # WR (Win Rate) ≥ 45% pour promote
PROMOTE_MIN_PF = 1.3              # PF (Profit Factor) ≥ 1.3
PROMOTE_MAX_DD_PCT = 10.0         # Drawdown max < 10% du capital

DEMOTE_MAX_RE_PAUSES_60D = 2      # 2× re-pause auto en 60j → DEMOTED


def _compute_pf(trades_pnl: list[float]) -> float:
    """Profit Factor = sum(gains) / sum(losses en absolu). Inf si pas de loss."""
    gains = sum(p for p in trades_pnl if p > 0)
    losses = abs(sum(p for p in trades_pnl if p < 0))
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return round(gains / losses, 2)


def _compute_max_dd(trades_pnl: list[float], capital: float) -> float:
    """Drawdown max en % du capital sur la séquence chronologique des trades.

    On prend l'equity curve = cumul des PnL, et on calcule le plus grand
    écart entre un pic et le creux suivant. Le résultat est exprimé en %
    négatif (ex: -7.5 = -7.5% du capital).
    """
    if not trades_pnl or capital <= 0:
        return 0.0
    # On reverse car nos sources retournent DESC par date — on veut chrono ASC
    chrono = list(reversed(trades_pnl))
    equity = 0.0
    peak = 0.0
    max_dd_eur = 0.0
    for p in chrono:
        equity += p
        peak = max(peak, equity)
        dd = equity - peak
        max_dd_eur = min(max_dd_eur, dd)
    return round(100.0 * max_dd_eur / capital, 2)


def _r_unit_eur() -> float:
    """Valeur en euros d'une unité de risque (1 R), selon la politique de sizing.

    Un signal résolu vaut `rr_realized` R ; on le convertit ici en euros pour
    l'homogénéiser avec les PnL réels de `personal_trades` / `ea_closed_trades`.

    Utiliser `TRADING_CAPITAL × RISK_PER_TRADE_PCT` — et non une constante —
    rend `pnl_pct` égal à `somme(R) × RISK_PER_TRADE_PCT`, donc **indépendant
    du capital configuré**. L'ancien chemin shadow figeait 1 R = 100 € contre
    un capital réel de 3 000 €, ce qui gonflait mécaniquement `pnl_pct` d'un
    facteur 3,3 et produisait les « −103 % » relevés dans l'historique des
    rétrogradations.
    """
    from config.settings import TRADING_CAPITAL, RISK_PER_TRADE_PCT
    return TRADING_CAPITAL * (RISK_PER_TRADE_PCT / 100.0)


def _fetch_signal_pnls(pair: str, direction: Optional[str], need: int) -> list[float]:
    """PnL en euros des N derniers signaux résolus, depuis `backtest.db.trades`.

    ⚠️ Cette fonction lisait `shadow_setups` jusqu'au 2026-08-04. Cette table
    répliquait une même idée de trade jusqu'à 960 fois (déduplication
    inopérante, cf. `shadow_v1._bar_timestamp`), et les décisions automatiques
    d'admission en dépendaient : trois paires equity ont été rétrogradées le
    2026-08-04 sur un `wr 0.0` qui n'était qu'un unique trade perdant compté
    457 fois. `backtest.db.trades` est saine (duplication ×1,00 vérifiée).
    """
    if need <= 0:
        return []
    try:
        from backend.services.backtest_service import fetch_recent_rr
        rr = fetch_recent_rr(pair, direction, need)
    except Exception as e:  # backtest.db indispo (tests isolés) : pas de fallback
        logger.debug(f"admission: backtest.db indisponible pour {pair}: {e}")
        return []
    unit = _r_unit_eur()
    return [r * unit for r in rr]


def _fetch_trades_for_pair(pair: str, window: int, direction: Optional[str] = None) -> list[float]:
    """Trades réels, complétés par des signaux si la fenêtre n'est pas pleine.

    Voir `_fetch_real_trades_for_pair` et `_fetch_signal_pnls`. Le scoring
    passe par ces deux-là directement, afin de savoir d'où vient chaque PnL.
    """
    pnls = _fetch_real_trades_for_pair(pair, window, direction)
    if len(pnls) < window:
        pnls.extend(_fetch_signal_pnls(pair, _normalize_direction(direction),
                                       window - len(pnls)))
    return pnls


def _fetch_real_trades_for_pair(pair: str, window: int, direction: Optional[str] = None) -> list[float]:
    """Union admin (personal_trades) + Premium (ea_closed_trades). Argent réel.

    Filtre optionnel par direction ('buy' ou 'sell'). Si direction None,
    agrège toutes directions confondues (= comportement pair-level).
    """
    _ensure_schema()
    from backend.services import ea_closed_trades_service as _eact
    _eact._ensure_schema()
    direction = _normalize_direction(direction)
    pnls: list[float] = []

    # ⛔ L'exclusion se fait EN SQL, avant le LIMIT. La faire en Python après
    # coup rendrait une fenêtre de moins de `window` trades comptables : on
    # noterait la paire sur 29 trades en croyant en avoir 30.
    # ⚠️ `CAST(... AS INTEGER)` n'est pas cosmétique. `mt5_ticket` est stocké en
    # TEXTE ici et en ENTIER ailleurs ; et `coalesce(mt5_ticket, 0)` EFFACE
    # l'affinité de la colonne, si bien que SQLite compare un texte à un entier
    # sans jamais les trouver égaux. Le filtre passait alors inaperçu — écarter
    # zéro ticket en silence, exactement le défaut qu'on prétend corriger.
    from backend.services.tickets_exclus import filtre_sql
    exclus = _tickets_exclus()
    filtre = filtre_sql(exclus)
    ex = tuple(exclus)

    with sqlite3.connect(_db_path()) as c:
        if direction is not None:
            # Filtre par direction sur toutes les sources
            rows = c.execute(
                f"""
                SELECT pnl, closed_at FROM personal_trades
                 WHERE pair = ? AND status = 'CLOSED'
                   AND is_auto = 1 AND pnl IS NOT NULL
                   AND LOWER(direction) = ?{filtre}
                UNION ALL
                SELECT pnl, closed_at FROM ea_closed_trades
                 WHERE pair = ? AND LOWER(direction) = ?{filtre}
                ORDER BY closed_at DESC LIMIT ?
                """,
                (pair, direction) + ex + (pair, direction) + ex + (window,),
            ).fetchall()
        else:
            rows = c.execute(
                f"""
                SELECT pnl, closed_at FROM personal_trades
                 WHERE pair = ? AND status = 'CLOSED'
                   AND is_auto = 1 AND pnl IS NOT NULL{filtre}
                UNION ALL
                SELECT pnl, closed_at FROM ea_closed_trades
                 WHERE pair = ?{filtre}
                ORDER BY closed_at DESC LIMIT ?
                """,
                (pair,) + ex + (pair,) + ex + (window,),
            ).fetchall()
        for r in rows:
            pnls.append(float(r[0]))
    return pnls


def _tickets_exclus() -> frozenset[int]:
    """Tickets retirés du scoring d'admission — et de rien d'autre.

    Lu à l'appel, jamais à l'import : un test doit pouvoir le régler, et le
    conteneur doit pouvoir changer sans reconstruction d'image.
    """
    from backend.services.tickets_exclus import tickets_exclus
    return tickets_exclus()


def tickets_exclus_presents(pair: str, direction: Optional[str] = None) -> list[int]:
    """Tickets exclus qui existent RÉELLEMENT pour cette paire et ce sens.

    Sert à inscrire l'exclusion dans le relevé de score. ⚠️ Sans cette trace,
    un score ne serait pas reproductible : un lecteur futur verrait des
    chiffres qu'il ne saurait pas refaire, et un scoring qui écarte en silence
    est indiscernable d'un scoring qui n'a rien écarté.
    """
    exclus = _tickets_exclus()
    if not exclus:
        return []
    _ensure_schema()
    direction = _normalize_direction(direction)
    trous = ",".join("?" * len(exclus))
    ex = tuple(exclus)
    sql = (f"SELECT DISTINCT mt5_ticket FROM personal_trades "
           f"WHERE pair = ? AND status = 'CLOSED' AND is_auto = 1 "
           f"AND pnl IS NOT NULL AND CAST(mt5_ticket AS INTEGER) IN ({trous})")
    args: tuple = (pair,) + ex
    if direction is not None:
        sql += " AND LOWER(direction) = ?"
        args += (direction,)
    with sqlite3.connect(_db_path()) as c:
        return sorted(int(r[0]) for r in c.execute(sql, args) if r[0] is not None)


def compute_promotion_score(pair: str, window: int = 30, direction: Optional[str] = None) -> dict[str, Any]:
    """Calcule le score composite pour décider si (pair, direction) peut transiter.

    Si direction None : agrège toutes directions (= scoring pair-level legacy).
    Si direction 'buy'/'sell' : scoring restreint à ce sens.

    Retourne :
    - sample : nb total de trades évalués (réels + simulés de complément)
    - n_real : nb de trades RÉELS dans ce total (sous-ensemble de `sample`)
    - sum_pnl : PnL cumulé en euros
    - pnl_pct : PnL en % du capital (cf TRADING_CAPITAL config)
    - wr : Win Rate en %
    - pf : Profit Factor
    - max_dd_pct : Max Drawdown en % du capital (négatif)
    - eligible_for : 'AUTO_EXEC' | 'TELEGRAM' | 'OBSERVED' | 'INDETERMINATE'
      (INDETERMINATE si n_real < PAC_MIN_REAL_TRADES — cf garde-fou ci-dessous)

    ⚠️ Garde-fou échantillon réel (2026-08-05) : quand `n_real` (trades
    RÉELS, argent effectivement engagé) est sous le plancher
    `config.settings.PAC_MIN_REAL_TRADES`, la fonction rend
    `eligible_for = STATE_INDETERMINATE` plutôt que de statuer — même si le
    complément par signaux simulés suffit à remplir `window`. Les métriques
    (sum_pnl, wr, pf, ...) restent calculées sur l'échantillon complet pour
    l'affichage/debug, mais ne doivent jamais servir de base à une transition
    automatique tant que `eligible_for == STATE_INDETERMINATE` : c'est
    `evaluate_pair` qui applique cette règle côté écriture.
    """
    from config.settings import TRADING_CAPITAL
    real_pnls = _fetch_real_trades_for_pair(pair, window, direction=direction)
    _exclus_vus = tickets_exclus_presents(pair, direction)
    n_real = len(real_pnls)
    pnls = list(real_pnls)
    # Complément signaux : les trades réels sont rares (une pair en OBSERVED
    # n'en a aucun), donc on remplit la fenêtre avec les signaux résolus du
    # radar pour calculer des métriques informatives. Cf. garde-fou ci-dessus :
    # ce complément n'autorise plus, à lui seul, une décision automatique.
    if n_real < window:
        pnls.extend(_fetch_signal_pnls(pair, _normalize_direction(direction),
                                       window - n_real))
    sample = len(pnls)
    n_simulated = sample - n_real
    min_real = _min_real_trades()
    indeterminate = n_real < min_real

    # Étiquette honnête : jusqu'au 2026-08-04 `pnl_source` annonçait
    # 'personal_trades' même quand 100 % de l'échantillon venait du shadow.
    if sample == 0 or n_real == sample:
        pnl_source = "personal_trades"
    elif n_real == 0:
        pnl_source = "backtest_trades"
    else:
        pnl_source = f"mixed({n_real}/{sample} réels)"

    if sample == 0:
        if indeterminate:
            eligible = STATE_INDETERMINATE
            reason = (
                f"indécidable : pas assez de données du tout "
                f"(0 trade réel, 0 signal résolu ; seuil minimum de trades "
                f"réels = {min_real})"
            )
        else:
            eligible = STATE_OBSERVED
            reason = "no data"
        return {
            "sample": 0, "n_real": 0, "sum_pnl": 0.0, "pnl_pct": 0.0,
            "wr": 0.0, "pf": 0.0, "max_dd_pct": 0.0,
            "eligible_for": eligible,
            "reason": reason,
            "pnl_source": pnl_source,
            # ⚠️ Sans cette trace le score ne serait pas reproductible : un
            # lecteur futur verrait des chiffres qu'il ne saurait pas refaire.
            "tickets_exclus": _exclus_vus,
        }

    sum_pnl = round(sum(pnls), 2)
    wins = sum(1 for p in pnls if p > 0)
    wr = round(100.0 * wins / sample, 2)
    pf = _compute_pf(pnls)
    pnl_pct = round(100.0 * sum_pnl / TRADING_CAPITAL, 2)
    max_dd_pct = _compute_max_dd(pnls, TRADING_CAPITAL)

    if indeterminate:
        eligible = STATE_INDETERMINATE
        reason = (
            f"indécidable : pas assez de trades réels ({n_real}/{min_real} "
            f"requis ; échantillon complété par {n_simulated} signal(aux) "
            "simulé(s) — insuffisant pour une décision auto)"
        )
        # ⛔ Métriques MASQUÉES (2026-08-13). Elles sont calculées sur un
        # échantillon complété par `backtest.db`, dont les issues sortent d'un
        # sondage du prix courant toutes les ~3 min — aucun rejeu de bougies.
        # Mesuré contre les bougies : 55 à 65 % de ses GAGNANTS avaient déjà
        # touché leur stop. Le biais ne va que dans un sens, il gonfle. Un `wr`
        # de 45 % y vaut environ 18 % réels.
        #
        # `PAC_MIN_REAL_TRADES` empêchait déjà ces chiffres de DÉCIDER ; il ne
        # les empêchait pas d'être LUS. `/api/admin/pair-admission` les affiche,
        # et 47 transitions de l'historique portent `admin_manual`.
        #
        # ⚠️ On MASQUE, on ne supprime pas : `sample`, `n_real` et
        # `n_simulated` restent, sinon l'écran dirait « pas de données » là où
        # il y en a — des mauvaises. Nommer la borne plutôt que laisser un trou.
        # Cf. [[feedback_detection_par_absence]].
        #
        # Sûr côté lecture : le seul consommateur numérique
        # (`evaluate_pair`, auto-pause sur `pnl_pct < -3`) est protégé par un
        # retour anticipé sur `eligible_for == STATE_INDETERMINATE`.
        return {
            "sample": sample, "n_real": n_real, "n_simulated": n_simulated,
            "sum_pnl": None, "pnl_pct": None,
            "wr": None, "pf": None, "max_dd_pct": None,
            "metriques_masquees": True,
            "eligible_for": eligible, "reason": reason,
            "pnl_source": pnl_source,
            # ⚠️ Sans cette trace le score ne serait pas reproductible : un
            # lecteur futur verrait des chiffres qu'il ne saurait pas refaire.
            "tickets_exclus": _exclus_vus,
        }

    # ---- n_real >= min_real : comportement inchangé depuis avant 2026-08-05 ----
    # Décision : tous les critères doivent passer pour promotion AUTO_EXEC
    eligible = STATE_OBSERVED
    reason_parts = []
    if sample < PROMOTE_MIN_SAMPLE:
        reason_parts.append(f"sample {sample} < {PROMOTE_MIN_SAMPLE}")
    if pnl_pct < PROMOTE_MIN_PNL_PCT:
        reason_parts.append(f"pnl_pct {pnl_pct} < {PROMOTE_MIN_PNL_PCT}")
    if wr < PROMOTE_MIN_WR_PCT:
        reason_parts.append(f"wr {wr} < {PROMOTE_MIN_WR_PCT}")
    if pf < PROMOTE_MIN_PF:
        reason_parts.append(f"pf {pf} < {PROMOTE_MIN_PF}")
    if max_dd_pct < -PROMOTE_MAX_DD_PCT:
        reason_parts.append(f"max_dd {max_dd_pct} < -{PROMOTE_MAX_DD_PCT}")

    if not reason_parts:
        # Tous critères OK : cible déterminée par env AUTO_PROMOTE_TARGET.
        # Défaut TELEGRAM (admin valide AUTO_EXEC ensuite) ; AUTO_EXEC = full-auto.
        eligible = AUTO_PROMOTE_TARGET
        reason = f"all promote criteria met → eligible for {AUTO_PROMOTE_TARGET}"
    else:
        reason = "; ".join(reason_parts)

    return {
        "sample": sample,
        "n_real": n_real,
        "sum_pnl": sum_pnl,
        "pnl_pct": pnl_pct,
        "wr": wr,
        "pf": pf,
        "max_dd_pct": max_dd_pct,
        "eligible_for": eligible,
        "reason": reason,
        "pnl_source": pnl_source,
        # ⚠️ Sans cette trace le score ne serait pas reproductible : un
        # lecteur futur verrait des chiffres qu'il ne saurait pas refaire.
        "tickets_exclus": _exclus_vus,
    }


def _count_recent_pauses(pair: str, days: int = 60) -> int:
    """Compte le nombre de transitions vers PAUSED dans les N derniers jours."""
    _ensure_schema()
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with sqlite3.connect(_db_path()) as c:
        row = c.execute(
            """
            SELECT COUNT(*) FROM pair_admission_state
             WHERE pair = ? AND state = 'PAUSED' AND state_since >= ?
            """,
            (pair, cutoff),
        ).fetchone()
    return int(row[0]) if row else 0


# ─── Retour de pause : contrôle par comparaison inter-paires (2026-08-05) ─
#
# Le défaut corrigé le 2026-08-05 : `evaluate_pair` rendait l'argent réel à
# une pair PAUSED après un simple délai écoulé, sans jamais consulter le
# `score` calculé (enregistré en snapshot, jamais lu). Décision d'architecture
# (Xavier) : le retour est désormais conditionné à « les signaux de la pair
# font-ils mieux que la moyenne des autres pairs de la même classe d'actif
# (même sens, même fenêtre) ? », pas à un seuil de rentabilité absolu — cf.
# `config.settings` section « Retour de pause » et
# `backend.services.random_entry_control` (module générique, non modifié ici)
# pour le mécanisme statistique (bootstrap par blocs apparié).
#
# ⚠️ Renommé le 2026-08-05 (suite) : le nom d'origine (« contrôle par entrées
# aléatoires ») était trompeur. Le domaine comparé n'a jamais été une entrée
# réellement aléatoire — c'est le recensement de TOUTES les pairs (même sens,
# même fenêtre), restreint depuis ce correctif à la MÊME CLASSE D'ACTIF que
# la pair testée (cf. `_build_peer_control_populations` : comparer une
# crypto à des pairs forex n'aurait pas de sens même comme comparaison entre
# pairs — régimes, volatilité, corrélations différents). La question posée
# est donc « cette pair vaut-elle mieux que choisir une autre pair comparable
# au hasard ? » — une comparaison ENTRE PAIRES, jamais un test contre une
# entrée réellement aléatoire sur le marché.
#
# ⚠️ CONDITION NÉCESSAIRE, JAMAIS SUFFISANTE : un résultat favorable ici dit
# seulement que la pair n'est pas pire que ses semblables — pas que les
# patterns battent une entrée réellement aléatoire. Cette dernière question
# est systémique (si les patterns sont mauvais partout, toutes les pairs sont
# également mauvaises, chacune paraît moyenne, et toutes passeraient ce
# contrôle) : elle ne se mesure que hors ligne, par backtest contre une VRAIE
# entrée aléatoire (`random_entry_control` appelé directement, hors de ce
# contrôleur, module non modifié ici et correct en lui-même). Réponse déjà
# connue pour au moins un système testé : les patterns font 0,182 R de MOINS
# qu'une entrée aléatoire (p<0,001) — cf. `scratchpad/test-difference-directe
# .md`. La porte de coût (frais mesurés, ailleurs) reste seule responsable de
# la rentabilité absolue.


def _pause_cooloff_days() -> int:
    """Délai de refroidissement (jours) avant réévaluation d'une pair PAUSED.

    Import différé, relu à chaque appel — même schéma que `_min_real_trades`
    ci-dessus : un test peut monkeypatcher `config.settings.PAC_PAUSE_COOLOFF_DAYS`
    et voir l'effet immédiatement.
    """
    try:
        from config.settings import PAC_PAUSE_COOLOFF_DAYS
        return int(PAC_PAUSE_COOLOFF_DAYS)
    except Exception:
        return 14


def _peer_control_block_size() -> int:
    try:
        from config.settings import PAC_PEER_CONTROL_BLOCK_SIZE
        return int(PAC_PEER_CONTROL_BLOCK_SIZE)
    except Exception:
        return 10


def _peer_control_n_boot() -> int:
    try:
        from config.settings import PAC_PEER_CONTROL_N_BOOT
        return int(PAC_PEER_CONTROL_N_BOOT)
    except Exception:
        return 1000


def _peer_control_min_domain_blocks() -> int:
    try:
        from config.settings import PAC_PEER_CONTROL_MIN_DOMAIN_BLOCKS
        return int(PAC_PEER_CONTROL_MIN_DOMAIN_BLOCKS)
    except Exception:
        return 3


def _peer_control_seed() -> int:
    try:
        from config.settings import PAC_PEER_CONTROL_SEED
        return int(PAC_PEER_CONTROL_SEED)
    except Exception:
        return 0


def _peer_control_cache_hours() -> float:
    try:
        from config.settings import PAC_PEER_CONTROL_CACHE_HOURS
        return float(PAC_PEER_CONTROL_CACHE_HOURS)
    except Exception:
        return 6.0


def _peer_control_since_iso() -> str:
    """Borne basse (ISO UTC) de la fenêtre saine de `shadow_setups`.

    Constante de code, pas un réglage : c'est un fait historique du dataset,
    pas un arbitrage produit. Tout `shadow_setups` antérieur au 2026-08-04
    souffre du bug de déduplication ×960 (cf. `shadow_v1._bar_timestamp`,
    mesuré ×960 sur SPX, ×229 sur AAPL) — une même idée de trade comptée des
    centaines de fois, dans des proportions qui varient par pair. Mélanger
    cet historique aux deux populations (domaine et pattern) les fausserait
    différemment l'une de l'autre, ce qui invaliderait précisément la
    comparabilité que le contrôle est censé garantir.
    """
    return "2026-08-04T00:00:00+00:00"


def _fetch_peer_control_rows(direction: str) -> list[tuple]:
    """Lignes `shadow_setups` résolues, ce sens, depuis la fenêtre saine.

    Retourne (id, pair, bar_timestamp, risk_pct, pnl_pct_net) — TOUTES pairs
    confondues (le filtre par classe d'actif est appliqué ensuite par
    `_build_peer_control_populations`, pas ici). C'est le recensement brut ;
    `_build_peer_control_populations` en dérive le domaine (pairs de la même
    classe d'actif) et le pattern (une seule pair), toujours à partir des
    MÊMES lignes, pour garantir que `pattern` reste un sous-ensemble strict
    de `domain`.
    """
    from backend.services.shadow_v2_core_long import ensure_schema as _ensure_shadow_schema
    _ensure_shadow_schema()
    since = _peer_control_since_iso()
    with sqlite3.connect(_db_path()) as c:
        rows = c.execute(
            """
            SELECT id, pair, bar_timestamp, risk_pct, pnl_pct_net
              FROM shadow_setups
             WHERE direction = ?
               AND bar_timestamp >= ?
               AND outcome IN ('TP1', 'SL')
               AND pnl_pct_net IS NOT NULL
               AND risk_pct IS NOT NULL AND risk_pct > 0
            """,
            (direction, since),
        ).fetchall()
    return rows


def _build_peer_control_populations(pair: str, direction: str) -> tuple[list, list]:
    """Construit (domaine, pattern) depuis `shadow_setups` pour une (pair, direction).

    - **pattern** = les setups de `pair`, ce `direction` — « les signaux de
      la pair » dont on veut savoir s'ils font mieux que leurs semblables.
    - **domain** = les lignes de la MÊME CLASSE D'ACTIF que `pair`
      (`config.settings.asset_class_for`, fonction existante — pas réécrite
      ici), même `direction`, même fenêtre temporelle. Comparer une crypto à
      des pairs forex n'aurait pas de sens même comme comparaison entre
      pairs : régimes, volatilité et corrélations différents. Représente
      « choisir une autre pair de la MÊME FAMILLE au hasard », par
      opposition à choisir spécifiquement `pair` — PAS une entrée réellement
      aléatoire sur le marché (cf. avertissement en tête de section « Retour
      de pause »).

    ⚠️ Restreindre le domaine à la classe d'actif le rend mécaniquement plus
    petit. Le seuil minimal du bootstrap (`min_domain_blocks × block_size`,
    cf. `paired_block_bootstrap_delta`) porte sur CE domaine réduit : une
    classe représentée par une SEULE pair dans `WATCHED_PAIRS` (ex. `energy`
    = WTI/USD seule à ce jour, cf. `config.settings.asset_class_for`) fait
    que `domain == pattern` À L'IDENTIQUE — aucune AUTRE pair de la classe
    pour servir de comparaison. Dans ce cas, `delta_observed` est
    STRUCTURELLEMENT nul et le contrôle ne peut JAMAIS trancher en faveur de
    la pair, quelle que soit la qualité réelle de ses signaux : ce n'est pas
    un bug, c'est l'absence de pairs comparables qui rend la question
    elle-même sans réponse pour une classe mono-pair. Le repli reste sûr
    (la pair reste en pause), mais une classe mono-pair ne pourra JAMAIS
    revenir en AUTO_EXEC par cette voie — seule une transition manuelle le
    peut. Voir le rapport de la tâche pour le décompte pair/classe actuel.

    Garantie de comparabilité : `pattern` est un sous-ensemble STRICT de
    `domain` — mêmes objets `TimedTrade`, filtrés en Python après une seule
    requête SQL — jamais deux populations construites séparément (ce qui
    pourrait laisser une clé `pattern` absente de `domain`, invalidant
    l'appariement du bootstrap : cf. docstring de
    `random_entry_control.paired_block_bootstrap_delta`).

    La clé (`TimedTrade.key`) est `(bar_timestamp, id)`, PAS `bar_timestamp`
    seul. Plusieurs pairs partagent le même `bar_timestamp` H1 (les cycles
    radar tournent pour toutes les pairs en même temps) : une clé non unique
    ferait que le module associerait à tort la ligne d'une AUTRE pair au
    pattern testé dès qu'elle partage l'horodatage — silencieusement, car le
    module fait confiance à l'égalité de clé pour apparier domaine et
    pattern. `id` (clé primaire, unique par construction) désambiguïse sans
    perdre l'ordre chronologique : le tri par tuple compare `bar_timestamp`
    d'abord, `id` seulement en cas d'égalité.
    """
    from backend.services.random_entry_control import TimedTrade, r_multiple as _rc_r_multiple
    from config.settings import asset_class_for

    target_class = asset_class_for(pair)
    rows = _fetch_peer_control_rows(direction)
    domain: list[TimedTrade] = []
    pattern: list[TimedTrade] = []
    for row_id, row_pair, bar_ts, risk_pct, pnl_pct_net in rows:
        if asset_class_for(row_pair) != target_class:
            continue  # restriction 2026-08-05 : hors classe d'actif, pas comparable
        r = _rc_r_multiple(pnl_pct_net, risk_pct)
        if r is None:
            continue
        trade = TimedTrade(key=(bar_ts, row_id), r_multiple=r)
        domain.append(trade)
        if row_pair == pair:
            pattern.append(trade)
    return domain, pattern


def peer_control_for_pair(pair: str, direction: Optional[str]):
    """Contrôle « les signaux de `pair` font-ils mieux que la moyenne des
    pairs comparables (même classe d'actif) ? » (non caché).

    Retourne un `random_entry_control.RandomControlResult` (type du module
    générique, non renommé ici — cf. avertissement en tête de section
    « Retour de pause »). `pattern` et `domain` sont restreints à la MÊME
    classe d'actif que `pair` (`_build_peer_control_populations`).
    `direction` DOIT être 'buy'/'sell' explicite : le contrôle compare des
    populations de même sens — un bucket pair-level (`direction=None`) n'a
    pas de sens unique à comparer, donc rend un résultat explicitement
    indéterminé plutôt que de deviner un sens ou de mélanger les deux.

    ⚠️ CONDITION NÉCESSAIRE, JAMAIS SUFFISANTE : un résultat favorable dit
    seulement que `pair` n'est pas pire que ses semblables de la même classe
    d'actif — jamais que les patterns battent une entrée réellement
    aléatoire (question systémique distincte, cf. tête de section).
    """
    from backend.services.random_entry_control import paired_block_bootstrap_delta, RandomControlResult

    direction_n = _normalize_direction(direction)
    block_size = _peer_control_block_size()
    n_boot = _peer_control_n_boot()
    seed = _peer_control_seed()
    if direction_n is None:
        return RandomControlResult(
            n_pattern=0, n_random=0, delta_observed=None,
            ci95_low=None, ci95_high=None, p_value=None, significant=None, mde80=None,
            n_boot_valid=0, n_boot_requested=n_boot, n_boot_skipped=0,
            block_size=block_size, seed=seed,
            insufficient_reason="direction non spécifiée (buy/sell requis pour comparer un même sens)",
        )
    domain, pattern = _build_peer_control_populations(pair, direction_n)
    return paired_block_bootstrap_delta(
        domain, pattern,
        block_size=block_size, n_boot=n_boot, seed=seed,
        min_domain_blocks=_peer_control_min_domain_blocks(),
    )


# Cache mémoire de process : {(pair, direction): (calculé_à, résultat)}.
# `evaluate_pair` tourne sur tout l'univers à chaque cycle planifié (60 min,
# cf. scheduler.py) ; sans ce cache, une pair PAUSED restée éligible (délai
# écoulé, disjoncteur non déclenché) relancerait le bootstrap par blocs à
# CHAQUE cycle tant qu'elle reste PAUSED — coûteux et inutile, le résultat ne
# change pas d'un cycle à l'autre en l'absence de nouvelles données shadow.
_PEER_CONTROL_CACHE: dict[tuple[str, str], tuple[datetime, Any]] = {}


def peer_control_for_pair_cached(pair: str, direction: Optional[str]):
    """`peer_control_for_pair`, mémoïsé `PAC_PEER_CONTROL_CACHE_HOURS` heures.

    Cache en mémoire de process, vidé à chaque redémarrage — acceptable : un
    recalcul de plus au démarrage n'est un problème que de coût, jamais de
    correction (le résultat est toujours recalculable depuis `shadow_setups`).
    """
    from datetime import timedelta

    direction_n = _normalize_direction(direction)
    key = (pair, direction_n or "")
    now = datetime.now(timezone.utc)
    ttl = timedelta(hours=_peer_control_cache_hours())
    cached = _PEER_CONTROL_CACHE.get(key)
    if cached is not None and (now - cached[0]) < ttl:
        return cached[1]
    result = peer_control_for_pair(pair, direction_n)
    _PEER_CONTROL_CACHE[key] = (now, result)
    return result


def _fmt_r(x: Optional[float]) -> str:
    """Formatte un champ potentiellement `None` de `RandomControlResult` pour un message."""
    return "?" if x is None else f"{x:.3f}"


def _peer_control_summary(control) -> str:
    """Résumé compact du résultat, pour `reason` / logs — jamais un crash sur champ `None`."""
    return (
        f"Δ={_fmt_r(control.delta_observed)}R "
        f"IC95=[{_fmt_r(control.ci95_low)},{_fmt_r(control.ci95_high)}] "
        f"p={_fmt_r(control.p_value)} n_pattern={control.n_pattern} n_domaine={control.n_random}"
    )


def _beats_peer_control(control) -> bool:
    """True seulement si le contrôle tranche EN FAVEUR de la pair : IC95 entièrement
    positif (`significant=True` ET `ci95_low > 0`). Tout le reste — indéterminé
    (`significant is None`), non tranché (`significant=False`, l'IC couvre 0), ou
    significativement SOUS la moyenne des pairs comparables (`ci95_high < 0`) — ne
    rend jamais l'argent réel : « on ne sait pas encore » n'est pas un échec, mais ce
    n'est pas non plus une preuve.

    ⚠️ Rappel (cf. tête de section « Retour de pause ») : `True` ici signifie
    seulement « cette pair n'est pas pire que ses semblables de la même classe
    d'actif » — jamais « les patterns battent une entrée réellement aléatoire »,
    question systémique distincte, non répondue par ce contrôle.
    """
    return bool(control.significant is True and control.ci95_low is not None and control.ci95_low > 0)


def _peer_control_keep_reason(control) -> str:
    """Message expliquant pourquoi la pair reste en pause après le contrôle par
    comparaison inter-paires."""
    if control.significant is None:
        return (
            f"comparaison inter-paires indécidable ({control.insufficient_reason}) "
            "— reste en pause, ce n'est pas un échec"
        )
    if control.significant is False:
        return f"signaux non distinguables de la moyenne des pairs comparables ({_peer_control_summary(control)}) — reste en pause"
    return f"signaux significativement SOUS la moyenne des pairs comparables ({_peer_control_summary(control)}) — reste en pause"


def evaluate_pair(pair: str, direction: Optional[str] = None) -> dict[str, Any]:
    """Décide la transition d'un (pair, direction) selon son état + score.

    Si direction None : scoring + transition agrégés (= pair-level legacy).
    Si direction 'buy'/'sell' : scoring + transition restreint à ce sens.

    Retourne {action, from_state, to_state?, score, reason}.
    """
    direction = _normalize_direction(direction)
    current = get_current_state(pair, direction)
    score = compute_promotion_score(pair, direction=direction)

    if current == STATE_OBSERVED:
        # Accepte TELEGRAM ou AUTO_EXEC comme cible selon AUTO_PROMOTE_TARGET env.
        target = score["eligible_for"]

        # ⚠️ PORTE À SENS UNIQUE — corrigée le 2026-08-06.
        #
        # `INDETERMINATE` signifie « moins de PAC_MIN_REAL_TRADES trades
        # RÉELS », pas « mauvaise paire ». Or une paire `OBSERVED` **n'exécute
        # rien** : elle n'accumulera JAMAIS ces trades réels. La condition
        # était donc insatisfaisable par construction — aucune paire ne pouvait
        # plus être promue, et l'univers tradable ne pouvait que rétrécir.
        #
        # Le garde-fou du 2026-08-05 existe pour empêcher une décision prise
        # sur des données SIMULÉES quand elle touche à de l'argent réel. Or
        # `TELEGRAM` n'engage **aucun argent** : c'est une notification. Le
        # garde-fou n'y protège rien et n'y produit que de la paralysie.
        #
        # On oriente donc l'indécidable vers `TELEGRAM`, **jamais** directement
        # vers `AUTO_EXEC` : le passage à l'argent réel reste soumis au palier
        # temporel de la branche `TELEGRAM` ci-dessous.
        if target == STATE_INDETERMINATE:
            target = STATE_TELEGRAM

        if target in (STATE_TELEGRAM, STATE_AUTO_EXEC):
            set_state(pair, target, f"auto-promote: {score['reason']}", direction=direction, score_snapshot=score)
            return {"action": "transition", "from_state": current, "to_state": target, "score": score, "reason": score["reason"]}
        return {"action": "keep", "from_state": current, "score": score, "reason": score["reason"]}

    elif current == STATE_TELEGRAM:
        # Idem : `eligible_for == STATE_OBSERVED` et `eligible_for in (TELEGRAM,
        # AUTO_EXEC)` ci-dessous sont tous deux naturellement faux quand
        # eligible_for == STATE_INDETERMINATE — aucune transition n'est prise
        # sur un échantillon insuffisamment réel, sans code de garde dédié.
        if score["eligible_for"] == STATE_OBSERVED and score["sample"] >= PROMOTE_MIN_SAMPLE:
            set_state(pair, STATE_OBSERVED, f"auto-demote: {score['reason']}", direction=direction, score_snapshot=score)
            return {"action": "transition", "from_state": current, "to_state": STATE_OBSERVED, "score": score, "reason": score["reason"]}
        # Palier loss-averse asymétrique : promote TELEGRAM → AUTO_EXEC après
        # PAC_TELEGRAM_TO_AUTOEXEC_DAYS stables (default 7j) sans demote.
        # Évite les promotes auto trop rapides vers l'argent réel (cas XAU buy
        # 2026-06-08 cool-off → AUTO_EXEC → -125% PnL en 24h).
        from datetime import timedelta
        try:
            from config.settings import PAC_TELEGRAM_TO_AUTOEXEC_DAYS as _tg_days
        except ImportError:
            _tg_days = 7
        full = get_full_state(pair, direction)
        try:
            since = datetime.fromisoformat(full["state_since"].replace("Z", "+00:00"))
            elapsed = datetime.now(timezone.utc) - since
        except (ValueError, AttributeError, TypeError):
            elapsed = timedelta(days=0)
        # ⚠️ Second étage de la porte à sens unique (2026-08-06).
        #
        # Exiger `eligible_for in (TELEGRAM, AUTO_EXEC)` bloquait aussi ce
        # passage, pour la même raison : `TELEGRAM` n'exécute pas, donc la
        # paire n'accumule aucun trade réel et reste `INDETERMINATE` à vie.
        # Corriger le seul premier étage aurait déplacé l'impasse d'un cran.
        #
        # ⚠️ Et la preuve attendue ne peut PAS arriver : la promotion par paire
        # est statistiquement indécidable à cette échelle (~1500 trades requis
        # par paire, 1561 existent au TOTAL — cf.
        # `project_promotion_indecidable_2026_08_05`). Attendre une certitude
        # impossible n'est pas de la prudence, c'est de la paralysie.
        #
        # On distingue donc « on ne sait pas » de « on sait que c'est mauvais » :
        #   INDETERMINATE (inconnu, faute de trades réels)  → passe
        #   OBSERVED      (jugé insuffisant SUR du réel)    → bloque
        #
        # Le risque du premier passage à l'argent réel n'est pas porté par ce
        # test mais par les contenants en aval, tous vérifiés le 2026-08-06 :
        # palier temporel (`PAC_TELEGRAM_TO_AUTOEXEC_DAYS`), plafonds de lot par
        # classe, ajustement à la marge disponible, porte de coût, et
        # rétrogradation sur drawdown mesuré.
        _indetermine_ok = _promotion_indetermine_autorisee()
        _juge_negatif = score["eligible_for"] == STATE_OBSERVED
        _eligible_ok = (
            score["eligible_for"] in (STATE_TELEGRAM, STATE_AUTO_EXEC)
            or (_indetermine_ok and not _juge_negatif)
        )
        # Débit maximal vers l'argent réel — cf. `_budget_promotions_hebdo`.
        # Placé en DERNIER des conditions pour que le message de refus
        # distingue « pas encore mûr » de « mûr mais en file d'attente ».
        _budget = _budget_promotions_hebdo()
        _deja = _promotions_recentes_vers_auto_exec()
        _pret = (
            elapsed >= timedelta(days=_tg_days)
            and score["sample"] >= PROMOTE_MIN_SAMPLE
            and _eligible_ok
        )
        if _pret and _deja >= _budget:
            return {
                "action": "keep", "from_state": current, "score": score,
                "reason": (
                    f"éligible mais en file d'attente : {_deja} promotion(s) "
                    f"automatique(s) vers AUTO_EXEC sur les 7 derniers jours, "
                    f"budget = {_budget}"
                ),
            }
        if _pret:
            set_state(
                pair, STATE_AUTO_EXEC,
                f"auto-promote TELEGRAM stable {elapsed.days}j ≥ {_tg_days}j",
                direction=direction, score_snapshot=score,
            )
            return {"action": "transition", "from_state": current, "to_state": STATE_AUTO_EXEC, "score": score, "reason": "stable in TELEGRAM"}
        days_left = max(0, _tg_days - elapsed.days)
        return {"action": "keep", "from_state": current, "score": score, "reason": f"telegram stable {elapsed.days}j (encore {days_left}j avant AUTO_EXEC)"}

    elif current == STATE_AUTO_EXEC:
        # Garde-fou échantillon réel : `sample`/`pnl_pct` peuvent être calculés
        # sur un échantillon complété par des signaux simulés (cf.
        # `compute_promotion_score`). Une rétrogradation retire l'accès à de
        # l'argent réel — elle ne doit jamais se décider sur cette contamination.
        # C'est le chemin exact de l'incident du 2026-08-04 (jusqu'à -251 %
        # de capital sur une fenêtre de 30, entièrement due à un artefact de
        # déduplication côté données simulées).
        if score["eligible_for"] == STATE_INDETERMINATE:
            return {"action": "keep", "from_state": current, "score": score, "reason": score["reason"]}
        if score["sample"] >= PROMOTE_MIN_SAMPLE and score["pnl_pct"] < -3.0:
            set_state(pair, STATE_PAUSED, f"auto-pause: pnl_pct {score['pnl_pct']}% < -3%", direction=direction, score_snapshot=score)
            return {"action": "transition", "from_state": current, "to_state": STATE_PAUSED, "score": score, "reason": "saignement détecté"}
        return {"action": "keep", "from_state": current, "score": score, "reason": "auto_exec healthy"}

    elif current == STATE_PAUSED:
        from datetime import timedelta
        full = get_full_state(pair, direction)
        try:
            since = datetime.fromisoformat(full["state_since"].replace("Z", "+00:00"))
            elapsed = datetime.now(timezone.utc) - since
        except (ValueError, AttributeError, TypeError):
            elapsed = timedelta(days=0)
        cooloff_days = _pause_cooloff_days()
        if elapsed >= timedelta(days=cooloff_days):
            recent_pauses = _count_recent_pauses(pair, days=60)
            if recent_pauses >= DEMOTE_MAX_RE_PAUSES_60D:
                # Circuit breaker anti-cascade : PRIME sur tout, y compris un
                # contrôle par comparaison inter-paires favorable (cf.
                # 2026-06-07/08 — 17 demotions en 48h). Une pair qui re-pause
                # à répétition n'a pas besoin d'un contrôle statistique pour être jugée
                # instable — évalué EN PREMIER, avant même de lancer le
                # bootstrap (inutile de payer son coût sur une pair qui de
                # toute façon ne reviendra pas en AUTO_EXEC ce cycle-ci).
                if is_demotion_blocked():
                    n_recent = _count_recent_auto_demotions(_breaker_window())
                    logger.warning(
                        f"pac_circuit_breaker: blocking DEMOTED for {pair}/{direction} "
                        f"({n_recent} auto-demotes / {_breaker_window()}d)"
                    )
                    _notify_circuit_breaker_block(pair, direction, n_recent)
                    return {
                        "action": "keep",
                        "from_state": current,
                        "score": score,
                        "reason": f"DEMOTE bloquée par circuit breaker ({n_recent} demotes/{_breaker_window()}d)",
                    }
                set_state(pair, STATE_DEMOTED, f"auto-demote: {recent_pauses} pauses on 60d (max {DEMOTE_MAX_RE_PAUSES_60D})", direction=direction, score_snapshot=score)
                return {"action": "transition", "from_state": current, "to_state": STATE_DEMOTED, "score": score, "reason": "trop instable"}

            # ── Le délai seul ne suffit plus (cf. section « Retour de pause »
            # ci-dessus) : le retour à l'argent réel exige que le contrôle par
            # comparaison inter-paires établisse que les signaux de la pair
            # font mieux que la moyenne des autres pairs de la même classe
            # d'actif, sur shadow_setups récent. `score` (compute_promotion_score,
            # basé sur real trades + backtest.db) n'est PAS la condition ici —
            # une pair PAUSED ne trade plus, donc n'accumule jamais de trades
            # réels ; l'exiger verrouillerait le retour pour toujours (c'est
            # exactement ce que le garde-fou PAC_MIN_REAL_TRADES ferait s'il
            # s'appliquait ici — il ne s'applique QUE dans les branches
            # OBSERVED/TELEGRAM/AUTO_EXEC ci-dessus, jamais à ce retour).
            #
            # ⚠️ CONDITION NÉCESSAIRE, JAMAIS SUFFISANTE : un résultat
            # favorable dit seulement « cette pair n'est pas pire que ses
            # semblables de la même classe d'actif ». Il ne dit RIEN sur la
            # question de savoir si les patterns battent une entrée réellement
            # aléatoire — question systémique, mesurable seulement hors ligne
            # par backtest, et déjà répondue négativement pour au moins un
            # système testé (cf. section dédiée en tête de fichier).
            if direction is None:
                return {
                    "action": "keep",
                    "from_state": current,
                    "score": score,
                    "reason": (
                        f"cool-off {cooloff_days}j expiré mais direction non spécifiée — la "
                        "comparaison inter-paires exige un sens explicite (buy/sell), "
                        "reste en pause"
                    ),
                }
            control = peer_control_for_pair_cached(pair, direction)
            if _beats_peer_control(control):
                from dataclasses import asdict as _asdict
                snapshot = {**score, "peer_control": _asdict(control)}
                set_state(
                    pair, STATE_AUTO_EXEC,
                    f"cool-off {cooloff_days}j expiré + signaux au-dessus de la moyenne "
                    f"des pairs comparables ({_peer_control_summary(control)})",
                    direction=direction, score_snapshot=snapshot,
                )
                return {"action": "transition", "from_state": current, "to_state": STATE_AUTO_EXEC, "score": score, "reason": "bat la moyenne des pairs comparables"}
            return {
                "action": "keep",
                "from_state": current,
                "score": score,
                "reason": f"cool-off {cooloff_days}j expiré, {_peer_control_keep_reason(control)}",
            }
        return {"action": "keep", "from_state": current, "score": score, "reason": f"cool-off encore {(timedelta(days=cooloff_days) - elapsed).days}j"}

    elif current == STATE_DEMOTED:
        return {"action": "keep", "from_state": current, "score": score, "reason": "DEMOTED requires manual admin transition"}

    return {"action": "keep", "from_state": current, "score": score, "reason": "unknown state"}


def check_and_regulate() -> dict[str, Any]:
    """Job scheduler : évalue tous les (pair × direction) de l'univers."""
    from config.settings import WATCHED_PAIRS
    universe = set(WATCHED_PAIRS)
    for s in list_all_states():
        universe.add(s["pair"])

    decisions = []
    for pair in sorted(universe):
        for direction in ("buy", "sell"):
            try:
                d = evaluate_pair(pair, direction=direction)
                d["pair"] = pair
                d["direction"] = direction
                decisions.append(d)
            except Exception:
                logger.exception(f"pair_admission: evaluate {pair}/{direction} failed")

    transitions = sum(1 for d in decisions if d["action"] == "transition")
    logger.info(f"pair_admission: check n_buckets={len(decisions)} transitions={transitions}")
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "n_buckets": len(decisions),
        "n_pairs": len({d["pair"] for d in decisions}),
        "n_transitions": transitions,
        "decisions": decisions,
    }


def backfill_initial_states() -> dict[str, Any]:
    """Au premier deploy, donne un état initial à chaque pair de WATCHED_PAIRS.

    Évolution 2026-05-13 : backfill (pair × direction) au lieu de pair-level
    seul. Matérialise explicitement le filtre `*:buy` historique en posant
    (pair, 'buy') = OBSERVED pour toutes les pairs, et (pair, 'sell') hérite
    du comportement legacy pair-level (AUTO_EXEC pour les stars sauf XAG
    SELL paused, OBSERVED pour les autres).

    Stratégie :
    - Phase 1 (rétrocompat) : si pair n'a AUCUNE row, applique la logique
      pair-level legacy (= comportement v1 contrôleur).
    - Phase 2 (direction granularité) : pour chaque (pair, direction) qui
      n'a pas de row direction-specific, déclare l'état initial selon les
      règles ci-dessus.

    Idempotent : ré-appel = 0 changement si état déjà posé.
    """
    from config.settings import WATCHED_PAIRS
    from backend.services.shadow_v2_core_long import SHADOW_PAIRS as _STAR_PAIRS
    from backend.services import pair_pnl_regulator

    _ensure_schema()

    star_set = frozenset(_STAR_PAIRS)
    transitions: list[dict[str, Any]] = []
    universe = set(WATCHED_PAIRS) | star_set

    for pair in sorted(universe):
        # Phase 1 : Backfill pair-level legacy si jamais aucune row
        with sqlite3.connect(_db_path()) as c:
            has_any = c.execute(
                "SELECT 1 FROM pair_admission_state WHERE pair = ? LIMIT 1", (pair,)
            ).fetchone()
            has_pair_level = c.execute(
                "SELECT 1 FROM pair_admission_state WHERE pair = ? AND direction IS NULL LIMIT 1", (pair,)
            ).fetchone()

        if not has_any:
            if pair in star_set:
                if pair_pnl_regulator.is_paused(pair):
                    pair_level_target = STATE_PAUSED
                    pair_level_reason = "backfill: pair was in _STAR_PAIRS_SET and paused by pair_pnl_regulator"
                else:
                    pair_level_target = STATE_AUTO_EXEC
                    pair_level_reason = "backfill: pair was in _STAR_PAIRS_SET (legacy star) and active"
            else:
                pair_level_target = STATE_OBSERVED
                pair_level_reason = "backfill: pair not in legacy _STAR_PAIRS, default OBSERVED"

            inserted = set_state(pair, pair_level_target, pair_level_reason, transitioned_by="auto:backfill")
            if inserted and inserted > 0:
                transitions.append({"pair": pair, "direction": None, "to_state": pair_level_target, "reason": pair_level_reason})

        # Phase 2 : Backfill direction-specific (buy / sell)
        # Récupère le state pair-level effectif (post phase 1)
        pair_level_state = get_current_state(pair)  # direction=None → pair-level lookup

        for direction in ("buy", "sell"):
            # Skip si déjà une row direction-specific pour ce sens
            with sqlite3.connect(_db_path()) as c:
                has_dir = c.execute(
                    "SELECT 1 FROM pair_admission_state WHERE pair = ? AND direction = ? LIMIT 1",
                    (pair, direction),
                ).fetchone()
            if has_dir:
                continue

            if direction == "buy":
                # Reproduit le filtre *:buy historique : tout buy = OBSERVED
                # (= pas d'auto-exec). Sera promu manuellement ou par
                # check_and_regulate quand un edge buy émerge (V2 long).
                dir_target = STATE_OBSERVED
                dir_reason = "backfill: direction=buy default OBSERVED (= remplace filtre statique *:buy)"
            else:  # sell
                # Hérite du comportement pair-level : si pair était AUTO_EXEC,
                # le SELL hérite (= seul sens autorisé sous *:buy historique).
                # Si pair était PAUSED, on propage à SELL (= la direction qui
                # saignait, cas XAG).
                dir_target = pair_level_state
                dir_reason = f"backfill: direction=sell inherits pair-level state ({pair_level_state})"

            inserted = set_state(pair, dir_target, dir_reason, direction=direction, transitioned_by="auto:backfill")
            if inserted and inserted > 0:
                transitions.append({"pair": pair, "direction": direction, "to_state": dir_target, "reason": dir_reason})

    logger.info(
        f"pair_admission: backfill_initial_states applied {len(transitions)} transitions"
    )
    return {"applied": len(transitions), "transitions": transitions}


def get_recent_transitions(pair: str, limit: int = 10) -> list[dict[str, Any]]:
    """Historique des N dernières transitions d'un pair (pour audit/dashboard)."""
    _ensure_schema()
    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            """
            SELECT * FROM pair_admission_state
             WHERE pair = ? ORDER BY state_since DESC LIMIT ?
            """,
            (pair, limit),
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if d.get("score_snapshot"):
            try:
                d["score_snapshot"] = json.loads(d["score_snapshot"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result
