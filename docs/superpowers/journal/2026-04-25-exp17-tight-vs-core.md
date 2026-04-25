# Expérience #17 — Test V2_TIGHT_LONG (2 patterns) vs V2_CORE (3 patterns)

**Date :** 2026-04-26 (~02h Paris)
**Tracks :** Phase 4 calibration finale
**Numéro d'expérience :** 17
**Statut :** `closed-positive` *(découverte régime-dépendance)*

---

## Hypothèse

> "Si on retire `breakout_up` (le moins solide des 3 stars sur 4 ans pré-bull à PF 1.11), V2_TIGHT_LONG = {momentum_up, engulfing_bullish} BUY a un PF supérieur à V2_CORE_LONG sur ≥3 des 4 fenêtres."

## Critère

| Sortie | Condition | Verdict |
|---|---|---|
| **TIGHT meilleur** | PF TIGHT ≥ PF CORE + 0.05 sur ≥3/4 fenêtres | Switch system live |
| **Trade-off** | TIGHT meilleur sur certaines, CORE sur d'autres | Système adaptatif possible (futur) |
| **CORE meilleur** | PF CORE ≥ PF TIGHT sur ≥3/4 fenêtres | Garder CORE actuel |

## Résultats — XAU H4

| Période | TIGHT PF | CORE PF | Δ | TIGHT maxDD | CORE maxDD |
|---|---|---|---|---|---|
| 12M (2025-26) | 1.43 (n=248) | **1.58** (n=318) | -0.15 | 48.4 | 51.8 |
| 24M (2024-26) | 1.31 (n=473) | **1.41** (n=601) | -0.10 | 48.4 | 51.8 |
| 6 ans (2020-26) | 1.30 (n=1129) | **1.33** (n=1441) | -0.03 | 49.1 | 52.8 |
| 4 ans pré-bull (2020-24) | **1.31** (n=653) | 1.26 (n=837) | +0.05 | **27.8** | 40.7 |

## Verdict

> Hypothèse **PARTIELLEMENT CONFIRMÉE — résultat asymétrique selon régime** :
> - **Bull cycle (12M, 24M)** : V2_CORE bat V2_TIGHT (Δ -0.10 à -0.15)
> - **6 ans cumulés** : V2_CORE marginal (-0.03)
> - **Pré-bull cycle (4 ans calme)** : V2_TIGHT bat V2_CORE (Δ +0.05) avec maxDD massivement réduit (40.7% → 27.8%)

## Lecture économique

`breakout_up` BUY :
- En **bull cycle** (forts trends directionnels métaux) : les breakouts haussiers sont productifs car la tendance continue ⇒ TPs atteints
- En **marché calme** (consolidations + petits moves) : les breakouts sont souvent des fausses cassures (whipsaws), le prix revient ⇒ SLs hits

C'est cohérent avec la théorie classique des breakouts : ils marchent quand il y a vraiment quelque chose qui pousse le prix (volume + macro driver), nuls quand le marché manque de direction.

## Conséquences actées

### Pour V2_CORE_LONG actuel (système live)
- **Reste optimal pour le régime 2024-2026** (bull cycle métaux). Pas de changement à apporter.
- Le shadow log déployé mesure le bon système.

### Pour Phase 4 future / Phase 5
- **Insight précieux** : un système **régime-adaptatif** pourrait améliorer le risk-adjusted return en cycles calmes :
  - Si régime macro identifié comme "bull cycle métaux" (DXY weak, TNX bas, gold dist_sma200 > 5%) → activer V2_CORE (3 patterns)
  - Si régime "calme" (gold dans range ± 5% SMA200) → switcher V2_TIGHT (2 patterns)
- Critère détection régime à définir (utiliser features Track B macro)
- Estimated gain : maxDD réduit de ~30% en marché calme

### Pour le code prod
- Pas de modif V1 / V2_CORE_LONG actuels
- L'extension régime-adaptive est à scoper dans une future Phase

## Synthèse cumulée des 3 sets testés (XAU H4 6 ans)

| Set | n | PF | maxDD% | Profil |
|---|---|---|---|---|
| V2_TIGHT (2 patterns) | 1129 | 1.30 | 49.1 | Conservateur, mieux en marché calme |
| **V2_CORE (3 patterns)** | **1441** | **1.33** | **52.8** | **Optimal moyen, ce qu'on déploie** |
| V2_EXT (4 patterns) | 1813 | 1.29 | 61.0 | Trop dilué |

V2_CORE est le **sweet spot** sur 6 ans cumulés : meilleur PF, maxDD acceptable, volume conséquent. Le système live est calibré exactement où il faut.

## Artefacts

- Modifié : `scripts/research/track_a_backtest.py` (+ filter_v2_tight_long pour traçabilité)
- Commit : à venir
