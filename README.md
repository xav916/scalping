# Scalping Radar - Decision Tool

An intelligent scalping radar that analyzes market volatility and trends, detects opportunities, and sends real-time notifications. **This is a decision-support tool only** — it does not execute trades.

## Features

- **Volatility monitoring** via Mataf.net — detects volatility spikes on watched currency pairs
- **Economic calendar** via Forex Factory — tracks high-impact events and market context
- **Signal detection engine** — combines volatility + trend + event data to identify scalping opportunities
- **Real-time notifications** — WebSocket-based live alerts + browser push notifications
- **Web dashboard** — dark-themed interface showing signals, volatility, and economic events

## Architecture

```
backend/
  app.py                  # FastAPI application
  models/schemas.py       # Pydantic data models
  services/
    mataf_service.py      # Mataf.net volatility scraper
    forexfactory_service.py  # Forex Factory calendar scraper
    analysis_engine.py    # Core signal detection logic
    notification_service.py  # WebSocket notification manager
    scheduler.py          # Periodic analysis scheduler
frontend/
  index.html              # Dashboard page
  css/style.css           # Styles
  js/app.js               # Frontend logic
config/settings.py        # Configuration
main.py                   # Entry point
```

## Quick Start

```bash
# Install dependencies (runtime)
pip install -r requirements.txt

# Copy and edit config
cp .env.example .env

# Run
python main.py
```

Open http://localhost:8000 in your browser.

## Running the tests

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
python -m pytest backend/tests -q
```

Both files are needed. `requirements-dev.txt` adds Flask — the MT5 bridge
tests import `mt5-bridge/bridge.py`, which depends on it — and
`pytest-randomly`. Flask is deliberately kept out of `requirements.txt`: the
backend runs on FastAPI and does not need a second web framework in
production.

The suite runs in full on Linux. The five MT5 risk-guard test files load the
bridge, which imports `MetaTrader5` — a Windows-only module. Where it is
absent, `conftest.py` installs a stand-in whose constants are checked against
the real module on any Windows machine
(`backend/tests/test_doublure_metatrader5.py`). Those tests therefore **run**
off Windows rather than being skipped.

### Reproducing an intermittent failure

The suite does not always return the same verdict (audit finding R-27: eight
runs of one commit gave seven clean runs and one with six failures, cause
unknown). CI therefore runs it in random order with a fixed, printed seed, so
a failure can be replayed exactly:

```bash
python -m pytest backend/tests -q --randomly-seed=20261031
```

Change the seed to search for an order that breaks; the seed that fails stays
replayable.

## How It Works

1. **Data collection**: Periodically scrapes Mataf (volatility) and Forex Factory (events)
2. **Analysis**: Computes volatility ratios, derives trend direction, evaluates event impact
3. **Signal detection**: When volatility is elevated + trend is clear + conditions align → signal
4. **Notification**: Signals are pushed to the dashboard via WebSocket and browser notifications

## Configuration

All settings are in `.env` (see `.env.example`):

| Variable | Default | Description |
|---|---|---|
| `MATAF_POLL_INTERVAL` | 300 | Seconds between volatility checks |
| `VOLATILITY_THRESHOLD_HIGH` | 1.5 | Ratio to classify as high volatility |
| `TREND_STRENGTH_MIN` | 0.6 | Minimum trend strength for signals |
| `WATCHED_PAIRS` | 9 major pairs | Comma-separated currency pairs |
