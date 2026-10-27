---
name: or-verdict
description: >-
  Refuse de publier un resultat de mesure sur l'or dont le rejeu n'est pas
  valide. A utiliser AVANT d'annoncer un chiffre, un verdict, un gain, une
  perte evitee ou une conclusion issue d'un banc : recalcule la condition de
  validite pre-inscrite, applique les branches du critere, et refuse si le
  critere a ete reecrit apres coup. Declenche sur : « le resultat est »,
  « la mesure donne », « ca rapporte », « verdict », « conclusion », avant
  tout chiffre issu d'une mesure.
  Juge DEUX formes, declarees par le champ `forme` du resultat : `rejeu`
  (defaut, fidelite mesuree par `ecart_par_trade`) et `placebo` (toutes les
  clauses du critere recalculees), et `seuil` (sans aucun second bras : juge
  sur ses clauses, mais rend `PUBLIABLE SANS CONTROLE` et jamais `PUBLIABLE`).
  ⛔ Ne JAMAIS fabriquer `ecart_par_trade` pour passer la porte : declarer la
  bonne forme est la seule voie.
---

# or-verdict

```bash
python .claude/skills/or-verdict/verdict.py \
  docs/predictions/AAAA-MM-JJ_sujet.md /tmp/resultat_banc.json
```

Code 0 : `PUBLIABLE`. Code 1 : `NE PAS PUBLIER`, avec la raison.

## Pourquoi cette skill existe

Le 25/10, deux mesures, deux issues opposees. Le 12/10 : le rejeu reproduisait
la journee sur **trois cibles** (total, mix de sorties, reussite) -> publiable.
Le hors echantillon : **-0,5731 EUR/trade** contre une barre de **0,50** posee
d'avance -> NON CONCLUANT.

🔑 C'est ce calcul qui m'a arrete, pas ma prudence.

## Ce qu'elle refuse

- un banc de forme `rejeu` qui n'emet pas `ecart_par_trade` et `valide` : la
  validite n'est pas calculable, donc le verdict n'est pas rendable. ⚠️ Si
  votre banc compare le reel a un PLACEBO, declarez `forme: "placebo"` -- il
  sera juge sur ses clauses, et `ecart_par_trade` n'est alors pas attendu. ⛔ Ne
  fabriquez JAMAIS ce champ pour passer la porte ;
- une forme de banc inconnue : elle n'est pas rabattue sur `rejeu` ;
- sur la forme `placebo` : une clause du critere NON TENUE, ILLISIBLE, ou qui
  cite un champ absent du resultat. Un critere ne s'applique pas en partie ;
- un rejeu hors de la barre pre-inscrite ;
- une expression de seuil (`admission`, `rejet`, `validite`) sans nombre lisible ;
- un critere dont l'empreinte ne correspond plus a sa version commitee ;
- ⛔ et une empreinte **indeterminable** : ne pas pouvoir comparer n'est pas
  comparer.

## Les TROIS FORMES de banc jugees

La forme est **declaree** dans le resultat, sous `forme`. ⛔ Elle n'est jamais
devinee : inferer « placebo » de `ecart_par_trade is None` confondrait « il n'y
a pas de rejeu » avec « le rejeu est casse ». Une forme **inconnue** est
refusee, pas traitee comme un rejeu -- se tromper doit rendre bavard, jamais
permissif. Forme absente = `rejeu`, donc toute pre-inscription anterieure au
2026-10-27 est jugee exactement comme avant.

| `forme` | ce qu'elle compare | validite exigee |
|---|---|---|
| `rejeu` (defaut) | une periode rejouee a la realite VECUE | `abs(ecart_par_trade)` sous la barre pre-inscrite |
| `placebo` | le reel a une distribution de REFERENCE | **toutes** les clauses de `validite`, recalculees |
| `seuil` | le reel a une CONSTANTE arithmetique | idem -- mais la decision favorable est `PUBLIABLE SANS CONTROLE` |

### La forme `placebo` (posee le 2026-10-27)

🔑 **Les clauses sont RECALCULEES, le drapeau du banc ne suffit pas.** C'est la
raison d'etre de cette skill : un banc qui s'auto-declare `valide: true` alors
que ses propres nombres violent une clause est **refuse**, et la clause fautive
est nommee avec sa valeur mesuree.

⛔ **`admission` et `rejet` sont evalues EN ENTIER**, pas sur leur premier
nombre. Un critere a trois clauses dont on ne verifierait que le `t` donnerait
un feu vert sur un critere PARTIEL -- et c'est exactement sur un critere
partiel que le banc du 27/10 aurait ete publie a tort.

Trois formes de clause sont comprises, separees par ` ET ` :

```
champ <op> nombre                     n_reel >= 1000
champ_a <op> champ_b                  esperance_R_reel > cout_R_median
abs(champ_a - champ_b) <op> nombre    abs(risk_pct_median_placebo
                                          - risk_pct_median_reel) < 1.0
```

⛔ **Une clause illisible REFUSE, elle n'est pas ignoree.** Passer outre une
clause non comprise reviendrait a publier sur un critere partiel. Idem pour un
champ cite par le critere mais absent du resultat, ou non numerique : refus,
en le nommant.

⚠️ L'evaluateur est **volontairement etroit**. Un evaluateur d'expressions
arbitraires ne serait pas auditable, et ce qui juge une mise en production doit
l'etre. Une quatrieme forme de clause se rajoute en quelques lignes, avec son
test ; elle ne doit pas se deviner.

### La forme `seuil` (posee le 2026-10-27)

Un banc **sans aucun second bras** : il compare une mesure a une constante
pre-inscrite -- par exemple un taux de reussite aux **35,71 %** qu exige un
R:R de 1,8. Mecaniquement, c est le meme evaluateur que `placebo`.

⛔ **Sa decision favorable est `PUBLIABLE SANS CONTROLE`, jamais `PUBLIABLE`.**
Un banc sans controle ne peut pas dire s il existe une **information** ; il dit
seulement si une geometrie atteint **son propre seuil**. Rendre `PUBLIABLE`
effacerait cette difference dans la seule sortie que quelqu un lit vraiment.
La note part avec la decision :

```
=== PUBLIABLE SANS CONTROLE
  - REJET : toutes les clauses tenues -- ⛔ AUCUN CONTROLE : ce banc n a ni
    rejeu ni placebo, donc il ne dit PAS s il existe une information,
    seulement si une geometrie atteint son propre seuil arithmetique. Une
    comparaison a des entrees tirees au HASARD reste a faire.
```

ⓘ Le **code de sortie vaut 0** : c est publiable. Ce qui change est ce que la
sortie DIT, pas le droit de publier -- un code 1 ferait croire a un refus, et
un code 0 muet ferait croire a un controle.

### 🔑 Ce que ces formes apportent MEME sans controle

Le lien **NOM PAR NOM** entre les champs que le critere engage et ceux que le
banc emet. Mesure du 2026-10-27 sur le banc de la geometrie 1d :

| cite par le critere | emis par le banc, avant correction |
|---|---|
| `n_resolus_1d` | `n_1d_resolus_TP1_ou_SL` |
| `reussite_1d_resolus_pct` | `P3_reussite_1d_convention_B_pct` |
| `z_binomial` | `P3_z_binomial` |
| `part_rows_RR_conforme_pct` | `P1_rr_conforme_1d_pct` |
| `part_mfe_non_nul_pct` | `validite_mfe_non_nul_pct` |

**Cinq noms sur cinq divergeaient**, et rien ne l avait vu : le banc evaluait
ses branches en interne avec des constantes recopiees, et son test ne
verifiait que les NOMBRES. 🔑 Un critere engage sous un nom et mesure sous un
autre n est pas un critere.

### Ce que la forme `placebo` ne dit toujours PAS

Elle verifie que le **placebo reproduit la structure du reel** (memes paires,
meme nombre d'observations, meme periode, meme geometrie, meme sens -- via les
clauses que la pre-inscription ecrit). Elle ne verifie **pas** que le placebo
est un bon contrefactuel : ca, c'est la conception du banc, et aucune skill ne
la remplace.

## Hors v1 (futures extensions)

- Verification que chaque prediction du fichier de pre-inscription est notee
  (exige `sections.compter_predictions`).
- ✅ **FAIT le 2026-10-27** : la seconde forme de validite pour les bancs
  apparies a un PLACEBO. Cf. « Les DEUX FORMES de banc jugees ».
