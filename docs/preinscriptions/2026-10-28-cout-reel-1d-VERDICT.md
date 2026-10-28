# Verdict — le coût réel des 36 paires est **INMESURABLE**, et c'est un défaut de PRODUCTION

**Pré-inscription** : `1528de5` · **Le banc n'a pas pu tourner**, et c'est le résultat.

Sa clause de validité exigeait `paires_mesurees >= 3 ET trades_mesures >= 300`.
**Il y a ZÉRO paire mesurable sur les 36.**

## 🔴 La réponse, pièces à l'appui

| source de coût | état mesuré | diagnostic |
|---|---|---|
| `personal_trades.fill_price` | **693 trades avec `entry` ET `fill` · `fill ≠ entry` dans 0 (0,0 %)** | 🔴 **c'est une COPIE de `entry_price`** |
| `trade_financial_ledger.spread_cost` | **0 / 1 784 renseignée** | 🔴 **colonne jamais peuplée** |
| `trade_financial_ledger.slippage` | 545 renseignés, de **−3 839 900** à **+4 129 900** | 🔴 **échelle inutilisable** |
| `personal_trades.slippage_pips` | ex. 237 800 · −276 000 · 4 129 900 | 🔴 idem |
| `trade_financial_ledger.commission` | 920 renseignées, **0 non nulle** | ⚖️ **peut être exact** (courtier au spread seul) |
| `trade_financial_ledger.swap` | 920 renseignés, **90 non nuls (9,8 %)** | ⚖️ **peut être exact** (portage dû seulement la nuit) |
| `ticks_courtier.db` → `ticks (pair, bid, ask)` | **11 480 670 lignes, 100 % `XAU/USD`** | 🔴 **ne couvre AUCUNE des 36 paires** |

⚠️ **Je distingue ce qui est cassé de ce qui est peut-être juste** : `commission`
à zéro et `swap` rarement non nul sont **plausibles** pour un courtier au spread
sur des positions courtes. Ce qui est **cassé**, c'est `spread_cost` (vide),
`slippage` (échelle absurde) et `fill_price` (copie de l'entrée).

⇒ 🔴 **Aucune des 36 paires du `1d` n'a de bid/ask ni d'exécution exploitable.**
Les seules données réelles d'écart achat/vente couvrent **`XAU/USD`**, absent de
**toutes** les populations de cette série (`1d`, `4h`, `5min`).

## ⇒ Ce que ça fait au `+0,113 R`

Le `+0,112848 R` du `1d` sous exécution réalisable **ne peut ni être défendu ni
être réfuté sur le coût**. Ma prédiction `P4` — « le coût ne mangera pas
l'écart » — est **indécidable**, pas tenue.

⇒ **Le `+0,113 R` reste NON ÉTABLI**, pour les raisons déjà nommées en
`6b58cdd` et **inchangées** :

- **56,7 %** de sa population porte sur des instruments **hors
  `WATCHED_PAIRS`**, dont 7 ETF sectoriels US d'une classe que le pont
  **n'autorise pas** ;
- `FILL_OUVERTURE` est **une autre stratégie**, jamais exécutée ;
- **zéro hors échantillon** ;
- **47,7 % de TIMEOUT sur 240 h** — un pari directionnel à dix jours, hors du
  périmètre d'un système de scalping.

🔑 **Et j'ajoute celle-ci, qui est nouvelle** : **son coût est inconnaissable
avec l'instrumentation actuelle.**

## 🔴 LE CONSTAT QUI DÉPASSE CE BANC

**Le système ne sait pas mesurer ce que ses trades coûtent.**

Chaque chiffre de coût de **toute cette série** — `cout_R_median` du `1d`
(0,0021), du `4h`, du `5min` (0,0395 puis 0,0950) — dérive d'une **constante
codée en dur** :

```
SPREAD_PCT = 0.0002      # 0,02 % du prix, pour TOUS les instruments
```

⇒ Cette constante n'a **jamais** été confrontée à une exécution réelle sur les
instruments concernés, et **elle ne peut pas l'être** : la donnée n'existe pas.
⚠️ Elle est sans doute **raisonnable** pour `BTC/USD` ou `EUR/USD` chez un bon
courtier ; elle est **certainement fausse** pour `INJ/USD`, `ETHFI/USD` ou
`XLRE` — et c'est **56,7 %** de la population `1d`.

⚖️ **Nuance importante** : le travail du **12/10** (`bancs refaits au coût
réel`) avait bien mesuré un coût réel — **sur l'or**, avec ce magasin de ticks.
C'est donc faisable, et ça n'a **jamais** été fait pour les autres instruments.

## ✅ Ce que ce passage a établi d'autre

- **La fausse alerte que je n'ai PAS criée.** La colonne `risk_pct` vaut
  **0,1464** là où le banc calcule **14,64 %** : rapport **exactement 100,0×**,
  donc **une unité, pas un défaut** (`ETH/USD` : 2331,40 → 1857,70 = 20,32 %,
  colonne 0,2032, `rr` 1,8000). 🔑 **Mesuré avant d'être annoncé** — c'est
  exactement ce que j'avais raté deux verdicts plus tôt.
- **L'univers du `1d`, chiffré** : 13 paires surveillées (590 setups, 43,3 %)
  contre 23 hors liste (772 setups, 56,7 %).

## 🔬 La suite, et ce n'est plus de la mesure

1. 🔴 **INSTRUMENTER le coût.** Dans l'ordre : enregistrer le **bid/ask à
   l'instant de l'entrée et de la sortie** ; **peupler `spread_cost`** ;
   **réparer l'échelle de `slippage`** ; et **cesser de recopier `entry_price`
   dans `fill_price`**, qui fait croire à une donnée d'exécution inexistante.
   ⇒ **C'est du travail de production, pas de banc.**
2. **Étendre le magasin de ticks** au-delà de `XAU/USD`, au moins aux
   instruments de `WATCHED_PAIRS`.
3. ⛔ **Et en attendant, ne plus publier de `cout_R` sans dire qu'il vient
   d'une constante.** Les verdicts de cette série l'ont fait sans le signaler
   assez fort.

🛑 **Je ne propose pas de réarmer l'IA.** REM-002 reste `DISARMED_MANUALLY` —
et un système qui ne mesure pas ses coûts est une raison de plus.
