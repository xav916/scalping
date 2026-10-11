# La bougie SUIVANTE suit-elle le motif ? — en M5 puis en M1

**Question de Xavier, 2026-10-11**, dans ses mots :

> *« si on observe les bougies d'une minute et que là on détecte un des
> patterns, on peut ensuite donner le sens de la bougie suivante qui va suivre
> le pattern, non ? »*

Mesure déclarée **avant de regarder le résultat en M1** : le script
(`scripts/banc_bougie_suivante.py`) a été écrit et éprouvé en **M5** d'abord,
puis relancé **sans un seul changement** sur un magasin M1.

## Ce qui est mesuré, exactement

À la clôture de chaque bougie, on appelle `detect_patterns` sur les **50**
dernières (le `CANDLE_COUNT` de la production), puis on regarde le signe de
`close − open` de la bougie **suivante**.

### Le contrôle, et pourquoi il est indispensable

Un taux brut ne veut rien dire si le marché a dérivé : sur une période
baissière, tout motif « down » gagne sans rien prévoir. On publie donc le
**taux de base** des mêmes bougies, et un **plafond par permutation** — les
détections sont retirées au hasard parmi les bougies de la **même heure UTC**,
200 fois, plafond = 95ᵉ centile du **max |z|**.

## RÉSULTAT — M5, bougies du courtier, 30 000 bougies (08/05 → 09/10/2026)

    detections 55 432, 38 motifs
    taux de base                    49,10 % des bougies montent
    dans le sens du motif           49,13 %
    plafond (max|z|, 200 tirages)   3,072
    motifs qui le franchissent      2 / 30, les DEUX negatifs :
        momentum_down    n=2182   47,02 %  contre base 50,90 %   z -3,62
        order_block_up   n=2674   45,96 %  contre base 49,10 %   z -3,25

🔑 **49,13 % contre un taux de base de 49,10 %** : les motifs font exactement
ce que fait le marché sans eux. Ce n'est pas « sous la pièce », c'est **nul**.

⚠️ Et je corrige ma propre formulation du matin : j'avais dit « 49,07 %, sous
la pièce ». La pièce n'est pas à 50 % ici — l'or clôture sous son ouverture
50,90 % du temps sur cette fenêtre. L'écart à expliquer était donc **0,03
point**, pas 0,93.

## RÉSULTAT — M1, bougies du courtier, 39 337 bougies (01/09 → 08/10/2026)

    detections 74 893, 38 motifs
    taux de base                    49,24 % des bougies montent
    dans le sens du motif           49,63 %
    plafond (max|z|, 200 tirages)   3,002
    motifs qui le franchissent      **0 / 28**        (meilleur |z| = 2,12)

⇒ **En M1, la réponse est NON, et plus nettement qu'en M5** : pas un seul des
28 motifs ne se distingue du hasard, et les deux anomalies négatives du M5 ne
se reproduisent pas — ce qui est la signature de l'échantillonnage, pas d'un
signal.

## Le magasin M1, et sa limite — dite plutôt que cachée

Bâti depuis le pont du courtier (`scripts/batir_magasin_courtier.py`,
paramétré par l'environnement pour ne pas toucher le chemin M5) :

    39 337 bougies M1   2026-08-30 21:59 -> 2026-10-08 12:41
    39 308 ecarts de 1 min exactement, 22 de 62 min (coupure quotidienne),
    5 de ~49 h (week-ends), 0 doublon, 0 retour en arriere

⛔ **La vérification d'ancres ÉCHOUE en M1** : sur les 121 ancres d'exécution
couvertes, **55 tombent exactement dans leur minute et 66 à ±1 minute**. Le
magasin est donc juste **à la minute près**, pas à la minute exacte.

🔑 Pourquoi c'est suffisant **ici** et pas ailleurs : cette mesure n'utilise
que l'**ORDRE** des bougies (motif à l'indice *i*, résultat à *i+1*) et
l'heure UTC au grain de l'heure. Un décalage d'une minute ne change ni l'un ni
l'autre. ⛔ Mais il interdit d'utiliser ce magasin pour **aligner une
exécution**, et le script a raison de refuser son propre contrôle.

## Ce que ça ferme

Le mécanisme que Xavier décrivait — « le motif donne le sens de la bougie
suivante » — est testé **à l'échelle qu'il proposait**, sur les bougies **du
courtier**, avec un contrôle apparié et un plafond de permutation :
**0 retenu sur 28**. C'est le quatrième zéro indépendant sur la direction
(22 motifs M1, 250 cellules de labo, 6 géométries à bornes symétriques, et
celui-ci).
