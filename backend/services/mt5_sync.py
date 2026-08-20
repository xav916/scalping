"""Synchronisation bridge MT5 → table personal_trades.

Pull périodique depuis le bridge (/audit?since_id=...) pour :
- Détecter les ordres LIVE fills → INSERT dans personal_trades (status=OPEN)
- Détecter les fermetures (status='closed' dans le bridge) → UPDATE du
  personal_trade correspondant (exit_price, pnl, closed_at, status=CLOSED)

Conséquence : tout ordre auto placé par le bridge apparaît dans les sections
Mes trades / Risque / Equity / Détecteur d'erreurs du dashboard — même si
l'utilisateur n'a jamais cliqué sur "J'ai pris ce signal".

Schéma de dédup : `mt5_ticket` dans personal_trades est unique par trade.
Si la sync rejoue (crash, re-pull), les INSERT sont UPSERT (pas de doublons).
"""

import asyncio
import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from backend.services import macro_context_service

from config.settings import (
    AUTH_USERS,
    AUTO_TRADE_USER,
    MT5_BRIDGE_API_KEY,
    MT5_BRIDGE_URL,
    MT5_SYNC_ENABLED,
)

logger = logging.getLogger(__name__)

# Persisté sur disque pour survivre au restart du backend
_STATE_PATH = Path("/app/data/mt5_sync_state.json") if Path("/app").exists() else Path("mt5_sync_state.json")
_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load_last_synced_id() -> int:
    """Compat legacy : retourne last_id du bridge admin_legacy uniquement."""
    return _load_state().get("bridges", {}).get("legacy", 0)


def _save_last_synced_id(last_id: int) -> None:
    """Compat legacy : écrit last_id pour admin_legacy uniquement."""
    state = _load_state()
    state.setdefault("bridges", {})["legacy"] = int(last_id)
    _save_state(state)


def _load_state() -> dict:
    """Charge l'état multi-bridge {bridges: {<name>: last_id}}.

    Migre transparent l'ancien format {'last_id': N} → {'bridges': {'legacy': N}}.
    """
    try:
        if _STATE_PATH.exists():
            data = json.loads(_STATE_PATH.read_text())
            if isinstance(data, dict):
                if "bridges" not in data and "last_id" in data:
                    return {"bridges": {"legacy": int(data["last_id"])}}
                return data
    except Exception:
        pass
    return {"bridges": {}}


def _save_state(state: dict) -> None:
    try:
        _STATE_PATH.write_text(json.dumps(state))
    except Exception as e:
        logger.warning(f"mt5_sync: write state failed: {e}")


def _resolve_auto_user() -> str:
    """Retourne l'user auquel attribuer les trades auto.

    - AUTO_TRADE_USER si défini
    - sinon le 1er user de AUTH_USERS
    - sinon 'anonymous' (auth désactivée)
    """
    if AUTO_TRADE_USER:
        return AUTO_TRADE_USER
    if AUTH_USERS:
        return next(iter(AUTH_USERS.keys()))
    return "anonymous"


def _db_path():
    from backend.services.trade_log_service import _DB_PATH
    return _DB_PATH


def _pip_size(pair: str) -> float:
    """Approx cohérente avec le reste du code (XAU/XAG = 0.01, JPY = 0.01,
    forex standard = 0.0001). Utilisé uniquement pour afficher le slippage."""
    base = pair.split("/")[0].upper() if "/" in pair else pair.upper()
    quote = pair.split("/")[1].upper() if "/" in pair else ""
    if base in {"XAU", "XAG", "XPT", "XPD"}:
        return 0.01
    if quote == "JPY":
        return 0.01
    return 0.0001


def _upsert_open_trade(row: dict[str, Any], user: str,
                       destination_id: str | None = None) -> None:
    """INSERT un ordre auto comme personal_trade. Silencieusement ignoré si
    le mt5_ticket existe déjà (dedup rejouable)."""
    ticket = row.get("ticket")
    if not ticket:
        return

    ctx_json = None
    snap = macro_context_service.get_macro_snapshot()
    if snap is not None and macro_context_service.is_fresh(snap.fetched_at):
        ctx_json = json.dumps({
            "dxy": snap.dxy_direction.value,
            "spx": snap.spx_direction.value,
            "vix_level": snap.vix_level.value if snap.vix_level is not None else None,
            "vix_value": snap.vix_value,
            "risk_regime": snap.risk_regime.value,
            "fetched_at": snap.fetched_at.isoformat(),
        })

    # Prix planifié (entry) vs prix réellement exécuté (fill). Le bridge
    # peut remonter plusieurs conventions selon sa version — on regarde
    # les noms habituels.
    pair = row.get("pair") or row.get("symbol") or "?"
    direction = (row.get("direction") or "").lower()
    entry_price = row.get("entry") or 0
    fill_price = (
        row.get("fill_price")
        or row.get("price_open")
        or row.get("open_price")
    )

    # Référence du glissement : le prix DEMANDÉ, jamais `entry`.
    #
    # ⚠️ Le bridge écrit le prix OBTENU dans sa colonne `entry` (le planifié y
    # était écrasé). Comparer `entry` au fill revient donc à comparer le fill à
    # lui-même — c'est ce qui laissait `slippage_pips` vide sur 1581/1581
    # trades avant le 2026-08-06. `entry_requested` porte le prix demandé.
    planned_price = row.get("entry_requested")

    # `requested` = le bridge n'a pas pu observer le fill et s'est replié sur
    # le prix demandé. Le glissement vaudrait alors zéro PAR CONSTRUCTION.
    # Mieux vaut ne rien mesurer que d'injecter de faux zéros qui tireraient la
    # moyenne vers l'absence de coût. Absent (ancien bridge) ⇒ pas de
    # `entry_requested` non plus, donc pas de calcul : rétrocompatible.
    fill_source = row.get("fill_source")

    slippage_pips = None
    if fill_price and planned_price and fill_source != "requested":
        pip = _pip_size(pair)
        # Slippage signé : positif = en faveur du trade, négatif = défavorable.
        if direction == "buy":
            raw = planned_price - fill_price  # acheté plus bas = favorable
        else:
            raw = fill_price - planned_price  # vendu plus haut = favorable
        if pip:
            slippage_pips = round(raw / pip, 1)

    # Matching signal_id : on cherche un signal recent qui correspond a ce
    # fill (pair + direction + entry a +/-0.1% pres, dans les 30 dernieres
    # minutes). Best-effort : si aucun match, reste NULL.
    signal_id = None
    signal_pattern = None
    try:
        from backend.services.backtest_service import find_signal_for_order, _DB_PATH as _SIGNALS_DB
        signal_id = find_signal_for_order(pair, direction, float(entry_price or 0))
        # Récupère le pattern du signal matché pour le persister sur le trade.
        # Permet au diagnostic de ventiler les trades par pattern gagnant/perdant
        # (avant ce fix, signal_pattern était hardcodé NULL → diag aveugle).
        if signal_id:
            try:
                with sqlite3.connect(str(_SIGNALS_DB)) as sc:
                    r = sc.execute(
                        "SELECT pattern FROM signals WHERE id = ?", (signal_id,)
                    ).fetchone()
                    if r and r[0]:
                        signal_pattern = r[0]
            except Exception as e:
                logger.debug(f"mt5_sync: lookup pattern for signal_id={signal_id} failed: {e}")
    except Exception as e:
        logger.debug(f"mt5_sync: find_signal_for_order failed: {e}")

    with sqlite3.connect(_db_path()) as c:
        from backend.services.trade_log_service import assurer_colonne_destination
        assurer_colonne_destination(c)
        c.execute("""
            INSERT OR IGNORE INTO personal_trades (
                user, pair, direction, entry_price, stop_loss, take_profit,
                size_lot, signal_pattern, signal_confidence, checklist_passed,
                notes, status, created_at, mt5_ticket, is_auto,
                post_entry_sl, post_entry_tp, post_entry_size, context_macro,
                signal_id, fill_price, slippage_pips, destination_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 'OPEN', ?, ?, 1, 1, 1, 1, ?, ?, ?, ?, ?)
        """, (
            user,
            pair,
            direction,
            entry_price,
            row.get("sl") or 0,
            row.get("tp") or 0,
            row.get("lots") or 0.01,
            # signal_pattern = récupéré depuis signals via signal_id matché
            # (NULL si aucun match, ex: trade manuel ou signal_id introuvable).
            signal_pattern,
            # signal_confidence = score de confidence envoyé par le radar au moment du /order
            # (bridge a une colonne audit dédiée depuis 2026-04-21 pour capturer la valeur).
            # Les anciens trades auto ont NULL ici car bridge ne la persistait pas.
            row.get("confidence"),
            f"Auto-exec via bridge MT5 (ticket #{ticket}, risk_money={row.get('risk_money')}, comment: {row.get('client_comment', '')})",
            row.get("created_at") or datetime.now(timezone.utc).isoformat(),
            ticket,
            ctx_json,
            signal_id,
            fill_price,
            slippage_pips,
            # Destination (2026-08-20) : sans elle, demo et reel se
            # confondaient dans le plafond journalier.
            destination_id,
        ))


def _derive_close_reason_from_exit(
    ticket: int, exit_price: float | None
) -> str | None:
    """Heuristique de DERNIER RECOURS : quand aucune cause ne vient du
    courtier, on situe `exit_price` par rapport à l'entrée, au SL et au TP
    stockés en DB.

    ⚠️ Depuis le 2026-08-10 le bridge REMONTE `reason` dans /deals (lu de
    `DEAL_REASON_*`), et `_reconcile_open_trades` le transmet. Cette fonction
    ne doit donc plus servir que pour les fermetures sans cause connue —
    principalement l'historique déjà en base. Ne pas rétablir un appel
    inconditionnel : il ferait perdre une mesure au profit d'une déduction.

    ⚠️ Chaque branche est une DÉTERMINATION POSITIVE. La branche par défaut
    renvoie "INDETERMINE", jamais "MANUAL" : affirmer « fermé à la main » parce
    qu'on n'a pas su conclure, c'est inventer une mesure.

    Mesuré le 2026-08-10 : 215 trades portaient "MANUAL", dont 215 (100 %) avec
    `post_entry_sl=1` — aucun n'avait été fermé à la main. C'étaient les sorties
    du stop suiveur (TRAIL_DISTANCE_POINTS=150) et de la mise à zéro du risque
    (BREAKEVEN_TRIGGER_PCT=50), que la comparaison au SL *d'origine* ne pouvait
    pas reconnaître puisque le stop avait bougé.

    - exit ≈ SL d'origine            → SL
    - exit atteint ou dépasse le TP  → TP1   (le prix l'a traversé)
    - exit ≈ prix d'entrée           → BREAKEVEN
    - gain < TP, et le SL a bougé    → TRAILING_SL
    - tout le reste                  → INDETERMINE

    "MANUAL" ne peut venir que du courtier, via `_normalize_close_reason`
    (DEAL_REASON_CLIENT). Cf. [[project_cloture_externe_pnl_inconnu_2026_08_09]]
    pour la même maladie sur `pnl`.

    Tolérance par classe d'actif pour absorber le glissement (~2 pips forex,
    0,30 $ sur XAU, etc.).
    """
    if exit_price is None:
        return None
    with sqlite3.connect(_db_path()) as c:
        row = c.execute(
            """
            SELECT stop_loss, take_profit, pair, direction, entry_price,
                   COALESCE(post_entry_sl, 0)
              FROM personal_trades
             WHERE mt5_ticket = ?
            """,
            (ticket,),
        ).fetchone()
    if not row:
        return None
    sl, tp, pair, direction, entry, post_entry_sl = row
    if sl is None and tp is None:
        return None

    base = pair.split("/")[0].upper() if pair and "/" in pair else (pair or "").upper()
    # Tolérances de fermeture (en unités de prix) — couvrent le slippage
    # broker et les approximations de rounding côté MT5.
    if base == "XAU":
        tol = 0.3   # ~3 pips or
    elif base == "XAG":
        tol = 0.02
    elif base in {"BTC", "ETH"}:
        tol = 15.0
    elif base in {"BCH", "LTC"}:
        # 2026-06-29 — fix observabilite altcoins range 100-500 USD.
        # Sans cette branche, fallback tol=0.0002 (forex) -> 100% MANUAL
        # sur l'analyse historique. Cf. audit BCH 209/217 = MANUAL alors
        # qu'il s'agissait majoritairement de SL touches au sizing minimum.
        tol = 5.0
    elif base in {"DOT", "ADA", "XRP", "SOL"}:
        # Idem pour altcoins petite cap (range 0.5-5 USD).
        tol = 0.05
    elif base in {"SPX", "NDX"}:
        tol = 2.0
    elif base == "WTI":
        tol = 0.05
    else:
        tol = 0.0002  # 2 pips sur 5-dp forex

    # 1. Le stop d'origine a été touché.
    #    ⚠️ Garde : si le stop est plus proche de l'entrée que la tolérance,
    #    ce test déclarerait « stop touché » y compris pour une sortie AU PRIX
    #    D'ENTRÉE. Il ne discrimine plus rien — il doit se taire.
    if sl is not None and abs(exit_price - sl) <= tol:
        if entry and abs(entry - sl) <= tol:
            # Stop indiscernable du prix d'entrée à la tolérance près : ce test
            # dirait « stop touché » y compris pour une sortie au prix d'entrée.
            # ⛔ Ne PAS laisser glisser vers BREAKEVEN — ce serait remplacer une
            # affirmation douteuse par une autre. On nomme l'ambiguïté.
            return "INDETERMINE"
        return "SL"

    # Sens du trade : +1 à l'achat, -1 à la vente. Sans lui on ne peut pas
    # distinguer un gain d'une perte, donc on ne conclut rien de plus.
    sens = None
    if direction:
        sens = 1 if str(direction).strip().lower().startswith("b") else -1

    # ⚠️ `entry` peut valoir 0.0 : les anciens fills du bridge écrivaient un
    # zéro faute de mieux. Tester `is None` laisserait passer ce zéro, et le
    # gain calculé vaudrait alors le prix de sortie tout entier (−1790 sur un
    # ETH à 1790) — un nombre qui ne veut rien dire, sur lequel les branches
    # suivantes trancheraient quand même. Encore un zéro qui se fait passer
    # pour une mesure, cf. `pnl=0.0` des clôtures Kraken (08-09).
    if sens is None or not entry:
        if tp is not None and abs(exit_price - tp) <= tol:
            return "TP1"
        return "INDETERMINE"

    gain = (exit_price - entry) * sens

    # ⚠️ Objectif du mauvais côté de l'entrée (TP au-dessus sur une vente) :
    # la ligne est incohérente. Ni le gain visé ni la mise à zéro du risque ne
    # s'y calculent honnêtement — on ne conclut rien plutôt que de conclure
    # depuis des nombres qui se contredisent.
    if tp is not None and (tp - entry) * sens <= 0:
        return "INDETERMINE"

    # 2. Le stop a été traversé (gap). Symétrique du TP ci-dessous : sortir
    #    AU-DELÀ du stop implique que le prix est passé par lui. L'étiqueter
    #    "indéterminé" masquerait précisément les gaps, qu'on veut voir.
    if sl is not None:
        perte_stop = (entry - sl) * sens
        # ⚠️ `perte_stop > tol` et non `> 0` : si la distance au stop est plus
        # petite que la tolérance, le seuil `perte_stop - tol` devient négatif
        # et N'IMPORTE QUELLE perte serait déclarée « stop touché ». Le test
        # doit se taire quand il ne discrimine plus rien.
        if perte_stop > tol and -gain >= perte_stop - tol:
            return "SL"

    # 3. Le TP a été atteint — ou traversé. Sortir au-delà du TP implique que
    #    le prix est passé par lui : l'ordre a bien été touché, avec un
    #    glissement favorable. C'est une conséquence de l'ordre des prix, pas
    #    une conjecture.
    if tp is not None:
        gain_vise = (tp - entry) * sens
        # Même garde que pour le stop : une cible plus proche que la tolérance
        # ne discrimine rien.
        if gain_vise > tol and gain >= gain_vise - tol:
            return "TP1"

    # 4. Sortie au prix d'entrée : mise à zéro du risque.
    if abs(gain) <= tol:
        return "BREAKEVEN"

    # 5. Gain positif mais sous la cible, ET le stop a bougé après l'entrée :
    #    c'est le stop suiveur qui a fermé.
    if gain > tol and post_entry_sl:
        return "TRAILING_SL"

    # 6. Sortie défavorable sans avoir touché le stop d'origine : /kill,
    #    fermeture partielle, stop-out courtier ou vraie main humaine. On ne
    #    peut pas trancher — on le dit.
    return "INDETERMINE"


def _affiner_cause_du_courtier(
    ticket: int, cause: str | None, pnl: float | None
) -> str | None:
    """Distingue le stop SUIVEUR du stop de sécurité.

    Le suiveur ferme en DÉPLAÇANT le stop : MT5 rapporte donc `DEAL_REASON_SL`,
    exactement comme une perte sur stop initial. Sans cet affinage, les 104
    sorties du suiveur mesurées le 2026-08-10 (+15,90 € en moyenne) seraient
    rangées parmi les stops touchés, donc parmi les pertes.

    Deux conditions, toutes deux nécessaires : le stop a bougé après l'entrée,
    et le trade sort en gain. Un stop non déplacé ne peut pas avoir suivi.

    ⛔ Ne touche QUE la cause "SL". Une liquidation courtier (STOP_OUT) reste
    une sortie subie même si elle sort en gain.
    """
    if cause != "SL" or pnl is None or pnl <= 0:
        return cause
    try:
        with sqlite3.connect(_db_path()) as c:
            row = c.execute(
                "SELECT COALESCE(post_entry_sl, 0) FROM personal_trades "
                " WHERE mt5_ticket = ?",
                (ticket,),
            ).fetchone()
    except Exception as e:
        logger.debug(f"mt5_sync: affinage cause ticket={ticket} impossible: {e}")
        return cause
    if row and row[0]:
        return "TRAILING_SL"
    return cause


def _normalize_close_reason(raw: str | None) -> str | None:
    """Le bridge peut remonter des libelles variables selon la version MT5
    (deal.reason, position.close_reason, etc.). On normalise en un set
    reduit et stable pour l'analyse ML downstream."""
    if not raw:
        return None
    r = str(raw).strip().lower()
    # ⚠️ AVANT la règle "stop" : DEAL_REASON_SO est la LIQUIDATION par le
    # courtier (stop out), pas un stop-loss. Les confondre effacerait la
    # distinction entre une sortie choisie et une sortie subie — exactement ce
    # qui menace la position or ouverte.
    if r.endswith("_so") or r == "so" or "stop_out" in r or "stopout" in r:
        return "STOP_OUT"
    if "tp2" in r or "take_profit_2" in r:
        return "TP2"
    if "tp" in r or "take_profit" in r:
        return "TP1"
    if "sl" in r or "stop" in r:
        return "SL"
    if "manual" in r or "client" in r:
        return "MANUAL"
    if "timeout" in r or "expiry" in r:
        return "TIMEOUT"
    return raw.upper()[:16]


def _decalage_courtier_h() -> float:
    """Écart entre l'horloge du serveur du courtier et l'UTC réel, en heures.

    IC Markets tourne à UTC+3 (établi le 2026-08-13 par trois voies
    indépendantes). ⚠️ Ce n'est PAS une constante : les serveurs MT5 suivent
    l'heure d'été américaine et repassent à UTC+2 vers fin octobre. D'où la
    variable d'environnement, à ajuster au changement d'heure.
    """
    try:
        return float(os.getenv("MT5_BROKER_UTC_OFFSET_HOURS", "3"))
    except ValueError:
        return 3.0


def _heure_reelle_de_cloture(iso: str | None) -> str | None:
    """Ramène en UTC réel une date que le bridge a étiquetée `+00:00` alors
    qu'il l'a lue sur l'horloge du COURTIER.

    Le bridge construit `closed_at` avec
    `datetime.fromtimestamp(deal.time, tz=timezone.utc)` : `deal.time` est
    exprimé en heure serveur, pas en epoch. Le décalage passe donc entier dans
    la date, qui atterrit 3 h dans le futur.

    ⚠️ Une valeur illisible est rendue **telle quelle**, jamais décalée :
    corriger ce qu'on n'a pas su lire inventerait une précision qu'on n'a pas.
    Cf. [[feedback_detection_par_absence]].
    """
    if not iso:
        return iso
    try:
        dt = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return iso
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt - timedelta(hours=_decalage_courtier_h())).isoformat()


def _update_closed_trade(row: dict[str, Any]) -> None:
    """Quand le bridge log une fermeture (status='closed'), met à jour la
    ligne personal_trades correspondante (par mt5_ticket).

    Idempotent : on accepte aussi d'enrichir une ligne déjà CLOSED tant que
    les nouvelles colonnes (exit_price, pnl) sont non-null. Utile quand le
    status a été forcé manuellement avant que le sync ait remonté les valeurs
    finales du broker. closed_at est protégé par COALESCE pour ne pas écraser
    une date de fermeture déjà enregistrée."""
    ticket = row.get("ticket")
    if not ticket:
        return
    close_reason = _normalize_close_reason(
        row.get("close_reason") or row.get("reason") or row.get("deal_reason")
    )
    # Fallback : bridge `/deals` ne remonte pas le reason → heuristique
    # par proximité de l'exit price aux SL/TP stockés en DB.
    if close_reason:
        # La cause vient du courtier : elle fait autorité, mais "SL" ne
        # distingue pas le stop de sécurité du stop suiveur (les deux ferment
        # sur un SL, l'un déplacé, l'autre non).
        close_reason = _affiner_cause_du_courtier(
            ticket, close_reason, row.get("pnl")
        )
    else:
        close_reason = _derive_close_reason_from_exit(ticket, row.get("exit_price"))
    with sqlite3.connect(_db_path()) as c:
        c.execute("""
            UPDATE personal_trades
               SET status       = 'CLOSED',
                   exit_price   = COALESCE(?, exit_price),
                   pnl          = COALESCE(?, pnl),
                   closed_at    = COALESCE(closed_at, ?),
                   close_reason = COALESCE(close_reason, ?)
             WHERE mt5_ticket = ?
        """, (
            row.get("exit_price"),
            row.get("pnl"),
            row.get("created_at") or datetime.now(timezone.utc).isoformat(),
            close_reason,
            ticket,
        ))


def _fetch_closed_trade_for_notify(ticket: int) -> dict[str, Any] | None:
    """Charge la ligne personal_trades complète pour préparer une notif
    Telegram de fermeture. Retourne None si introuvable."""
    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT pair, direction, entry_price, exit_price, pnl, "
            "close_reason, signal_pattern, signal_confidence, mt5_ticket, "
            "created_at, closed_at, size_lot FROM personal_trades WHERE mt5_ticket=?",
            (ticket,),
        ).fetchone()
    return dict(row) if row else None


async def _notify_close_telegram(ticket: int) -> None:
    """Envoie la notif Telegram pédagogique de fermeture pour ce ticket.

    Best-effort : tout échec est loggé, jamais propagé (ne doit pas
    casser la réconciliation).
    """
    try:
        trade = _fetch_closed_trade_for_notify(ticket)
        if not trade:
            return
        from backend.services.telegram_service import send_close
        await send_close(trade)
    except Exception as e:
        logger.warning(f"mt5_sync: notify_close_telegram ticket={ticket} failed: {e}")


def _select_open_auto_tickets() -> set[int]:
    """Tickets **MT5** des personal_trades auto encore OPEN.

    ⚠️ Les identifiants non MT5 sont ecartes, et ce n'est pas defensif : ces
    tickets servent a interroger le ``/positions`` du bridge **MT5**. Un ordre
    Kraken y est etranger — il a sa propre reconciliation, toutes les 2 min.

    Incident du 2026-08-09. Le premier trade de l'univers Kraken elargi
    (ETHFI, 08-08 a 23:58) a ete materialise dans ``personal_trades`` avec un
    UUID pour ``mt5_ticket``. Le ``int()`` qui suivait levait, et comme
    ``_reconcile_open_trades`` est le DERNIER appel de ``sync_from_bridge``,
    la reconciliation des cloturees naturelles MT5 est morte pendant dix
    heures : 59 echecs par heure, zero succes, avec une position or ouverte.

    ``mt5_ticket`` est declare ``INTEGER``, mais SQLite est type
    dynamiquement : la colonne a accepte le texte sans broncher. Le filtre
    porte donc sur la FORME de la valeur, pas sur son type de stockage — un
    ticket MT5 arrive parfois en TEXT et doit rester lu.
    """
    with sqlite3.connect(_db_path()) as c:
        rows = c.execute(
            "SELECT mt5_ticket FROM personal_trades "
            "WHERE status='OPEN' AND is_auto=1 AND mt5_ticket IS NOT NULL"
        ).fetchall()
    tickets: set[int] = set()
    ecartes = 0
    for (valeur,) in rows:
        try:
            tickets.add(int(valeur))
        except (TypeError, ValueError):
            ecartes += 1
    if ecartes:
        # Journalise : ecarter en silence rejouerait le defaut sous une autre
        # forme — on saurait que la reconciliation ne trouve rien, jamais
        # pourquoi.
        logger.debug(
            "mt5_sync: %d ticket(s) non MT5 ecarte(s) de la reconciliation "
            "(identifiants d'une autre destination), %d conserve(s)",
            ecartes, len(tickets),
        )
    return tickets


def _mark_ticket_closed_no_deal(ticket: int) -> None:
    """Fallback quand le deal MT5 est introuvable (history purgée) :
    status=CLOSED seul, sans exit_price ni pnl. closed_at est protégé
    par COALESCE pour préserver une date déjà enregistrée."""
    with sqlite3.connect(_db_path()) as c:
        c.execute(
            "UPDATE personal_trades "
            "SET status='CLOSED', closed_at=COALESCE(closed_at, ?) "
            "WHERE mt5_ticket=?",
            (datetime.now(timezone.utc).isoformat(), ticket),
        )


async def _reconcile_open_trades() -> None:
    """Compare les tickets DB OPEN vs /positions du bridge et réconcilie
    les fermetures naturelles (SL/TP touchés par le marché).

    Appelé à la fin de sync_from_bridge. No-op si bridge non configuré
    ou s'il n'y a aucun ticket OPEN en DB."""
    if not (MT5_SYNC_ENABLED and MT5_BRIDGE_URL and MT5_BRIDGE_API_KEY):
        return

    open_tickets = _select_open_auto_tickets()
    if not open_tickets:
        return

    # ⚠️ TOUS les bridges, pas seulement le démo. `personal_trades` ne porte
    # pas de colonne de destination : les tickets du compte réel y côtoient
    # ceux du démo. N'interroger que `MT5_BRIDGE_URL` faisait répondre
    # `closed=None` au démo sur un ticket qu'il n'a jamais vu — lu comme
    # « historique purgé », donc fermeture. Mesuré le 2026-08-13 : les 16
    # trades réels d'août portaient tous une durée d'exactement 1 minute.
    bridges = [(MT5_BRIDGE_URL.rstrip("/"), MT5_BRIDGE_API_KEY)]
    live_url = os.getenv("MT5_BRIDGE_LIVE_URL", "")
    live_key = os.getenv("MT5_BRIDGE_LIVE_API_KEY", "")
    if live_url and live_key:
        bridges.append((live_url.rstrip("/"), live_key))

    live_tickets: set[int] = set()
    for base, key in bridges:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(
                    f"{base}/positions", headers={"X-API-Key": key}
                )
                if r.status_code != 200:
                    logger.warning(f"mt5_sync: /positions {r.status_code} ({base})")
                    return
                positions = r.json().get("positions", []) or []
                live_tickets |= {
                    int(p["ticket"]) for p in positions if "ticket" in p
                }
        except Exception as e:
            # ⛔ Un bridge muet ne prouve RIEN. Poursuivre déclarerait fermés
            # tous les tickets qu'il est seul à porter. Cf.
            # [[feedback_detection_par_absence]].
            logger.debug(f"mt5_sync: /positions unreachable ({base}): {e}")
            return

    closed_tickets = open_tickets - live_tickets
    if not closed_tickets:
        return

    n_full = 0
    n_partial = 0
    for ticket in closed_tickets:
        # On demande à chaque bridge. Le premier qui CONNAÎT la clôture fait
        # foi ; les autres répondent `closed=None` parce que le ticket n'est
        # pas le leur, ce qui n'est pas une information sur sa fermeture.
        data = None
        for base, key in bridges:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    r = await client.get(
                        f"{base}/deals", headers={"X-API-Key": key},
                        params={"ticket": ticket},
                    )
                    if r.status_code != 200:
                        continue
                    reponse = r.json()
            except Exception as e:
                logger.debug(
                    f"mt5_sync: /deals ticket={ticket} failed ({base}): {e}"
                )
                continue
            if reponse.get("closed") is True:
                data = reponse
                break
            if data is None:
                data = reponse
        if data is None:
            continue

        if data.get("closed") is True:
            _update_closed_trade({
                "ticket": ticket,
                "exit_price": data.get("exit_price"),
                "pnl": data.get("pnl"),
                # ⚠️ `/deals` lit l'heure sur l'horloge du COURTIER (UTC+3) et
                # l'étiquette `+00:00`. Sans correction, la clôture est datée
                # 3 h dans le futur — et `closed_at` étant protégé par
                # COALESCE, la valeur fausse devient définitive.
                "created_at": _heure_reelle_de_cloture(data.get("closed_at")),
                # La cause vient de MT5 (`DEAL_REASON_*`), pas d'une comparaison
                # de prix. Sans elle, `_update_closed_trade` retombe sur
                # l'heuristique, qui ne peut structurellement jamais rendre
                # "MANUAL" — elle ne connaît que les SL/TP stockés.
                "reason": data.get("reason"),
            })
            n_full += 1
            await _notify_close_telegram(int(ticket))
        elif data.get("closed") is None:
            logger.warning(
                f"mt5_sync: ticket {ticket} history introuvable, status=CLOSED sans pnl"
            )
            _mark_ticket_closed_no_deal(ticket)
            n_partial += 1
            await _notify_close_telegram(int(ticket))

    if n_full or n_partial:
        logger.info(
            f"mt5_sync: {n_full} closures reconciled (full), {n_partial} partial"
        )


async def _cause_du_courtier(
    base_url: str, api_key: str, ticket: int
) -> str | None:
    """Demande à CE bridge la cause de clôture enregistrée par MT5.

    Ajouté le 2026-08-17. Les lignes d'audit d'une fermeture ne portent AUCUNE
    cause : `_log_closed_position` (bridge) itère les deals, a `d.reason` sous
    la main, et ne l'écrit pas. `_update_closed_trade` retombait donc sur
    l'heuristique de prix — qui ne peut structurellement jamais rendre
    "MANUAL", puisqu'elle ne connaît que les SL/TP stockés.

    Mesuré ce jour-là : trois XAU/USD fermés à la main par l'utilisateur,
    enregistrés `TRAILING_SL` alors que `/deals` répondait `MANUAL` pour les
    trois. Le réconciliateur, lui, avait la bonne cause — mais il arrive après
    et `close_reason = COALESCE(close_reason, ?)` lui interdit d'y toucher.
    Demander ICI fait atterrir la cause juste dès la PREMIÈRE écriture, ce qui
    supprime la course au lieu de l'arbitrer.

    ⚠️ On interroge le bridge d'où vient la ligne d'audit, pas « les bridges » :
    à ce stade on sait exactement à qui appartient le ticket. C'est ce que le
    réconciliateur ne peut pas savoir, lui qui doit tous les questionner.

    Retourne `None` si le bridge est muet — jamais une cause inventée.
    Cf. [[feedback_detection_par_absence]].
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"{base_url.rstrip('/')}/deals",
                headers={"X-API-Key": api_key} if api_key else {},
                params={"ticket": ticket},
            )
        if r.status_code != 200:
            return None
        return r.json().get("reason")
    except Exception as e:
        logger.debug(f"mt5_sync: cause /deals ticket={ticket} indisponible: {e}")
        return None


async def _sync_one(name: str, base_url: str, api_key: str) -> tuple[int, int]:
    """Pull /audit d'un bridge MT5 + applique à personal_trades. Retourne (n_open, n_closed).

    Le bridge non-joignable est silencieux (PC éteint, VPS down — no-op).
    """
    state = _load_state()
    last_id = int(state.get("bridges", {}).get(name, 0))
    url = f"{base_url.rstrip('/')}/audit"
    headers = {"X-API-Key": api_key} if api_key else {}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                url, headers=headers,
                params={"since_id": last_id, "limit": 100},
            )
        if r.status_code != 200:
            logger.warning(f"mt5_sync[{name}]: /audit {r.status_code}: {r.text[:200]}")
            return (0, 0)
        orders = r.json().get("orders", [])
    except Exception as e:
        logger.debug(f"mt5_sync[{name}]: unreachable: {e}")
        return (0, 0)

    if not orders:
        return (0, 0)

    user = _resolve_auto_user()
    new_open = 0
    new_closed = 0
    max_id = last_id
    for row in orders:
        rid = row.get("id", 0)
        if rid > max_id:
            max_id = rid
        if row.get("mode") != "live":
            continue
        status = row.get("status")
        if status == "filled":
            _upsert_open_trade(row, user, destination_id=f"admin_{name}")
            new_open += 1
        elif status == "closed":
            # La cause d'abord, l'écriture ensuite : `close_reason` est protégé
            # par COALESCE, donc la PREMIÈRE valeur posée est définitive. Y
            # laisser atterrir une devinette condamne la cause du courtier.
            if not (row.get("close_reason") or row.get("reason")
                    or row.get("deal_reason")) and row.get("ticket"):
                cause = await _cause_du_courtier(
                    base_url, api_key, int(row["ticket"])
                )
                if cause:
                    row = {**row, "reason": cause}
            _update_closed_trade(row)
            new_closed += 1
            ticket = row.get("ticket")
            if ticket:
                await _notify_close_telegram(int(ticket))

    state.setdefault("bridges", {})[name] = max_id
    _save_state(state)
    if new_open or new_closed:
        logger.info(
            f"mt5_sync[{name}]: {new_open} nouveaux open, {new_closed} closed "
            f"(user={user}, last_id={max_id})"
        )
    return (new_open, new_closed)


async def sync_from_bridge() -> None:
    """Pull incrémental des événements audit des bridges MT5 configurés.

    Itère sur :
    - legacy : MT5_BRIDGE_URL + MT5_BRIDGE_API_KEY (Pepperstone Demo)
    - live   : MT5_BRIDGE_LIVE_URL + MT5_BRIDGE_LIVE_API_KEY (IC Markets Live)

    Chaque bridge a son propre last_id dans state['bridges'][name]. Un bridge
    injoignable est silencieux (no-op pour ce cycle).
    """
    if not MT5_SYNC_ENABLED:
        return

    if MT5_BRIDGE_URL and MT5_BRIDGE_API_KEY:
        await _sync_one("legacy", MT5_BRIDGE_URL, MT5_BRIDGE_API_KEY)

    live_url = os.getenv("MT5_BRIDGE_LIVE_URL", "")
    live_key = os.getenv("MT5_BRIDGE_LIVE_API_KEY", "")
    if live_url and live_key:
        await _sync_one("live", live_url, live_key)

    await _reconcile_open_trades()
