# L'amplitude de l'or aux publications : le mécanisme TIENT-IL sur les bougies du COURTIER, et change-t-il une DÉCISION ?

**Déclaré le 2026-10-11, AVANT d'écrire la mesure.** Décision de Xavier :
« les 2 » — ce banc, plus le tableau « bougie suivante » en M1 dès que le
terminal MT5 se reconnecte.

## La question, et pourquoi elle se pose maintenant

Le 2026-10-10 j'ai mesuré que l'amplitude d'une bougie M5 d'or passe de
**1,952 $** de fond à **4,510 $** à une publication **High** américaine
(×2,31, 383 publications). C'était **le seul mécanisme démontré de la
journée** — tout le reste (direction, dollar décalé, §9 des ticks) est mort.

⛔ **Mais il a été mesuré sur `candles_5min.db`**, dont j'ai établi le même
soir qu'il vient de **Twelve Data**, mélange **deux conventions horaires** et
a **2026 troué**. Le chiffre n'est donc **pas défendable**.

✅ Depuis, `candles_courtier.db` existe : **99 750 bougies M5 XAU/USD du
courtier**, 2025-05-14 → 2026-10-09, en **vrai UTC** (formule du décalage
vérifiée 21 jours sur 21, 154 ancres ; coupure hebdomadaire retombée sur
`vendredi 20h55 → dimanche 22h00`).

⇒ Ce banc refait la mesure sur cette source, puis pousse jusqu'à la seule
chose qui change une décision.

## A. LE MÉCANISME — l'amplitude monte-t-elle, et combien de temps ?

Pour chaque publication de `economic_events` (83 813 lignes, `ts_utc` en vrai
UTC, vérifié à 85,7 % sur les heures américaines connues), je relève
l'amplitude `high − low` des bougies M5 à **sept décalages** :

    −30, −15, 0, +5, +10, +15, +30 minutes autour de la publication

croisés avec **trois impacts** (`High`, `Medium`, `Low`) ⇒ **21 cellules**.

### ⚠️ LE CONFOND QUI TUERAIT CETTE MESURE, et comment je l'écarte

Le profil horaire de l'or, mesuré sur ce même magasin :

    13h UTC  7,859 $      03h UTC  3,680 $      ⇒ facteur 2,14

🔑 **Les publications américaines tombent à 12h30/13h30/14h00 UTC**, c'est-à-
dire exactement sur le pic. Comparer « à une publication » contre « le fond de
la journée » ne mesurerait donc **pas la publication : ça remesurerait la
session de New York**, et ça produirait un ×2 par construction.

⇒ Le fond de référence est **APPARIÉ sur l'heure UTC et sur le jour de la
semaine** : une bougie à publication n'est comparée qu'aux bougies de la
**même heure** et du **même jour de semaine** sans publication. C'est la leçon
du « +8,60 contre le hasard » retiré le 01/10.

### Ce que je prédis, maintenant

- à l'offset **0**, impact **High** : rapport dans la bande **1,3 – 2,3**
  *(plus bas que le ×2,31 annoncé hier, précisément parce que l'appariement
  horaire retire ce que la session faisait passer pour la publication)* ;
- **décroissance monotone** de +5 à +30 ;
- **−30 et −15 ≈ 1,0** (rien avant : sinon mon appariement fuit) ;
- **`Low` ≈ 1,0**, `Medium` entre les deux.

⛔ Si le rapport `High` à l'offset 0 tombe **sous 1,15**, j'écris que le ×2,31
d'hier était un **artefact du magasin Twelve Data**, et la piste meurt.

## B. LA DÉCISION — faut-il FERMER la porte autour des publications ?

Une amplitude plus grande **ne crée aucun avantage à elle seule** : dans une
marche sans dérive, atteindre +2 € avant −20 € vaut `20/22 = 90,91 %`
**quelle que soit la volatilité**. Elle ne change que la **vitesse** de
résolution — et le **coût**.

Je rejoue donc la géométrie de production (**TP 2 € / SL 20 €**, soit
2,24 $ / 22,40 $ au taux du courtier) à partir de **chaque clôture de bougie
M5**, dans les deux sens, et je compare :

| | dans la fenêtre `[0, +30 min]` d'une High US | hors fenêtre, **apparié heure × jour** |
|---|---|---|
| réussite du 2/20 | ? | ? |
| spread médian (`spread_pts`, du courtier) | ? | ? |
| euro net par trade | ? | ? |

### Ce que je prédis

- **la réussite ne se distinguera PAS** de 90,91 % dans les deux colonnes —
  la volatilité n'ouvre pas la porte 20/22 ;
- **le spread sera PLUS LARGE** dans la fenêtre (le magasin contient déjà
  1 141 bougies à 40 points et 96 à 50, contre un plancher de 5) ;
- ⇒ **net légèrement NÉGATIF dans la fenêtre**, et la conclusion actionnable
  sera **« fermer la porte, pas l'ouvrir »**.

🔑 Si c'est l'inverse — réussite **au-dessus** du plafond dans la fenêtre —
alors la publication casse la pièce 20/22, et **ça serait la première
trouvaille directionnelle du projet**. Je l'écris maintenant pour ne pas
pouvoir la raconter après coup.

## LE PLAFOND, posé avant de regarder

Pas de Bonferroni arbitraire : **placebo par permutation**. Je tire **200
fois** des faux instants de publication, **appariés sur l'heure UTC et le jour
de semaine** (donc avec le même profil horaire que les vrais), je recalcule
**max |t| sur les 21 cellules**, et le plafond est le **95ᵉ centile** de ces
200 maxima. Une cellule ne compte que si elle le franchit.

⛔ Et le même placebo s'applique à la partie B : `dans − hors` doit battre le
95ᵉ centile des 200 `faux dans − hors`.

## Les limites, dites d'avance

- ⓘ **17 mois, pas cinq ans** : l'historique M5 du courtier s'arrête au
  2025-05-14. Les 51 666 surprises de 2021-2026 restent hors de portée ; les
  codes mensuels n'auront qu'une dizaine d'observations chacun, c'est pourquoi
  ce banc **n'ouvre pas** le découpage par code d'événement.
- ⓘ Je mesure l'**amplitude**, pas la surprise signée : la direction est morte
  (49,83 % à bornes symétriques, 49,07 % sur la bougie suivante).
- ⚠️ `spread_pts` est la valeur portée par la bougie M5 du courtier, pas un
  relevé tick par tick : c'est un **plancher** de ce que coûte vraiment un
  passage dans la minute d'une publication.
