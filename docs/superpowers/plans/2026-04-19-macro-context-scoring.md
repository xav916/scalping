# Macro Context Scoring — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich the trade setup confidence scoring with a macro context layer (DXY, SPX, VIX, yields, oil, Nikkei, gold) that applies a multiplier (0.75–1.2) and a hard veto in extreme conditions, with safe fallback when data is stale.

**Architecture:** One fetcher service (`macro_context_service`) pulls 8 macro symbols from Twelve Data every 15 min and caches a `MacroContext` snapshot in RAM. One pure scoring module (`macro_scoring`) maps a (setup, snapshot) pair to `(multiplier, veto, reasons)`. The result is injected into `enrich_trade_setup()` after the existing 5-factor computation. Feature flags (`MACRO_SCORING_ENABLED`, `MACRO_VETO_ENABLED`) allow shadow-mode rollout. Macro snapshot is logged to `personal_trades.context_macro` for future ML traceability.

**Tech Stack:** Python 3.11, httpx (already in use for Twelve Data), APScheduler, SQLite, pytest + pytest-asyncio (to scaffold), FastAPI.

**Source spec:** `docs/superpowers/specs/2026-04-19-macro-context-scoring-design.md`

---

## File Structure

**Created:**
- `backend/models/macro_schemas.py` — dataclasses & enums (`MacroContext`, `MacroDirection`, `VixLevel`, `RiskRegime`)
- `backend/services/macro_scoring.py` — pure scoring function `apply(setup, snapshot) -> (multiplier, veto, reasons)`
- `backend/services/macro_context_service.py` — fetcher + in-memory cache, exposes `get_macro_snapshot()` and `refresh_macro_context()`
- `backend/tests/__init__.py` — empty marker
- `backend/tests/conftest.py` — pytest fixtures (event_loop, sample_setup, sample_snapshot)
- `backend/tests/test_macro_schemas.py`
- `backend/tests/test_macro_scoring.py`
- `backend/tests/test_macro_context_service.py`
- `backend/tests/test_trade_log_migration.py`

**Modified:**
- `requirements.txt` — add pytest, pytest-asyncio
- `config/settings.py` — add ~10 new env vars
- `backend/models/schemas.py` — add optional `source: str | None` to `ConfidenceFactor`
- `backend/services/analysis_engine.py` — inject macro scoring at end of `enrich_trade_setup()`
- `backend/services/scheduler.py` — register `refresh_macro_context` job every 15 min
- `backend/services/trade_log_service.py` — add `context_macro` column + persist on `record_trade`
- `backend/services/mt5_sync.py` — persist `context_macro` when inserting auto trades
- `backend/app.py` — add `GET /debug/macro` endpoint
- `frontend/js/app.js` — render macro badge on setup cards
- `.env.example` — document new variables

---

## Task 1: Scaffold pytest infrastructure

**Files:**
- Modify: `requirements.txt`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_smoke.py`

- [ ] **Step 1: Add test dependencies**

Edit `requirements.txt`, append:

```
pytest==8.3.4
pytest-asyncio==0.25.0
```

- [ ] **Step 2: Install**

Run:
```bash
pip install pytest==8.3.4 pytest-asyncio==0.25.0
```

Expected: `Successfully installed pytest-8.3.4 pytest-asyncio-0.25.0`

- [ ] **Step 3: Create empty package marker**

Create `backend/tests/__init__.py`:

```python
```

(empty file)

- [ ] **Step 4: Create conftest**

Create `backend/tests/conftest.py`:

```python
"""Shared pytest fixtures for the Scalping Radar backend."""
import pytest
import pytest_asyncio


@pytest.fixture
def anyio_backend():
    return "asyncio"
```

- [ ] **Step 5: Create a smoke test**

Create `backend/tests/test_smoke.py`:

```python
def test_pytest_is_wired():
    assert 1 + 1 == 2
```

- [ ] **Step 6: Run it**

Run from repo root:
```bash
python -m pytest backend/tests/test_smoke.py -v
```

Expected: `1 passed`

- [ ] **Step 7: Commit**

```bash
git add requirements.txt backend/tests/
git commit -m "test: scaffold pytest infrastructure for backend"
```

---

## Task 2: Add config settings

**Files:**
- Modify: `config/settings.py`
- Modify: `.env.example`

- [ ] **Step 1: Append new section to `config/settings.py`**

Add at the end of the file:

```python
# ─── Macro context scoring (Vague 1 enrichissement) ─────────────
# Feature flags
MACRO_SCORING_ENABLED = os.getenv("MACRO_SCORING_ENABLED", "false").lower() in ("1", "true", "yes", "on")
MACRO_VETO_ENABLED = os.getenv("MACRO_VETO_ENABLED", "false").lower() in ("1", "true", "yes", "on")

# Refresh cadence and cache tolerance
MACRO_REFRESH_INTERVAL_SEC = int(os.getenv("MACRO_REFRESH_INTERVAL_SEC", "900"))  # 15 min
MACRO_CACHE_MAX_AGE_SEC = int(os.getenv("MACRO_CACHE_MAX_AGE_SEC", "7200"))  # 2h fallback

# Symbols mapping (logical name → Twelve Data ticker)
MACRO_SYMBOL_DXY = os.getenv("MACRO_SYMBOL_DXY", "DXY")
MACRO_SYMBOL_SPX = os.getenv("MACRO_SYMBOL_SPX", "SPX")
MACRO_SYMBOL_VIX = os.getenv("MACRO_SYMBOL_VIX", "VIX")
MACRO_SYMBOL_US10Y = os.getenv("MACRO_SYMBOL_US10Y", "TNX")
MACRO_SYMBOL_DE10Y = os.getenv("MACRO_SYMBOL_DE10Y", "DE10Y")
MACRO_SYMBOL_OIL = os.getenv("MACRO_SYMBOL_OIL", "WTI")
MACRO_SYMBOL_NIKKEI = os.getenv("MACRO_SYMBOL_NIKKEI", "NKY")
MACRO_SYMBOL_GOLD = os.getenv("MACRO_SYMBOL_GOLD", "XAU/USD")

# Thresholds (overridable for tuning)
MACRO_ZSCORE_STRONG = float(os.getenv("MACRO_ZSCORE_STRONG", "1.5"))
MACRO_ZSCORE_WEAK = float(os.getenv("MACRO_ZSCORE_WEAK", "0.5"))
MACRO_VIX_HIGH = float(os.getenv("MACRO_VIX_HIGH", "30.0"))
MACRO_VIX_ELEVATED = float(os.getenv("MACRO_VIX_ELEVATED", "20.0"))
MACRO_VIX_LOW = float(os.getenv("MACRO_VIX_LOW", "15.0"))
MACRO_DXY_VETO_SIGMA = float(os.getenv("MACRO_DXY_VETO_SIGMA", "2.0"))
```

- [ ] **Step 2: Document in `.env.example`**

Append to `.env.example`:

```bash
# Macro context scoring (Vague 1)
MACRO_SCORING_ENABLED=false
MACRO_VETO_ENABLED=false
MACRO_REFRESH_INTERVAL_SEC=900
MACRO_CACHE_MAX_AGE_SEC=7200
```

- [ ] **Step 3: Verify import still works**

Run:
```bash
python -c "from config.settings import MACRO_SCORING_ENABLED, MACRO_SYMBOL_DXY; print('OK', MACRO_SCORING_ENABLED, MACRO_SYMBOL_DXY)"
```

Expected: `OK False DXY`

- [ ] **Step 4: Commit**

```bash
git add config/settings.py .env.example
git commit -m "config: add macro scoring env vars (disabled by default)"
```

---

## Task 3: Macro schemas (dataclasses + enums)

**Files:**
- Create: `backend/models/macro_schemas.py`
- Create: `backend/tests/test_macro_schemas.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_macro_schemas.py`:

```python
"""Tests for MacroContext schemas and enum thresholds."""
import pytest
from datetime import datetime, timezone

from backend.models.macro_schemas import (
    MacroDirection,
    VixLevel,
    RiskRegime,
    MacroContext,
    direction_from_zscore,
    vix_level_from_value,
)


class TestDirectionFromZscore:
    @pytest.mark.parametrize("z,expected", [
        (2.0, MacroDirection.STRONG_UP),
        (1.5, MacroDirection.STRONG_UP),
        (1.0, MacroDirection.UP),
        (0.5, MacroDirection.UP),
        (0.2, MacroDirection.NEUTRAL),
        (0.0, MacroDirection.NEUTRAL),
        (-0.2, MacroDirection.NEUTRAL),
        (-0.5, MacroDirection.DOWN),
        (-1.0, MacroDirection.DOWN),
        (-1.5, MacroDirection.STRONG_DOWN),
        (-2.0, MacroDirection.STRONG_DOWN),
    ])
    def test_direction_boundaries(self, z, expected):
        assert direction_from_zscore(z) == expected


class TestVixLevelFromValue:
    @pytest.mark.parametrize("v,expected", [
        (10.0, VixLevel.LOW),
        (14.9, VixLevel.LOW),
        (15.0, VixLevel.NORMAL),
        (19.9, VixLevel.NORMAL),
        (20.0, VixLevel.ELEVATED),
        (29.9, VixLevel.ELEVATED),
        (30.0, VixLevel.HIGH),
        (50.0, VixLevel.HIGH),
    ])
    def test_vix_boundaries(self, v, expected):
        assert vix_level_from_value(v) == expected


class TestMacroContextConstruction:
    def test_can_build_minimal(self):
        ctx = MacroContext(
            fetched_at=datetime.now(timezone.utc),
            dxy_direction=MacroDirection.UP,
            spx_direction=MacroDirection.NEUTRAL,
            vix_level=VixLevel.NORMAL,
            vix_value=17.5,
            us10y_trend=MacroDirection.NEUTRAL,
            de10y_trend=MacroDirection.NEUTRAL,
            us_de_spread_trend="flat",
            oil_direction=MacroDirection.NEUTRAL,
            nikkei_direction=MacroDirection.UP,
            gold_direction=MacroDirection.NEUTRAL,
            risk_regime=RiskRegime.NEUTRAL,
            raw_values={"DXY": 103.2},
        )
        assert ctx.vix_value == 17.5
        assert ctx.risk_regime == RiskRegime.NEUTRAL
```

- [ ] **Step 2: Run to verify failure**

Run:
```bash
python -m pytest backend/tests/test_macro_schemas.py -v
```

Expected: `ModuleNotFoundError: No module named 'backend.models.macro_schemas'`

- [ ] **Step 3: Implement the schemas**

Create `backend/models/macro_schemas.py`:

```python
"""Schemas for the macro context scoring layer.

- MacroDirection / VixLevel / RiskRegime: enums capturing normalized state
- MacroContext: a full snapshot of the 8 macro indicators at a point in time
- direction_from_zscore / vix_level_from_value: pure helpers used by the
  fetcher to build a MacroContext from raw price data
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from config.settings import (
    MACRO_VIX_ELEVATED,
    MACRO_VIX_HIGH,
    MACRO_VIX_LOW,
    MACRO_ZSCORE_STRONG,
    MACRO_ZSCORE_WEAK,
)


class MacroDirection(str, Enum):
    STRONG_UP = "strong_up"
    UP = "up"
    NEUTRAL = "neutral"
    DOWN = "down"
    STRONG_DOWN = "strong_down"


class VixLevel(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    ELEVATED = "elevated"
    HIGH = "high"


class RiskRegime(str, Enum):
    RISK_ON = "risk_on"
    NEUTRAL = "neutral"
    RISK_OFF = "risk_off"


@dataclass
class MacroContext:
    fetched_at: datetime
    dxy_direction: MacroDirection
    spx_direction: MacroDirection
    vix_level: VixLevel
    vix_value: float
    us10y_trend: MacroDirection
    de10y_trend: MacroDirection
    us_de_spread_trend: str  # widening | flat | narrowing
    oil_direction: MacroDirection
    nikkei_direction: MacroDirection
    gold_direction: MacroDirection
    risk_regime: RiskRegime
    raw_values: dict[str, float] = field(default_factory=dict)
    dxy_intraday_sigma: float = 0.0  # used for veto condition only


def direction_from_zscore(z: float) -> MacroDirection:
    """Maps a z-score to a MacroDirection using thresholds from settings."""
    if z >= MACRO_ZSCORE_STRONG:
        return MacroDirection.STRONG_UP
    if z >= MACRO_ZSCORE_WEAK:
        return MacroDirection.UP
    if z <= -MACRO_ZSCORE_STRONG:
        return MacroDirection.STRONG_DOWN
    if z <= -MACRO_ZSCORE_WEAK:
        return MacroDirection.DOWN
    return MacroDirection.NEUTRAL


def vix_level_from_value(v: float) -> VixLevel:
    """Maps a VIX raw value to a VixLevel using absolute thresholds."""
    if v >= MACRO_VIX_HIGH:
        return VixLevel.HIGH
    if v >= MACRO_VIX_ELEVATED:
        return VixLevel.ELEVATED
    if v >= MACRO_VIX_LOW:
        return VixLevel.NORMAL
    return VixLevel.LOW
```

- [ ] **Step 4: Run to verify pass**

Run:
```bash
python -m pytest backend/tests/test_macro_schemas.py -v
```

Expected: 24 tests passed.

- [ ] **Step 5: Commit**

```bash
git add backend/models/macro_schemas.py backend/tests/test_macro_schemas.py
git commit -m "feat(macro): MacroContext schemas with pure threshold helpers"
```

---

## Task 4: Macro scoring (pure module)

**Files:**
- Create: `backend/services/macro_scoring.py`
- Create: `backend/tests/test_macro_scoring.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_macro_scoring.py`:

```python
"""Table-driven tests for macro_scoring.apply()."""
from datetime import datetime, timezone

import pytest

from backend.models.macro_schemas import (
    MacroContext,
    MacroDirection,
    RiskRegime,
    VixLevel,
)
from backend.services.macro_scoring import apply


def _make_ctx(
    dxy=MacroDirection.NEUTRAL,
    spx=MacroDirection.NEUTRAL,
    vix_level=VixLevel.NORMAL,
    vix_value=17.0,
    us10y=MacroDirection.NEUTRAL,
    de10y=MacroDirection.NEUTRAL,
    spread_trend="flat",
    oil=MacroDirection.NEUTRAL,
    nikkei=MacroDirection.NEUTRAL,
    gold=MacroDirection.NEUTRAL,
    risk=RiskRegime.NEUTRAL,
    dxy_intraday_sigma=0.0,
) -> MacroContext:
    return MacroContext(
        fetched_at=datetime.now(timezone.utc),
        dxy_direction=dxy,
        spx_direction=spx,
        vix_level=vix_level,
        vix_value=vix_value,
        us10y_trend=us10y,
        de10y_trend=de10y,
        us_de_spread_trend=spread_trend,
        oil_direction=oil,
        nikkei_direction=nikkei,
        gold_direction=gold,
        risk_regime=risk,
        raw_values={},
        dxy_intraday_sigma=dxy_intraday_sigma,
    )


class TestUsdMajors:
    def test_eurusd_sell_aligned_with_dxy_strong_up_gets_boost(self):
        ctx = _make_ctx(dxy=MacroDirection.STRONG_UP)
        mult, veto, reasons = apply("EUR/USD", "sell", ctx)
        assert mult == 1.2
        assert veto is False

    def test_eurusd_buy_against_dxy_strong_up_gets_penalty(self):
        ctx = _make_ctx(dxy=MacroDirection.STRONG_UP)
        mult, veto, reasons = apply("EUR/USD", "buy", ctx)
        assert mult == 0.75
        assert veto is False

    def test_usdjpy_buy_aligned_with_dxy_up_and_risk_on_gets_boost(self):
        ctx = _make_ctx(
            dxy=MacroDirection.UP,
            nikkei=MacroDirection.UP,
            vix_level=VixLevel.LOW,
            risk=RiskRegime.RISK_ON,
        )
        mult, veto, reasons = apply("USD/JPY", "buy", ctx)
        assert mult >= 1.1


class TestVetoConditions:
    def test_vix_above_30_and_setup_against_risk_off_vetoes(self):
        ctx = _make_ctx(
            vix_value=32.0,
            vix_level=VixLevel.HIGH,
            risk=RiskRegime.RISK_OFF,
        )
        mult, veto, reasons = apply("AUD/USD", "buy", ctx)
        assert veto is True
        assert any("vix" in r.lower() for r in reasons)

    def test_dxy_intraday_sigma_above_2_and_setup_against_vetoes(self):
        ctx = _make_ctx(
            dxy=MacroDirection.STRONG_UP,
            dxy_intraday_sigma=2.5,
        )
        mult, veto, reasons = apply("EUR/USD", "buy", ctx)
        assert veto is True
        assert any("dxy" in r.lower() for r in reasons)


class TestCommodityCurrencies:
    def test_audusd_buy_with_risk_on_gold_up_gets_boost(self):
        ctx = _make_ctx(
            dxy=MacroDirection.DOWN,
            spx=MacroDirection.STRONG_UP,
            gold=MacroDirection.UP,
            risk=RiskRegime.RISK_ON,
        )
        mult, _, _ = apply("AUD/USD", "buy", ctx)
        assert mult >= 1.1


class TestCADPair:
    def test_usdcad_sell_with_oil_strong_up_gets_boost(self):
        ctx = _make_ctx(oil=MacroDirection.STRONG_UP, dxy=MacroDirection.NEUTRAL)
        mult, _, _ = apply("USD/CAD", "sell", ctx)
        assert mult >= 1.1


class TestGold:
    def test_xauusd_buy_with_refuge_activated_gets_strong_boost(self):
        ctx = _make_ctx(
            vix_level=VixLevel.ELEVATED,
            vix_value=22.0,
            dxy=MacroDirection.DOWN,
            us10y=MacroDirection.DOWN,
        )
        mult, _, _ = apply("XAU/USD", "buy", ctx)
        assert mult >= 1.1


class TestEURSpread:
    def test_eurusd_buy_with_spread_narrowing_adds_to_alignment(self):
        ctx = _make_ctx(
            dxy=MacroDirection.NEUTRAL,
            spread_trend="narrowing",
        )
        mult, _, reasons = apply("EUR/USD", "buy", ctx)
        assert mult >= 1.0
        assert any("spread" in r.lower() or "eur" in r.lower() for r in reasons)


class TestNeutralNoEffect:
    def test_fully_neutral_context_gives_multiplier_1(self):
        ctx = _make_ctx()
        mult, veto, reasons = apply("EUR/USD", "buy", ctx)
        assert mult == 1.0
        assert veto is False
```

- [ ] **Step 2: Run to verify failure**

Run:
```bash
python -m pytest backend/tests/test_macro_scoring.py -v
```

Expected: `ModuleNotFoundError: No module named 'backend.services.macro_scoring'`

- [ ] **Step 3: Implement the scoring module**

Create `backend/services/macro_scoring.py`:

```python
"""Pure macro scoring — no I/O.

Given a trade setup (pair, direction) and a MacroContext snapshot, returns:
- a multiplier to apply to the base confidence score (0.75 ≤ mult ≤ 1.2)
- a boolean veto flag for extreme conditions
- a list of human-readable reasons (for logs and UI badges)

No state, no side effects. Fully table-driven via apply().
"""
from __future__ import annotations

from config.settings import MACRO_DXY_VETO_SIGMA
from backend.models.macro_schemas import (
    MacroContext,
    MacroDirection,
    RiskRegime,
    VixLevel,
)


# Classes a pair can belong to (non-exclusive; we sum primaries from all
# matching classes, deduplicating by indicator identity).
_USD_MAJOR = {"EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF"}
_USD_COMMODITY = {"USD/CAD"}
_COMMODITY_CURRENCY = {"AUD/USD", "NZD/USD"}
_JPY_PAIR = {"USD/JPY", "EUR/JPY", "GBP/JPY"}
_EUR_PAIR = {"EUR/USD", "EUR/GBP", "EUR/JPY", "EUR/CHF"}
_CHF_PAIR = {"USD/CHF", "EUR/CHF"}
_XAU = {"XAU/USD"}


def _dir_sign(d: MacroDirection) -> int:
    """Map a direction to a sign multiplier for alignment math."""
    if d in (MacroDirection.STRONG_UP, MacroDirection.UP):
        return 1
    if d in (MacroDirection.STRONG_DOWN, MacroDirection.DOWN):
        return -1
    return 0


def _setup_sign(direction: str) -> int:
    """'buy' => +1, 'sell' => -1. Case-insensitive."""
    return 1 if direction.lower() == "buy" else -1


def _pair_is_usd_long_on_buy(pair: str) -> int:
    """For USD pairs, how does a BUY relate to USD direction?

    - USD/XXX pairs: buy = long USD  (sign = +1)
    - XXX/USD pairs: buy = short USD (sign = -1)
    """
    base, _, quote = pair.partition("/")
    if base == "USD":
        return 1
    if quote == "USD":
        return -1
    return 0


def _primaries_for(pair: str, ctx: MacroContext, setup_sign: int) -> list[tuple[str, int, str]]:
    """Return list of (indicator_name, alignment_sign, reason) tuples.

    `alignment_sign` is +1 if macro supports the setup direction, -1 if
    against, 0 if neutral. The list is already deduplicated by indicator
    since each is evaluated at most once per pair.
    """
    result: list[tuple[str, int, str]] = []
    used: set[str] = set()

    pair_u = pair.upper()

    # USD exposure via DXY — applies to USD-major, USD-commodity, commodity-currency
    if pair_u in _USD_MAJOR or pair_u in _USD_COMMODITY or pair_u in _COMMODITY_CURRENCY:
        if "dxy" not in used:
            usd_long_on_buy = _pair_is_usd_long_on_buy(pair_u)
            # alignment = setup's USD-long direction × DXY direction
            setup_usd_sign = setup_sign * usd_long_on_buy  # +1 if setup wants strong USD
            align = setup_usd_sign * _dir_sign(ctx.dxy_direction)
            reason = f"DXY {ctx.dxy_direction.value}"
            result.append(("dxy", align, reason))
            used.add("dxy")

    # USD/CAD: Oil is primary (CAD strengthens with oil)
    if pair_u in _USD_COMMODITY:
        # For USD/CAD: buy means long USD short CAD. Oil up = CAD strong = against USD/CAD buy.
        # So align = -setup_sign × oil_sign
        if "oil" not in used:
            align = -setup_sign * _dir_sign(ctx.oil_direction)
            reason = f"Oil {ctx.oil_direction.value}"
            result.append(("oil", align, reason))
            used.add("oil")

    # Commodity currencies: SPX + Gold
    if pair_u in _COMMODITY_CURRENCY:
        # AUD/USD, NZD/USD: buy = long commodity currency. Risk-on (SPX up, Gold up) helps.
        # setup_sign (buy=+1) * spx_sign => +1 if aligned
        if "spx" not in used:
            align = setup_sign * _dir_sign(ctx.spx_direction)
            reason = f"SPX {ctx.spx_direction.value}"
            result.append(("spx", align, reason))
            used.add("spx")
        if "gold" not in used:
            align = setup_sign * _dir_sign(ctx.gold_direction)
            reason = f"Gold {ctx.gold_direction.value}"
            result.append(("gold", align, reason))
            used.add("gold")

    # JPY pairs: VIX + Nikkei (JPY strengthens in risk-off)
    if pair_u in _JPY_PAIR:
        # For XXX/JPY: buy = long XXX short JPY. Risk-off (VIX up, Nikkei down) = JPY strong = against XXX/JPY buy.
        # USD/JPY: same logic.
        # align = -setup_sign × vix_sign   (VIX up => risk-off => JPY strong => against buy)
        if "vix" not in used:
            vix_sign = 1 if ctx.vix_level in (VixLevel.ELEVATED, VixLevel.HIGH) else (
                -1 if ctx.vix_level == VixLevel.LOW else 0
            )
            align = -setup_sign * vix_sign
            reason = f"VIX {ctx.vix_level.value}"
            result.append(("vix", align, reason))
            used.add("vix")
        if "nikkei" not in used:
            align = setup_sign * _dir_sign(ctx.nikkei_direction)
            reason = f"Nikkei {ctx.nikkei_direction.value}"
            result.append(("nikkei", align, reason))
            used.add("nikkei")

    # EUR pairs: US-DE spread (widening = US yields fuir = EUR weak)
    if pair_u in _EUR_PAIR:
        if "us_de_spread" not in used:
            # For XXX/YYY where EUR is base: buy = long EUR. Spread narrowing = DE rattrape = EUR strong = aligned with buy.
            # Determine EUR position in the pair
            base, _, quote = pair_u.partition("/")
            eur_long_on_buy = 1 if base == "EUR" else (-1 if quote == "EUR" else 0)
            spread_sign = {"narrowing": 1, "flat": 0, "widening": -1}[ctx.us_de_spread_trend]
            align = setup_sign * eur_long_on_buy * spread_sign
            reason = f"Spread US-DE {ctx.us_de_spread_trend}"
            result.append(("us_de_spread", align, reason))
            used.add("us_de_spread")

    # CHF pairs: VIX secondary (refuge)
    if pair_u in _CHF_PAIR and "vix" not in used:
        # XXX/CHF: buy = long XXX short CHF. Risk-off = CHF strong = against buy.
        base, _, quote = pair_u.partition("/")
        chf_long_on_buy = 1 if base == "CHF" else (-1 if quote == "CHF" else 0)
        vix_sign = 1 if ctx.vix_level in (VixLevel.ELEVATED, VixLevel.HIGH) else (
            -1 if ctx.vix_level == VixLevel.LOW else 0
        )
        align = setup_sign * chf_long_on_buy * vix_sign
        reason = f"VIX {ctx.vix_level.value} (CHF refuge)"
        result.append(("vix", align, reason))
        used.add("vix")

    # XAU/USD: VIX + DXY + US10Y (refuge activated when all aligned)
    if pair_u in _XAU:
        if "vix" not in used:
            vix_sign = 1 if ctx.vix_level in (VixLevel.ELEVATED, VixLevel.HIGH) else (
                -1 if ctx.vix_level == VixLevel.LOW else 0
            )
            # Gold up with VIX up (risk-off): aligned with buy XAU
            align = setup_sign * vix_sign
            reason = f"VIX {ctx.vix_level.value} (refuge)"
            result.append(("vix", align, reason))
            used.add("vix")
        if "dxy" not in used:
            # Gold up with DXY down: aligned with buy XAU
            align = -setup_sign * _dir_sign(ctx.dxy_direction)
            reason = f"DXY {ctx.dxy_direction.value}"
            result.append(("dxy", align, reason))
            used.add("dxy")
        if "us10y" not in used:
            # Gold up with yields down: aligned with buy XAU
            align = -setup_sign * _dir_sign(ctx.us10y_trend)
            reason = f"US10Y {ctx.us10y_trend.value}"
            result.append(("us10y", align, reason))
            used.add("us10y")

    return result


def _multiplier_from_alignment(avg: float) -> float:
    """Map [-1, +1] alignment to a multiplier, per spec thresholds."""
    if avg >= 0.6:
        return 1.2
    if avg >= 0.2:
        return 1.1
    if avg > -0.2:
        return 1.0
    if avg > -0.6:
        return 0.9
    return 0.75


def _check_vetoes(pair: str, direction: str, ctx: MacroContext) -> list[str]:
    """Return veto reasons if any extreme condition is hit, else []."""
    reasons: list[str] = []
    setup_sign = _setup_sign(direction)
    pair_u = pair.upper()

    # VETO 1: VIX above 30 AND setup aligned against risk_regime
    if ctx.vix_value > 30.0 and ctx.risk_regime == RiskRegime.RISK_OFF:
        # A buy on risk-on assets (AUD, NZD, commodity, equities) during panic = risky
        risk_on_asset = pair_u in _COMMODITY_CURRENCY or pair_u in _JPY_PAIR
        if pair_u in _COMMODITY_CURRENCY and setup_sign == 1:
            reasons.append(f"VIX={ctx.vix_value:.1f}>30 and risk_off, against commodity currency buy")
        elif pair_u in _JPY_PAIR and setup_sign == 1 and pair_u.startswith(("USD", "EUR", "GBP")):
            reasons.append(f"VIX={ctx.vix_value:.1f}>30 and risk_off, against XXX/JPY buy")

    # VETO 2: DXY intraday move > N sigma AND setup against DXY direction
    if ctx.dxy_intraday_sigma >= MACRO_DXY_VETO_SIGMA:
        usd_long_on_buy = _pair_is_usd_long_on_buy(pair_u)
        if usd_long_on_buy != 0:
            setup_usd_sign = setup_sign * usd_long_on_buy
            dxy_sign = _dir_sign(ctx.dxy_direction)
            if setup_usd_sign * dxy_sign < 0:
                reasons.append(
                    f"DXY intraday moved {ctx.dxy_intraday_sigma:.1f}σ {ctx.dxy_direction.value}, "
                    f"setup against"
                )

    return reasons


def apply(pair: str, direction: str, ctx: MacroContext) -> tuple[float, bool, list[str]]:
    """Compute (multiplier, veto, reasons) for a setup given a snapshot.

    - pair: e.g. "EUR/USD"
    - direction: "buy" or "sell"
    - ctx: a MacroContext
    """
    setup_sign = _setup_sign(direction)
    primaries = _primaries_for(pair, ctx, setup_sign)
    reasons = [r for _, _, r in primaries]

    if not primaries:
        # Pair not covered by any class — neutral fallback
        return 1.0, False, []

    avg = sum(align for _, align, _ in primaries) / len(primaries)
    multiplier = _multiplier_from_alignment(avg)

    veto_reasons = _check_vetoes(pair, direction, ctx)
    veto = len(veto_reasons) > 0
    if veto:
        reasons.extend(veto_reasons)

    return multiplier, veto, reasons
```

- [ ] **Step 4: Run to verify all tests pass**

Run:
```bash
python -m pytest backend/tests/test_macro_scoring.py -v
```

Expected: all tests pass.

If a test fails, read the failure, inspect the logic in `_primaries_for` or `_check_vetoes`, adjust until green. Do not change the test assertions without re-validating against the spec.

- [ ] **Step 5: Commit**

```bash
git add backend/services/macro_scoring.py backend/tests/test_macro_scoring.py
git commit -m "feat(macro): pure scoring module with multiplier + veto logic"
```

---

## Task 5: Macro context service (fetcher + cache)

**Files:**
- Create: `backend/services/macro_context_service.py`
- Create: `backend/tests/test_macro_context_service.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_macro_context_service.py`:

```python
"""Tests for macro_context_service: fetch, cache, stale fallback."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from backend.models.macro_schemas import MacroContext, MacroDirection, VixLevel, RiskRegime
from backend.services import macro_context_service as svc


@pytest.fixture(autouse=True)
def reset_cache():
    """Ensure each test starts with a clean cache."""
    svc._cache_snapshot = None
    yield
    svc._cache_snapshot = None


def _fake_candles(values: list[float]) -> list[dict]:
    """Mock Twelve Data time_series response shape."""
    return [{"close": str(v)} for v in values]


class TestZScoreComputation:
    def test_zscore_zero_when_price_equals_mean(self):
        closes = [100.0] * 20
        assert svc._compute_zscore(100.0, closes) == 0.0

    def test_zscore_positive_when_price_above_mean(self):
        closes = [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0,
                  101.0, 101.0, 101.0, 101.0, 101.0, 101.0, 101.0, 101.0, 101.0, 101.0]
        z = svc._compute_zscore(102.0, closes)
        assert z > 0

    def test_zscore_zero_when_series_is_flat(self):
        # stddev=0 — should return 0 instead of dividing by zero
        closes = [50.0] * 20
        assert svc._compute_zscore(55.0, closes) == 0.0


class TestRiskRegimeDerivation:
    def test_risk_off_when_vix_high_and_spx_down(self):
        regime = svc._derive_risk_regime(VixLevel.ELEVATED, MacroDirection.DOWN)
        assert regime == RiskRegime.RISK_OFF

    def test_risk_on_when_vix_low_and_spx_up(self):
        regime = svc._derive_risk_regime(VixLevel.LOW, MacroDirection.UP)
        assert regime == RiskRegime.RISK_ON

    def test_neutral_otherwise(self):
        regime = svc._derive_risk_regime(VixLevel.NORMAL, MacroDirection.NEUTRAL)
        assert regime == RiskRegime.NEUTRAL


class TestCache:
    def test_get_returns_none_before_first_fetch(self):
        assert svc.get_macro_snapshot() is None

    def test_get_returns_cached_after_set(self):
        ctx = MacroContext(
            fetched_at=datetime.now(timezone.utc),
            dxy_direction=MacroDirection.UP,
            spx_direction=MacroDirection.NEUTRAL,
            vix_level=VixLevel.NORMAL,
            vix_value=17.0,
            us10y_trend=MacroDirection.NEUTRAL,
            de10y_trend=MacroDirection.NEUTRAL,
            us_de_spread_trend="flat",
            oil_direction=MacroDirection.NEUTRAL,
            nikkei_direction=MacroDirection.NEUTRAL,
            gold_direction=MacroDirection.NEUTRAL,
            risk_regime=RiskRegime.NEUTRAL,
            raw_values={},
        )
        svc._cache_snapshot = ctx
        assert svc.get_macro_snapshot() is ctx

    def test_is_fresh_returns_false_when_older_than_max_age(self):
        old = datetime.now(timezone.utc) - timedelta(hours=3)
        assert svc.is_fresh(old) is False

    def test_is_fresh_returns_true_when_recent(self):
        recent = datetime.now(timezone.utc) - timedelta(minutes=30)
        assert svc.is_fresh(recent) is True


class TestRefreshFromMockedTwelveData:
    @pytest.mark.asyncio
    async def test_refresh_populates_cache_on_success(self):
        fake_candles = _fake_candles([100.0] * 19 + [102.0])
        with patch("backend.services.macro_context_service._fetch_candles_for_symbol",
                   new=AsyncMock(return_value=fake_candles)):
            ok = await svc.refresh_macro_context()
        assert ok is True
        assert svc.get_macro_snapshot() is not None

    @pytest.mark.asyncio
    async def test_refresh_returns_false_when_all_symbols_fail(self):
        with patch("backend.services.macro_context_service._fetch_candles_for_symbol",
                   new=AsyncMock(return_value=[])):
            ok = await svc.refresh_macro_context()
        assert ok is False

    @pytest.mark.asyncio
    async def test_refresh_preserves_existing_cache_on_failure(self):
        # Pre-populate cache
        existing = MacroContext(
            fetched_at=datetime.now(timezone.utc) - timedelta(minutes=30),
            dxy_direction=MacroDirection.UP,
            spx_direction=MacroDirection.NEUTRAL,
            vix_level=VixLevel.NORMAL,
            vix_value=17.0,
            us10y_trend=MacroDirection.NEUTRAL,
            de10y_trend=MacroDirection.NEUTRAL,
            us_de_spread_trend="flat",
            oil_direction=MacroDirection.NEUTRAL,
            nikkei_direction=MacroDirection.NEUTRAL,
            gold_direction=MacroDirection.NEUTRAL,
            risk_regime=RiskRegime.NEUTRAL,
            raw_values={},
        )
        svc._cache_snapshot = existing

        with patch("backend.services.macro_context_service._fetch_candles_for_symbol",
                   new=AsyncMock(return_value=[])):
            await svc.refresh_macro_context()

        # Cache unchanged
        assert svc.get_macro_snapshot() is existing
```

- [ ] **Step 2: Run to verify failure**

Run:
```bash
python -m pytest backend/tests/test_macro_context_service.py -v
```

Expected: `ModuleNotFoundError: No module named 'backend.services.macro_context_service'`

- [ ] **Step 3: Implement the service**

Create `backend/services/macro_context_service.py`:

```python
"""Fetches macro indicators from Twelve Data and caches the latest snapshot.

- `refresh_macro_context()` is called periodically by the scheduler.
- `get_macro_snapshot()` is called synchronously from enrich_trade_setup().
- `is_fresh(dt)` returns True if `dt` is within MACRO_CACHE_MAX_AGE_SEC.
- If all fetches fail, the previous cached snapshot is kept.
"""
from __future__ import annotations

import asyncio
import logging
import statistics
from datetime import datetime, timezone
from typing import Optional

import httpx

from config.settings import (
    MACRO_CACHE_MAX_AGE_SEC,
    MACRO_SCORING_ENABLED,
    MACRO_SYMBOL_DE10Y,
    MACRO_SYMBOL_DXY,
    MACRO_SYMBOL_GOLD,
    MACRO_SYMBOL_NIKKEI,
    MACRO_SYMBOL_OIL,
    MACRO_SYMBOL_SPX,
    MACRO_SYMBOL_US10Y,
    MACRO_SYMBOL_VIX,
    TWELVEDATA_API_KEY,
)
from backend.models.macro_schemas import (
    MacroContext,
    MacroDirection,
    RiskRegime,
    VixLevel,
    direction_from_zscore,
    vix_level_from_value,
)

logger = logging.getLogger(__name__)

_TWELVEDATA_BASE = "https://api.twelvedata.com"
_cache_snapshot: Optional[MacroContext] = None


async def _fetch_candles_for_symbol(symbol: str, outputsize: int = 21) -> list[dict]:
    """Fetch daily closes for a single symbol. Returns [] on any failure."""
    if not TWELVEDATA_API_KEY:
        return []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"{_TWELVEDATA_BASE}/time_series",
                params={
                    "symbol": symbol,
                    "interval": "1day",
                    "outputsize": outputsize,
                    "apikey": TWELVEDATA_API_KEY,
                },
            )
        if r.status_code != 200:
            logger.warning(f"macro: {symbol} HTTP {r.status_code}")
            return []
        data = r.json()
        values = data.get("values", [])
        return values
    except Exception as e:
        logger.warning(f"macro: {symbol} fetch error: {e}")
        return []


def _compute_zscore(current: float, closes: list[float]) -> float:
    """Z-score of `current` vs the mean/stddev of `closes` (20-day window)."""
    if not closes:
        return 0.0
    mean = statistics.fmean(closes)
    if len(closes) < 2:
        return 0.0
    try:
        stddev = statistics.pstdev(closes)
    except statistics.StatisticsError:
        return 0.0
    if stddev == 0:
        return 0.0
    return (current - mean) / stddev


def _extract_last_and_series(candles: list[dict]) -> tuple[Optional[float], list[float]]:
    """From Twelve Data response (newest first), extract current spot + series of 20 prior closes."""
    if not candles:
        return None, []
    try:
        floats = [float(c["close"]) for c in candles]
    except (ValueError, KeyError):
        return None, []
    current = floats[0]
    prior = floats[1:21]  # 20 days
    return current, prior


def _derive_risk_regime(vix_level: VixLevel, spx_dir: MacroDirection) -> RiskRegime:
    if vix_level in (VixLevel.ELEVATED, VixLevel.HIGH) and spx_dir in (
        MacroDirection.DOWN,
        MacroDirection.STRONG_DOWN,
    ):
        return RiskRegime.RISK_OFF
    if vix_level == VixLevel.LOW and spx_dir in (MacroDirection.UP, MacroDirection.STRONG_UP):
        return RiskRegime.RISK_ON
    return RiskRegime.NEUTRAL


def _spread_trend(us_z: float, de_z: float) -> str:
    diff = us_z - de_z
    if diff > 0.5:
        return "widening"
    if diff < -0.5:
        return "narrowing"
    return "flat"


async def refresh_macro_context() -> bool:
    """Fetch all 8 symbols and rebuild the cached snapshot.

    Returns True if a fresh snapshot was built, False otherwise.
    On any total failure, the previous cached snapshot is preserved.
    """
    global _cache_snapshot

    if not MACRO_SCORING_ENABLED:
        return False

    symbols = {
        "dxy": MACRO_SYMBOL_DXY,
        "spx": MACRO_SYMBOL_SPX,
        "vix": MACRO_SYMBOL_VIX,
        "us10y": MACRO_SYMBOL_US10Y,
        "de10y": MACRO_SYMBOL_DE10Y,
        "oil": MACRO_SYMBOL_OIL,
        "nikkei": MACRO_SYMBOL_NIKKEI,
        "gold": MACRO_SYMBOL_GOLD,
    }

    # Fetch all in parallel
    tasks = {k: _fetch_candles_for_symbol(sym) for k, sym in symbols.items()}
    results = await asyncio.gather(*tasks.values(), return_exceptions=False)
    raw = dict(zip(tasks.keys(), results))

    # Compute current + series for each
    spot: dict[str, float] = {}
    zscore: dict[str, float] = {}
    for k, candles in raw.items():
        current, prior = _extract_last_and_series(candles)
        if current is None:
            continue
        spot[k] = current
        zscore[k] = _compute_zscore(current, prior)

    # If we got nothing usable, preserve existing cache
    if not spot:
        logger.warning("macro: refresh failed — no symbols returned data, keeping previous cache")
        return False

    # If any critical symbol missing, log it but proceed with neutral for that one
    def _dir(key: str) -> MacroDirection:
        return direction_from_zscore(zscore.get(key, 0.0))

    vix_value = spot.get("vix", 17.0)
    vix_level = vix_level_from_value(vix_value)
    spx_dir = _dir("spx")

    snapshot = MacroContext(
        fetched_at=datetime.now(timezone.utc),
        dxy_direction=_dir("dxy"),
        spx_direction=spx_dir,
        vix_level=vix_level,
        vix_value=vix_value,
        us10y_trend=_dir("us10y"),
        de10y_trend=_dir("de10y"),
        us_de_spread_trend=_spread_trend(zscore.get("us10y", 0.0), zscore.get("de10y", 0.0)),
        oil_direction=_dir("oil"),
        nikkei_direction=_dir("nikkei"),
        gold_direction=_dir("gold"),
        risk_regime=_derive_risk_regime(vix_level, spx_dir),
        raw_values=spot,
        dxy_intraday_sigma=0.0,  # computed elsewhere if needed
    )

    _cache_snapshot = snapshot
    logger.info(
        f"macro: refreshed — dxy={snapshot.dxy_direction.value} "
        f"spx={snapshot.spx_direction.value} vix={vix_value:.1f}({vix_level.value}) "
        f"risk={snapshot.risk_regime.value}"
    )
    return True


def get_macro_snapshot() -> Optional[MacroContext]:
    """Return the currently cached snapshot, or None if none exists."""
    return _cache_snapshot


def is_fresh(fetched_at: datetime) -> bool:
    """True if fetched_at is within MACRO_CACHE_MAX_AGE_SEC."""
    age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
    return age <= MACRO_CACHE_MAX_AGE_SEC
```

- [ ] **Step 4: Run to verify tests pass**

Run:
```bash
python -m pytest backend/tests/test_macro_context_service.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/services/macro_context_service.py backend/tests/test_macro_context_service.py
git commit -m "feat(macro): fetcher service with Twelve Data + in-memory cache"
```

---

## Task 6: Scheduler integration

**Files:**
- Modify: `backend/services/scheduler.py`

- [ ] **Step 1: Add the refresh job registration**

Find the block in `backend/services/scheduler.py` where `sync_from_bridge` is registered (search for `id="mt5_sync"`). Add a new `add_job` call immediately after it, following the same pattern:

```python
from backend.services.macro_context_service import refresh_macro_context
from config.settings import MACRO_REFRESH_INTERVAL_SEC, MACRO_SCORING_ENABLED

# ... inside start_scheduler(), after the mt5_sync job registration:

if MACRO_SCORING_ENABLED:
    _scheduler.add_job(
        refresh_macro_context,
        "interval",
        seconds=MACRO_REFRESH_INTERVAL_SEC,
        id="macro_context_refresh",
        name="Refresh macro context snapshot",
        replace_existing=True,
    )
    logger.info(f"macro: refresh job scheduled every {MACRO_REFRESH_INTERVAL_SEC}s")
```

Place the `import` at the top of the file in the existing imports block (grouped with other `backend.services` imports).

- [ ] **Step 2: Verify the file still parses**

Run:
```bash
python -c "from backend.services.scheduler import start_scheduler; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Run all tests**

```bash
python -m pytest backend/tests/ -v
```

Expected: all previous tests still pass (no regression).

- [ ] **Step 4: Commit**

```bash
git add backend/services/scheduler.py
git commit -m "feat(macro): register 15-min refresh job in scheduler"
```

---

## Task 7: Inject macro scoring into enrich_trade_setup

**Files:**
- Modify: `backend/models/schemas.py`
- Modify: `backend/services/analysis_engine.py`
- Create: `backend/tests/test_analysis_engine_macro.py`

- [ ] **Step 1: Extend `ConfidenceFactor` with an optional source field**

In `backend/models/schemas.py`, locate the `ConfidenceFactor` class (around lines 108–112) and add a `source` field with default `None`:

```python
class ConfidenceFactor(BaseModel):
    name: str
    score: float
    detail: str
    positive: bool
    source: str | None = None  # "pattern" | "macro" | etc. — optional tag for UI/log
```

- [ ] **Step 2: Write the integration tests first**

Create `backend/tests/test_analysis_engine_macro.py`:

```python
"""Integration-level tests: enrich_trade_setup applies macro scoring correctly."""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from backend.models.macro_schemas import (
    MacroContext,
    MacroDirection,
    RiskRegime,
    VixLevel,
)
from backend.models.schemas import (
    PatternDetection,
    TradeDirection,
    TradeSetup,
)
from backend.services.analysis_engine import enrich_trade_setup


def _neutral_ctx() -> MacroContext:
    return MacroContext(
        fetched_at=datetime.now(timezone.utc),
        dxy_direction=MacroDirection.NEUTRAL,
        spx_direction=MacroDirection.NEUTRAL,
        vix_level=VixLevel.NORMAL,
        vix_value=17.0,
        us10y_trend=MacroDirection.NEUTRAL,
        de10y_trend=MacroDirection.NEUTRAL,
        us_de_spread_trend="flat",
        oil_direction=MacroDirection.NEUTRAL,
        nikkei_direction=MacroDirection.NEUTRAL,
        gold_direction=MacroDirection.NEUTRAL,
        risk_regime=RiskRegime.NEUTRAL,
        raw_values={},
    )


def _dxy_against_ctx() -> MacroContext:
    ctx = _neutral_ctx()
    ctx.dxy_direction = MacroDirection.STRONG_UP
    return ctx


def _basic_setup(pair="EUR/USD", direction=TradeDirection.BUY) -> TradeSetup:
    return TradeSetup(
        pair=pair,
        direction=direction,
        pattern=PatternDetection(
            name="test_pattern",
            confidence=0.8,
            detected_at=datetime.now(timezone.utc),
        ),
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit_1=1.1050,
        take_profit_2=1.1100,
        risk_pips=50.0,
        reward_pips_1=50.0,
        reward_pips_2=100.0,
        risk_reward_1=1.0,
        risk_reward_2=2.0,
        message="test",
        timestamp=datetime.now(timezone.utc),
    )


class TestFeatureFlagOff:
    def test_no_macro_factor_added_when_flag_off(self):
        with patch("backend.services.analysis_engine.MACRO_SCORING_ENABLED", False):
            with patch(
                "backend.services.macro_context_service.get_macro_snapshot",
                return_value=_neutral_ctx(),
            ):
                setup = _basic_setup()
                enriched = enrich_trade_setup(setup, {}, [], 10000.0, 1.0)

        macro_factors = [f for f in enriched.confidence_factors if f.source == "macro"]
        assert macro_factors == []


class TestFeatureFlagOn:
    def test_macro_factor_added_when_flag_on(self):
        with patch("backend.services.analysis_engine.MACRO_SCORING_ENABLED", True):
            with patch(
                "backend.services.macro_context_service.get_macro_snapshot",
                return_value=_dxy_against_ctx(),
            ):
                setup = _basic_setup(pair="EUR/USD", direction=TradeDirection.BUY)
                enriched = enrich_trade_setup(setup, {}, [], 10000.0, 1.0)

        macro_factors = [f for f in enriched.confidence_factors if f.source == "macro"]
        assert len(macro_factors) == 1
        # EUR/USD buy against DXY strong_up => multiplier 0.75 => negative factor
        assert macro_factors[0].positive is False

    def test_stale_cache_falls_back_to_neutral(self):
        stale_ctx = _dxy_against_ctx()
        stale_ctx.fetched_at = datetime.now(timezone.utc).replace(year=2020)

        with patch("backend.services.analysis_engine.MACRO_SCORING_ENABLED", True):
            with patch(
                "backend.services.macro_context_service.get_macro_snapshot",
                return_value=stale_ctx,
            ):
                setup = _basic_setup()
                enriched = enrich_trade_setup(setup, {}, [], 10000.0, 1.0)

        # Stale => no macro factor should be applied (neutral mode)
        macro_factors = [f for f in enriched.confidence_factors if f.source == "macro"]
        assert macro_factors == []
```

- [ ] **Step 3: Run to verify failure**

Run:
```bash
python -m pytest backend/tests/test_analysis_engine_macro.py -v
```

Expected: tests fail (either import errors or assertion failures because macro is not yet applied).

- [ ] **Step 4: Modify `enrich_trade_setup()` to apply macro scoring**

In `backend/services/analysis_engine.py`:

4a. Add imports at the top (grouped with other `backend.services` / `config` imports):

```python
from config.settings import MACRO_SCORING_ENABLED, MACRO_VETO_ENABLED
from backend.services import macro_context_service, macro_scoring
from backend.models.macro_schemas import MacroContext
```

4b. Locate the end of `enrich_trade_setup()` (around line 544, just after `setup.confidence_factors = factors` and before `return setup`). Insert the macro block:

```python
    # ── Macro context enrichment (Vague 1) ─────────────────────────────
    if MACRO_SCORING_ENABLED:
        snapshot: MacroContext | None = macro_context_service.get_macro_snapshot()
        if snapshot is not None and macro_context_service.is_fresh(snapshot.fetched_at):
            try:
                multiplier, veto, reasons = macro_scoring.apply(
                    setup.pair, setup.direction.value, snapshot
                )
                # Always add a factor for traceability, even at multiplier=1.0
                factor_score = round((multiplier - 1.0) * 100, 1)  # signed points
                factors.append(
                    ConfidenceFactor(
                        name="Contexte macro",
                        score=factor_score,
                        detail=f"×{multiplier:.2f} — " + (" | ".join(reasons) if reasons else "neutre"),
                        positive=multiplier >= 1.0,
                        source="macro",
                    )
                )
                # Apply multiplier to the already-computed total_score
                new_total = min(100, max(0, total_score * multiplier))
                setup.confidence_score = round(new_total, 1)
                setup.confidence_factors = factors

                if MACRO_VETO_ENABLED and veto:
                    setup.verdict_action = "SKIP"
                    blockers = list(setup.verdict_blockers or [])
                    blockers.extend([f"Macro veto: {r}" for r in reasons])
                    setup.verdict_blockers = blockers
                logger.info(
                    f"macro_applied pair={setup.pair} dir={setup.direction.value} "
                    f"base={round(total_score, 1)} mult={multiplier} "
                    f"final={setup.confidence_score} veto={veto}"
                )
            except Exception as e:
                logger.warning(f"macro scoring error: {e}")
        else:
            logger.debug("macro: snapshot stale or missing, neutral mode")
```

Note: place this block AFTER the existing `setup.confidence_factors = factors` and BEFORE `return setup`. It may need to be after the full enrichment block (explanation, suggested_amount, etc.) — put it right before the return.

- [ ] **Step 5: Run all tests**

```bash
python -m pytest backend/tests/ -v
```

Expected: all tests pass, including the new `test_analysis_engine_macro.py`.

- [ ] **Step 6: Commit**

```bash
git add backend/models/schemas.py backend/services/analysis_engine.py backend/tests/test_analysis_engine_macro.py
git commit -m "feat(macro): inject macro multiplier + veto into enrich_trade_setup"
```

---

## Task 8: Persist context_macro on trades

**Files:**
- Modify: `backend/services/trade_log_service.py`
- Modify: `backend/services/mt5_sync.py`
- Create: `backend/tests/test_trade_log_migration.py`

- [ ] **Step 1: Write migration test**

Create `backend/tests/test_trade_log_migration.py`:

```python
"""Verify that _init_schema() adds the context_macro column idempotently."""
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from backend.services import trade_log_service


def test_context_macro_column_added_on_fresh_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "test.db"
        with patch.object(trade_log_service, "_DB_PATH", db):
            trade_log_service._init_schema()
            cols = [r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(personal_trades)").fetchall()]
        assert "context_macro" in cols


def test_init_schema_is_idempotent():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "test.db"
        with patch.object(trade_log_service, "_DB_PATH", db):
            trade_log_service._init_schema()
            trade_log_service._init_schema()  # must not raise
            cols = [r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(personal_trades)").fetchall()]
        # column still exactly once
        assert cols.count("context_macro") == 1
```

- [ ] **Step 2: Run to verify failure**

Run:
```bash
python -m pytest backend/tests/test_trade_log_migration.py -v
```

Expected: `test_context_macro_column_added_on_fresh_db` fails (column not present yet).

- [ ] **Step 3: Add the migration**

In `backend/services/trade_log_service.py`, inside `_init_schema()`, add one line to the migration ladder (after `is_auto`):

```python
        if "context_macro" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN context_macro TEXT")
```

Place it between the `is_auto` check and the `CREATE INDEX` block.

- [ ] **Step 4: Run test to verify pass**

```bash
python -m pytest backend/tests/test_trade_log_migration.py -v
```

Expected: both tests pass.

- [ ] **Step 5: Persist the snapshot in record_trade**

In `backend/services/trade_log_service.py::record_trade()`, update the INSERT to include `context_macro`:

```python
def record_trade(data: dict, user: str = "anonymous") -> int:
    """Enregistre un trade pris par l'utilisateur `user`."""
    _init_schema()
    import json
    from backend.services import macro_context_service

    # Snapshot macro au moment de la prise du trade (pour analyse a posteriori)
    ctx_json = None
    snap = macro_context_service.get_macro_snapshot()
    if snap is not None and macro_context_service.is_fresh(snap.fetched_at):
        ctx_json = json.dumps({
            "dxy": snap.dxy_direction.value,
            "spx": snap.spx_direction.value,
            "vix_level": snap.vix_level.value,
            "vix_value": snap.vix_value,
            "us_de_spread_trend": snap.us_de_spread_trend,
            "risk_regime": snap.risk_regime.value,
            "fetched_at": snap.fetched_at.isoformat(),
        })

    with _conn() as c:
        cur = c.execute(
            "INSERT INTO personal_trades "
            "(user, pair, direction, entry_price, stop_loss, take_profit, size_lot, "
            "signal_pattern, signal_confidence, checklist_passed, notes, created_at, "
            "post_entry_sl, post_entry_tp, post_entry_size, post_entry_alarm, context_macro) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user, data["pair"], data["direction"], float(data["entry_price"]),
                float(data["stop_loss"]), float(data["take_profit"]),
                float(data["size_lot"]),
                data.get("signal_pattern"),
                float(data["signal_confidence"]) if data.get("signal_confidence") else None,
                1 if data.get("checklist_passed") else 0,
                data.get("notes"),
                datetime.now(timezone.utc).isoformat(),
                1 if data.get("post_entry_sl") else 0,
                1 if data.get("post_entry_tp") else 0,
                1 if data.get("post_entry_size") else 0,
                1 if data.get("post_entry_alarm") else 0,
                ctx_json,
            ),
        )
        return cur.lastrowid
```

- [ ] **Step 6: Persist in mt5_sync upsert**

In `backend/services/mt5_sync.py::_upsert_open_trade()`, extend the INSERT to include `context_macro`:

6a. Add import at top: `import json` (if not present), and `from backend.services import macro_context_service`.

6b. Before the INSERT statement, compute `ctx_json` the same way as in `record_trade`:

```python
    ctx_json = None
    snap = macro_context_service.get_macro_snapshot()
    if snap is not None and macro_context_service.is_fresh(snap.fetched_at):
        ctx_json = json.dumps({
            "dxy": snap.dxy_direction.value,
            "spx": snap.spx_direction.value,
            "vix_level": snap.vix_level.value,
            "vix_value": snap.vix_value,
            "risk_regime": snap.risk_regime.value,
            "fetched_at": snap.fetched_at.isoformat(),
        })
```

6c. Extend the INSERT column list and VALUES to include `context_macro`:

```python
        c.execute("""
            INSERT OR IGNORE INTO personal_trades (
                user, pair, direction, entry_price, stop_loss, take_profit,
                size_lot, signal_pattern, signal_confidence, checklist_passed,
                notes, status, created_at, mt5_ticket, is_auto,
                post_entry_sl, post_entry_tp, post_entry_size, context_macro
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, 1, ?, 'OPEN', ?, ?, 1, 1, 1, 1, ?)
        """, (
            user,
            row.get("pair") or row.get("symbol") or "?",
            (row.get("direction") or "").lower(),
            row.get("entry") or 0,
            row.get("sl") or 0,
            row.get("tp") or 0,
            row.get("lots") or 0.01,
            row.get("risk_money"),
            f"Auto-exec via bridge MT5 (ticket #{ticket}, comment: {row.get('client_comment', '')})",
            row.get("created_at") or datetime.now(timezone.utc).isoformat(),
            ticket,
            ctx_json,
        ))
```

- [ ] **Step 7: Run all tests**

```bash
python -m pytest backend/tests/ -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add backend/services/trade_log_service.py backend/services/mt5_sync.py backend/tests/test_trade_log_migration.py
git commit -m "feat(macro): persist macro snapshot on trade record + MT5 auto-sync"
```

---

## Task 9: Debug endpoint /debug/macro

**Files:**
- Modify: `backend/app.py`

- [ ] **Step 1: Add the endpoint**

In `backend/app.py`, find the auth/routing section and add a new route. Place it next to existing admin routes:

```python
from backend.services.macro_context_service import get_macro_snapshot, is_fresh as macro_is_fresh
from datetime import datetime, timezone


@app.get("/debug/macro")
async def debug_macro(request: Request):
    """Admin-only debug view of the cached macro snapshot."""
    # Use existing authenticate() helper if present; otherwise the root auth guard covers this.
    user = authenticate(request)  # existing function
    if not user:
        raise HTTPException(status_code=401)

    snap = get_macro_snapshot()
    if snap is None:
        return {"status": "no_snapshot_yet", "snapshot": None}

    age_sec = (datetime.now(timezone.utc) - snap.fetched_at).total_seconds()
    return {
        "status": "ok",
        "fresh": macro_is_fresh(snap.fetched_at),
        "age_seconds": round(age_sec, 1),
        "snapshot": {
            "fetched_at": snap.fetched_at.isoformat(),
            "dxy": snap.dxy_direction.value,
            "spx": snap.spx_direction.value,
            "vix_level": snap.vix_level.value,
            "vix_value": snap.vix_value,
            "us10y": snap.us10y_trend.value,
            "de10y": snap.de10y_trend.value,
            "us_de_spread_trend": snap.us_de_spread_trend,
            "oil": snap.oil_direction.value,
            "nikkei": snap.nikkei_direction.value,
            "gold": snap.gold_direction.value,
            "risk_regime": snap.risk_regime.value,
            "raw_values": snap.raw_values,
        },
    }
```

- [ ] **Step 2: Smoke-test the route registration**

Run:
```bash
python -c "from backend.app import app; print([r.path for r in app.routes if 'debug' in r.path])"
```

Expected: `['/debug/macro']` (or includes it)

- [ ] **Step 3: Commit**

```bash
git add backend/app.py
git commit -m "feat(macro): add /debug/macro admin endpoint"
```

---

## Task 10: Frontend macro badge on setup cards

**Files:**
- Modify: `frontend/js/app.js`

- [ ] **Step 1: Locate `tradeSetupHTML(s)`**

Search for `tradeSetupHTML` in `frontend/js/app.js` (around line 1090). The function receives a setup object `s` and returns HTML.

- [ ] **Step 2: Add the macro badge rendering**

In `tradeSetupHTML(s)`, after the existing `simBadge` definition (around line 1100–1103), add:

```javascript
const macroFactor = (s.confidence_factors || []).find(f => f.source === 'macro');
const macroBadge = macroFactor
    ? `<span class="data-badge macro ${macroFactor.positive ? 'macro-pos' : 'macro-neg'}" title="${macroFactor.detail}">${macroFactor.detail.split(' — ')[0]}</span>`
    : '';
```

Then include `${macroBadge}` in the returned template string, in the same row as `simBadge`.

- [ ] **Step 3: Add CSS for the badge**

Find the CSS file used for setup cards (search for `.data-badge` to locate it). Append:

```css
.data-badge.macro {
    background: rgba(100, 100, 150, 0.2);
    border: 1px solid rgba(100, 100, 150, 0.4);
    color: #aab;
}
.data-badge.macro.macro-pos {
    background: rgba(50, 160, 80, 0.2);
    border-color: rgba(50, 160, 80, 0.4);
    color: #9c9;
}
.data-badge.macro.macro-neg {
    background: rgba(200, 80, 80, 0.2);
    border-color: rgba(200, 80, 80, 0.4);
    color: #e99;
}
```

- [ ] **Step 4: Manual verification**

- Start dev server: `python main.py`
- Open http://localhost:8000, log in
- Wait for a setup to be detected (or inject fake one via dev console)
- Verify badge appears next to `simBadge` with macro text

- [ ] **Step 5: Commit**

```bash
git add frontend/js/app.js frontend/css/
git commit -m "feat(macro): display macro multiplier badge on setup cards"
```

---

## Task 11: Rollout documentation

**Files:**
- Modify: `.env.example` (completed in Task 2)
- Modify: `DEPLOY.md` or create `docs/macro-rollout.md`

- [ ] **Step 1: Document the rollout phases**

Create `docs/macro-rollout.md`:

```markdown
# Macro Context Scoring — Rollout Guide

## Phase 1 — Shadow mode (no impact)

Set in `.env`:

```
MACRO_SCORING_ENABLED=false
MACRO_VETO_ENABLED=false
```

The refresh job does not run (because `MACRO_SCORING_ENABLED=false`), and no scoring adjustment is applied.

**To enter shadow observation:** set `MACRO_SCORING_ENABLED=true` but keep `MACRO_VETO_ENABLED=false`. The multiplier is applied to `confidence_score`; vetos are not.

Inspect via `GET /debug/macro` (admin auth) and scheduler logs:
```
macro: refreshed — dxy=up spx=neutral vix=17.3(normal) risk=neutral
macro_applied pair=EUR/USD dir=buy base=72 mult=0.9 final=64.8 veto=false
```

## Phase 2 — Multiplier live, veto off (3–5 days)

Observe divergences between setups that would previously have fired vs the adjusted score. Validate against intuition.

## Phase 3 — Full activation

```
MACRO_SCORING_ENABLED=true
MACRO_VETO_ENABLED=true
```

## Kill switch

At any time, set `MACRO_SCORING_ENABLED=false` and restart the service. The refresh job stops, `enrich_trade_setup` skips the block, behavior reverts to pre-macro baseline.

## Inspecting the database

```sql
SELECT id, pair, direction, confidence_score, context_macro
FROM personal_trades
WHERE context_macro IS NOT NULL
ORDER BY id DESC
LIMIT 20;
```
```

- [ ] **Step 2: Commit**

```bash
git add docs/macro-rollout.md
git commit -m "docs(macro): rollout phases + kill switch + inspection queries"
```

---

## Final validation

- [ ] **Run the full test suite**

```bash
python -m pytest backend/tests/ -v
```

Expected: all tests pass.

- [ ] **Smoke-check startup with flag off**

```bash
python main.py
```

Expected: no errors, server starts, no macro refresh log.

- [ ] **Smoke-check startup with flag on (local, with a valid Twelve Data key)**

Set `MACRO_SCORING_ENABLED=true` in `.env`, restart. Check logs contain `macro: refreshed`.

- [ ] **Verify `/debug/macro` returns payload**

```bash
curl -H "Cookie: <admin session>" http://localhost:8000/debug/macro
```

- [ ] **Final commit / merge**

```bash
git log --oneline -15
```

All 11 feature commits should be visible. No placeholder branches left.

---

## Deferred / out of scope (Vagues 2-3)

- Retail sentiment (Myfxbook / OANDA order book) — separate spec
- News sentiment (Finnhub / Alpha Vantage) — separate spec
- ML model trained on `context_macro` history — requires ≥200 trades first
- Frontend macro dashboard panel (beyond per-card badge) — v1 has badge only
