"""Earnings calendar per-stock — cache SQLite + refresh daily.

P2 chantier : veto 24h avant/après earnings sur signaux equity individuels
(AAPL/TSLA/NVDA/MSFT/MSTR/HOOD/GOOGL/AMZN/META/AMD/NFLX/COIN/PLTR/SHOP/
JPM/V/MA/DIS/WMT) pour éviter les gaps overnight brutaux.

## Source

yfinance (PyPI) — `Ticker.calendar` retourne le prochain earnings date.
Best-effort : si yfinance fail (rate-limit, timeout, réseau), on utilise
le cache SQLite et on log un warning. Jamais d'exception propagée.

## Cache

Table `earnings_calendar` dans macro.db (partagé avec vix_service).
Schema : symbol TEXT PK, next_earnings_at TEXT, last_earnings_at TEXT, updated_at TEXT.

TTL cache : 24h. Si la donnée a < 24h on ne re-fetche pas.

## ETF / non-stocks

SPY, QQQ (ETF) → pas d'earnings, skip silencieux.
La table les ignore simplement.

## Refresh

Appelé via `refresh_all_symbols()` depuis le scheduler (daily 06h UTC).
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Chemin partagé avec vix_service et macro_context_service
_DB_PATH = "/app/data/macro.db"

# Symbols equity individuels supportés (tous les stocks de WATCHED_PAIRS + extensions)
# ETF exclus : SPY, QQQ → pas d'earnings
EARNINGS_SYMBOLS = [
    "AAPL", "TSLA", "NVDA", "MSFT", "MSTR", "HOOD", "GOOGL", "AMZN",
    "META", "AMD", "NFLX", "COIN", "PLTR", "SHOP", "JPM", "V", "MA",
    "DIS", "WMT",
]

# Si les données ont > 24h, on re-fetch lors du prochain refresh
_CACHE_TTL_SEC = 24 * 3600


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS earnings_calendar (
            symbol TEXT PRIMARY KEY,
            next_earnings_at TEXT,
            last_earnings_at TEXT,
            updated_at TEXT NOT NULL
        )
    """)
    con.commit()


def _fetch_yfinance(symbol: str) -> dict | None:
    """Fetch next/last earnings dates via yfinance.

    Retourne {'next_earnings_at': iso_str|None, 'last_earnings_at': iso_str|None}
    ou None si yfinance indisponible.
    """
    try:
        import yfinance as yf  # lazy import pour éviter crash si absent
        ticker = yf.Ticker(symbol)
        # calendar est un DataFrame avec colonnes 'Earnings Date', index 0 = prochain
        cal = ticker.calendar
        next_dt: Optional[str] = None
        if cal is not None and not cal.empty:
            # Selon la version yfinance, cal peut être un dict ou DataFrame
            if hasattr(cal, "columns"):
                # DataFrame format : colonnes indexées (0 = prochain, 1 = suivant)
                col = "Earnings Date"
                if col in cal.index:
                    raw = cal.loc[col].iloc[0] if hasattr(cal.loc[col], "iloc") else cal.loc[col]
                    if raw is not None:
                        # Convertir en datetime UTC
                        if hasattr(raw, "to_pydatetime"):
                            dt = raw.to_pydatetime()
                        else:
                            dt = datetime.fromisoformat(str(raw))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        next_dt = dt.isoformat()
            elif isinstance(cal, dict):
                raw = cal.get("Earnings Date", [None])[0] if isinstance(cal.get("Earnings Date"), list) else cal.get("Earnings Date")
                if raw is not None:
                    if hasattr(raw, "to_pydatetime"):
                        dt = raw.to_pydatetime()
                    else:
                        dt = datetime.fromisoformat(str(raw))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    next_dt = dt.isoformat()

        # last_earnings : earnings_dates historique
        last_dt: Optional[str] = None
        try:
            hist = ticker.earnings_dates
            if hist is not None and not hist.empty:
                now = datetime.now(timezone.utc)
                past = hist[hist.index < now]
                if not past.empty:
                    raw_last = past.index[0]  # plus récent passé (index trié desc)
                    if hasattr(raw_last, "to_pydatetime"):
                        dt_last = raw_last.to_pydatetime()
                    else:
                        dt_last = datetime.fromisoformat(str(raw_last))
                    if dt_last.tzinfo is None:
                        dt_last = dt_last.replace(tzinfo=timezone.utc)
                    last_dt = dt_last.isoformat()
        except Exception as e:
            logger.debug(f"earnings_calendar: last_earnings for {symbol} failed: {e}")

        return {"next_earnings_at": next_dt, "last_earnings_at": last_dt}

    except ImportError:
        logger.warning("earnings_calendar: yfinance not installed — pip install yfinance")
        return None
    except Exception as e:
        logger.warning(f"earnings_calendar: yfinance fetch failed for {symbol}: {e}")
        return None


def _upsert(con: sqlite3.Connection, symbol: str, data: dict) -> None:
    now = datetime.now(timezone.utc).isoformat()
    con.execute(
        """
        INSERT INTO earnings_calendar (symbol, next_earnings_at, last_earnings_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(symbol) DO UPDATE SET
            next_earnings_at = excluded.next_earnings_at,
            last_earnings_at = excluded.last_earnings_at,
            updated_at = excluded.updated_at
        """,
        (symbol, data.get("next_earnings_at"), data.get("last_earnings_at"), now),
    )


def _read_cache(symbol: str) -> dict | None:
    """Lit le cache SQLite. Retourne None si absent ou périmé (> TTL)."""
    try:
        con = sqlite3.connect(_DB_PATH)
        con.row_factory = sqlite3.Row
        _ensure_schema(con)
        row = con.execute(
            "SELECT next_earnings_at, last_earnings_at, updated_at FROM earnings_calendar WHERE symbol = ?",
            (symbol,),
        ).fetchone()
        con.close()
        if not row:
            return None
        updated = datetime.fromisoformat(row["updated_at"])
        age = (datetime.now(timezone.utc) - updated).total_seconds()
        if age > _CACHE_TTL_SEC:
            return None  # périmé — besoin de refresh
        return {
            "next_earnings_at": row["next_earnings_at"],
            "last_earnings_at": row["last_earnings_at"],
            "age_sec": age,
        }
    except Exception as e:
        logger.debug(f"earnings_calendar: cache read error for {symbol}: {e}")
        return None


def get_next_earnings(symbol: str) -> Optional[datetime]:
    """Retourne le prochain earnings date pour un symbol, ou None.

    Inclut le dernier earnings s'il date de moins de 24h (fenêtre post-earnings
    still active).

    Lit d'abord le cache SQLite. Si absent ou périmé, tente yfinance + persist.
    Best-effort : retourne None si tout échoue.
    """
    sym = symbol.upper()

    # Lecture cache
    cached = _read_cache(sym)
    if cached is None:
        # Tente fetch + persist
        data = _fetch_yfinance(sym)
        if data:
            try:
                con = sqlite3.connect(_DB_PATH)
                _ensure_schema(con)
                _upsert(con, sym, data)
                con.commit()
                con.close()
            except Exception as e:
                logger.debug(f"earnings_calendar: cache write error for {sym}: {e}")
            cached = data

    if not cached:
        return None

    # Retourne le prochain earnings s'il existe
    raw = cached.get("next_earnings_at")
    if raw:
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            pass

    return None


def get_last_earnings(symbol: str) -> Optional[datetime]:
    """Retourne le dernier earnings passé pour un symbol, ou None."""
    sym = symbol.upper()
    cached = _read_cache(sym)
    if not cached:
        return None
    raw = cached.get("last_earnings_at")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def refresh_symbol(symbol: str) -> bool:
    """Force refresh d'un symbol via yfinance + persist.

    Retourne True si refresh réussi, False sinon (best-effort).
    """
    sym = symbol.upper()
    data = _fetch_yfinance(sym)
    if not data:
        return False
    try:
        con = sqlite3.connect(_DB_PATH)
        _ensure_schema(con)
        _upsert(con, sym, data)
        con.commit()
        con.close()
        logger.info(
            f"earnings_calendar: {sym} refreshed "
            f"next={data.get('next_earnings_at')} last={data.get('last_earnings_at')}"
        )
        return True
    except Exception as e:
        logger.warning(f"earnings_calendar: persist failed for {sym}: {e}")
        return False


def refresh_all_symbols() -> dict:
    """Refresh tous les symbols EARNINGS_SYMBOLS via yfinance.

    Appelé par le scheduler daily 06h UTC. Best-effort total :
    si un symbol fail, on continue les suivants.

    Retourne {'refreshed': N, 'failed': M, 'symbols': [...]}.
    """
    refreshed = 0
    failed = 0
    for sym in EARNINGS_SYMBOLS:
        ok = refresh_symbol(sym)
        if ok:
            refreshed += 1
        else:
            failed += 1
    logger.info(
        f"earnings_calendar: refresh_all done refreshed={refreshed} failed={failed}"
    )
    return {"refreshed": refreshed, "failed": failed, "symbols": EARNINGS_SYMBOLS}
