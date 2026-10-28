# Verdict — 🔴 **JE RETIRE LE SIGNAL `5min`** : les deux bras n'ont jamais partagé leur MODÈLE D'EXÉCUTION

**Pré-inscription** : `b9cf462` · **Divulgation** : `14c5d81` · **Banc** : `a124732`
**`or-verdict` : NE PAS PUBLIER — ni admission ni rejet**

## Le résultat

```
n = 4280   couverture 100,00 %   reproduction des chiffres publies : 0,001 %
placebo (UNIQUE, inchange) -0,151296   sd nul 0,020967   200 tirages

BRAS REEL           esperance        ECART         t      tirages battus
STOCKE              -0,059336    +0,091961    +4,386        100,0 %
FILL OUVERTURE      -0,197829    -0,046533    -2,219          1,5 %

entrees HORS de leur bougie : stocke 50,2 %   fill 0,0 %
des la 1re bougie, SL / TP1 :
   reel STOCKE  6,2 % / 7,0 %      reel FILL  6,7 % / 0,4 %
   placebo      9,7 % / 2,4 %
```

✅ **La cellule `REF_STOCKE` reproduit les chiffres publiés à 0,001 %.** La
comparaison entre spécifications est donc valide, et **un seul placebo** sert
aux deux cellules — il entre déjà à l'ouverture, donc tout l'écart entre
cellules vient du **bras réel**.

## 🔴 CE QUE JE RETIRE, ET POURQUOI C'EST ÉTABLI

L'écart publié en `c5c68dc` (+0,0557 R en échantillon), `d591d42`/`c5c68dc`
(+0,0874 R hors échantillon), `2613282` (+0,0905 R) et `8935497` (`t ≈ +4,58`)
repose sur un **prix d'entrée non exécutable** :

- `entry_price` n'est **ni une ouverture ni une clôture** de bougie dans
  **87,8 %** des cas — c'est un **niveau de motif** ;
- il tombe **hors de l'amplitude** de sa bougie d'entrée dans **50,2 %** des
  cas (mesuré par le banc, garde `part_entree_hors_bougie_stocke_pct`) ;
- et ce fill accordé est **net favorable** : **11,1 %** d'objectifs déjà
  franchis contre **2,0 %** de stops ;
- ⇒ la **seule première bougie** contribuait **+0,0634 R** au bras réel contre
  **−0,0538 R** au placebo, soit **+0,117 R** d'écart — **plus que l'écart
  total de +0,092 R.**

🔑 **Le placebo, lui, entrait toujours à l'ouverture : un prix toujours
atteignable.** Les deux bras n'ont donc **jamais partagé leur modèle
d'exécution**, et c'est cette asymétrie — non l'instant d'entrée — que le banc
mesurait.

⇒ 🔴 **LE SIGNAL `5min` EST RETIRÉ, comme NON ÉTABLI.** Pas « réfuté » :
**non établi**. Et cela vaut pour **les quatre verdicts** qui s'appuyaient sur
lui.

⇒ **Aucun horizon n'a d'information démontrée à l'entrée** : `1d` pire que le
hasard, `4h` indiscernable, `5min` **retiré**.

## ⚠️ CE QUE JE MESURE MAIS NE PUBLIE PAS COMME VERDICT

Sous la spécification symétrique testée, l'écart devient **−0,046533 R**,
`t = −2,219`, et le réel ne bat plus que **1,5 %** des 200 tirages.

⛔ **`or-verdict` REFUSE d'en faire un verdict**, et il a raison : `écart < 0`
avec `|t| ≥ 2` tombe **entre** mes deux branches déclarées. C'est la branche que
j'avais pré-écrite :

> « l'instant porterait une information **défavorable**, comme le `1d`.
> ⇒ **Même conclusion pratique** : rien à exploiter. »

⇒ Je rapporte ce chiffre comme **mesure**, pas comme conclusion. **Affirmer que
l'instant porte une information défavorable demanderait sa propre
pré-inscription.**

## ⛔ Les prédictions, et ce que j'en compte

| | seuil | mesuré | | compté ? |
|---|---|---|---|---|
| `P1` écart | `< +0,05` | −0,0465 | ✅ | ⛔ **non** (divulgué) |
| **`P2` `|t|`** | **`< 2,00`** | **2,2193** | ⛔ **ÉCHEC** | ✅ oui — ma prédiction **décisive** |
| `P3` espérance réelle | `< −0,12` | −0,1978 | ✅ | ⛔ **non** (divulgué) |
| **`P4` asymétrie 1ʳᵉ bougie** | **`< 2,0 pts`** | **5,0 pts** | ⛔ **ÉCHEC** | ✅ oui — **ma seule prédiction aveugle** |
| `P5` écart | `> −0,08` | −0,0465 | ✅ | ⛔ **non** (divulgué) |

⇒ **Mes deux prédictions qui comptaient ont TOUTES LES DEUX échoué.** Les trois
qui passent étaient connues d'avance (`14c5d81`) et je ne les porte pas au
crédit du banc.

### 🔑 Et l'échec de `P4` est instructif

L'asymétrie n'a pas disparu : **elle a changé de forme**.

```
reel FILL  SL 6,7 %  TP 0,4 %      placebo  SL 9,7 %  TP 2,4 %
```

Le bras réel touche **MOINS SOUVENT LES DEUX barrières** dès la première
bougie. ⇒ **le détecteur tire dans des moments CALMES.** Et avec une géométrie
`1,8 : 1`, c'est net défavorable : `−2,0 pts × 1,8 = −0,036` contre
`+3,0 pts × 1,0 = +0,030`, soit **−0,006 R**.

⚖️ Cohérent avec [[project_volatilite_ni_quand_ni_sens_2026_10_14]] : aucun
motif de volatilité ne dit quand ouvrir.

### Et la première bougie n'explique plus l'écart

```
ecart du a la 1re bougie :  -0,0048 R   (10 % du total)
RESTE de la fenetre      :  -0,0418 R   (90 %)
```

⇒ Sous la spécification symétrique, le désavantage du réel est **réparti sur
toute la fenêtre de 96 h**, pas concentré à l'entrée.

## ⛔ CE QUE JE NE PRÉTENDS PAS

- **Que la production perd −0,1978 R.** C'est une **re-spécification** destinée
  à rendre les deux bras comparables, pas une mesure du P&L réel. Les fills
  réels sont ceux du courtier, et ce banc n'en dit rien.
- **Qu'une autre spécification symétrique donnerait la même réponse.** Exiger
  que le prix **atteigne** le niveau du motif (sinon pas de trade) est tout
  aussi défendable, change `n`, et **n'a pas été testé**. ⇒ Le chiffre publié
  n'est défendable **ni dans un sens ni dans l'autre** : c'est bien un retrait,
  pas un remplacement.
- **Que l'artefact explique le `1d` et le `4h`.** L'échelle `décalage / risk_pct`
  (0,007 · 0,18 · **0,341** pour des écarts de −0,105 · −0,022 · **+0,092**) est
  **monotone** et je l'avais écrite d'avance en `b9cf462` — mais elle reste
  **annoncée, non testée**.

## 🔑 La leçon, et elle complète une famille

Quatre bancs, trois verdicts et une « première réplication du mur » reposaient
sur une comparaison dont les deux bras avaient des **modèles d'exécution
différents**. J'avais vérifié, l'un après l'autre :

- la **géométrie** (paires, `risk_pct`, sens, fenêtre) — symétrique ;
- la **source** des bougies — corrigée le 27/10 (`d591d42`) ;
- la **structure** temporelle (réseau horaire, appariement) — vérifiée le 28/10
  (`2613282`) ;
- ⛔ **l'EXÉCUTION — jamais.**

⇒ **Un placebo doit partager la géométrie, la source, la structure ET LE MODÈLE
D'EXÉCUTION du bras réel.** Et le signe d'alerte était visible depuis le début :
**toute la différence vivait dans la première bougie**, ce que personne n'avait
décomposé.

## 🔬 La suite

1. **Décomposer les écarts `1d` et `4h` par la première bougie** — l'échelle
   annoncée se vérifie ou tombe.
2. **Tester la seconde spécification symétrique** (limite qui doit être
   atteinte), qui change `n` et demande sa propre pré-inscription.
3. **Pré-inscrire la question « l'instant porte-t-il une information
   défavorable ? »**, que ce banc mesure mais ne peut pas conclure.
4. ⚠️ **Et la question de production qui en découle** : si `entry_price` est un
   niveau de motif rarement atteint, **que vaut le vivier d'admission** qui s'en
   sert ? C'est une question d'**exploitation**, pas de mesure.

🛑 **Je ne propose pas de réarmer l'IA.** REM-002 reste `DISARMED_MANUALLY`.
