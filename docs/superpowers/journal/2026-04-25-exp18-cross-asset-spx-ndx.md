# Expérience #18 — V2_CORE_LONG sur indices équités SPX/NDX

**Date :** 2026-04-26 (~02h15 Paris)
**Tracks :** Phase 4 cross-asset
**Numéro d'expérience :** 18
**Statut :** `closed-negative` *(confirme spécificité assets continus)*

---

## Hypothèse

> "V2_CORE_LONG XAU+XAG H4 (validé Sharpe 1.59) — est-ce que la même recette s'applique aux **indices équités** H4 (SPX, NDX) qui sont aussi des actifs majeurs avec données disponibles ?"

## Données

- SPX : 2605 H1 (2020-05 → 2026-04), couverture limitée aux heures trading US
- NDX : 455 H1 (2025-02 → 2026-04, 14 mois) — limité
- Pas de WTI dans la DB

## Critère

| Sortie | Condition | Verdict |
|---|---|---|
| **Étendable** | PF V2_CORE ≥ 1.15 sur ≥1 asset (24M ou 6y) | Ajouter au shadow log |
| **Spécifique métaux** | PF < 1.0 sur tous indices testés | Confirmer XAU+XAG comme unique périmètre |

## Résultats

```
SPX H4 24M    BASELINE PF 0.42  V2_CORE PF 0.47  (16 trades, WR 12.5%)
SPX H4 6 ans  BASELINE PF 0.31  V2_CORE PF 0.23  (40 trades, WR 10.0%)
NDX H4 12M    BASELINE PF 0.75  V2_CORE PF 0.73  (28 trades, WR 39.3%)
```

## Verdict

> Hypothèse **INFIRMÉE** : V2_CORE_LONG ne marche pas sur indices équités H4.

## Lecture

Deux causes probables :

1. **Gaps overnight + sessions discontinues** : SPX/NDX cash markets ferment. L'aggrégation H4 inclut des bars partiels avec gaps, le pattern detector se déclenche sur des moves qui ne sont pas vraiment des "breakouts" mais des ajustements cash post-fermeture.

2. **Couverture data sparse** : SPX 6y a seulement 191 H4 bars (~32/an), vs ~1500 attendus pour un asset 24/5. Confirme que seules les heures cash trading US sont en data → backtest pas représentatif d'un trading équité réel (qui se ferait sur futures ES/NQ pour avoir 23/5).

## Conséquences actées

### Pour Phase 4 / système live
- **XAU + XAG H4 confirmés comme unique périmètre validé.** Le shadow log déployé observe le bon scope.
- Pas d'extension du shadow log à des assets supplémentaires sur la base de cette exp.

### Pour exp future (si voulu)
- Si on veut vraiment tester équités, il faudrait des **futures** (ES, NQ) avec data 23/5 et timestamps continus. Pas dans la DB actuelle.
- Idem WTI/Brent : pas dans la DB. Twelve Data peut peut-être les fetcher, à explorer si Phase 5+ veut diversifier.

### Confirmation du pattern : V2_CORE = système assets continus
Les assets validés (XAU, XAG) sont **24/5 quasi-continus**. Les forex (EUR/USD, GBP/USD, etc.) aussi 24/5 mais à plat. Crypto 24/7 (BTC, ETH) à plat. Indices cash : à plat ou négatif.

→ **Pattern → assets continus 24/5 + métaux/safe-haven semble être la combinaison gagnante.** Pas généralisable au-delà.

## Artefacts

- Pas de modif code (utilise track_a_backtest.py existant)
- Commit : à venir (avec exp #16, #17 et XAG 6 ans qui suivent)
