# Design — Consolidation `mtf_trader.py` paramétrique

## Contexte

À ce jour (après PR #38), l'archi multi-TF compte **9 pipelines séparés** :

| Pipeline | Timeframe | Fichier |
|---|---|---|
| scalp | 1min | `scalp_trader.py` |
| meanrev | 15min/1h | `meanrev_trader.py` |
| trader_m5 | 5min | `trader_m5.py` |
| trader_m30 | 30min | `trader_m30.py` |
| trader_h2 | 2h | `trader_h2.py` |
| trader_h4 | 4h | `trader_h4.py` |
| daily | 1d | `daily_trader.py` |
| weekly | 1w | `weekly_trader.py` |
| trader_mo | 1mo | `trader_mo.py` |

Les 7 pipelines "RSI/ATR" (scalp + 5 nouveaux + daily + weekly) partagent **~90% de leur code** : même structure `cycle()`/`check_exits()`/`recap()`, même détection de signal RSI/ATR, même routing MT5. Ce doc design propose de les consolider en un seul `mtf_trader.py` **paramétré par une config**, pour lever la dette de duplication.

Meanrev et scalp (en version "scalp réel" avec gestion de 15-30 trades/jour) ont des spécificités qui les gardent dehors de la consolidation initiale.

## Pourquoi consolider

- **Duplication** : ~5000 lignes identiques × 7 pipelines. Un bugfix (comme PR #32 sur `entry` dans `_mt5_submit_order`) doit être porté 7 fois.
- **Maintenance** : ajouter une feature (ex: le trailing stop de PR #41) demande 7 Edit identiques.
- **Observabilité** : chaque pipeline a son propre state file, son propre canal Telegram, ses propres jobs scheduler → éclatement des métriques.
- **Scaling horizontal** : ajouter une 11e TF (ex: 10min, 3h) = copier 700 lignes.

## Pourquoi NE PAS consolider (contre-arguments)

- **Mental model** : "1 fichier = 1 pipeline" est simple à lire.
- **Blast radius** : un bug dans le moteur générique casse les 7 pipelines d'un coup.
- **Chaque pipeline a ses specificités** (ex: `WEEKLY_TIME_STOP_DAYS` vs `M5_TIME_STOP_HOURS`).
- **Tuning indépendant** : certains params ne font sens que pour certaines TF.

## Proposition : moteur paramétrique

### Fichier unique `backend/services/mtf_trader.py`

Un moteur générique qui prend une **config déclarative** par instance :

```python
@dataclass
class MTFInstance:
    name: str                    # ex: "trader_m5"
    prefix: str                  # ex: "M5"
    timeframe: str               # ex: "5min" (passé à price_service.fetch_candles)
    universe: list[str]          # paires
    sl_atr_mult: float
    tp_r_mult: float
    risk_pct: float
    max_positions: int
    max_period_loss_eur: float
    time_stop_sec: int           # unifié en secondes
    reset_mode: Literal["daily", "weekly", "monthly"]
    friday_close: bool           # True pour intraday, False pour daily+
    scan_cron: str               # ex: "*/5 * * * *" ou "0 23 * * sun"
    check_exits_interval_sec: int
    recap_cron: str
    state_path: str
    bridge_url: str
    bridge_api_key: str
    account_is_demo: bool
    invert_direction: bool
    momentum_tp_r_mult: float
    # Trailing (depuis PR #41)
    trailing_enabled: bool
    trailing_activation_r: float
    trailing_distance_r: float
```

### Config déclarative dans `.env`

Pattern env var : `MTF_INSTANCES` = CSV de prefixes activés.

```
MTF_INSTANCES=M5,M30,H2,H4,DAILY,WEEKLY,MO
M5_TIMEFRAME=5min
M5_UNIVERSE=XAU/USD,EUR/USD,GBP/USD,USD/JPY
M5_SL_ATR_MULT=1.2
M5_TP_R_MULT=1.5
...
```

Au démarrage, `mtf_trader.load_instances()` scanne `MTF_INSTANCES`, lit les env vars par préfixe, et instancie la liste.

### API unique

```python
async def cycle(instance: MTFInstance) -> dict
async def check_exits(instance: MTFInstance) -> dict
async def period_recap(instance: MTFInstance) -> dict
async def friday_force_close(instance: MTFInstance) -> dict  # no-op si not instance.friday_close
```

### Scheduler

Un helper unique dans `scheduler.py` prend la liste des `MTFInstance` et enregistre les 3-4 jobs par instance :

```python
for instance in mtf_trader.load_instances():
    _register_mtf_instance(instance)  # ajoute cycle + check_exits + friday_close + recap
```

Remplace les 150+ lignes actuelles de scheduler.py qui instancient les 7 pipelines à la main.

## Plan de migration

Migration **non destructive** sur 3 PRs pour permettre l'observation et le rollback :

### PR N+1 : Moteur à côté des anciens pipelines

- Nouveau `mtf_trader.py` avec les fonctions `cycle/check_exits/recap`.
- Nouveau `MTF_INSTANCES_<PREFIX>=...` env vars pour config.
- Les 7 anciens pipelines **restent intouchés et actifs**.
- Le scheduler peut lancer les 2 en parallèle, mais par défaut `MTF_INSTANCES` est vide → 0 instance mtf lancée.
- Tests unitaires du moteur (signal detection, trailing, SL/TP, time stop, reset daily/weekly/monthly).

### PR N+2 : Observation en shadow

- Activer `MTF_INSTANCES=M5_SHADOW` avec `state_path=/app/data/mtf_m5_shadow_state.json`.
- Mode dry_run forcé.
- Compare pendant 1 semaine : est-ce que le moteur paramétrique génère les MÊMES signaux que `trader_m5.py` ? Métriques : count signaux/jour, dispersion RSI, TPs vs SLs.
- Script `scripts/compare_mtf_vs_legacy.py` qui diff les deux state files.

### PR N+3 : Migration définitive

- Si shadow montre équivalence parfaite, bascule : `MTF_INSTANCES=M5,M30,H2,H4,DAILY,WEEKLY,MO`.
- Désactive scheduler des anciens pipelines (`SCALP`/`M5`/etc. `_ENABLED=false`).
- Après 1 semaine stable en prod paramétrique, suppression des 7 fichiers legacy dans une PR dédiée.

## Points d'attention

### Reset daily/weekly/monthly

Chaque instance utilise `reset_mode`. Les 3 variantes existent déjà dans les fichiers actuels :
- `scalp/meanrev/m5/m30/h2/h4/daily` → `daily` (`YYYY-MM-DD`)
- `weekly` → `weekly` (`YYYY-Www`)
- `trader_mo` → `monthly` (`YYYY-MM`)

Le moteur doit gérer les 3 — déjà fait dans mon script `gen_traders.py` du jour.

### Friday force-close

Flag booléen `friday_close` sur chaque instance. Appel conditionnel du job.

### Scalp réel non consolidé

`scalp_trader.py` a des particularités (haute fréquence, gestion du `last_seen_price` enrichi, plus de verbose logging) qui pourraient casser si on les généralise. **Garder scalp séparé** dans la migration initiale ; consolider plus tard après validation sur les 6-7 autres.

### Meanrev non consolidé

Mean reversion = logique différente (pas de polling tick, VWAP target). **Hors scope** de cette consolidation. `meanrev_trader.py` garde sa vie.

## Décision à prendre

Trois options après lecture de ce doc :

1. **GO maintenant** : on commence PR N+1 cette semaine.
2. **GO après observation** : laisser les 9 pipelines tourner 2-3 semaines (task #30), identifier les 2-3 qui méritent de survivre, consolider seulement ceux-là. Évite de consolider du code qu'on va jeter.
3. **NO GO** : garder "1 fichier = 1 TF" est délibéré, la lisibilité vaut la duplication.

**Recommandation** : option 2. Consolider ce qui a survécu à l'épreuve du dry_run, pas tout aveuglément.
