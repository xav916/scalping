# Verdict — mécanisme CONFIRMÉ, et il corrige le `t` de `2613282` à la baisse

**Pré-inscription** : `a176cdf` · **Banc** : `e63cf0a`
**4 prédictions sur 5** · **`or-verdict` : PUBLIABLE — ADMISSION**

## Le résultat

```
n = 4280   couverture 100,00 %   duos = 1877   2D/N = 0,87710
reproduction de 2613282 : ecart maximum 0,000 %

ecart RESEAU           +0,091961   (sd nul 0,020967)
ecart RESEAU_ET_PAIRES +0,090488   (sd nul 0,016153)   t +5,602

rho intra-duo PLACEBO : -0,4432   (sur 375 400 duos-tirages)
rho intra-duo REEL    : -0,1273   (sur 1 877 duos)
une jambe TP1 / l autre SL : 66,3 % du placebo, 53,0 % du reel

sd nul PREDIT depuis rho : 0,016393  contre 0,016153 observe  =>  ecart 1,48 %
```

## ✅ LE MÉCANISME EST CONFIRMÉ — la baisse de 20,2 % est comprise

| | prédit **avant** | mesuré |
|---|---|---|
| `ρ` du placebo apparié | **−0,4634** | **−0,4432** (4,4 % d'écart) |
| reconstruction de l'écart-type | < 15 % | **1,48 %** |

🔑 **C'est `P3` qui compte, et elle tient à 1,48 %.** Le `ρ` mesuré
**reconstruit** l'écart-type nul observé par la formule pré-inscrite
`sd = sd_base × √(1 + (2D/N)·ρ)`. Sans anti-corrélation, l'écart aurait été de
**29,8 %** — vingt fois plus. ⇒ La baisse de variance n'est plus un fait
inexpliqué : **elle vient bien de l'anti-corrélation des deux jambes.**

`P5` le rend concret : dans **66,3 %** des duos du placebo, une jambe atteint
l'objectif et l'autre le stop.

## ⛔ MAIS P4 ÉCHOUE, ET ÇA CORRIGE `2613282`

`ρ` sur les **duos réels d'août** : **−0,1273**, contre −0,4432 au placebo
apparié. Seuil engagé : −0,20.

⚠️ **Et ce n'est pas du bruit.** Sur 1 877 duos, l'erreur-type vaut 0,0231 :
le `ρ` réel est à **5,5 σ de zéro** — donc franchement négatif — mais à
**3,2 σ du seuil**. **Les duos réels sont réellement bien moins anti-corrélés
que ceux du placebo.**

### 🔑 La conséquence, chiffrée

Le placebo apparié est **PLUS** anti-corrélé que le réel, donc son écart-type
est **trop petit** comme référence nulle. En injectant le `ρ` **réel** dans la
même formule :

| référence nulle | σ | `t` |
|---|---|---|
| placebo apparié (`ρ = −0,443`) | 0,016393 | **+5,520** |
| **`ρ` RÉEL (`−0,127`)** | **0,019762** | **+4,579** |
| sans appariement (`ρ = 0`) | 0,020967 | +4,316 |

⛔ **Je retire donc le `t = +5,602` comme « le bon chiffre »** annoncé en
`2613282`. Le chiffre défendable est **≈ +4,58**.

⇒ Et par conséquent : **le placebo uniforme était À PEINE conservateur**
(+4,32 contre +4,58), **pas conservateur de 28 %** comme le barreau apparié le
suggérait. ✅ **La conclusion de fond ne bouge pas** — `t ≈ +4,6`, très au-dessus
de 2 — mais **la magnitude que j'avais annoncée était surestimée.**

### Pourquoi le réel est moins anti-corrélé — et je l'avais pré-écrit

Dans le placebo, les deux jambes d'un duo partagent **la même entrée**
(l'ouverture de la bougie tirée) : leurs barrières sont donc quasi en miroir.
Dans le réel, **chaque jambe porte son propre prix d'entrée d'août** — différent
dans **94 %** des duos, avec un rapport des `risk_pct` de médiane **1,11** — ce
qui **dissymétrise** les barrières et dilue l'anti-corrélation.

✅ Corroboré par `P5` : une jambe `TP1` / l'autre `SL` dans **66,3 %** du
placebo contre **53,0 %** du réel.

## ✅ Le contrôle de reproduction a attrapé un BUG au premier passage

Première passe : **écart maximum 153,05 %**, banc **ARRÊTÉ**. Diagnostic : les
deux barreaux de placebo étaient exacts (σ 0,02096715 et 0,01615326, identiques
au publié) et **seul le bras réel était faux** — **−0,19783** au lieu de
−0,059336.

🔴 **Cause** : j'avais évalué le bras réel avec l'évaluateur du **placebo**, qui
recalcule `entry`/`sl`/`tp` depuis la bougie tirée. Le bras réel doit garder ses
**bornes d'août** et ne rejouer que l'**issue**.

🔑 **Sans ce contrôle j'aurais publié un `ρ` calculé sur un bras réel faux.**
C'est la première fois dans cette série qu'un garde-fou **d'outillage** attrape
un défaut avant publication, et non une prédiction chiffrée. Après correction :
**0,000 %**.

## ⚠️ Transparence sur l'ordre des faits

J'ai **vu** `ρ(placebo)`, `P3` et `P5` dans la passe arrêtée, **avant** de
corriger le bras réel. Deux garanties :

- la correction ne touche **que** le bras réel, et le chemin du placebo est à
  **graine fixe** — ces trois valeurs étaient donc déjà arrêtées ;
- **aucun seuil n'a été modifié**, et la seule prédiction encore inconnue était
  `P4` — **c'est précisément celle qui a échoué.**

## ⚠️ Limites, et une qui pèse

- 🔴 **La formule suppose la variance PAR JAMBE identique entre schémas.** Non
  vérifié. Si elle diffère, mon `t ≈ +4,58` corrigé est lui-même approximatif.
  ⇒ C'est la limite la plus sérieuse de ce verdict.
- **Groupes supposés indépendants entre eux**, alors que les fenêtres de 96 h se
  recouvrent massivement (cf. `409d194`). Le `ρ` déduit absorbe une part de
  cette dépendance inter-groupes.
- **Hors échantillon seulement** : 4 280 lignes, 7 paires crypto, 05 → 19/08.
- Mesure **descriptive** : elle explique un écart-type, elle ne dit **rien** de
  plus sur l'existence du signal.

## Où en est la réplication du `5min`

| étape | `t` |
|---|---|
| placebo uniforme (`c5c68dc`) | +4,32 |
| barreau apparié brut (`2613282`) | ~~+5,60~~ **retiré** |
| **corrigé du `ρ` réel (ici)** | **+4,58** |

✅ **Le signal tient**, et son `t` défendable vaut **≈ +4,6**.
⛔ **Et ça ne paie toujours pas** : écart **+0,0905 R** contre un coût de
**+0,0950 R**, espérance nette **−0,0593 R**.

## 🔬 La suite

1. **Vérifier la variance par jambe** entre schémas — c'est ce qui rendrait le
   `t ≈ +4,58` exact plutôt qu'approché.
2. **La même échelle en échantillon** (18 668 lignes).
3. **Placebo par BLOCS** — l'**espacement** reste le dernier axe de dépendance
   non testé.
4. ⚠️ **Et le dispositif** : **1 877 straddles sur 2 403 instants**, deux
   spreads pour une exposition nette quasi nulle. Question de conception.

🛑 **Je ne propose pas de réarmer l'IA.** REM-002 reste `DISARMED_MANUALLY`.
