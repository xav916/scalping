#!/usr/bin/env bash
# Fetch H1 5y pour les 41 nouveaux instruments à pre-screener.
set -u
export PYTHONIOENCODING=utf-8

PAIRS=(
  # Forex emerging
  USD/ZAR USD/TRY USD/SGD USD/NOK USD/SEK USD/PLN USD/HUF USD/CZK
  NZD/USD AUD/JPY EUR/AUD
  # Crypto majors
  SOL/USD ADA/USD XRP/USD BNB/USD DOGE/USD DOT/USD AVAX/USD LINK/USD
  # Indices intl (= "asset" mais TD les expose comme symbols simples)
  DAX FTSE CAC SMI ASX IBEX MIB AEX
  # Sector ETFs
  XLE XLF XLV XLK XLI XLY XLP XLU XLB XLRE SLV USO UNG
  # Soft commodity dispo
  CORN
)

DB=_macro_veto_analysis/backtest_candles.db

for pair in "${PAIRS[@]}"; do
  echo "=== $pair ==="
  python scripts/fetch_historical_backtest.py --pair "$pair" --interval 1h --days 1825 --db "$DB" --env .env 2>&1 | tail -3
done
