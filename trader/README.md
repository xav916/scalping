# trader/ — données runtime de trader-skill

Dossier de travail du pack de skills `.claude/skills/trader-*` (fork MIT de
[Jakeschincariol/trader-skill](https://github.com/Jakeschincariol/trader-skill),
installé le 2026-11-10).

## Fichiers

- `config.json` **(committé)** — configuration partagée des skills : broker,
  mode paper/live, budget, garde-fous. Ne pas y mettre de clé API.
- `state/` **(ignoré via .gitignore)** — état runtime des skills (orders,
  décisions, lots fiscaux, portefeuille). Local uniquement, par défaut paper.

## Configuration broker — IBKR via connecteur Claude

`config.json` fixe `"broker": "ibkr"` et `"paper": true`. L'intégration
utilise le **connecteur Interactive Brokers déjà monté dans la session Claude**
(tools `mcp__Interactive_Brokers_IBKR__*`), pas le `ibkr-bridge/` local.

Les deux chemins coexistent et ne se marchent pas dessus :

| Chemin | Utilisé par | Auth | Approbation |
|---|---|---|---|
| **`.claude/skills/trader-*` → MCP IBKR** | Claude conversationnel (trader-skill) | Session Claude (connecteur IBKR) | Chaque ordre : yes chat → Allow once Claude → review final dans IBKR |
| **`ibkr-bridge/` (Flask local)** | Radar FastAPI automatique | `X-Bridge-Key` + Gateway IBKR | Sans humain — gates côté bridge (`IBKR_ALLOW_ORDERS`, `readonly`) |

En pratique, quand `/trader-broker` dit d'appeler `place_stock_order`
(API Alpaca du SKILL.md), **substituer** par
`mcp__Interactive_Brokers_IBKR__create_order_instruction` et surfacer
l'URL retournée à l'utilisateur pour validation finale dans IBKR.

Mapping des champs (ticket Alpaca → IBKR MCP) :

| Alpaca ticket | IBKR `create_order_instruction` |
|---|---|
| `symbol` | → résoudre via `search_contracts` pour obtenir `contract_id_ex` |
| `side` (`buy`/`sell`) | `side` (`BUY`/`SELL`, uppercase) |
| `qty` | `quantity` (whole shares conseillé : `fractional: false`) |
| `notional` | **non supporté** — convertir en quantité via prix spot |
| `type` (`market`/`limit`) | `order_type` (`MARKET`/`LIMIT`, uppercase) |
| `limit_price` | `limit_price` |
| `time_in_force` (`day`/`gtc`/…) | `time_in_force` (`DAY`/`GTC`/`OVT`/`OND`/`OPG`) |
| `stop_price` / bracket | **non supporté en un appel** — ordre séparé après fill |

## Skills retenus / écartés pour ce projet

Le pack trader-skill est US-stocks + Alpaca. Scalping Radar est forex +
métaux + indices + crypto. Le filtre ci-dessous reflète cette réalité.

### Utilisables tels quels

- `trader-broker` (routé IBKR via override ci-dessus)
- `trader-risk` (checks numériques, broker-agnostique)
- `trader-budget` (sizing, broker-agnostique)
- `trader-screener` (filtres, à alimenter avec nos propres rules)
- `trader-rebalance` (si un jour on ouvre un volet portefeuille)
- `trader-tax` (tracker de lots PnL — attention : règles wash sale US, pas
  FR ; utiliser comme suivi, déclaration fiscale faite à part)

### Doublons avec l'existant (ne pas utiliser)

- `trader-alerts` — redondant avec notifications Telegram
  (`TELEGRAM_MIN_STRENGTH`, `TELEGRAM_LONG_HORIZON_*`)
- `trader-news` — redondant avec `backend/services/forexfactory_service.py`

### Hors scope (US-only, ignorer)

- `trader-copycat` (13F SEC)
- `trader-pelosi` (House Clerk PTR)
- `trader-analyst` (SEC XBRL / earnings US)

## Prérequis

- Connecteur Interactive Brokers activé dans la session Claude
  (Customize → Connectors → Interactive Brokers, auth OAuth IBKR)
- Dans Claude Desktop ou Claude Code : tools IBKR qui créent des
  instructions sur **Needs approval**, jamais Always allow
- `config.json` ci-dessus — modifier `sec_user_agent` si on active jamais
  un skill touchant SEC EDGAR

## Flux type pour un ordre

1. `/trader-screener` ou analyse manuelle → identifie une candidate
2. `/trader-budget` → calcule la taille de position vs `budget` et `max_position_pct`
3. `/trader-risk` → PASS/BLOCK sur la proposition
4. `/trader-broker` → affiche le ticket, demande "yes" explicite, puis appelle
   `mcp__Interactive_Brokers_IBKR__create_order_instruction` et surface
   l'URL IBKR pour validation finale
5. État enregistré dans `trader/state/broker.json`
