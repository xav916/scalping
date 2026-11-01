# Le retour à la moyenne sur BTC et ETH

Troisième pré-inscription sur ce motif, et celle qui comble le vrai trou.

Le verdict du 01/11 l'a **rejeté sur l'or** — deux fenêtres disjointes, 225 595
bougies, aucune cellule retenue. Mais `mean_reversion` est armé sur le démo
**plus largement** sur la crypto que sur l'or :

| paire | sens armés |
|---|---|
| BTC/USD | `mean_reversion_up` **et** `_down` |
| ETH/USD | `mean_reversion_up` **et** `_down` |
| XAU/USD | `_down` seul |

⛔ **Les deux paires les plus largement armées n'ont jamais été mesurées.** Et
j'avais affirmé à Xavier qu'aucun historique n'existait pour elles, n'ayant
regardé que le magasin du courtier. C'était faux : Twelve Data en porte
**317 702** (BTC) et **317 755** (ETH).

## La fenêtre

**2023-08-01 → 2026-08-08**, les deux paires, 635 457 bougies M5 au total.
Jamais lue pour ce motif.

## ⚠️ DEUX limites, assumées d'avance

**1. La source est Twelve Data**, comme pour la fenêtre hors échantillon de
l'or. Ce dépôt a mesuré son écart aux bougies du courtier (3,807 $ de médiane
sur quinze mois à décalage unique) et conclu qu'un banc d'objectif ou de stop
doit y être refait sur bougies courtier. ⛔ Il n'existe **aucune** bougie
courtier pour la crypto : ce verdict ne pourra donc pas être « refait » — il
restera le meilleur disponible, pas un définitif.

**2. Le spread du courtier n'est PAS mesuré.** `spreads_minute.db` ne porte que
l'or. J'ai mesuré sur Kraken le 2026-11-01 :

```
BTC/USD  bid 77 846,0  ask 77 847,0  ->  1,00 $   (0,0013 % du prix)
ETH/USD  bid  2 264,3  ask  2 264,4  ->  0,10 $   (0,0044 % du prix)
```

Ce sont des **futures perpétuels**, plus serrés qu'un CFD MT5. J'encadre donc :
borne basse = la valeur mesurée, borne haute = un CFD pessimiste (40 $ sur BTC,
3 $ sur ETH, soit ~0,05 % et ~0,13 %).

🔑 **Le sens de l'erreur est sûr pour une réfutation.** Un spread plus serré ne
peut qu'AIDER le motif : s'il échoue à la borne basse mesurée, l'échec ne
s'explique pas par un coût que j'aurais surestimé. Une admission à la seule
borne basse, en revanche, serait suspecte et exigerait un spread courtier réel
avant tout armement.

⚠️ Et le spread est ABSOLU quand le prix de BTC a varié de ~25 000 à
~120 000 $ sur la fenêtre. La borne basse restant sous 0,005 % du prix sur
toute la plage, la distorsion ne menace pas une réfutation ; elle menacerait
une admission.

## L'appareil

`laboratoire_or`, inchangé : rejeu **séquentiel**, **stop testé avant**
l'objectif, **spread facturé** en R, **stops placebos écartés** (< 0,1 % du
prix), **contrôle aléatoire apparié en nombre et en sens**, et le détecteur
**de production** dont le seuil est balayé par `MEAN_REVERSION_SIGMA`.

48 cellules : 3 seuils (1,5σ / 2,0σ / 2,5σ) × 4 échelles (M5, M15, M30, M60)
× 2 sens × **2 paires**. Le plafond du hasard pour 48 cellules vaut **2,496**
(`plafond_hasard(48)`).

## LE CRITÈRE

`forme: placebo` — le second bras est le contrôle aléatoire. Aucun rejeu d'une
réalité vécue à reproduire : `mean_reversion` n'a jamais passé le moindre ordre
(0 push sur 436).

Une hypothèse est **retenue** quand le laboratoire la retient avec le plafond
des 48 (`t_vs_hasard > 2,496` **et** `r_moyen > 0`), que son
`delta_hasard > 0,02`, qu'elle compte `n >= 20`, et que cela tient **aux deux
spreads**. Les clauses de validité **épinglent** ces seuils aux valeurs que le
banc déclare avoir appliquées.

<!-- CRITERE-MACHINE
forme: placebo
admission: cellules_retenues >= 1
rejet: cellules_retenues < 1 ET cellules_mesurables >= 24
validite: non_resolus_pct < 5 ET bougies_m5 >= 600000 ET plafond_applique >= 2.496 ET min_delta_hasard_applique >= 0.02 ET min_trades_applique >= 20 ET spreads_exiges >= 2 ET paires_mesurees >= 2
cellules: 48
plafond: permutation_p95
-->

**Admission** — au moins une hypothèse retenue. ⛔ Si cela arrive, les deux
limites ci-dessus s'appliquent et **rien n'est armé** avant d'avoir un spread
courtier réel.

**Rejet** — aucune hypothèse retenue **et** au moins 24 des 48 réellement
mesurables. La seconde clause évite de confondre « rien n'a été retenu » avec
« rien n'a pu être mesuré ».

**Validité du rejeu** — sept clauses : moins de 5 % de trades soldés de force,
au moins 600 000 bougies lues, les deux paires effectivement mesurées, et les
quatre seuils du banc épinglés.

## Les prédictions

1. **Aucune hypothèse ne sera retenue** : `cellules_retenues` vaudra 0. Sur
   l'or, le `t_vs_hasard` maximal plafonnait à +1,586 en échantillon et +1,912
   hors échantillon, contre des plafonds de 2,241.
2. **Au moins 24 hypothèses seront mesurables**, donc le rejet sera
   prononçable. La fenêtre compte cinq fois plus de bougies que celle de l'or,
   et la crypto cote 24 h sur 24 — le volume ne devrait pas manquer.
3. **Le `t_vs_hasard` maximal restera sous 2,496.**
4. **BTC et ETH se comporteront pareil** : ni l'une ni l'autre admise. Si une
   seule passait, ce serait le profil d'un artefact de paire — deux actifs
   dont la corrélation dépasse 0,8 n'ont pas de raison de différer sur un
   motif aussi simple, et je le dirais plutôt que de célébrer la gagnante.

## Ce que le résultat décide

- **Rejet** ⇒ le motif est clos sur les trois paires où il est armé. La suite
  cohérente est de le **désarmer du démo** : le garder armé après trois
  réfutations contredirait « ne jamais élargir avant d'avoir validé ».
- **Admission** ⇒ aucun armement supplémentaire. Il faudrait d'abord un spread
  courtier mesuré sur la crypto, qui n'existe pas aujourd'hui.
- **Refus de la porte** ⇒ volume insuffisant, et la question reste ouverte
  sans qu'on ait le droit de la dire tranchée.

⛔ Dans les trois cas l'argent réel est hors d'atteinte : sa liste blanche ne
porte que `range_bounce_*`, et les extras sont démo-seulement par construction.
