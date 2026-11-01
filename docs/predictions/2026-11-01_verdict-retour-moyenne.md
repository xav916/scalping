# VERDICT — le retour à la moyenne est REJETÉ sur l'or

Pré-inscription : `2026-11-01_retour-moyenne-hors-echantillon.md`.
Porte : `or-verdict` → **`PUBLIABLE` · `REJET : toutes les clauses tenues`**,
code 0, empreinte du critère intacte.

## Le résultat

Fenêtre **jamais lue** avant cette mesure : XAU/USD, 2023-08-01 → 2025-05-13,
**125 845 bougies M5**, antérieures au magasin du courtier.

```
cellules_retenues            0        (admission exigeait >= 1)
cellules_mesurables          20 / 24  (rejet exigeait >= 12)
n                            11 450 trades
t_vs_hasard maximal          1,912    (plafond du hasard : 2,241)
non_resolus_pct              0,0      (validité exigeait < 5)
valide                       true
```

🔑 **`non_resolus_pct` à zéro** : aucun trade n'a été soldé de force. Tous ont
touché leur stop ou leur objectif, donc chaque R décrit une issue de marché.
C'est l'instrument que j'avais déclaré le 31/10 sans le construire, et il dit
que le rejeu était propre.

## Les deux fenêtres, côte à côte

| | en échantillon (courtier) | hors échantillon (Twelve Data) |
|---|---|---|
| période | 2025-05-14 → 2026-10-09 | **2023-08-01 → 2025-05-13** |
| bougies M5 | 99 750 | 125 845 |
| cellules retenues | **0** | **0** |
| `t_vs_hasard` max | +1,586 | +1,912 |
| plafond du hasard | 2,241 | 2,241 |

Deux fenêtres disjointes, deux sources différentes, **24 hypothèses chacune** —
3 seuils × 4 échelles × 2 sens, exigées aux deux spreads. Aucune cellule
retenue, nulle part. Le motif se déclenche abondamment : 11 450 trades ici,
jusqu'à 1 433 sur une seule cellule en échantillon. Il ne bat jamais des
entrées tirées au hasard de même nombre et de même sens.

## Les prédictions, notées

1. **« Aucune cellule ne sera retenue »** — ✅ `cellules_retenues = 0`.
2. **« Au moins 12 hypothèses mesurables »** — ✅ 20 sur 24.
3. **« `t_vs_hasard` maximal sous 2,0 »** — ✅ 1,912. ⚠️ Mais j'avais écrit
   « avec une marge franche », et 1,912 n'est pas franc : c'est 0,09 sous ma
   propre barre d'alerte. Prédiction tenue, formulation trop confiante.
4. **« L'ordre par échelle se reproduira, croissant de M60 vers M5 »** —
   ⛔ **FAUSSE**, et je l'avais dit falsifiable :

   | | M60 | M30 | M15 | M5 |
   |---|---|---|---|---|
   | en échantillon | 0,205 | 0,515 | 0,987 | **1,586** |
   | hors échantillon | 0,779 | 1,126 | **1,912** | 1,016 |

   En échantillon le `t` croissait régulièrement avec le nombre de trades ;
   hors échantillon le maximum est sur M15 et M5 retombe **sous** M30. Ma
   lecture du mécanisme — « le nombre de trades commande la statistique » —
   est donc fausse.

🔑 **Et cette prédiction fausse renforce le rejet plutôt que de l'affaiblir.**
Si ces `t` mesuraient un effet du motif, leur ordre entre échelles aurait une
raison d'être stable. Il ne l'est pas : il se réarrange d'une fenêtre à
l'autre, ce qui est le comportement du bruit.

## ⚠️ Ce que ce verdict ne dit PAS

- **La source hors échantillon est Twelve Data**, dont ce dépôt a mesuré
  l'écart aux bougies du courtier (3,807 $ de médiane sur quinze mois à
  décalage unique) et conclu qu'un banc d'objectif ou de stop doit y être
  refait. Déclaré d'avance dans la pré-inscription : cette fenêtre ne pouvait
  rendre qu'une **réfutation** utile. C'est ce qu'elle rend, et c'est la seule
  lecture autorisée. Une admission aurait exigé une reprise sur bougies
  courtier.
- **Rien sur BTC/USD ni ETH/USD**, où `mean_reversion` est pourtant armé dans
  **les deux sens** (l'or ne l'est qu'en vente). Twelve Data porte 317 700
  bougies sur chacune : la mesure est faisable et reste à faire. ⚠️ J'avais
  affirmé le contraire — « aucun historique pour BTC ni ETH » — en n'ayant
  regardé que le magasin du courtier. C'était faux.
- **Rien sur un filtre de régime de tendance**, et ce n'est pas un oubli : la
  piste N a été réfutée hors échantillon le 2026-10-08 (`N − B` : t = +2,09 →
  **+0,16**) et le sujet est clos depuis.

## Ce qui est décidé

⛔ **On n'arme rien de plus et on ne desserre aucun seuil.**
`MEAN_REVERSION_SIGMA` reste à 2,0, sa valeur armée depuis le 2026-09-04.
`mean_reversion` reste détecté, journalisé, et sans ordre — ce qu'il est déjà
de fait, n'ayant jamais poussé un seul push quand douze autres motifs en ont
poussé de 6 à 90.

La demande initiale — « peut-on implémenter le retour à la moyenne » — a donc
sa réponse complète : **il était déjà implémenté, déjà armé, et muet** ; le
garde-fou souhaité était **déjà réfuté** ; et sur deux fenêtres disjointes
totalisant 225 595 bougies, **aucun seuil ni aucune échelle ne le sauve**.

## Ce qui reste utile du chantier

- `MEAN_REVERSION_SIGMA`, réglable et testé, qui a rendu ce balayage possible
  sans qu'un second z-score existe dans le dépôt.
- `laboratoire_or` sait désormais dire combien de ses trades ont été **soldés
  de force** (`resolu` par trade, `non_resolus` par cellule). Un R issu d'une
  liquidation administrative ne décrit aucune issue de marché, et la sonde
  nocturne peut maintenant le voir.
