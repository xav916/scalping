# Recherche edge — portefeuille de 3 tracks parallèles

**Date :** 2026-04-25
**Statut :** spec active
**Auteur :** session collaborative humain + assistant
**Horizon :** 6 semaines (gate décisionnel ~2026-06-06)
**Budget :** 30 h/sem, ~10 h par track

---

## Contexte

### Ce qui est confirmé

V1 (scalping H1 + scoring rule-based + ML technique) **n'a pas d'edge structurel**. Deux tests indépendants concordent :

| Test | Volume | Résultat | Doc |
|---|---|---|---|
| Backtest 12 mois × 12 paires | 39 689 trades | Toutes stratégies négatives avec coûts 0.02% | `2026-04-22-backtest-v1-findings.md` |
| ML training V1 | 233 567 samples / 6-10 ans | AUC 0.526 (seuil edge 0.55) | `2026-04-22-ml-findings.md` |

### Ce qui n'est PAS testé

1. **Horizons autres que H1** (4h, daily, weekly)
2. **Features non-techniques** (macro, retail sentiment, news, cross-asset)
3. **Paradigmes autres que pattern detection** (trend-following systématique, mean-reversion stat, carry, cross-asset momentum)

### Choix stratégique du 2026-04-25

Plutôt que :
- (a) tester les 5 pistes des findings ML en série → 6+ semaines avant signal
- (b) parier tout sur une piste (ex : macro features) → biais de tunnel
- (c) capituler immédiatement vers Observatoire SaaS-only → prématuré

→ **Portefeuille recherche : 3 tracks parallèles, gate à 6 semaines**.

## Les 3 tracks

### Track A — Horizon expansion

- **Hypothèse** : l'edge existe à H4/Daily car le coût spread/slippage est amorti sur des mouvements 5-10× plus larges, et la micro-noise H1 est filtrée mécaniquement
- **Critère succès** : PF ≥ 1.15 sur backtest 12 mois (≥1 paire/strat avec coûts 0.02%)
- **Critère échec** : PF < 1.10 sur toutes les combinaisons paire×stratégie×horizon → l'horizon n'est pas le problème
- **Effort estimé** : 10 h/sem
- **Spec détaillée** : `2026-04-25-track-a-horizon-h4.md`

### Track B — Alt-data + cross-asset features

- **Hypothèse** : l'edge existe dans des features non-techniques (macro VIX/DXY/SPX, sentiment retail, calendrier news) qu'on n'a jamais testées
- **Critère succès** : AUC test ≥ 0.55 ET prec@0.65 > 0 sur ML re-entraîné avec features étendues, sur ≥1 horizon
- **Critère échec** : AUC < 0.53 sur toutes les combinaisons feature_set × horizon × modèle
- **Effort estimé** : 10 h/sem
- **Spec détaillée** : `2026-04-25-track-b-altdata-cross-asset.md`

### Track C — Trend-following systématique

- **Hypothèse** : changer de paradigme — pas de pattern detection, pas de timing court terme. Implémenter un trend-following multi-asset à la Carver/Hurst (signal = momentum N mois, sizing = vol target, diversification = portefeuille)
- **Critère succès** : Sharpe ratio annualisé > 0.7 sur backtest 12 mois multi-asset (avec coûts)
- **Critère échec** : Sharpe < 0.4 → même un paradigme académiquement reconnu ne donne rien sur nos données → soit les données ont un problème, soit retail forex est trop arbitragé
- **Effort estimé** : 10 h/sem
- **Spec détaillée** : `2026-04-25-track-c-trend-following.md`

## Track 0 — prérequis (FAIT le 2026-04-25)

- Journal d'expériences `docs/superpowers/journal/` créé (README, template, INDEX)
- Convention d'écriture : 1 expérience = 1 fichier daté, 1 hypothèse falsifiable, critère go/no-go fixé AVANT
- Master spec présente (ce fichier)
- Specs des 3 tracks (à écrire juste après)

## Cadence — 6 semaines

| Phase | Semaines | Objectif |
|---|---|---|
| **Spike** | S1-S2 (2026-04-26 → 2026-05-09) | Implémenter chaque track jusqu'au premier verdict binaire (succès / échec / indécis). Pas de polish, pas de prod. |
| **Approfondir** | S3-S4 (2026-05-10 → 2026-05-23) | Tracks avec signal → ablation studies, sensitivity analysis, robustness. Tracks sans signal → fermer ou pivoter dans le journal. |
| **Préparer prod** | S5-S6 (2026-05-24 → 2026-06-06) | Survivants : intégration au pipeline live en mode shadow log (mesure live vs backtest). Pas encore d'auto-exec sur du nouveau. |
| **Gate** | 2026-06-06 (samedi) | Décision : démo réelle / pivot / Observatoire SaaS-only |

## Règles d'or

1. **Pas de modif sur le live V1** entre maintenant et le gate. Toute modif pollue les expériences. Le live continue de tourner avec ses filtres anti-saigne (cf `project_scalping_algo_tuning_v1.md`).
   - **Gel explicite des fixes en attente :** le commit `b750fa5` (fix Bug #1 — remplace scraping Mataf par ATR local pour la volatilité) est **mergé sur main mais non déployé**. Il sera déployé au gate S6 si on bascule en mode Observatoire SaaS-only ou si on intègre une track gagnante en prod. Pas de `bash deploy-v2.sh` entre 2026-04-25 et 2026-06-06.
2. **Critères go/no-go écrits AVANT** d'exécuter. Sinon biais de confirmation.
3. **Une expérience clôturée = un fichier dans le journal + INDEX.md mis à jour + commit git**. Sans exception.
4. **Pas de re-écriture rétroactive d'expériences** — si on s'aperçoit qu'une expérience était mal protocolée, on en ouvre une nouvelle qui cite l'ancienne.
5. **Les tracks ne se contaminent pas entre elles** — si une features de Track B est testée en isolation, c'est Track B. Si on combine Track B + Track A (features macro sur H4), c'est une 4e expérience cross-track explicite.
6. **Si une track montre un signal très clair en S1 ou S2** (PF > 1.5, AUC > 0.60, Sharpe > 1.0), OK pour la prioriser et reporter les autres — mais documenter explicitement la décision dans le journal.

## Gate du 2026-06-06 — décision honnête

À ce moment, 3 sorties possibles :

### A) Au moins 1 track a passé son critère succès
→ Cette track passe en **migration prod + shadow log** sur démo Pepperstone pendant 4-8 semaines. On suit les conditions de passage live définies dans la roadmap initiale (win rate > 45%, drawdown < 5%, Sharpe > 1, etc.). Les autres tracks sont mises en backlog.

### B) Aucune track n'a passé son critère succès, mais ≥1 a montré un signal partiel
→ Pivot vers une expérience croisée (ex : meilleures features de B + horizon de A) ou vers une piste non-listée. On rédige une nouvelle spec et on reprend pour 6 semaines max.

### C) Aucun signal sur les 3 tracks
→ **Bascule Observatoire SaaS-only**. Le projet conserve sa valeur (visibilité, alertes, dashboard, infra) sans prétention edge. C'est un résultat empirique honnête, pas un échec personnel. Les 3 mois investis ont produit un dataset de référence + une infra MT5 réutilisable pour de futurs paris.

## Notes méthodologiques

### Pourquoi 0.55 d'AUC comme seuil edge

L'AUC mesure la capacité à classer trades gagnants vs perdants. 0.50 = aléatoire, 1.00 = parfait. **0.55 = +5 points vs aléatoire** ; en pratique, c'est le seuil minimum à partir duquel un edge est exploitable après spread/slippage sur retail forex (cf Lopez de Prado, *Advances in Financial ML*, ch. 8).

### Pourquoi PF 1.15 et pas 1.20+

PF 1.15 sur backtest = ~1.05-1.10 en live (dégradation entre 5% et 10% en moyenne sur retail forex avec slippage non-modélisé + execution gaps). 1.05 live est le minimum pour rester rentable au-dessus du coût psychologique et de la variance.

### Pourquoi Sharpe 0.7 pour TF

Carver (*Systematic Trading*) cite Sharpe 0.5-1.0 pour trend-following multi-asset bien conçu sur retail. 0.7 est la médiane des stratégies publiées. < 0.4 indique un problème data ou paradigme.
