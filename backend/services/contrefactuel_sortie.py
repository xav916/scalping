"""Ce que le SL/TP AURAIT donné, sur les trades sortis autrement.

Posé le 2026-09-06. Sur `[RÉEL · IC_MARKETS]`, deux tiers des clôtures ne sont
ni SL ni TP : elles sortent en moyenne à **+0,42 R** avec 86 % de gagnants,
tandis que les sorties automatiques font **−0,40 R**. Tentant d'en conclure que
sortir tôt vaut mieux — sauf qu'on ne sait pas ce que ces trades AURAIENT fait
si on les avait laissés courir.

⛔ **Sans ce contrefactuel, la comparaison est biaisée par construction** : on
compare les trades qu'on a choisi de couper à ceux qu'on a choisi de laisser.
Ce module rend la comparaison possible sur les **mêmes** trades, aux **mêmes**
prix.

🔑 **Il ne touche pas au chemin de clôture.** C'est un BALAYAGE en lecture :
il relit `personal_trades` après coup. Un outil de mesure qui peut casser un
ordre n'est pas un outil de mesure, c'est un risque.

## Comment la résolution est faite

Depuis l'instant de la clôture, on rejoue les **bougies** (haut/bas), pas des
sondes ponctuelles : une mèche qui touche le niveau entre deux sondes serait
invisible, et le biais irait toujours dans le même sens — sous-compter les
touches.

⚠️ **Si le haut ET le bas d'une même bougie franchissent les deux niveaux, le
résultat est `indetermine`.** On ne sait pas dans quel ordre le prix les a
touchés à l'intérieur de la barre, et deviner ferait pencher la mesure du côté
qu'on espère. C'est rare, et c'est compté à part.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DB = Path("/app/data/trades.db") if Path("/app").exists() else Path("trades.db")

# Au-delà, on cesse d'attendre : un trade dont ni le stop ni l'objectif n'ont
# été touchés en une semaine ne dit plus rien sur la décision de sortie.
JOURS_MAX = 7

# ⛔ Un stop collé à l'entrée fait exploser le R — un USD/JPY à 0,0063 % de
# distance a rendu +79 R sur le démo et déplacé la moyenne de +0,43 à +3,99.
# Ces trades sont EXCLUS de la mesure, pas corrigés : leur R n'a pas de sens.
DISTANCE_STOP_MIN_PCT = 0.05

_MOTIFS_AUTOMATIQUES = {"SL", "TP1", "TP2"}


def _conn():
    c = sqlite3.connect(str(_DB), isolation_level=None)
    c.row_factory = sqlite3.Row
    return c


def init_schema() -> None:
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS contrefactuels_sortie (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER NOT NULL UNIQUE,
                destination_id TEXT NOT NULL,
                pair TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                sl REAL NOT NULL,
                tp REAL NOT NULL,
                exit_price REAL NOT NULL,
                closed_at TEXT NOT NULL,
                close_reason TEXT,
                r_realise REAL NOT NULL,
                r_contrefactuel REAL,
                issue TEXT,              -- SL | TP | indetermine | expire | NULL
                resolu_a TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_cf_issue ON contrefactuels_sortie(issue);
        """)


def r_realise(entry: float, exit_: float, sl: float, achat: bool) -> float | None:
    """R effectivement obtenu. ``None`` si le risque est nul ou illisible."""
    try:
        d = abs(float(entry) - float(sl))
        if d <= 0:
            return None
        return (float(exit_) - float(entry)) * (1.0 if achat else -1.0) / d
    except (TypeError, ValueError):
        return None


def stop_utilisable(entry: float, sl: float) -> bool:
    """⛔ Un stop trop proche de l'entrée rend un R sans signification."""
    try:
        entry, sl = float(entry), float(sl)
    except (TypeError, ValueError):
        return False
    if entry <= 0:
        return False
    # ⛔ Epsilon obligatoire : `100,0 - 99,95` vaut 0,049999999999997 en
    # flottant, et un stop PILE au seuil serait rejete. Meme piege que la sonde
    # des paliers, ou une position exactement au tiers ne declenchait pas.
    return abs(entry - sl) / entry * 100.0 >= DISTANCE_STOP_MIN_PCT - 1e-9


def issue_depuis_bougies(bougies, sl: float, tp: float, achat: bool) -> str | None:
    """`SL` | `TP` | `indetermine` | ``None`` si aucun niveau n'est touché.

    ⚠️ Les deux niveaux franchis dans la MÊME bougie ⇒ `indetermine` : l'ordre
    des touches à l'intérieur d'une barre est inconnaissable, et le deviner
    ferait pencher la mesure du côté qu'on espère.
    """
    for b in bougies or []:
        try:
            haut = float(getattr(b, "high", None) if not isinstance(b, dict) else b["high"])
            bas = float(getattr(b, "low", None) if not isinstance(b, dict) else b["low"])
        except (TypeError, ValueError, KeyError):
            continue
        if achat:
            touche_tp, touche_sl = haut >= tp, bas <= sl
        else:
            touche_tp, touche_sl = bas <= tp, haut >= sl
        if touche_tp and touche_sl:
            return "indetermine"
        if touche_tp:
            return "TP"
        if touche_sl:
            return "SL"
    return None


def balayer(depuis: str = "2026-08-25") -> int:
    """Enregistre les clôtures NON automatiques qui n'ont pas encore de ligne.

    Lecture seule sur `personal_trades` — ce module ne ferme rien et ne modifie
    aucun trade.
    """
    init_schema()
    ajouts = 0
    with _conn() as c:
        connus = {r["trade_id"] for r in c.execute(
            "SELECT trade_id FROM contrefactuels_sortie")}
        for r in c.execute(
                "SELECT rowid AS rid, * FROM personal_trades WHERE closed_at >= ?",
                (depuis,)):
            if r["rid"] in connus:
                continue
            if (r["close_reason"] or "") in _MOTIFS_AUTOMATIQUES:
                continue          # déjà sorti par son niveau : rien à simuler
            try:
                e = float(r["entry_price"]); x = float(r["exit_price"])
                sl = float(r["sl_at_close"]); tp = float(r["tp_at_close"])
            except (TypeError, ValueError):
                continue
            if not stop_utilisable(e, sl):
                continue
            achat = str(r["direction"] or "").lower().startswith("b")
            # ⛔ Un objectif du mauvais côté de l'entrée ne peut pas être touché :
            # 14 % des TP stockés étaient dans ce cas en août.
            if (achat and tp <= e) or (not achat and tp >= e):
                continue
            rr = r_realise(e, x, sl, achat)
            if rr is None:
                continue
            c.execute("""INSERT OR IGNORE INTO contrefactuels_sortie
                (trade_id, destination_id, pair, direction, entry_price, sl, tp,
                 exit_price, closed_at, close_reason, r_realise)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                      (r["rid"], r["destination_id"], r["pair"], r["direction"],
                       e, sl, tp, x, r["closed_at"], r["close_reason"], rr))
            ajouts += 1
    return ajouts


async def resoudre(fetch_candles=None) -> dict:
    """Rejoue les bougies depuis la clôture et tranche chaque ligne en attente."""
    init_schema()
    if fetch_candles is None:
        from backend.services.price_service import fetch_candles as _f
        fetch_candles = _f

    compte = {"SL": 0, "TP": 0, "indetermine": 0, "expire": 0, "en_attente": 0}
    with _conn() as c:
        lignes = [dict(r) for r in c.execute(
            "SELECT * FROM contrefactuels_sortie WHERE issue IS NULL")]

    for l in lignes:
        try:
            ferme = datetime.fromisoformat(str(l["closed_at"]).replace("Z", "+00:00"))
            if ferme.tzinfo is None:
                ferme = ferme.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        age = (datetime.now(timezone.utc) - ferme).days
        achat = str(l["direction"] or "").lower().startswith("b")

        issue = None
        try:
            bougies, _ = await fetch_candles(l["pair"], interval="1h", outputsize=200)
            recentes = [b for b in (bougies or [])
                        if _apres(b, ferme)]
            issue = issue_depuis_bougies(recentes, l["sl"], l["tp"], achat)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"contrefactuel: bougies indisponibles pour {l['pair']} : {e}")

        if issue is None and age >= JOURS_MAX:
            issue = "expire"
        if issue is None:
            compte["en_attente"] += 1
            continue

        if issue == "TP":
            rc = abs(l["tp"] - l["entry_price"]) / abs(l["entry_price"] - l["sl"])
        elif issue == "SL":
            rc = -1.0
        else:
            rc = None       # indetermine / expire : pas de R invente
        with _conn() as c:
            c.execute("UPDATE contrefactuels_sortie SET issue=?, r_contrefactuel=?, "
                      "resolu_a=? WHERE id=?",
                      (issue, rc, datetime.now(timezone.utc).isoformat(), l["id"]))
        compte[issue] = compte.get(issue, 0) + 1
    return compte


def _apres(bougie, instant) -> bool:
    t = getattr(bougie, "timestamp", None) or getattr(bougie, "time", None)
    if isinstance(bougie, dict):
        t = bougie.get("timestamp") or bougie.get("time")
    if t is None:
        return False
    if isinstance(t, str):
        try:
            t = datetime.fromisoformat(t.replace("Z", "+00:00"))
        except ValueError:
            return False
    if getattr(t, "tzinfo", None) is None:
        t = t.replace(tzinfo=timezone.utc)
    return t > instant


def bilan(destination_id: str = "admin_live") -> dict:
    """Compare le R obtenu au R qu'on aurait obtenu, sur les MÊMES trades."""
    init_schema()
    with _conn() as c:
        lignes = [dict(r) for r in c.execute(
            "SELECT * FROM contrefactuels_sortie WHERE destination_id=? "
            "AND r_contrefactuel IS NOT NULL", (destination_id,))]
    if not lignes:
        # ⛔ « Pas encore de verdict » n'est pas « pas d'écart ».
        return {"n": 0, "verdict": "aucune ligne résolue — la question reste ouverte"}
    reel = sum(l["r_realise"] for l in lignes)
    cf = sum(l["r_contrefactuel"] for l in lignes)
    n = len(lignes)
    return {
        "n": n,
        "r_realise_total": round(reel, 2),
        "r_contrefactuel_total": round(cf, 2),
        "r_realise_moyen": round(reel / n, 3),
        "r_contrefactuel_moyen": round(cf / n, 3),
        "ecart_moyen": round((reel - cf) / n, 3),
        "verdict": ("sortir tôt a MIEUX fait" if reel > cf
                    else "laisser courir aurait mieux fait" if cf > reel
                    else "égalité"),
    }
