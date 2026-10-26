# Verdict — la cause des TIMEOUT « forex »

**Pré-inscription** : `f177cdc`, `2026-10-26-cause-timeout-forex.md`.
**1 prédiction sur 5 informative et juste.** Et mon cadrage de la question
était faux.

## CRITERE-MACHINE

```
P1_branche_sans_bougie_pct      = 0.0      # predit > 50  -> REFUTE
P2_statut                       = SANS_OBJET   # n = 0
P3_statut                       = SANS_OBJET   # n = 0
P4_controle_crypto_pct          = 0.0      # predit < 20 -> passe mais VACUEUX
P5_mfe_sous_distance_tp_pct     = 100.0    # predit > 80  -> PASSE
mecanisme_retenu                = H2_distance_non_parcourue
attribution_classe_actif        = REFUTEE
confusion_residuelle            = classe_et_horizon_CONFONDUS
```

## P1 — REFUTÉE, et sans ambiguïté

La branche « aucune bougie dans la fenêtre » n'a **jamais** tiré :
**0 ligne sur 1 031**. J'avais prédit > 50 %.

Et j'ai vérifié que la comparaison était *capable* d'être vraie avant de
conclure — une comparaison toujours fausse ressemble exactement à une
hypothèse réfutée. Les deux colonnes sont au même format
(`'2026-08-20T04:00:00+00:00'`), et la durée réellement tenue le confirme :

| | n | médiane | ≥ 95 h | < 24 h |
|---|---|---|---|---|
| « forex » TIMEOUT | 1 031 | **96,00 h** | **99,4 %** | 0,0 % |
| crypto TIMEOUT | 276 | 240,00 h | 100,0 % | 0,0 % |
| « forex » résolus | 1 788 | 29,17 h | 11,9 % | 43,8 % |
| crypto résolus | 18 710 | **1,17 h** | 0,2 % | 95,5 % |

⇒ Les bougies étaient là, toute la fenêtre. **Ce n'est pas un trou de donnée.**

## P4 — passe, mais VACUEUSE

Je prédisais < 20 % pour la crypto. Mesuré : **0 %**. Mais le « forex » est
aussi à 0 % : **il n'y a aucun contraste**, donc ce contrôle ne départage
rien. Je le compte comme non informatif, pas comme un succès.

## P5 — PASSE, et c'est le mécanisme survivant

**100 %** des TIMEOUT ont un `mfe_pct` inférieur à la distance exigée jusqu'au
TP (prédit > 80 %). Médiane du rapport : **0,368** — en 96 heures, le prix a
parcouru à peine plus du **tiers** du chemin.

## ⛔ MAIS MON CADRAGE ÉTAIT FAUX : il n'y a pas d'effet « forex »

Stratifié par horizon, l'écart s'évapore :

| horizon | non-Binance | crypto Binance | écart |
|---|---|---|---|
| `5min` | 0,0 % (n=28) | 0,6 % (n=18 640) | −0,6 pt |
| `1d` | **46,3 %** (n=1 016) | **47,4 %** (n=346) | **−1,1 pt** |
| `4h` | 31,6 % (n=1 775) | *aucune ligne* | — |

Le **36,6 % contre 1,5 %** que j'ai rapporté est donc une **composition** :
la crypto Binance est à **98,2 % des setups `5min`**, le reste à 63 % de `4h`
et 36 % de `1d`.

Et ma deuxième erreur de cadrage : les paires les plus exigeantes du `1d` ne
sont pas du forex mais des **altcoins** — ARB 46,7 %, INJ 37,8 %, UNI 35,2 %,
ETHFI 33,2 %, SUI 30,4 %. Mon étiquette « forex » désignait en fait « tout ce
qui n'est pas coté par Binance ».

## La décomposition réelle

| classe | horizon | n | TIMEOUT | TP exigé (méd.) | `mfe` (méd.) |
|---|---|---|---|---|---|
| crypto | `5min` | 18 668 | **0,6 %** | 0,91 % | 0,487 % |
| forex major | `4h` | 1 696 | **31,5 %** | 0,64 % | 0,247 % |
| métal | `4h` | 79 | 32,9 % | 5,19 % | 1,378 % |
| ETF/indice | `1d` | 166 | 42,2 % | 3,35 % | 1,613 % |
| crypto | `1d` | 1 148 | **48,3 %** | **21,32 %** | 6,059 % |
| métal | `1d` | 48 | 20,8 % | 2,62 % | 1,077 % |

## ⚠️ La limite que je ne peux pas franchir

**Classe d'actif et horizon sont CONFONDUS dans cette donnée** : il n'existe
aucun setup crypto en `4h`, et quasiment aucun forex major en `5min`. Je peux
donc affirmer que dans le seul stratum comparable (`1d`) l'effet de classe
vaut **~1 point**, c'est-à-dire rien. Je ne peux **pas** dire lequel des deux,
classe ou horizon, porte l'écart global — le plan d'expérience ne le permet
pas.

## 🔬 Une piste, posée comme piste et non comme conclusion

Les setups `1d` exigent un TP médian de **21,3 % en crypto** et **17,3 %**
dans l'autre poche, pour un `mfe` médian de 6,1 % et 4,9 %. Soit **25 fois** la
distance exigée en `4h` (0,64 %). Un objectif atteint moins d'une fois sur
deux en **dix jours** ressemble davantage à un **réglage mal mis à l'échelle
pour l'horizon journalier** qu'à une propriété du marché. ⛔ Mais je n'ai
mesuré ni la façon dont cette distance est calculée, ni ce qu'elle vaudrait à
une autre échelle. À éprouver séparément, et pré-inscrit.

## Ce que ce verdict ne dit pas

Rien sur la rentabilité. Il explique une répartition d'issues sur de la donnée
rattrapée (`resolved_backfill = 1`), pas un edge. Et les `TIMEOUT` sortent au
dernier prix connu, donc leur P&L (+5 116 € sur 1 307 lignes) mesure une
clôture arbitraire, pas une décision.
