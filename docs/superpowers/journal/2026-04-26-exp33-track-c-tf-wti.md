# Expérience #33 — Track C TF systématique sur WTI/USD H4

**Date :** 2026-04-26 (~00h Paris)
**Tracks :** Phase 4 extension stratégique
**Statut :** `closed-negative`

---

## Hypothèse

> "Track C TF systématique (EMA12/48 cross filtré par EMA100, ATR×3 stop) capture un edge LONG cross-régime sur WTI/USD H4 avec PF ≥ 1.15 sur ≥3 des 4 fenêtres, comme observé sur XAU H4 (PF 5.60 PRE_TEST / 2.32 TEST)."

## Motivation

WTI vient d'être ajouté en V2_WTI_OPTIMAL (exp #29, PF 1.20-1.78 sur 4/4 fenêtres). Track C TF avait été testé uniquement sur métaux. Le pétrole a un caractère "trend post-news OPEC" qui pourrait coller au filter EMA. Si succès → 4e candidat (ou WTI multi-stratégie) avant gate S6.

## Données

- Source : `_macro_veto_analysis/backtest_candles.db` (déjà fetchée pour exp #29)
- Période : 2020-10-04 → 2026-04-25 (5.5 ans, identique exp #29)
- 4 fenêtres : 5.5y cumul / 12M / 24M / pré-bull 3.5y

## Protocole

Réutilisation directe du script `scripts/research/track_c_trend_following.py` (Carver/Faith style, EMA fast=12 / slow=48 / filter=100, ATR period=14 ×3). Coûts spread/slippage 0.02% inclus.

## Résultats

### LONG only — fenêtre par fenêtre

| Fenêtre | n | WR% | PF | PnL | maxDD% | Verdict |
|---|---|---|---|---|---|---|
| pré-bull 3.5y | 100 | 25.0 | **1.58** ✓ | +60.05% | 44.8 | confirmé |
| 5.5y cumul | 182 | 19.8 | **1.07** ❌ | +12.67% | 75.2 | sous seuil |
| 24M | 80 | 13.8 | **0.46** ❌ | -45.85% | 52.5 | catastrophique |
| 12M récent | 39 | 12.8 | **0.55** ❌ | -18.14% | 28.6 | catastrophique |

### Direction breakdown 5.5y cumul

| Direction | n | WR% | PF | PnL |
|---|---|---|---|---|
| LONG | 182 | 19.8 | 1.07 | +12.67% |
| SHORT | 179 | 21.8 | **0.58** | -78.10% |

LONG only marginalement positif sur le cumul, SHORTs catastrophiques (cohérent avec V2_WTI_OPTIMAL qui est aussi LONG only).

## Verdict

> Hypothèse **INFIRMÉE**.
>
> Track C TF LONG sur WTI fonctionne uniquement en pré-bull (PF 1.58) et **casse en bull cycle 2024-2026** (PF 0.46-0.55). Edge inversé par rapport à V2_WTI_OPTIMAL (qui est confirmé cross-régime PF 1.20-1.78).

## Lecture économique

Le filter EMA marche quand WTI a des trends directionnels longs :
- 2020-2021 : recovery post-COVID (trend up net)
- 2022 : invasion Ukraine (trend up explosif)
- 2023 : OPEC+ cuts (trend up directionnel)

Mais en 2024-2026, WTI bascule en **range trading** entre niveaux OPEC implicites (75-90 USD). Le TF est systématiquement piégé : il entre LONG après un breakout up, prend une tape de retour en range, sort sur signal reverse, perd la prime. WR 13-25% confirme ça (vs 35-45% normal pour TF).

V2_WTI_OPTIMAL fait exactement l'inverse en intégrant `range_bounce_up` qui exploite ce range trading.

## Comparaison avec Track C métaux

| Asset | Track C TF LONG H4 — PF cross-régime | Verdict |
|---|---|---|
| XAU/USD | 5.60 PRE / 2.32 TEST — robuste | candidat secondaire |
| XAG/USD | 1.12 PRE / 3.76 TEST — régime-dépendant | candidat conditionnel |
| **WTI/USD** | **1.58 PRE / 0.46 TEST — INVERSÉ** | **rejeté** |

Le Track C TF est donc spécifique aux métaux (drivers structurels real yields / industrial demand) et ne se généralise pas à WTI (driver politique / range OPEC).

## Caveats

1. **Paramètres pas optimisés sur WTI** — 12/48/100/ATR3 viennent de Carver/Faith pour métaux. Un grid search sur WTI pourrait améliorer marginalement, mais le pattern "perd en bull cycle" suggère que le problème est structurel (régime range), pas paramétrique.
2. **Pas de SHORT testé séparément** — SHORT PF 0.58 sur 5.5y, 0.18 sur 12M. Pas d'edge.
3. **Sample 24M n=80 limité** — interprétation "casse en bull cycle" robuste mais pas exempte de bruit.

## Conséquences actées

### Pour Phase 4

**Aucune modif.** WTI reste single-stratégie V2_WTI_OPTIMAL. Le portefeuille shadow log reste **3 candidats** (XAU/XAG/WTI).

### Pour le futur

- **WTI ne sera pas multi-stratégie** — Track C TF est spécifique métaux, pas universel commodity.
- **Confirmation exp #29 validée a posteriori** — V2_WTI_OPTIMAL avec range_bounce_up est bien adapté au régime actuel range OPEC.
- **Si régime WTI change** (retour à trends post-OPEC surprise majeur) → re-tester Track C TF dans une future session.

## Pistes restantes pour étendre les "supports stars"

Suite à ce rejet, pistes ordonnées par promesse :

1. **NatGas H4** — pas du tout testé, driver météo orthogonal à tout, ~1h
2. **Crypto Daily V2** (BTC, ETH) — H4 a échoué, Daily pas creusé en profondeur, ~45 min
3. **Forex emerging USD/MXN** — high beta oil-correlated, ~1h
4. **Indices internationaux DAX/FTSE/NKY** — sessions différentes pour gap problem, ~1h
5. **Copper (XCU)** — data access problem TD Grow, ~2h

## Artefacts

- Modifié : aucun (script `track_c_trend_following.py` réutilisé tel quel)
- Commit : à venir
