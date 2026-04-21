"""COT (Commitments of Traders) reports : positionnement des gros.

La CFTC publie chaque vendredi les positions des traders sur les futures
US, arretees au mardi precedent. Source utilisee : endpoint Socrata JSON
`publicreporting.cftc.gov/resource/gpe5-46if.json` (disaggregated report).

Lecture du rapport
- Leveraged funds = hedge funds, proxy "smart money"
- Non reportables = petits traders, proxy contrarien (quand ils sont
  extremement long → souvent proche d'un top)
- Net position = long contracts - short contracts

Usage dans le systeme
- Table `cot_snapshots` dans trades.db (stockage persistant hebdo)
- Pour chaque contrat watchliste, z-score net position sur 52 semaines
- Flag `extreme` si |z-score| >= 2.0 (top / bottom historique)
- Expose `get_latest()` pour le cockpit, `find_extremes()` pour les
  alertes

Le service est defensif : toute erreur reseau / parsing est loggee et
retourne un payload vide — jamais d'exception qui remonte au scheduler.

Integration dans le risk scoring : **pas encore**. On ingere et on
affiche d'abord, pour valider visuellement que les signaux matchent
les retournements observes. Une modulation auto de sizing necessitera
des regles validees sur 6+ mois de donnees.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


CFTC_ENDPOINT = (
    "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
)

# Mapping CFTC market_and_exchange_names → pair interne.
# Choix "$only_=..." : tous les contrats utiles pour WATCHED_PAIRS.
_CONTRACT_MAP: dict[str, str] = {
    "U.S. DOLLAR INDEX - ICE FUTURES U.S.": "DXY",
    "EURO FX - CHICAGO MERCANTILE EXCHANGE": "EUR/USD",
    "BRITISH POUND STERLING - CHICAGO MERCANTILE EXCHANGE": "GBP/USD",
    "JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE": "USD/JPY",
    "CANADIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE": "USD/CAD",
    "AUSTRALIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE": "AUD/USD",
    "SWISS FRANC - CHICAGO MERCANTILE EXCHANGE": "USD/CHF",
    "GOLD - COMMODITY EXCHANGE INC.": "XAU/USD",
    "SILVER - COMMODITY EXCHANGE INC.": "XAG/USD",
    "WTI-PHYSICAL - NEW YORK MERCANTILE EXCHANGE": "WTI/USD",
    "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE": "SPX",
    "NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE": "NDX",
    "BITCOIN - CHICAGO MERCANTILE EXCHANGE": "BTC/USD",
}

# Nombre de semaines pour le calcul du z-score (baseline roulante).
_ZSCORE_WINDOW_WEEKS = 52
# Seuil |z-score| au-dela duquel on flag "extreme".
_EXTREME_ZSCORE_THRESHOLD = 2.0


def _db_path() -> Path:
    from backend.services.trade_log_service import _DB_PATH
    return _DB_PATH


@contextmanager
def _conn():
    conn = sqlite3.connect(str(_db_path()), isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _init_schema() -> None:
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS cot_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_date TEXT NOT NULL,
                contract TEXT NOT NULL,
                pair TEXT NOT NULL,
                lev_funds_long INTEGER,
                lev_funds_short INTEGER,
                lev_funds_net INTEGER,
                asset_mgr_long INTEGER,
                asset_mgr_short INTEGER,
                asset_mgr_net INTEGER,
                non_reportables_long INTEGER,
                non_reportables_short INTEGER,
                non_reportables_net INTEGER,
                open_interest INTEGER,
                fetched_at TEXT NOT NULL,
                UNIQUE(report_date, contract)
            );
            CREATE INDEX IF NOT EXISTS idx_cot_pair_date
                ON cot_snapshots(pair, report_date);
        """)


def _to_int(v) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except Exception:
        return None


async def fetch_latest_report(limit: int = 50) -> list[dict]:
    """Recupere les dernieres lignes du rapport disaggregated.
    Best-effort : retourne [] en cas de probleme reseau/parsing."""
    params = {
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": str(limit),
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(CFTC_ENDPOINT, params=params)
            if r.status_code != 200:
                logger.warning(f"cot: CFTC {r.status_code}: {r.text[:200]}")
                return []
            return r.json()
    except Exception as e:
        logger.warning(f"cot: CFTC fetch failed: {e}")
        return []


def _parse_row(row: dict) -> dict | None:
    """Extrait les champs utiles d'une ligne CFTC. Retourne None si le
    contrat n'est pas dans notre whitelist."""
    name = row.get("market_and_exchange_names") or row.get("contract_market_name") or ""
    pair = _CONTRACT_MAP.get(name)
    if not pair:
        return None

    def _field(*keys):
        for k in keys:
            v = row.get(k)
            if v is not None and v != "":
                return _to_int(v)
        return None

    lev_long = _field("m_money_positions_long_all", "lev_money_positions_long")
    lev_short = _field("m_money_positions_short_all", "lev_money_positions_short")
    am_long = _field("asset_mgr_positions_long", "asset_mgr_positions_long_all")
    am_short = _field("asset_mgr_positions_short", "asset_mgr_positions_short_all")
    nr_long = _field("nonrept_positions_long_all", "non_rept_positions_long")
    nr_short = _field("nonrept_positions_short_all", "non_rept_positions_short")

    report_date = (
        row.get("report_date_as_yyyy_mm_dd")
        or row.get("report_date_as_mm_dd_yyyy")
        or ""
    )[:10]

    return {
        "report_date": report_date,
        "contract": name,
        "pair": pair,
        "lev_funds_long": lev_long,
        "lev_funds_short": lev_short,
        "lev_funds_net": (lev_long or 0) - (lev_short or 0) if lev_long is not None else None,
        "asset_mgr_long": am_long,
        "asset_mgr_short": am_short,
        "asset_mgr_net": (am_long or 0) - (am_short or 0) if am_long is not None else None,
        "non_reportables_long": nr_long,
        "non_reportables_short": nr_short,
        "non_reportables_net": (nr_long or 0) - (nr_short or 0) if nr_long is not None else None,
        "open_interest": _field("open_interest_all", "open_interest"),
    }


def _upsert_snapshot(parsed: dict) -> None:
    _init_schema()
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            """
            INSERT OR REPLACE INTO cot_snapshots (
                report_date, contract, pair,
                lev_funds_long, lev_funds_short, lev_funds_net,
                asset_mgr_long, asset_mgr_short, asset_mgr_net,
                non_reportables_long, non_reportables_short, non_reportables_net,
                open_interest, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                parsed["report_date"], parsed["contract"], parsed["pair"],
                parsed["lev_funds_long"], parsed["lev_funds_short"],
                parsed["lev_funds_net"],
                parsed["asset_mgr_long"], parsed["asset_mgr_short"],
                parsed["asset_mgr_net"],
                parsed["non_reportables_long"], parsed["non_reportables_short"],
                parsed["non_reportables_net"],
                parsed["open_interest"], now,
            ),
        )


async def sync_latest() -> dict:
    """Pull + parse + store. Idempotent (UNIQUE report_date+contract).
    Retourne un summary pour le logging."""
    rows = await fetch_latest_report(limit=100)
    parsed_count = 0
    for row in rows:
        parsed = _parse_row(row)
        if parsed and parsed["report_date"]:
            try:
                _upsert_snapshot(parsed)
                parsed_count += 1
            except Exception as e:
                logger.warning(f"cot: upsert failed for {parsed.get('contract')}: {e}")
    logger.info(f"cot: sync terminee — {parsed_count} contrats indexes")
    return {"fetched": len(rows), "stored": parsed_count}


def _zscore(values: list[float], current: float) -> float | None:
    """Z-score de `current` contre l'historique `values` (ecart-type
    population). Retourne None si echantillon insuffisant ou std=0."""
    if len(values) < 8:  # au moins 2 mois d'historique
        return None
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    if var == 0:
        return None
    std = var ** 0.5
    return round((current - mean) / std, 2)


def get_latest() -> list[dict]:
    """Dernier snapshot connu par pair, avec z-score des positions nettes
    sur la fenetre roulante 52 semaines."""
    _init_schema()
    with _conn() as c:
        pairs = [
            r["pair"] for r in c.execute(
                "SELECT DISTINCT pair FROM cot_snapshots"
            ).fetchall()
        ]
        out: list[dict] = []
        for pair in pairs:
            rows = c.execute(
                """
                SELECT * FROM cot_snapshots
                 WHERE pair = ?
                 ORDER BY report_date DESC
                 LIMIT ?
                """,
                (pair, _ZSCORE_WINDOW_WEEKS),
            ).fetchall()
            if not rows:
                continue
            latest = rows[0]
            history = list(reversed(rows))  # chronologique
            lev_nets = [r["lev_funds_net"] for r in history if r["lev_funds_net"] is not None]
            nr_nets = [r["non_reportables_net"] for r in history if r["non_reportables_net"] is not None]
            lev_z = _zscore(lev_nets[:-1], lev_nets[-1]) if lev_nets else None
            nr_z = _zscore(nr_nets[:-1], nr_nets[-1]) if nr_nets else None
            out.append({
                "pair": pair,
                "contract": latest["contract"],
                "report_date": latest["report_date"],
                "lev_funds_net": latest["lev_funds_net"],
                "lev_funds_z": lev_z,
                "non_reportables_net": latest["non_reportables_net"],
                "non_reportables_z": nr_z,
                "open_interest": latest["open_interest"],
            })
    return out


def find_extremes() -> list[dict]:
    """Flag les pairs ou leveraged_funds OU non_reportables sont a
    >= |_EXTREME_ZSCORE_THRESHOLD| ecarts-types de la moyenne 52s."""
    items: list[dict] = []
    for entry in get_latest():
        lev_z = entry.get("lev_funds_z")
        nr_z = entry.get("non_reportables_z")
        signals = []
        if lev_z is not None and abs(lev_z) >= _EXTREME_ZSCORE_THRESHOLD:
            signals.append({
                "actor": "leveraged_funds",
                "z": lev_z,
                "interpretation": (
                    "smart money tres long"
                    if lev_z >= 0
                    else "smart money tres short"
                ),
            })
        if nr_z is not None and abs(nr_z) >= _EXTREME_ZSCORE_THRESHOLD:
            signals.append({
                "actor": "non_reportables",
                "z": nr_z,
                "interpretation": (
                    "petits traders tres long (contrarien bear)"
                    if nr_z >= 0
                    else "petits traders tres short (contrarien bull)"
                ),
            })
        if signals:
            items.append({
                "pair": entry["pair"],
                "report_date": entry["report_date"],
                "signals": signals,
            })
    return items
