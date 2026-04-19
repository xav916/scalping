# Brief — Extension multi-assets (Session 1 + 2)

**Date** : 2026-04-19
**Statut** : pré-spec, à finaliser en session dédiée
**Objectif** : documenter ce qu'on a décidé + les questions à trancher pour accélérer la reprise

---

## Rappel du contexte

- L'utilisateur veut étendre le radar à des supports au-delà des 10 paires forex actuelles
- On a séparé l'effort en **2 options combinées (A+B)** pour limiter le risque :
  - **A** — observation uniquement (dashboard + scoring), pas de trading
  - **B** — auto-trading sur ces nouveaux supports (broker multi-assets requis)
- La Session 1 ne traitera **que A**. B viendra en Session 2, quand le compte broker est prêt.

## Pré-requis à faire AVANT la Session 1 (par l'utilisateur)

1. **Vérifier la couverture de MetaQuotes-Demo** (pour info) :
   - Ouvrir MT5 Desktop → Ctrl+M → clic droit → "Show All"
   - Noter les classes dispo (forex, métaux, autres ?) — permet de savoir si le broker actuel reste viable ou si B est obligatoire

2. **Ouvrir un compte démo multi-assets pour B** (en parallèle, pas urgent pour A) :
   - **IC Markets** : https://www.icmarkets.com/eu/en/open-trading-account/demo — offre forex + crypto + indices + commodities
   - **Pepperstone** : https://pepperstone.com/en/trading-accounts/open-an-account/ — alternative similaire
   - Noter : `login`, `password`, `server` du compte démo
   - Aucun engagement, compte démo 30 jours renouvelable

## Supports proposés pour Option A (observation)

À valider en Session 1 — user choisira quels supports activer.

### Crypto (à choisir)
- BTC/USD — Bitcoin (le benchmark, forte liquidité)
- ETH/USD — Ethereum (seconde crypto par cap)
- SOL/USD — Solana (haute volatilité, opportunités scalping)
- XRP/USD — Ripple

### Indices (à choisir)
- SPX500 / US500 — S&P 500 (indice actions US)
- NAS100 / US100 — Nasdaq 100 (tech-heavy, volatil)
- US30 / DOW — Dow Jones (moins volatil mais large cap)
- DE40 / DAX — DAX allemand (exposition Europe)
- NIK225 — Nikkei Japon (déjà fetch en macro, pourrait être affiché)
- UK100 / FTSE — FTSE Londres

### Commodities (à choisir)
- WTI / USOIL — pétrole brut US (déjà fetch en macro)
- BRENT / UKOIL — pétrole brut européen
- XAG/USD — argent (cousin de l'or)
- NGAS — gaz naturel (très volatil)
- COPPER — cuivre (proxy industriel)

## Questions à trancher en Session 1

### Q1 — Scope initial
Combien de supports actives-tu d'un coup ? Options :
- **Minimum** : BTC/USD + SPX500 + XAG/USD (3, les plus emblématiques)
- **Étendu** : BTC, ETH, SPX500, NAS100, DE40, WTI, XAG (7)
- **Complet** : tous les listés ci-dessus (~15)

### Q2 — Intégration UI
Comment afficher les nouveaux supports ?
- **(a)** Mélangés dans la liste actuelle des setups (triés par confidence, tous supports confondus)
- **(b)** Onglets séparés : "Forex", "Crypto", "Indices", "Commodities"
- **(c)** Section "Autres supports" en dessous du forex principal
- **(d)** Filtre au-dessus de la liste (checkbox par classe)

### Q3 — Pattern detector
Les patterns actuels (breakout, momentum, engulfing, pin bar) sont calibrés pour forex 5min.
- Faut-il adapter pour crypto (volatilité x10, spikes fréquents) ?
- Faut-il adapter pour indices (sessions stricts : US 14h30-21h UTC, Europe 7h-15h30) ?
- Ma reco : phase 1 = les patterns tels quels, on observe, on voit ce qui ne marche pas, on ajuste.

### Q4 — Macro scoring mapping
Il faut étendre les classes dans `backend/services/macro_scoring.py` :
- BTC/USD, ETH/USD → nouvelle classe **"crypto"** — quels macro primaires ? (ma proposition : VIX inverse, SPX corrélé, DXY inverse)
- SPX500, NAS100 → nouvelle classe **"equity_index"** — primaires : VIX inverse, US10Y inverse, SPX self-reference ?
- WTI, BRENT → nouvelle classe **"energy"** — primaires : DXY inverse, risk regime
- XAG/USD → rattacher à la classe existante "XAU/USD" (métal refuge) ?

### Q5 — Fréquence de fetch
Crypto tourne 24/7, les indices ont des sessions strictes.
- Garde-t-on le cycle 200s uniforme ?
- Ou traitement différencié (crypto toutes les 200s, indices seulement pendant les sessions) ?
- Ma reco : uniforme pour simplicité, on verra si besoin.

### Q6 — Budget API Twelve Data Grow
6000 req/jour disponibles. Estimation :
- État actuel : ~1170 req/j
- +7 supports × 2 intervalles × cycle 200s = +4200 req/j
- Total projected : ~5370 req/j → OK mais serré
- Si on monte à 15 supports → ~9000 req/j → DÉPASSE

Options :
- Limiter à ~7 supports d'abord
- Faire tourner certains fetchs moins fréquemment (ex : 1h only à 15min d'intervalle)

### Q7 — Extension du dashboard mobile (PWA)
L'UI mobile actuelle est pensée pour 10 paires. Ajouter 7-15 supports crée de l'encombrement.
- Faut-il revoir le layout (grille plus dense, scroll horizontal) ?
- Ou cacher par défaut les setups faible confiance des nouvelles classes ?

## Ce qui changera dans le code (estimation)

### Backend
- `config/settings.py` : extension de `WATCHED_PAIRS` + nouveau mapping `ASSET_CLASS`
- `backend/models/schemas.py` : nouvel enum `AssetClass` ?
- `backend/services/price_service.py` : adaptation si Twelve Data renvoie un format différent pour crypto/indices
- `backend/services/macro_scoring.py` : nouvelles classes (crypto, equity_index, energy) + primaires adaptés
- `backend/services/pattern_detector.py` : vérifier que les formules ATR/pips fonctionnent sur tous les supports (déjà probable grâce à la lib tick_size de Twelve Data)
- Tests : 10-15 nouveaux cas table-driven dans `test_macro_scoring.py`

### Frontend
- Filtres par classe d'actifs (nouveau composant)
- Peut-être un petit indicateur "CRYPTO / INDEX / COMMODITY" sur chaque carte pour l'identifier rapidement
- Adaptation du bandeau macro (rien à changer normalement, il reste focus sur le contexte global)

## Ce qui changera pour Option B (Session 2)

### Pré-requis B
- Compte broker multi-assets ouvert et crédentials fournis
- Mapping précis du broker pour chaque symbole (ex : IC Markets utilise `BTCUSD`, Pepperstone utilise `BTCUSD.i`)

### Code à toucher pour B
- `.env` backend (nouveau `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`)
- `MT5_SYMBOL_MAP` en env var (grande extension)
- `C:\Scalping\mt5-bridge\.env` et `bridge.py` — adaptation du sizing :
  - Crypto : 1 lot = 1 BTC (sizing très différent, besoin de recalcul)
  - Indices : 1 lot = 1 contrat CFD (variable)
  - Commodities : WTI 1 lot = 100 barils (variable)
- `MAX_LOT` par classe ? (0.1 lot BTC = 0.1 BTC ≈ $4000 à $6000 de notionnel)
- Trading hours par classe (crypto 24/7 OK, indices strictement session-bound)
- Tests : flows bout-en-bout par asset class

### Risques spécifiques B
- Crypto volatilité → SL/TP doivent être calculés en % pas en pips absolus
- Indices overnight gaps (SPX peut gap de 50 points le dimanche)
- Commodities news-driven (EIA oil inventory, OPEC) — besoin d'intégrer ces events dans ForexFactory ou ailleurs

## Plan d'exécution

```
[Aujourd'hui]     User : MT5 "Show All" check + ouverture compte broker démo
       ↓
[Session 1]       Brainstorming A + spec + plan + implémentation (3h env)
       ↓
[+3-5 jours]      Observation en shadow
       ↓
[Session 2]       Brainstorming B + spec + plan + implémentation (4h env)
       ↓
[+1 semaine]      Auto-trading shadow sur démo multi-assets
       ↓
[+ 2 semaines]    Passage éventuel en live si résultats bons
```

## Notes pour la reprise

- Démarre la session 1 en lisant ce brief en premier
- Invoque le skill brainstorming pour cadrer formellement les décisions Q1-Q7 avec le user
- Écris une spec propre `2026-04-XX-multi-assets-observation-design.md` après validation
- Suit la boucle spec → plan → subagent-driven comme pour la Vague 1 macro

Ce brief n'est **pas** un spec validé, c'est un point de départ pour reprendre vite.
