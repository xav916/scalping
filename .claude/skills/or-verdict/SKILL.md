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
  calculable, donc le verdict n'est pas rendable ;
- un rejeu hors de la barre pre-inscrite ;
- une expression de seuil (`admission`, `rejet`, `validite`) sans nombre lisible ;
- un critere dont l'empreinte ne correspond plus a sa version commitee ;
- ⛔ et une empreinte **indeterminable** : ne pas pouvoir comparer n'est pas
  comparer.

## Hors v1 (futures extensions)

- Verification que chaque prediction du fichier de pre-inscription est notee
  (exige `sections.compter_predictions`).
