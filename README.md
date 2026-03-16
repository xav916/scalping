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
# Install dependencies
pip install -r requirements.txt

# Copy and edit config
cp .env.example .env

# Run
python main.py
```

Open http://localhost:8000 in your browser.

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
