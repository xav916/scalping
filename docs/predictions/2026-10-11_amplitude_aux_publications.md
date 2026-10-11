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

---

# VERDICT — 2026-10-11

Mesuré le jour même, sur `candles_courtier.db` (99 750 bougies M5,
2025-05-14 → 2026-10-09) et `economic_events` (21 440 publications USD).
Scripts : `scripts/banc_amplitude_publications.py`,
`_isolees.py`, `_grappes.py`, `_b2.py`.

## A. LE MÉCANISME EXISTE, mais il appartient à la GRAPPE, pas à la publication

Brut, les 21 cellules, plafond par permutation **7,765** — 5 le franchissent :

    High   +0 min   n=653   rapport 1,888   t +11,87     <- dans ma bande 1,3-2,3
    Low   +30 min   n=2427  rapport 1,233   t +10,64
    Medium +0 min   n=1735  rapport 1,339   t  +9,77
    High   +5 min   n=653   rapport 1,294   t  +8,10
    Low    +0 min   n=2590  rapport 1,204   t  +8,04

⛔ **Deux de mes prédictions tombent, et la cause est la même.** Je prédisais
une décroissance **monotone** de +5 à +30, et `Low ≈ 1,0`. Mesuré :

    21 440 publications USD tiennent sur 6 230 INSTANTS distincts
    3 557 instants portent 2 publications ou plus
    76,6 % des Low tombent a +/-5 min d'une High ou d'une Medium
    16,9 % des High ont une AUTRE publication a +30 min (+/-5)

🔑 Le `Low +0` et le `Low +30` ne sont donc **pas** des effets Low : c'est une
High ou une Medium qui saigne dedans. Et la remontée à +30 est le **paquet
suivant**, pas une persistance.

### Ce que ça donne quand on classe par TAILLE DE GRAPPE

Plafond **4,738** sur 24 cellules — **une seule** le franchit :

    grappe 5+   max=High   +0 min   n=215   rapport 1,523   t +5,02   ✅ RETENU
    grappe 3-4  max=High   +0 min   n=52    rapport 2,247   t +3,75   sous le plafond
    grappe 1-1  max=High   +0 min   n=102   rapport 1,360   t +3,06   sous le plafond

⇒ **Le mécanisme est réel et il est ÉTROIT** : l'amplitude de la bougie M5
**×1,523** quand **cinq chiffres ou plus** sont publiés à la même minute avec
au moins un High. Une High **seule** donne ×1,360 et ne passe pas le plafond.
Et **rien ne survit à +5 min** : c'est la bougie de la publication, pas la
demi-heure qui suit.

⚠️ **Et je retire mon propre ×2,31 d'hier.** La valeur défendable est
**×1,523** sur une grappe, ou ×1,888 toutes High confondues — mais ce dernier
mélange une publication et un paquet de cinq, donc il ne décrit rien.

## B. ÇA NE CHANGE AUCUNE DÉCISION — et mes prédictions là aussi sont fausses

Première version de la statistique : `t = −4,56`, qui avait l'air concluante.
⛔ **Elle était fausse par PSEUDO-RÉPLICATION** : je répliquais l'écart d'une
strate autant de fois qu'elle contenait d'entrées, donc le `t` grandissait avec
le nombre de jambes au lieu du nombre de strates. Le placebo l'a dit sans
ambiguïté : sur des fenêtres **tirées au hasard**, le 95ᵉ centile du |t|
valait **46,7**.

Refaite avec la strate comme unité (`_b2.py`), 28 strates (heure × jour) :

| | dans `[0, +30 min]` d'une High US | hors, apparié |
|---|---|---|
| réussite du 2/20 | **89,42 %** | **90,26 %** |
| spread moyen | 5,84 pts | 5,59 pts |
| spread p95 | 9,0 pts | 9,0 pts |
| net par jambe | −0,4264 $ | −0,2151 $ |

    dans - hors = -0,0833 $     t = -0,36     plafond = 1,906     ⇒ SOUS LE PLAFOND

- ✅ ma prédiction « la réussite ne se distinguera pas » : **juste** ;
- ⚠️ « le spread sera plus large » : **juste mais trivial** — +0,25 point,
  soit 0,0025 $, et le p95 est identique ;
- ⛔ « net négatif dans la fenêtre ⇒ fermer la porte » : **NON SOUTENU**.
  L'écart est dans ce que produisent des fenêtres au hasard.

## CE QUI RESTE, en une ligne

✅ Un mécanisme de **volatilité** mesuré et défendable (×1,523 sur la bougie
d'une grappe de 5+ dont une High). ⛔ **Aucune** conséquence sur la géométrie
2/20, et la direction reste muette. Pour que cette volatilité devienne de
l'argent, il faudrait un couple objectif/stop qui **paie l'amplitude** — ce qui
est la question de la grille TP/SL, pré-inscrite le même jour, pas celle-ci.
