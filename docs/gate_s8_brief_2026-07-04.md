# Brief gate S8 — 2026-07-04

**Auteur** : Xavier (via Claude Code)
**Session prep** : 2026-07-03 matin Paris
**Décideur** : Xavier

---

## TL;DR — recommandation

**Voie α ajustée + prep β en parallèle.**

- Sur Live : **abaisser `MT5_BRIDGE_LIVE_MIN_CONFIDENCE 65 → 60`**, **retirer WTI de la whitelist** (`MT5_BRIDGE_LIVE_WHITELIST_PAIRS=XAU/USD,EUR/USD`), garder verdict-bypass.
- En parallèle : démarrer la prep pipeline ML/V2 sur shadow XAU H4 (features Binance déjà stackées, 6 semaines de collecte encore nécessaires avant retrain).
- **Pas de fermeture Live**, pas de status quo.

---

## Contexte

Gate S8 (initialement S6, décalé après incident rsync du 2026-05-18) prévu à la mi-parcours de la phase recherche 6 semaines (démarrée 2026-04-25). Objectif : décider si on continue V1 en Live, si on pivote V2/ML, ou si on gèle.

## Constat opérationnel — les 4-5 derniers jours

| Composant | État | Détail |
|---|---|---|
| Radar | ✅ UP | Cycle 20086 à 05:06 UTC, 17 sig / 8.5 setups moyens depuis 30/06 |
| IC Markets Live (8788) | ✅ UP mais 0 push | Config actuelle rejette 100% des setups |
| Pepperstone Demo (8787) | ❌ DOWN | Abandonné 29/06 (`MT5_BRIDGE_ENABLED=false`) |
| Binance Testnet (8789) | ✅ Shadow ouvert | `BINANCE_RESPECT_VERDICT=false` depuis 29/06 |
| Shadow V2 XAU H4 | ⏳ Collecte | 4 setups open, 0 résolu |
| Shadow V2 WTI H4 | ❌ Verdict négatif | 16 setups, WR 11%, -205 EUR |

## Chiffres clés

### Historique Live all-time (admin_live destination)

Seulement 3 pairs ont jamais été poussées en Live :
- **ETH/USD** : 102 pushes (bloqué globalement depuis 29/06)
- **BCH/USD** : 87 pushes (bloqué globalement depuis 29/06)
- **XAU/USD** : 1 push all-time

**Interprétation** : le pipeline Live n'a jamais réellement testé XAU/WTI/EUR à volume. Le "Live" jusqu'ici = quasi-100% crypto perdantes. Donc **pas de baseline exploitable** sur les niches gagnantes en argent réel.

### Historique auto-exec toutes destinations (proxy admin_legacy)

| Pair | n | WR | PnL USD |
|---|---|---|---|
| XAU/USD | 223 | 38.4% | **+432.54** |
| EUR/USD | 31 | 27.3% | +110.11 |
| USD/CHF | 10 | 25.0% | +58.40 |
| WTI/USD | 116 | 6.1% (2 TP / 31 SL / 83 other) | +49.72 |
| ETH/USD | 609 | 26.8% | -0.89 (flat) |
| DOT/USD | 44 | 0% | -1.13 |
| BCH/USD | 217 | 6.2% | -11.77 |
| XAG/USD | 152 | 29.3% | **-1565.98** (pause active jusqu'au 06/07) |
| GBP/USD | 8 | 0% | -193 |
| EUR/JPY | 48 | 31.8% | -143 |
| AUD/USD | 30 | 33.3% | -79 |
| USD/CAD | 22 | 30.0% | -67 |

**Seul edge historique confirmé volumique** : **XAU/USD** (223 trades, WR 38%, +432 USD).
**EUR/USD** encourageant mais n=31 trop faible pour conclure.
**WTI** = 6% WR historique, cohérent avec le verdict shadow V2 négatif ci-dessous.

### Shadow V2 depuis 2026-06-19 (14 jours)

| Système | n | TP | SL | Open | WR | PnL EUR |
|---|---|---|---|---|---|---|
| V2_WTI_OPTIMAL_WTIUSD_4H | 16 | 1 | 8 | 5 | **11.1%** | **-205.07** |
| V2_CORE_LONG_XAUUSD_4H | 4 | 0 | 0 | 4 | — | — |
| V2_CORE_LONG_ETHUSD_1D | 1 | 0 | 1 | 0 | 0% | -25.10 |

- **V2 WTI** : verdict négatif clair, arrêter le shadow, retirer WTI de la whitelist Live.
- **V2 XAU H4** : 4 setups en 14 jours, tous open — **densité trop faible + résultats manquants**, besoin de **6 semaines supplémentaires** avant verdict.
- **V2 ETH 1D** : 1 setup, non conclusif.

## Pourquoi Live = 0 push depuis 30/06

Cumul de 3 filtres bloque 100% des setups :

1. `MT5_BRIDGE_LIVE_WHITELIST_PAIRS = XAU/USD, WTI/USD, EUR/USD`
2. `MT5_BRIDGE_LIVE_MIN_CONFIDENCE = 65`
3. `MT5_BRIDGE_LIVE_ALLOWED_ASSET_CLASSES = forex, metal, energy`

Sur les cycles 30/06→03/07 : les setups XAU/WTI/EUR-USD n'ont **jamais** atteint 65 aux patterns/sessions autorisés. Dernière rejection = 29/06 19:52 (`below_confidence`).

## Trois voies pour S8

### α — best-only (ajustée)

Continuer Live en configuration whitelist stricte mais paramètres relâchés pour laisser passer un flux mesurable.

**Actions** :
- `MT5_BRIDGE_LIVE_WHITELIST_PAIRS = XAU/USD, EUR/USD` (retirer WTI, verdict V2 négatif)
- `MT5_BRIDGE_LIVE_MIN_CONFIDENCE = 60`
- Garder `MT5_BRIDGE_LIVE_ALLOWED_ASSET_CLASSES = forex, metal`
- Garder `MT5_BRIDGE_LIVE_RESPECT_VERDICT = false`

**Attendu** : 3-10 trades Live/semaine sur XAU/EUR-USD. Baseline exploitable en 4 semaines pour trancher V1 argent-réel.

**Risque** : capital IC Markets Live actuel ~€200-300 (refund €300 du 13/06), un run rouge -€50 est absorbé sans pain. Si WR 30-40% comme XAU historique : espérance légèrement positive avec R:R 1.8.

### β — pivot V2/ML

Fermer Live, focus 100% sur retrain modèle avec features enrichies (Binance funding, LSR, orderbook, orderflow, OI, cache Tier 5).

**Actions** :
- `MT5_BRIDGE_ENABLED = false` (déjà), `MT5_BRIDGE_LIVE_ENABLED = false`
- Continuer shadow V2 XAU 6 semaines de plus
- Démarrer pipeline dataset + baseline logistic regression sur shadow setups + trades passés
- Objectif retrain à 1000 trades avec features complètes

**Attendu** : 4-8 semaines dev, 0 revenu, décision GO/NO-GO V2 fin août 2026.

**Risque** : perte de la fenêtre XAU actuelle si régime tourne (mais dataset shadow reste utilisable).

### γ — status quo

Rien changer. Live reste à 0 push. Attendre S12 (2026-08-01) pour re-évaluer.

**Attendu** : 4 semaines de plus sans donnée Live utile, perte de temps pure.

## Décision recommandée

**α ajustée + prep β en parallèle.**

Justification :
1. **XAU historique = seul edge volumique confirmé** (n=223, +432 USD). L'ignorer ne sert à rien.
2. **V2 WTI est mort empiriquement** (WR 11% sur 16 shadow) → retirer WTI de Live ET du shadow.
3. **V2 XAU trop tôt** pour trancher (4 setups open) → prolonger observation.
4. **Live à 0 push depuis 5 jours = data gap absurde** alors qu'on peut mesurer 3-10 trades/sem en relâchant un cran.
5. **β est le vrai avenir** (features Binance stackées, cache Tier 5 déployé), mais nécessite volume shadow → laisse tourner.

## Prochains steps si α ajustée validée demain

Ordre + durée :

1. **Modifier `.env` EC2** (5 min) : baisser MIN_CONFIDENCE + retirer WTI whitelist + retirer energy asset class + restart container
2. **Retirer V2 WTI du shadow** (15 min) : désactiver `V2_WTI_OPTIMAL_WTIUSD_4H` dans le scheduler
3. **Ping Telegram infra** : "Config α ajustée live 2026-07-04, watch flow XAU/EUR-USD sur 4 sem"
4. **Créer routine rappel S12** (5 min) : `RemoteTrigger` fire 2026-08-01 pour mesure baseline Live 4 semaines
5. **Ouvrir prep β** (post-décision, 2-4h) : script de dataset builder + audit features Binance persistées

## Points de vigilance à valider avant application

- [ ] **PAT GitHub `ghp_FXjyZ...`** encore exposé ? À rotater si oui
- [ ] **EBS 8GB → 16GB** : le prochain rebuild fail si pas fait
- [ ] Confirmer que **`.env` sur EC2 n'a pas dérivé** (double-check avant modif)
- [ ] Backup `.env.bak-2026-07-04-pre-s8` avant modif

## Sources & liens

- Sessions référence : `project_session_resume_2026_06_29.md`
- Config prod : `/opt/scalping/.env` sur EC2 `13.63.77.180`
- Verdict V2 WTI : query shadow_setups depuis 2026-06-19 (11.1% WR)
- Historique auto-exec : query personal_trades is_auto=1 all-time
