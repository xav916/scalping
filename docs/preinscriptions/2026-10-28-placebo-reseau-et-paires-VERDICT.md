# Verdict — le signal `5min` **SURVIT** aux trois contrôles de structure

**Pré-inscription** : `d488119` (v2, remplace `2fb952b`) · **Banc** : `d488119`
**3 prédictions sur 5** · **`or-verdict` : PUBLIABLE — ADMISSION**

## Le résultat

```
n = 4280 / 4280   couverture 100,00 %   moteur 4280 / 4280
bras reel RECALCULE : 24,5 % de desaccord   esperance -0,0593 R
cout median +0,0950 R   entrees sur le reseau horaire : 100,0 %
instants distincts du reel : 2403  (pour 4280 setups)
```

| barreau | placebo | ÉCART | `t` | battus | réseau % | groupes % | σ nul |
|---|---|---|---|---|---|---|---|
| `UNIFORME` | −0,1467 | **+0,0874** | +4,318 | 100 % | 0,0 | 21,9 | 0,02023 |
| `RESEAU` | −0,1513 | **+0,0920** | +4,386 | 100 % | 100,0 | 22,2 | 0,02097 |
| **`RESEAU_ET_PAIRES`** | −0,1498 | **+0,0905** | **+5,602** | 100 % | 100,0 | **100,0** | **0,01615** |

## ✅ Ce qui rend ce résultat croyable : le contrôle de reproduction

Le barreau `UNIFORME` rend **+0,0874 R** et **`t` = +4,318**, contre **+0,0874**
et **+4,3184** publiés en `c5c68dc` — **quatre décimales**. Ma
ré-implémentation du tirage est donc fidèle, et les trois barreaux sont
**comparables entre eux ET au résultat qu'ils remettent en question**.

⛔ Sans ce contrôle, toute différence entre barreaux aurait pu venir de mon code
plutôt que du schéma de tirage. C'était l'arrêt pré-inscrit du banc, et il n'a
pas eu à se déclencher.

## ⚠️ MES PRÉDICTIONS P1 ET P2 ONT ÉCHOUÉ, et « en mieux que prévu »

J'avais prédit que corriger les asymétries **ferait baisser** l'écart, de
+0,0874 à ≈ +0,040 R. **L'écart n'a pas baissé** : +0,0920 puis +0,0905.

🔴 **C'est exactement la configuration d'alarme du 27/10** — les deux
prédictions qui échouent sont les deux qui m'arrangent. Je l'ai donc traitée
comme un défaut possible avant d'y voir un résultat.

### Examen 1 : l'écart n'a pas vraiment bougé

L'erreur-type de la moyenne d'un placebo vaut `0,02024 / √200 = 0,00143 R`.

| comparaison | différence | en erreurs-types |
|---|---|---|
| `RESEAU` − `UNIFORME` | +0,0046 R | **2,27** |
| `RESEAU_ET_PAIRES` − `UNIFORME` | +0,0031 R | **1,54** |

⇒ **Ni le réseau horaire ni l'appariement ne contribuent matériellement à
l'écart.** Mes P1 et P2 n'ont pas échoué parce que l'effet s'inverse, mais
parce que **la contribution est ≈ 0 et le signe est tombé de l'autre côté**.

⚠️ La différence du barreau `RESEAU` (**2,27 σ**) est à la limite du
discernable, et dans le sens **opposé** au mien : entrer à l'heure pleine
serait plutôt **défavorable**. ⛔ **Je ne construis rien sur 2,3 σ d'une seule
cellule** — c'est une observation, pas un résultat.

### Examen 2 — 🔑 ce qui a changé est la VARIANCE NULLE, et elle a BAISSÉ

```
sigma nul UNIFORME          0,02023
sigma nul RESEAU_ET_PAIRES  0,01615     =>  -20,2 %
```

Le `t` passe de +4,318 à +5,602 **à écart quasi constant** : toute la hausse
vient de là.

⇒ **Le placebo uniforme était CONSERVATEUR, pas optimiste.** L'inquiétude qui a
motivé tout ce banc — « le placebo détruit la structure du réel, donc il
sous-estime la variance nulle et le `t` est flatté » — est **réfutée dans son
sens même** : restituer la structure *réduit* la variance nulle.

**Mécanisme plausible** : apparier deux jambes opposées au même instant rend
leurs issues **anti-corrélées** (l'une tend vers l'objectif quand l'autre touche
le stop), ce qui stabilise la moyenne de chaque tirage. ⛔ **Non mesuré** — c'est
une explication, pas un fait, et elle aura sa propre pré-inscription.

## ✅ La correction de la v1 était nécessaire, et le chiffre le prouve

L'arithmétique des collisions qui m'a fait retirer la clause de la v1 prédisait
**1 533** instants distincts pour le placebo apparié. Mesuré : **1 538**
(0,3 % d'écart).

⇒ La clause `abs(instants_distincts_placebo_apparie − instants_distincts_reel) < 1`
aurait **arrêté ce banc**, sur un défaut de ma pré-inscription. La v2 n'était
pas cosmétique.

## ✅ Les instruments discriminent sur la donnée réelle

- `part_entrees_reseau_pct` = **100,0 %** : le réel est bien sur le réseau.
- `part_placebo_reseau_pct` = **100,0 %** sur les deux barreaux réseau, **0,0 %**
  sur `UNIFORME`.
- `groupes_respectes_pct` = **100,0 %** sur le barreau décisif, **21,9 %** et
  **22,2 %** sur les autres. 🔑 Et **21,9 % = 526 / 2 403**, exactement la part
  des groupes à **un seul** setup — l'instrument mesure ce qu'il prétend.

⇒ Aucun « interrupteur armé et inerte » : les trois correctifs ont **agi**.

## ⛔ Et ça ne paie toujours pas

| | valeur |
|---|---|
| écart au placebo décisif | **+0,0905 R** |
| coût médian | **+0,0950 R** |
| **espérance nette du réel** | **−0,0593 R** |

Le signal reste **plus petit que le coût**, et la stratégie **perd** sur cette
période. Rien ici ne change cette conclusion.

## Où en est la réplication du `5min`

| contrôle | écart | `t` |
|---|---|---|
| placebo uniforme (publié `c5c68dc`) | +0,0874 | +4,32 |
| + réseau horaire respecté | +0,0920 | +4,39 |
| + appariement des jambes respecté | **+0,0905** | **+5,60** |

✅ **La réplication est RENFORCÉE, pas affaiblie.** Les trois asymétries que
j'avais identifiées comme explications concurrentes n'expliquent pas l'écart.

⚖️ Et je précise ce que je disais en `409d194` : « hors échantillon, rien
n'exclut une agglomération que cette géométrie ne peut pas voir ». La part
**appariement** de cette dépendance est désormais **traitée**, et elle va dans
le sens conservateur. L'**espacement** entre instants successifs, lui, reste
**non testé** — c'est le placebo par blocs.

## 🔬 Ce qui reste, par ordre

1. **Attribuer la baisse de 20,2 % de la variance nulle** à l'anti-corrélation
   des jambes appariées. Mesure directe, propre pré-inscription.
2. **La même échelle sur l'en échantillon** (18 668 lignes) — non couverte ici.
3. **Le placebo par BLOCS** (décalage circulaire par paire), seul contrôle
   restant sur l'**espacement**.
4. ⚠️ **Et le dispositif lui-même** : ouvrir un achat ET une vente sur la même
   barre **1 877 fois sur 2 403 instants**, c'est deux spreads payés pour une
   exposition nette quasi nulle. Ce n'est pas une question de mesure, c'est une
   question de conception, et elle mérite son propre banc.

🛑 **Je ne propose pas de réarmer l'IA.** REM-002 reste `DISARMED_MANUALLY`.
