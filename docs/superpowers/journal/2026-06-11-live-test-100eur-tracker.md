# Live Test 100€ — Tracker

**Démarrage prévu** : dès réception credentials IC Markets (KYC + funding en cours)
**Capital initial** : 100 EUR
**Broker** : IC Markets EU Razor Live (Cyprus CySEC)
**Compte MT5 Live** : login `<à renseigner>`, server `<à renseigner>` (probable `ICMarketsEU-Live01`)
**Bridge Live** : VPS Stockholm `100.74.160.72:8788` (port dédié, parallèle au Demo Pepperstone 8787)
**Bridge Demo** (en parallèle, ne s'arrête pas) : VPS Stockholm `100.74.160.72:8787` Pepperstone Demo `62119130`

## Historique du pivot

- **2026-06-11** : tentative Live Pepperstone 14021961 — bloquée par AMF (compte MT4 only pour retail FR, MT5/Razor pas marketed)
- **2026-06-12** : pivot IC Markets EU Cyprus (CySEC) qui offre MT5 Razor aux retail FR avec NBP
- Pepperstone Demo continue à tourner sur port 8787, IC Markets Live sur port 8788

## Paramètres de sécurité (côté Live uniquement, Demo garde ses params)

| Param | Valeur Live | Demo (inchangé) | Note |
|---|---|---|---|
| TRADING_CAPITAL | 100 EUR | 3000 EUR | Param destinations-specific côté backend si implémenté V2 |
| RISK_PER_TRADE_PCT | 0.5 | 1.0 | Idem |
| DAILY_LOSS_LIMIT_PCT | 3 | 90 | 3€/jour Live = kill switch auto |
| MAX_OPEN_POSITIONS | 2 | 6 | Limite via bridge.py côté Live (port 8788) |
| MT5_BRIDGE_LIVE_MIN_CONFIDENCE | 75 | 70 | Plus strict que Demo |
| Stars-only Live | XAU/USD, WTI/USD | tout stars | exclure ETH (rafale historique) + XAG (auto-paused) |
| Hard floor Live | 50€ | n/a | kill total à -50% capital |

## Tracker trades

| # | Date UTC | Pair | Dir | Conf | Entry signal | Entry fill | Slip (pips) | SL | TP | Exit | PnL EUR | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |  |  |  |  |  |

## Cumulé

| Métrique | Valeur |
|---|---|
| Capital actuel | 100.00 EUR |
| PnL total | 0.00 EUR |
| Drawdown max | 0% |
| N trades clos | 0 |
| N WIN | 0 |
| N LOSS | 0 |
| Win rate | n/a |
| Slip moyen | n/a |
| Sharpe live (≥ N=30 closed) | n/a |

## Comparaison Demo vs Live (en temps réel grâce architecture parallèle)

Chaque setup généré → 2 entrées `mt5_pushes` (1 par destination admin_legacy/admin_live) → 2 fills indépendants. Comparaison directe possible :

- Fill price Live vs Demo (mesure du slippage broker IC Markets vs Pepperstone)
- Latence end-to-end : Demo bridge log vs Live bridge log
- PnL final par trade (Demo et Live indépendamment, broker spec différentes possibles)
- WR Live vs WR Demo sur même fenêtre temporelle (signaux identiques)
- Spread instantané : différence ask-bid au moment du fill

Query SQL pour comparaison rapide :
```sql
SELECT setup_id, pair, direction, destination_id, fill_price, latency_ms, profit
FROM mt5_pushes
WHERE date >= '2026-06-12'
ORDER BY setup_id, destination_id;
```

## Checkpoint hebdomadaire

| Date | Cap actuel | PnL 7j | n_trades | Note |
|---|---|---|---|---|
|  |  |  |  |  |

## Décisions

| Date | Décision | Raison |
|---|---|---|
| 2026-06-11 | Démarrage live 100€ | Amendement Phase 4 anticipée (cf memory `project_transition_plan_amendment_2026_06_11`) |
| 2026-06-11 | Choix broker initial Pepperstone | Cohérence Demo+Live (Pepperstone UK Razor) |
| 2026-06-12 | Pivot broker → IC Markets EU | Pepperstone bloqué par AMF (MT4 only retail FR). IC Markets EU offre MT5 Razor + NBP aux retail FR via CySEC (cf memory `project_pepperstone_amf_blocker_2026_06_12`) |
| 2026-06-12 | Architecture parallèle Demo+Live | Garde le bridge Demo Pepperstone port 8787 + ajoute Live IC Markets port 8788. Commit `c3593eb` patch `admin_live` 2e destination admin. Permet comparaison side-by-side en temps réel. |
