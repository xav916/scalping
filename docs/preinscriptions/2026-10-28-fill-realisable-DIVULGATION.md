# ⛔ DIVULGATION — je connais déjà quatre des cinq réponses, et il faut le dire

**Écrit le 2026-10-28, APRÈS la pré-inscription `b9cf462`, AVANT toute mesure
de ce banc.** Ce fichier est séparé **exprès** : amender la pré-inscription
détruirait son empreinte, et `or-verdict` aurait raison de la refuser.

## Ce que je savais sans m'en rendre compte

La **passe ARRÊTÉE** du banc d'anti-corrélation (`a176cdf`, premier passage)
avait un bug : j'y évaluais le bras réel avec l'évaluateur du **placebo**, qui
calcule `entry = open(bougie après la barre)` et place les barrières à
`± risk_pct` autour.

🔴 **Ce bug EST exactement la spécification `FILL_OUVERTURE` que je viens de
pré-inscrire.** Les chiffres décisifs étaient donc déjà sous mes yeux :

```
esperance reelle (bug = specification FILL) : -0,197829
ecart au placebo RESEAU                     : -0,046533
sd nul                                      :  0,020967
=> t                                        : -2,2193
```

## Confrontation à mes prédictions pré-inscrites

| | seuil engagé | valeur déjà connue | |
|---|---|---|---|
| `P1` écart | `< +0,05` | **−0,0465** | ✅ PASSE |
| **`P2` `|t|`** | **`< 2,00`** | **2,2193** | ⛔ **ÉCHEC** |
| `P3` espérance réelle | `< −0,12` | **−0,1978** | ✅ PASSE |
| `P5` écart | `> −0,08` | **−0,0465** | ✅ PASSE |
| `P4` asymétrie 1ʳᵉ bougie | `< 2,0 pts` | **non mesurée** | — |

⇒ **Quatre réponses sur cinq étaient déterminées avant que j'écrive le
critère.** Seule `P4` est encore inconnue.

## 🔑 Ce qui plaide pour que ma dérivation ait été indépendante

Mes estimations pré-inscrites venaient de l'arithmétique de la première bougie,
et elles sont **nettement FAUSSES — dans le sens qui ne m'arrange pas** :

| | prédit | réel |
|---|---|---|
| espérance réelle | ≈ **−0,166** | **−0,1978** |
| écart | ≈ **−0,015** | **−0,0465** |
| `t` | ≈ **−0,7** | **−2,2193** |

J'ai sous-estimé l'effet d'un facteur **3** sur le `t`. Si j'avais retro-ajusté
mes seuils sur un chiffre connu, j'aurais placé `P2` ailleurs que là où elle
échoue. ⚠️ **Cela ne me dédouane pas** : la bonne discipline était de vérifier
si la réponse existait déjà **avant** d'engager des seuils, et je ne l'ai pas
fait.

## Conséquence pour la lecture du verdict

- ⛔ **`P1`, `P3` et `P5` ne comptent pas comme des prédictions tenues.** Je ne
  les porterai pas au crédit du banc.
- ✅ **`P2` compte comme un échec**, et c'était ma prédiction **décisive**.
- ✅ **`P4` reste une vraie prédiction aveugle.**
- 🔑 **La valeur de la passe à venir n'est plus prédictive, elle est
  CONFIRMATOIRE** : un banc dédié, avec son contrôle de reproduction sur
  `REF_STOCKE`, ses gardes de re-spécification et ses tests — au lieu d'un
  chiffre tombé d'un bug.

## Et la branche de décision où cela atterrit

`écart < 0` **et** `|t| ≥ 2` ⇒ **ni admission ni rejet**. C'est la branche que
j'avais écrite d'avance :

> « l'instant porterait une information **défavorable**, comme le `1d`.
> ⇒ **Même conclusion pratique** : rien à exploiter. »

⇒ Le `5min` ne rejoindrait donc **pas** le `4h` (indiscernable) mais le **`1d`**
(**pire que le hasard**). Je ne l'écris pas comme conclusion — la mesure reste à
faire proprement — mais c'est là que les chiffres connus pointent, et le dire
maintenant m'interdit de le présenter comme une découverte ensuite.
