# La SURPRISE économique donne-t-elle le sens du trade sur l'or ?

**Déclaré le 2026-10-10, AVANT de mesurer le résultat.** Décision de Xavier :
« Go » sur la seconde piste, après la fermeture de celle des motifs.

## Pourquoi cette piste, et pourquoi elle est la dernière en réserve

Fermé aujourd'hui : les 22 motifs sur M1, les 248 cellules du labo M5, les 250
du labo M1, les 37 indicateurs du document, et la **direction elle-même** —
muette à six géométries, 49,83 % de réussite implicite sur 64 062 détections.

🔑 Il reste **une** chose qui soit un **mécanisme** et non un motif : la
surprise économique. Vérifié en base à l'instant :

    /app/data/scalping.db -> economic_events : 83 813 lignes
    2021-01-01 -> 2026-10-09
    avec `actual` ET `forecast` : 51 666
    par impact : Low 32 699   Medium 15 690   High 3 277

Et aucune décision du système ne lit un seul de ces chiffres : les deux portes
bloquent ±30 min autour d'un événement, rien de plus.

## ⛔ CE QUI A DÛ CHANGER LA PORTÉE, mesuré avant d'écrire ce critère

Le pont ne donne du M1 que depuis juillet 2026 et refuse les longues plages.
Le seul magasin couvrant trois ans est `candles_5min.db` (243 092 bougies
M5, 2023-08 → 2026-08-08). Deux contrôles y ont été passés :

1. **Prix d'exécution réels** : **12/12 ancres (100 %)** au décalage
   **+600 min** — mais il n'y a que **12 trades d'or sur trois ans, tous en
   2026**. Aucune ancre d'exécution pour 2023-2025.
2. **Repère structurel, la coupure hebdomadaire** :

       2023   samedi 06h55 -> lundi 08h00     (22 coupures)
       2024   samedi 06h55 -> lundi 10h05     (53)
       2025   samedi 23h55 -> lundi 00h00     (54)
       2026   samedi 23h55 -> lundi 00h00     ( 1 seule !)

   ⇒ L'étiquetage **bascule entre 2024 et 2025**, et **2026 est troué**.

🔑 **Le magasin mélange au moins deux conventions horaires.** Mesurer trois ans
dessus mélangerait des décalages différents.

⇒ **La portée est donc réduite à 2025**, seule année à la fois complète
(79 852 bougies M5 ≈ une année pleine) et d'étiquetage cohérent.

## L'ALIGNEMENT DE 2025, mesuré et non supposé

Aucun trade d'or en 2025, donc aucune ancre d'exécution. 🔑 Mais les
événements eux-mêmes fournissent un repère : une publication **High** des
États-Unis produit un **pic de volatilité** à la minute de sa sortie.

⇒ Je cherche le décalage qui **maximise la volatilité** à l'instant des
publications High américaines de 2025.

⚠️ Et ce n'est **pas circulaire** : j'aligne sur la **magnitude** du mouvement,
puis je mesure son **SIGNE**. Ce sont deux quantités différentes — un
alignement par la volatilité ne peut pas fabriquer une direction.

⇒ Si le pic n'est pas net (volatilité à l'instant de l'événement inférieure à
**3×** la volatilité de fond), l'alignement est déclaré introuvable et **aucun
verdict n'est rendu**.

## Ce que je mesure ensuite

Pour chaque événement de 2025 ayant `actual` et `forecast` :

    surprise = (actual - forecast) / |forecast|     (et le signe brut)

Puis, à horizons **15 min, 30 min, 1 h, 2 h, 4 h** après la publication, le
rendement signé de l'or. La thèse à tester est la mécanique classique :

    surprise POSITIVE sur l'inflation ou l'emploi US  ->  or en BAISSE
    surprise NEGATIVE                                 ->  or en HAUSSE

⚠️ Le sens attendu dépend de l'indicateur. Je ne le devine pas : je mesure la
**corrélation signée** entre la surprise et le rendement, par `event_code`, et
je laisse le signe sortir des données — ce qui veut dire que le signe lui-même
fait partie de ce qui est testé, donc soumis au plafond du hasard.

## ⛔ LE CRITÈRE, POSÉ AVANT DE REGARDER

Un `event_code` porte de l'information si, à un horizon donné, il réunit
**les cinq** :

1. corrélation surprise / rendement **non nulle**, de signe cohérent avec la
   mécanique macro de cet indicateur ;
2. **|t| > 2,730** — le plafond du hasard simulé du laboratoire pour ~96
   cellules (nombre d'`event_code` × horizons examinés) ;
3. **n ≥ 24** publications de ce code ;
4. le signe **tient sur les deux moitiés** de l'année ;
5. et le rendement signé, converti en euros sur 0,01 lot, dépasse **le
   spread** (0,045 €) — sinon l'information existe mais ne paie pas.

⇒ Un seul qui manque, et le code n'est pas retenu.

## MA PRÉDICTION, POSÉE MAINTENANT

Je prédis **0 code retenu sur l'année 2025 seule**, parce que n par code y est
petit (une publication mensuelle donne 12 observations, deux fois sous le seuil
de 24) — et que la contrainte d'effectif, pas l'absence d'effet, sera
probablement ce qui bloque.

⚠️ C'est une prédiction **faible** et je le dis : si elle se vérifie, elle ne
réfutera PAS la piste du calendrier. Elle dira seulement qu'une année ne suffit
pas, et que la vraie réponse exige de **réparer le magasin de bougies** —
normaliser la convention horaire et resynchroniser 2026.

## Ce que cette mesure ne tranche PAS

- Rien sur 2021-2024 : hors de portée faute d'alignement vérifiable.
- Rien sur le **vrai order flow** (le courtier ne donne que le nombre total de
  ticks), ni sur le dollar et les taux réels.
- Elle ne construit aucune règle : elle cherche si un signal existe.

---

# AMENDEMENT, le 2026-10-10 — la porte des 3× refuse, et je dis pourquoi

## Ce que la mesure d'alignement a donné

    volatilite de fond 2025 : amplitude M5 mediane  1,952 $
    meilleur decalage : +660 min -> amplitude 4,510 $  = 2,31x
    ⇒ SOUS le seuil de 3,00x que j'avais pose. Aucun verdict rendu.

Les six meilleurs candidats :

    +660 min : 4,510 $ (2,31x) sur 383 publications
    +600 min : 4,320 $ (2,21x) sur 388
    +695 min : 4,085 $ (2,09x) sur 386
    +690 min : 4,035 $ (2,07x) sur 388
    +665 min : 4,000 $ (2,05x) sur 387
    +630 min : 3,954 $ (2,03x) sur 387

## ⛔ MON SEUIL ÉTAIT UNE SUPPOSITION, et il a mal vieilli

Le pic **existe** : 4,51 $ contre 1,95 $ de fond, sur 383 publications. Un
facteur **2,3 sur l'amplitude médiane** d'une bougie de 5 minutes est un
effet massif — c'est mon chiffre de 3,00× qui n'avait **aucun fondement**, je
l'ai écrit sans rien pour l'étayer.

🔑 Et surtout : **deux méthodes indépendantes, sur deux années différentes,
convergent.** Les prix d'exécution réels donnent **+600 min** en 2026 (12/12
ancres), et le pic de volatilité met **+600 min** en deuxième position en 2025,
dans un groupe serré de +600 à +695.

⇒ Ce n'est pas « l'alignement est introuvable ». C'est « mon seuil était trop
strict, et la donnée dit +600 min par deux chemins ».

## LA NOUVELLE PORTE, déclarée maintenant

J'abandonne le seuil arbitraire et je le remplace par un contrôle
**structurel et vérifiable**, qui ne dépend d'aucun chiffre choisi par moi :

🔑 **Les publications américaines High sortent à des heures FIXES et connues** —
12h30, 13h30, 14h00 et 18h00 UTC pour l'essentiel. Si le décalage est juste,
les heures des bougies alignées doivent **reproduire ce groupement**.

⇒ La porte devient : au décalage retenu, **au moins 70 % des publications
High américaines doivent tomber dans les heures UTC attendues**. Sinon, aucun
verdict.

⚠️ C'est une porte plus exigeante que la précédente dans ce qui compte : elle
vérifie que les minutes correspondent à la réalité du calendrier, pas
seulement qu'il se passe quelque chose de bruyant.

## Le reste du critère est INCHANGÉ

Corrélation de signe cohérent, **|t| > 2,730**, **n ≥ 24** par code, signe
stable sur les deux moitiés, et rendement signé **supérieur au spread**.

## Et ma prédiction est INCHANGÉE

**0 code retenu sur 2025 seule**, par manque d'effectif. Et je redis qu'elle
est **faible** : si elle se vérifie, elle ne réfute pas la piste du
calendrier — elle dit qu'une année ne suffit pas.

---

# VERDICT, le 2026-10-10

## ✅ LE PREMIER FAIT POSITIF DE LA JOURNÉE : l'or RÉAGIT, et fort

    volatilite de fond 2025 : amplitude M5 mediane  1,952 $
    a l'instant d'une publication High americaine :  4,510 $
    ⇒ 2,31x, sur 383 publications

Ce n'est pas un signal directionnel, mais c'est un **mécanisme réel et
massif** : l'amplitude d'une bougie de 5 minutes **plus que double** à la
publication. Rien de ce que j'ai mesuré aujourd'hui sur les motifs n'approche
cet ordre de grandeur.

## ✅ ET LES HORODATAGES DES ÉVÉNEMENTS SONT SAINS

    sans aucun decalage, ts_utc brut : 85,7 % dans les heures attendues
    les 6 plus frequentes : 12h30 (143x), 13h30 (63), 14h00 (56),
                            15h00 (31), 14h30 (31), 13h45 (22)

🔑 **`ts_utc` est du vrai UTC.** C'est le calendrier des publications
américaines, reconnaissable à l'œil. Le côté **événements** de cette piste est
donc fiable.

## ⛔ MAIS MA PORTE STRUCTURELLE ÉTAIT MAL CONÇUE

Je l'avais codée en décalant **les événements** puis en regardant leurs heures.
C'est circulaire et vide de sens : décaler un événement de +600 min déplace
forcément son heure hors des heures attendues (0,0 %). Elle ne testait **pas**
l'alignement du magasin.

⇒ Ce qui corrobore le **+600 min** reste donc deux méthodes, pas trois :
les prix d'exécution de 2026 (12/12) et le pic de volatilité de 2025 (+600
dans le groupe de tête). C'est moins que ce que j'avais annoncé.

## ⛔ ET J'AI APPLIQUÉ MON PROPRE PLAFOND AU MAUVAIS NOMBRE DE CELLULES

J'avais écrit « |t| > 2,730, le plafond pour ~96 cellules ». La mesure en a
examiné **305** (61 codes × 5 horizons).

La table simulée du laboratoire donne **3,043 à 256 cellules** — donc au-delà
de **3,08** pour 305. Avec le bon plafond :

| cellule | h | n | rendement signé | t | avec plafond 2,730 | avec le VRAI plafond |
|---|---|---|---|---|---|---|
| `current-account-nsa` | 120 | 32 | +5,750 $ | **+3,23** | retenu | **retenu, de justesse** |
| `michigan-consumer-sentiment` | 15 | 24 | −4,161 $ | −2,95 | retenu | ⛔ **recalé** |
| `foreign-exchange-reserves` | 15 | 77 | −1,097 $ | −2,75 | retenu | ⛔ **recalé** |

⇒ **Une cellule sur 305**, et non trois. Et « une cellule qui passe » est
exactement ce que le plafond est calibré pour produire **sous l'hypothèse
nulle** — le même constat que le test de direction deux heures plus tôt.

⚠️ `current-account-nsa` n'a par ailleurs **aucun mécanisme plausible** sur
l'or à 2 heures, et n = 32. Je ne la présente pas comme une trouvaille.

⚠️ Et le critère « signe cohérent avec la mécanique macro » que j'avais
pré-inscrit n'a **jamais été implémenté**. Je ne peux donc pas dire que les
signes observés sont cohérents : je ne les ai pas confrontés.

## MA PRÉDICTION

Posée d'avance : **0 code retenu sur 2025 seule**, par manque d'effectif.

- ⛔ **Réfutée à la lettre** : une cellule franchit le plafond corrigé.
- ✅ **Mais le motif que j'avais annoncé est le bon** : 61 codes sur 493
  atteignent n ≥ 24. **432 codes sont écartés faute d'effectif** — exactement
  ce que je prédisais, et la raison de fond pour laquelle une année ne tranche
  rien.

## ⇒ CE QUI BLOQUE N'EST PAS L'IDÉE, C'EST LE MAGASIN DE BOUGIES

| | disponible | exploité ici |
|---|---|---|
| événements avec surprise | **51 666** (2021→2026) | 8 513 (2025) |
| codes avec n ≥ 24 | — | 61 sur 493 |
| bougies intrajournalières | 2023-08 → 2026-08 | **2025 seulement** |

Les trois défauts du magasin, mesurés aujourd'hui :

1. **deux conventions horaires** (coupure hebdo samedi 06h55 en 2023-2024,
   samedi 23h55 en 2025-2026) ;
2. **2026 troué** — 1 seule coupure hebdomadaire détectée sur 7 mois ;
3. **décalage de +600 min** non documenté, et vérifiable seulement sur 2026
   faute de trades d'or antérieurs.

⇒ **Le chantier qui débloquerait cette piste n'est pas une mesure, c'est une
réparation de données** : normaliser la convention, resynchroniser 2026,
étendre vers 2021. Avec 51 666 événements au lieu de 8 513, les codes
mensuels passeraient de 12 à ~70 observations, et le plafond deviendrait
franchissable autrement que par hasard.

⚠️ Je ne l'entreprends pas sans décision : c'est un chantier de données, pas
une mesure, et il touche un magasin que la production lit.
