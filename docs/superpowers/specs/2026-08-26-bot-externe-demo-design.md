# Tester un bot externe sur le démo — conception

**Date** : 2026-08-26
**Statut** : validé, en implémentation

## Ce qu'on cherche à savoir

Un bot externe fait-il mieux que le nôtre ? La question n'a de sens que si sa
sélection est jugée **dans les mêmes conditions** : notre sizing, nos stops, nos
portes, notre comptabilité. D'où le choix retenu — **il envoie ses signaux, nous
exécutons**, sur le démo seul.

L'autre voie (observer son compte à lui) mesurait le package complet mais
mélangeait sa sélection et son exécution, et nous rendait dépendants de ce qu'il
veut bien exposer.

## Le contrat d'entrée

`POST /api/signals/external`, **un jeton par fournisseur**.

| champ | rôle |
|---|---|
| `source` | identifiant du fournisseur, **connu d'avance** |
| `external_id` | idempotence : rejouer le même signal ne double pas l'ordre |
| `pair`, `direction` | instrument et sens |
| `entry_price`, `stop_loss`, `take_profit` | niveaux |
| `horizon`, `pattern`, `confidence` | ce que nos portes lisent |
| `emitted_at` | horodatage d'émission côté fournisseur |

⛔ **Un `source` inconnu est refusé**, jamais accepté « au cas où ». Un jeton
valide pour un `source` ne vaut pas pour un autre.

⛔ **La réponse rend TOUJOURS le motif du refus.** Un fournisseur qui ne sait pas
pourquoi il est filtré croit qu'on l'ignore — et de notre côté, « il n'émet
rien » deviendrait indiscernable de « on jette tout ». C'est la forme de silence
que ce dépôt a déjà payée quatre fois.

## Où le signal débouche

Il devient un setup et part dans `mt5_bridge.send_setup()`. Il traverse donc
**toutes** les portes existantes : admission, whitelist, confiance, horizon,
motifs, coût, plafond de risque, banc d'essai. Aucune n'est contournée, aucune
n'est dupliquée.

### ⛔ Le seul ajout : le verrou dans le résolveur

`resolve_destinations` écarte **toute destination en argent réel** dès que
`source != "interne"`.

> **Le verrou est dans le résolveur, pas dans l'appelant.** Un appelant peut
> oublier ; un résolveur non. Même motif que la porte du banc dans `set_state`,
> et que `destination=None ⇒ argent réel` : on ne place pas une garde là où il
> faut penser à l'appeler.

Corollaire testé : un setup externe poussé **explicitement** vers `admin_live`
n'y arrive pas.

## L'attribution — la partie à ne pas rater

Colonne `source` sur `mt5_pushes` **et** `personal_trades`, portée par le chemin
posé le matin même pour `horizon` : dispatch → poussée → ticket → trade. Défaut
`interne`.

⛔ **À poser avant le premier trade externe.** Sans elle, la performance du bot et
la nôtre se mélangent dans le même P&L et plus rien ne les sépare. Le rattrapage
n'existe pas — l'horizon vient de le démontrer sur 390 676 signaux.

## Le jugement

Un essai déclaré au banc **par fournisseur** :

```
selector = {"sources": ["<fournisseur>"], "destinations": ["admin_legacy"]}
```

Le sélecteur du banc apprend donc `sources`, même patron que `horizons`. `N`
monte du nombre de variantes que le fournisseur déclare — un bot réglable est un
bot à variantes, et le compteur doit le savoir.

## Le risque, même sur démo

Le setup externe passe par `correlation_guard` et le plafond journalier comme les
nôtres. Sinon on comparerait un bot sans contrainte à un moteur qui en a, et
l'écart mesurerait **nos contraintes**, pas sa qualité.

## Hors périmètre

Pas d'UI, pas de facturation, pas de multi-fournisseur simultané, pas de reprise
d'historique. Un fournisseur à la fois suffit à la question posée.

## Ce que les tests verrouillent

1. Un `source` inconnu est refusé.
2. Un jeton valide pour un `source` ne vaut pas pour un autre.
3. **Un setup externe n'atteint AUCUNE destination en argent réel**, même poussé
   explicitement vers elle.
4. Un setup interne continue d'atteindre le réel — le verrou ne déborde pas.
5. Le même `external_id` deux fois produit **un seul** ordre.
6. Le trade enregistré porte sa `source`.
7. Le sélecteur du banc filtre par `source`, et une `source` absente n'est jamais
   assimilée à celle demandée.
8. Un refus rend son motif au fournisseur.

## Ce que ce dispositif ne dira pas

Il mesurera la sélection d'un bot **dans nos conditions d'exécution**, sur le
démo, sur des clôtures postérieures à la déclaration de son essai. Il ne dira
rien de sa performance chez lui, ni de ce qu'il vaudrait avec son propre sizing.
C'est le prix d'une comparaison trait pour trait, et c'est le bon prix.
