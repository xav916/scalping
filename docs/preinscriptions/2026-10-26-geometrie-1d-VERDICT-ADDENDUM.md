# Addendum — convention A retenue, et une faute dans ma propre pré-inscription

**Décision de Xavier, 2026-10-27** : *« Convention A : sortie au marché à
l'échéance »*. Un `TIMEOUT` est donc une sortie réelle, pas un setup avorté.

## Le verdict mécanique

```
CONVENTION RETENUE : A   (taux 38,69 %, z = +2,298, n = 1362)
VERDICT : ADMISSION_horizon_1d_CONSERVE

pour mémoire, convention B : 29,95 %, z = −3,246, n = 728
VERDICT : REJET_horizon_1d_ECARTE
```

La décision lève l'indécidabilité et **retourne le verdict**, exactement comme
la garde l'avait annoncé.

## 🔴 MAIS CE VERDICT N'ÉTABLIT PAS LE POINT MORT — faute de ma part

Le seuil de **35,71 %** vaut `1 / (1 + 1,8)`. C'est le taux de réussite au
point mort **à la condition que chaque issue vaille exactement +1,8 R ou
−1 R**. C'est vrai d'un `TP1` et d'un `SL`. **Ce n'est pas vrai d'un
`TIMEOUT`.**

Un `TIMEOUT` sort au dernier prix connu : son gain ou sa perte est une
**fraction** de R, pas ±1,8 R / −1 R. Or sous la convention A, **634 issues sur
1 362 — 46,5 %** sont des `TIMEOUT`. Les compter comme des « réussites » de
même poids qu'un `TP1` attribue 1,8 R à des sorties qui n'ont rapporté qu'une
bribe.

⇒ **Le `38,69 % ≥ 35,71 %` compare un NOMBRE de gagnants à un seuil qui ne
s'applique qu'à une structure de gains ±1,8 R / −1 R. Il n'établit donc pas que
la géométrie `1d` est au point mort.**

**C'est une faute de ma pré-inscription**, pas de la décision : j'ai écrit les
branches `admission` / `rejet` comme si le test de taux valait sous les deux
conventions. Il ne vaut que sous B — celle où toutes les issues ont bien la
géométrie annoncée. Sous A, la bonne statistique n'est pas un **taux** mais une
**espérance**.

## Ce que je ne fais pas, et pourquoi

Je **ne calcule pas l'espérance maintenant**. La pré-inscription dit :

> *« une seule cellule pré-spécifiée [...] et aucune autre cellule ne sera
> testée après coup sur cette donnée. »*

Choisir une nouvelle statistique **après** avoir vu que l'admission est fragile
serait exactement la pêche que ce dispositif existe pour empêcher — même si
le résultat m'était défavorable. L'espérance mérite sa **propre
pré-inscription**, avec sa barre dite d'avance et un placebo.

## État de la décision

| | sous A (retenue) | sous B |
|---|---|---|
| verdict mécanique engagé | **ADMISSION** | REJET |
| le seuil de 35,71 % s'applique-t-il ? | **NON** | oui |
| conclusion soutenable | **aucune** | « sous son seuil » |

🔑 **L'horizon `1d` n'est donc ni admis ni écarté sur des bases solides.** Le
verdict engagé dit ADMISSION ; l'arithmétique dit que ce verdict ne mesure pas
ce qu'il prétend. Les deux doivent être lus ensemble, et aucun ordre de
grandeur de rentabilité ne doit être tiré d'ici.

## La suite, si elle est voulue

Un banc d'**espérance** sur l'horizon `1d`, pré-inscrit à neuf :

- espérance en R par setup, `TIMEOUT` à leur P&L réel (convention A) ;
- barre dite d'avance, **au-dessus de zéro et du coût**, pas un seuil de taux ;
- **un placebo** : mêmes paires, même horizon, entrées tirées au hasard — sans
  lui, rien ne distinguera la géométrie du simple fait d'être exposé ;
- et une condition de validité qui annule tout si elle échoue.

⚠️ Et une limite qui vaudra aussi pour ce banc-là : la donnée reste
**rattrapée** (`resolved_backfill = 1`), sur 1 362 setups d'un seul régime de
marché.
