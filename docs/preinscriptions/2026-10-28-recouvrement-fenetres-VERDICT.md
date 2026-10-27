# Verdict — recouvrement des fenêtres : **énorme, mais PORTÉ AUSSI par le placebo**

**Pré-inscription** : `35b80d8`, révisée `faf9326` · **Banc** : `faf9326`
**4 prédictions sur 5** · **`or-verdict` : NE PAS PUBLIER** (critère réécrit — voir en bas)

## Le résultat

| | hors échantillon | en échantillon |
|---|---|---|
| `n` · paires · étendue moyenne | 4 280 · 7 · 350 h | 18 668 · 9 · 1 253 h |
| **recouvrement moyen par setup** | **286,0** | **354,2** |
| recouvrement du placebo uniforme | 289,5 | 307,9 |
| redondance `somme / union` | **×131,6** | **×159,9** |
| créneaux de 96 h distincts | **32,5** | **116,8** |
| blocs indépendants — réel | 28,20 | 105,00 |
| blocs indépendants — uniforme | 27,92 | 120,80 |
| **`ratio_blocs` (décision)** | **0,990** | **1,151** |
| plafond atteignable du ratio | 3,99 | 13,42 |
| écart médian entre entrées | **3 600 s** | **3 600 s** |

## ✅ Le recouvrement est bien énorme — la question posée est tranchée

Chaque setup partage sa fenêtre de 96 h avec **286** autres (hors échantillon)
et **354** autres (en échantillon). La somme des fenêtres dépasse leur union
d'un facteur **132** à **160**. Et la période ne contient que **32,5** créneaux
de 96 h réellement distincts hors échantillon, **116,8** en échantillon —
contre un `n` nominal de **4 280** et **18 668**.

⇒ **P1, P2 et P3 tenues**, aux valeurs estimées d'avance près (`n_eff` prédit
≈ 31, mesuré **32,5** ; redondance prédite ≈ 136, mesurée **131,6**).

## 🔑 MAIS LE PLACEBO PORTE LE MÊME RECOUVREMENT — et je retire ma formulation

289,5 contre 286,0 hors échantillon ; 307,9 contre 354,2 en échantillon. Le
tirage uniforme produit **la même dépendance massive**, parce que celle-ci est
une propriété du **dispositif** (fenêtre de 96 h sur une période courte), pas de
la disposition des instants.

⛔ **Je retire ce que j'ai écrit dans `c5c68dc`** : « un `t = +4,32` lu comme
p < 0,0001 **surestime** la certitude ». C'était une formulation de `t` de
Student sur observations indépendantes — **ce `t` ne l'a jamais été**. C'est un
rapport à la dispersion de 200 tirages calculés sur **les mêmes fenêtres
recouvrantes**, qui absorbe donc cette dépendance. **Correction, pas nuance.**

## ⚖️ En échantillon : agglomération réelle de 15 %, et ça ne change rien

105,00 blocs réels contre 120,80 uniformes ⇒ **`k = 1,151`**. Par la table
pré-inscrite, le rapport des écarts-types tend vers `√k = 1,073` :

```
t en echantillon :  6,28 / 1,073  =  5,86     (etait 6,28)
```

⇒ **Conclusion inchangée**, très loin de la barre de 2. C'est le seul endroit où
cette mesure répond vraiment, et elle répond : **borné, et sans conséquence.**

## ⛔ HORS ÉCHANTILLON, LE BANC EST MUET — et c'est là que j'en avais besoin

`ratio_blocs = 0,990`, donc **P4 échoue**. ⚠️ **Ce 0,990 ne veut pas dire
« pas d'agglomération ». Il veut dire « indiscernable ici ».**

350 h d'étendue pour une fenêtre de 96 h ⇒ **3,65 blocs par paire**. Les deux
bras mesurent ≈ **4,0 blocs par paire** : ils sont tous les deux **au sommet de
l'amplitude**, et aucune disposition de 611 instants sur 3,65 blocs ne peut en
laisser un vide. La statistique est **saturée par le bas**.

### 🔴 C'est le MÊME défaut que celui que j'avais corrigé une heure plus tôt

J'ai retiré le rapport des recouvrements parce qu'il saturait (plafond 2,04 pour
un seuil engagé à 2,00). J'ai déplacé la décision sur les blocs en vérifiant que
leur **plafond** laissait de la place (3,99). ⛔ **Et je n'ai pas vérifié le
PLANCHER que la densité de données impose.**

🔑 **La leçon précise** : contrôler l'amplitude **théorique** d'une statistique
ne suffit pas. Il faut contrôler l'amplitude **atteignable compte tenu de la
densité des données**. Ici le plafond valait 3,99 et la plage réellement
accessible était ≈ **[0,95 ; 1,05]** — un seuil à 2,00 y était tout aussi
infalsifiable que celui que je venais de retirer. **Deux fois le même défaut
dans la même séance**, la seconde fois sans l'attraper.

⇒ **P4 échoue pour une raison qui n'est pas une mesure.** Je ne la compte ni
comme confirmation ni comme réfutation.

## 🔬 Fait neuf, non prédit : le détecteur a une CADENCE HORAIRE

**L'écart médian entre deux entrées consécutives vaut exactement 3 600 s**, sur
les deux populations. Et l'écart **moyen** est plus petit (≈ 34 min hors
échantillon) : il y a donc à la fois des **rafales** très serrées et une
**cadence de 60 min** qui structure le reste.

⚠️ Je n'ai pas cherché la cause dans le code. C'est une observation, et elle
mérite sa propre vérification — un pas de temps aussi exact n'arrive pas par
hasard.

## ⛔ `or-verdict` REFUSE, et il a raison

```
=== NE PAS PUBLIER
  - critere REECRIT apres coup : son empreinte ne correspond plus
    a la version commitee
```

**C'est exact** : j'ai révisé le critère après son premier commit (`35b80d8` →
`faf9326`). Que la révision soit **antérieure à la mesure** est vérifiable —
`faf9326` est horodaté **21:35:10 UTC**, la mesure a tourné à **21:36:08 UTC**,
58 secondes plus tard — mais **l'outil ne peut pas le voir**, et je ne le
modifie pas pour me laisser passer. Publié **avec le refus en clair**.

🔑 **La règle pour la prochaine fois** : un critère révisé doit être un
**NOUVEAU fichier**, commité une seule fois. Amender en place détruit
l'empreinte qui est toute la valeur du dispositif.

⛔ **Et je n'ai pas re-pré-inscrit après coup.** Le faire maintenant, résultats
en main, serait bien pire que le refus.

## Où en est la réplication du `5min`

| | avant cette mesure | après |
|---|---|---|
| `t` en échantillon | +6,28 | **+5,86** (corrigé de `k = 1,151`) |
| `t` hors échantillon | +4,32 | **+4,32, non corrigé — non mesurable ici** |

✅ **La réplication de `c5c68dc` tient**, et sa mise en garde statistique est
**corrigée** : il n'y a pas d'inflation naïve à retirer, et l'agglomération
mesurable est bornée à 15 % là où elle est mesurable.

⛔ **Mais le point qui compte reste ouvert** : hors échantillon, rien n'exclut
une agglomération que cette géométrie ne peut pas voir.

## 🔬 La suite, et elle est précise

**Un placebo par BLOCS sur le banc d'espérance** : au lieu de tirer
`uniform(min, max)` par paire, appliquer **un seul décalage circulaire par
paire** à toute la série d'instants réels. Cela préserve **exactement** le
regroupement réel — rafales et cadence horaire comprises — et la dispersion des
tirages devient alors le bon écart-type nul.

⇒ C'est la seule mesure qui tranche hors échantillon, et elle ne dépend
d'aucune statistique géométrique susceptible de saturer.
