#!/usr/bin/env bash
# Fetch Daily 20 ans pour les 6 stars (max profondeur disponible TD).
# XAU/XAG/WTI/XLI/XLK : depuis 2005 (20y). ETH : depuis ~2021.
set -u
export PYTHONIOENCODING=utf-8

DB=_macro_veto_analysis/backtest_candles.db

# 20 ans = 7300 jours
DAYS=7300

PAIRS=(XAU/USD XAG/USD WTI/USD ETH/USD XLI XLK)

for pair in "${PAIRS[@]}"; do
  echo "=== $pair Daily 20y ==="
  python scripts/fetch_historical_backtest.py \
    --pair "$pair" \
    --interval 1day \
    --days $DAYS \
    --db "$DB" \
    --env .env 2>&1 | tail -3
done
