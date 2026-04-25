#!/usr/bin/env bash
# Diag pourquoi le shadow log ne logue rien : appelle run_shadow_log à la main
# avec les bougies H1 fetchées en live, et affiche les détails par paire.

set -u
KEY="C:/Users/xav91/Scalping/scalping/scalping-key.pem"
HOST="ec2-user@100.103.107.75"

echo "=== full cycle logs (5 min, dernières lignes) ==="
ssh -o StrictHostKeyChecking=no -i "$KEY" "$HOST" "sudo journalctl -u scalping --since '5 minutes ago' --no-pager | tail -40"

echo
echo "=== diag direct shadow_log dans le container ==="
ssh -i "$KEY" "$HOST" "sudo docker exec scalping-radar python -c \"
import asyncio
from datetime import datetime, timezone
from backend.services.price_service import fetch_candles
from backend.services.shadow_v2_core_long import (
    run_shadow_log, SHADOW_PAIRS, PATTERNS_BY_PAIR, aggregate_to_h4,
)
from backend.services.pattern_detector import detect_patterns

async def main():
    h1 = {}
    for pair in SHADOW_PAIRS:
        try:
            candles, meta = await fetch_candles(pair, interval='1h', outputsize=200)
            h1[pair] = candles
            print(f'{pair}: fetched {len(candles)} H1 candles, last={candles[-1].timestamp if candles else None}')
        except Exception as e:
            print(f'{pair}: fetch FAILED: {e}')
            h1[pair] = []
    print()
    for pair in SHADOW_PAIRS:
        c1 = h1.get(pair, [])
        h4 = aggregate_to_h4(c1)
        patterns = detect_patterns(h4, pair) if len(h4) >= 30 else []
        pair_patterns = PATTERNS_BY_PAIR.get(pair, set())
        matching = [p for p in patterns if (p.pattern.value if hasattr(p.pattern,'value') else str(p.pattern)) in pair_patterns]
        last_bar = h4[-1].timestamp if h4 else None
        print(f'{pair}: H1={len(c1)} H4={len(h4)} last_h4={last_bar} patterns={len(patterns)} matching={len(matching)}')
        for p in patterns[-5:]:
            pn = p.pattern.value if hasattr(p.pattern,'value') else str(p.pattern)
            print(f'  - {pn} dir={getattr(p,\\\"direction\\\",\\\"?\\\")} bar={getattr(p,\\\"bar_timestamp\\\", \\\"?\\\")}')
    print()
    print('=== call run_shadow_log directly ===')
    counts = await run_shadow_log(h1, cycle_at=datetime.now(timezone.utc))
    print('counts:', counts)

asyncio.run(main())
\""
