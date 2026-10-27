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
  ⛔ HORS PORTEE : ne juge que les REJEUX. Un banc sans rejeu -- un taux contre
  un seuil arithmetique, une esperance contre un placebo -- sera refuse faute
  d'`ecart_par_trade`, et c'est le comportement juste : publier son verdict
  sans cette skill, jamais fabriquer le champ.
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

- un banc qui n'emet pas `ecart_par_trade` et `valide` : la validite n'est pas
  calculable, donc le verdict n'est pas rendable. ⚠️ Si votre banc n'a PAS de
  rejeu -- un taux contre un seuil, une esperance contre un placebo -- ce refus
  est attendu : voir « HORS PORTEE » plus bas, et surtout **ne fabriquez pas le
  champ** ;
- un rejeu hors de la barre pre-inscrite ;
- une expression de seuil (`admission`, `rejet`, `validite`) sans nombre lisible ;
- un critere dont l'empreinte ne correspond plus a sa version commitee ;
- ⛔ et une empreinte **indeterminable** : ne pas pouvoir comparer n'est pas
  comparer.

## ⛔ HORS PORTEE : les bancs NON APPARIES

**Cette skill juge des REJEUX, et rien d'autre.** Un rejeu rejoue une periode
reelle et se confronte a ce qui s'est passe ; `ecart_par_trade` mesure cette
fidelite, et c'est ce que la condition de validite controle.

Elle ne sait donc **pas** juger un banc qui n'a pas de realite vecue a
laquelle se comparer. Deux cas rencontres le **2026-10-27**, tous deux refuses
sur `[ecart_par_trade] est null` :

| banc | ce qu'il compare | pourquoi hors portee |
|---|---|---|
| `banc_geometrie_1d` (`6fe3d82`) | un taux de reussite a un **seuil arithmetique** (35,71 % = 1/(1+1,8)) | aucun second bras, aucune periode rejouee |
| `banc_esperance_1d` (`b2ed1f6`) | une esperance reelle a un **placebo** de 200 tirages | le placebo n'est pas une realite vecue : c'est une distribution de reference |

### Ce qu'il faut faire face a ce refus

✅ **Le lire comme un refus LEGITIME** et publier le verdict du banc lui-meme,
en disant que `or-verdict` ne couvre pas cette forme. Les deux verdicts du
27/10 ont ete publies ainsi (`cf31258`, `0b8106b`), et c'etait correct.

⛔ **NE JAMAIS fabriquer `ecart_par_trade`.** Emettre `0.0` pour passer la
porte ferait croire a un rejeu de fidelite PARFAITE -- l'exact contraire de la
verite, qui est qu'il n'y a pas de rejeu. C'est la faute que cette skill
existe pour empecher, commise sur son propre champ de controle.

🔑 Emettre en revanche `n` et `t` sous ces noms est **exact** quand ils ont un
sens : `n` est la population du test, et un `z` **est** une statistique de test
standardisee a variance connue. Ce qui est faux, c'est d'inventer une fidelite
de rejeu qui n'existe pas.

### Ce qu'il manquerait pour les couvrir

Une seconde forme de validite, propre aux bancs apparies **a un placebo** :
non pas « le rejeu reproduit-il la realite » mais « le placebo reproduit-il la
structure du reel » -- memes paires, meme nombre d'observations par paire,
meme periode, meme geometrie, meme sens. Le banc du 27/10 la calcule deja
(`risk_pct_median_placebo` contre `risk_pct_median_reel`, `tirages_aboutis`),
mais sous des noms que cette skill ne lit pas. ⚠️ Tant que ce n'est pas fait,
**le refus est le comportement juste** : une skill qui juge une forme qu'elle
ne comprend pas serait pire que son absence.


## Hors v1 (futures extensions)

- Verification que chaque prediction du fichier de pre-inscription est notee
  (exige `sections.compter_predictions`).
- Une **seconde forme de validite** pour les bancs apparies a un PLACEBO, qui
  remplacerait `ecart_par_trade` par « le placebo reproduit-il la structure du
  reel ». Cf. « HORS PORTEE » : tant que ce n'est pas fait, ces bancs sont
  refuses, et c'est volontaire.
