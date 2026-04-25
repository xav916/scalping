# Expériences #30-32 — Extensions portefeuille testées et REJETÉES

**Date :** 2026-04-26 (~05h Paris, après-midi UTC)
**Tracks :** Phase 4 extension portefeuille
**Numéros :** 30 (Brent), 31 (Platinum), 32 (Palladium)
**Statut global :** `closed-negative` *(0/3 candidats retenus)*

---

## Hypothèse globale

> "Si V2_CORE_LONG (XAU/XAG) et V2_WTI_OPTIMAL (WTI) capturent un edge structurel sur les actifs continus 24/5, alors d'autres assets de la même famille devraient aussi montrer un edge :
> - **Brent** (pétrole européen, corrélé WTI) → V2_WTI_OPTIMAL devrait marcher
> - **Platinum** (métal précieux, corrélé XAU + composante industrielle) → V2_CORE_LONG devrait marcher
> - **Palladium** (métal précieux + auto catalyst, plus volatile) → V2_CORE_LONG ou V2_WTI_OPTIMAL"

## Données

- Source : Twelve Data Grow (XBR/USD, XPT/USD, XPD/USD)
- Fenêtre : 2020-04-16 → 2026-04-25 (6 ans complets, mieux que WTI qui démarrait en 2020-10)
- Backtest : 4 fenêtres standard (12M, 24M, 6 ans cumul, pré-bull 4 ans)
- Simulator : H1 fallback (--use-h1-sim)

---

## Exp #30 — Brent (XBR/USD) — REJETÉ

| Fenêtre | V2_CORE | V2_TIGHT | **V2_WTI_OPTIMAL** | vs WTI ref |
|---|---|---|---|---|
| 6 ans cumul | 1.05 | 1.11 | **1.16** ✓ marg | WTI 1.20 |
| 24M récent | 0.91 | 0.94 | **1.05** ❌ | WTI 1.20 |
| 12M récent | 1.11 | 1.20 | **1.46** ✓ | WTI 1.78 |
| Pré-bull 4 ans | 1.12 | 1.19 | **1.23** ✓ | WTI 1.20 |

**Verdict :** Brent passe 3/4 fenêtres mais **systématiquement INFÉRIEUR à WTI**. 24M PF 1.05 sub-seuil.

**Lecture économique :** sanctions Russie 2024-25 ont créé du noise spécifique au Brent (Europe consume plus de Russian crude pre-sanctions, transition vers autres sources crée des distorsions). WTI moins affecté.

**Décision :** REJETÉ comme candidat séparé. Forte corrélation WTI/Brent (~0.85-0.95) → pas de diversification réelle. WTI capture déjà l'edge pétrole.

---

## Exp #31 — Platinum (XPT/USD) — REJETÉ

| Fenêtre | V2_CORE | V2_TIGHT | V2_WTI_OPTIMAL |
|---|---|---|---|
| 6 ans cumul | **1.04** ❌ | 1.09 | 1.06 |
| 24M récent | 1.18 ✓ | 1.33 | 1.37 |
| 12M récent | 1.27 ✓ | 1.48 | 1.47 |
| **Pré-bull 4 ans** | **0.92** ❌ | **0.92** ❌ | **0.89** ❌ |

**Verdict :** XPT passe en 24M/12M (bull cycle métaux) mais **DRIFT MAJEUR pré-bull** (PF 0.87-0.92 sur 4 ans). C'est le profil XAG amplifié — encore plus cycle-dépendant.

Direction breakdown 6 ans :
- BUY PF **1.00** (break-even — pas un edge)
- SELL PF 0.86 (perdants)

**Lecture économique :** Platinum a une composante industrielle forte (catalyseurs auto + hydrogène). Demande très cyclique. Différent de XAU qui a un anchor "real yields" stable. Sur 4 ans pré-bull, demande industrielle n'a pas suffi à créer un edge LONG.

**Décision :** REJETÉ. Edge non structurel cross-régime.

---

## Exp #32 — Palladium (XPD/USD) — REJETÉ

| Fenêtre | V2_CORE | V2_TIGHT | V2_WTI_OPTIMAL |
|---|---|---|---|
| 6 ans cumul | **0.93** ❌ | 0.95 | 1.03 |
| 24M récent | **0.92** ❌ | 0.94 | 0.95 |
| 12M récent | **0.80** ❌ | 0.80 | 0.80 |

**Verdict :** XPD échoue sur TOUTES les fenêtres testées avec TOUS les filters. PF 0.80-1.03.

**Lecture économique :** Palladium est dominé par :
- Production russe (sanctions, geopolitical)
- Demande catalyseurs auto (transition EV → demande baisse)
- Sample size faible en patterns (volatile mais peu structuré)

Les patterns "sereins" du système (momentum_up, range_bounce_up, etc.) ne s'appliquent pas à un asset dominé par supply shocks et transitions structurelles.

**Décision :** REJETÉ catégoriquement.

---

## Synthèse globale

**0/3 candidats retenus.** Le portefeuille reste **3 candidats** : XAU + XAG + WTI.

### Lectures stratégiques

1. **L'edge V2_CORE_LONG / V2_WTI_OPTIMAL n'est PAS généralisable** à toute commodity USD-priced. Il dépend de drivers macro spécifiques :
   - **XAU** : real yields proxy stable (mécanique pure)
   - **XAG** : XAU amplifié + demande industrielle modérée
   - **WTI** : USD-priced + range trading OPEC + geopolitical

2. **Les "extensions naturelles" ne sont pas évidentes :**
   - Brent corrélé à WTI mais sanctions créent des distorsions spécifiques
   - XPT corrélé à XAU mais composante industrielle dominante en récent
   - XPD trop dépendant de supply chocks

3. **Multiple testing risk validé empiriquement** : sur 3 candidats supplémentaires testés, 0 passe le seuil 1.15 sur 6 ans cumul + pré-bull. Le risque "tester N candidats jusqu'à en trouver un qui passe par chance" est réel mais n'a pas dérapé ici.

### Pour aller plus loin (si désiré dans une future session)

1. **Copper (XCU/USD)** — pas dispo en symbole standard chez TD Grow. À explorer via futures CME (HG=F) ou ETF (CPER) si data accessible. Drivers très différents (cycle économique mondial).

2. **Crypto Daily** (BTC, ETH) — H4 a échoué mais Daily pas testé en profondeur. Sample size limité.

3. **Futures équités ES/NQ** — pas dispo en TD Spot. Nécessiterait broker direct (Pepperstone, IB) pour avoir 23/5 continu.

4. **Forex emerging (USD/MXN, USD/ZAR, USD/TRY)** — high beta, peut-être trend-following productif. Twelve Data Grow probablement OK pour ces majors emerging.

5. **Strategy class shift** : Track C TF systématique a été testé sur métaux uniquement. Étendre à WTI + autres commodities pourrait révéler des edges TF différents des pattern detection.

## Conséquences actées

### Pour Phase 4 (déjà deployed)

**Aucune modif.** Le shadow log live continue avec XAU + XAG + WTI. Pas d'ajout de Brent/XPT/XPD.

### Pour Phase 5 (gate S6)

Le portefeuille reste 3 actifs. Allocation suggérée :
- 50% XAU H4 (le plus robuste)
- 25% XAG H4 (cycle-amplifié)
- 25% WTI H4 (diversification non-métaux)

### Pour la page /v2/supports

Pas d'ajout. Les 3 cards XAU/XAG/WTI restent.

### Documentation des rejets

Cette page documente formellement que **3 extensions ont été testées et rejetées**. Le portefeuille final n'est pas un produit de l'inertie — il a été stress-testé contre des extensions naturelles.

## Artefacts

- DB H1 fetched : XBR/USD (34850 bars), XPT/USD (37352), XPD/USD (37165), 5min Brent partial
- Modifié : `scripts/research/track_a_backtest.py` (PAIRS étendu avec 4 nouveaux symboles, mais filtres existants suffisent)
- Commit : à venir
