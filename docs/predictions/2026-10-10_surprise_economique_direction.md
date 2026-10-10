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
