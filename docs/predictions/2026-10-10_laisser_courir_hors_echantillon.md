# « Laisser courir » tient-il hors échantillon ?

**Déclaré le 2026-10-10, AVANT d'écrire la mesure.** Décision de Xavier :
« Lancé la vérification » — avant d'armer quoi que ce soit.

## D'où vient l'hypothèse

Sur les **92 chemins reconstruits de la semaine du 05 au 09/10**, laisser
chaque trade d'or courir jusqu'à son objectif 2 € ou son stop 20 € donnait
**+44,04 €** (75 TP, 0 SL) contre **−6,05 €** réellement obtenus.

⇒ Avantage en échantillon : **+50,09 € sur 92 trades = +0,544 € par trade.**

⛔ Cette semaine est **celle qui a formé l'hypothèse**. Elle ne peut pas la
tester.

## Pourquoi je refuse d'armer sans ce test

Il y a deux heures, le signal `|Z| > 2` donnait **+0,96 $ par trade** sur
21 jours. Élargi à 56 jours : **+0,0024 $**. Un facteur **400**. Et mon
« +8,60 contre le hasard » du 01/10 avait été retiré pour la même raison.

🔑 Une mesure sur une fenêtre courte n'est pas un résultat, c'est une
hypothèse.

## Ce que je mesure

Sur **tous les trades d'or réels** de `personal_trades` (destination
`admin_live`) des **120 derniers jours**, chemin reconstruit minute par minute
depuis les bougies **M1 DU COURTIER**, je rejoue sur **les mêmes entrées** :

| politique | règle |
|-----------|-------|
| **A — laisser courir** | premier contact de l'objectif 2 € ou du stop 20 €, rien d'autre ne touche le stop |
| **B — la machinerie** | l'échelle de gains (`1,0:0,75 / 1,5:1,25 / 1,75:1,5 / 2,0:1,75`) **et** la protection de perte (fenêtre 300 s, moitié 150 s, stop ÷2, plancher perte + 2 €), telles qu'elles tournent en production |

⇒ Comparaison **APPARIÉE** : mêmes entrées, mêmes chemins, mêmes bornes
initiales. Le P&L réel sert de troisième colonne, pour référence seulement.

## ⛔ LE CRITÈRE, POSÉ AVANT DE REGARDER

« Laisser courir » est **retenu** s'il réunit **les quatre** :

1. avantage `A − B` **> 0** ;
2. **|t| > 2**, l'unité étant **LE JOUR** et non le trade — des trades du même
   jour partagent le même chemin, un `t` par trade serait gonflé ;
3. **n ≥ 100 trades** et **≥ 20 jours** ;
4. le signe de l'avantage **tient sur les DEUX moitiés** de la période.

⇒ Un seul qui manque, et **on n'arme pas**.

## MA PRÉDICTION, POSÉE MAINTENANT

Je prédis que l'avantage **rétrécit fortement** : je prédis `A − B` **sous
+0,20 € par trade** hors échantillon, contre +0,544 € en échantillon.

⇒ S'il reste **au-dessus de +0,20 €** avec les quatre critères, ma prédiction
est réfutée et l'expérience est justifiée.

## Garde-fous du rejeu

- ⛔ **Alignement MESURÉ par jour**, jamais supposé : les horodatages du pont
  dérivent (décalage vu de +10 796 à −64 209 s). On cherche le décalage qui
  place le plus de prix d'exécution réels dans la bougie correspondante, et un
  jour qui n'atteint pas **95 % d'ancres** est **ÉCARTÉ**.
- ⛔ Dans une bougie qui contient l'objectif **ET** le stop, on prend le
  **STOP**. Supposer l'objectif fabriquerait le résultat.
- ⛔ Le **spread est facturé** sur les deux politiques.
- ⚠️ Les trades ouverts **dans le terminal MT5** (`notes` = `MANUEL-TERM`) sont
  comptés **à part** : l'échelle et la protection ne les adoptent que depuis le
  09/10.

## Ce que cette mesure ne tranche PAS

- Elle ne dit rien d'un **autre couple** objectif/stop que 2 €/20 €.
- Elle ne dit rien de la **direction** des entrées : elle prend les entrées
  réelles comme données et ne compare que la **gestion de sortie**.
- Elle ne simule pas le **réemploi de la marge** : un trade qui se ferme tôt
  libère une place. Si « laisser courir » gagne, ce gain est **surestimé** de
  ce que les trades suivants auraient rapporté.

---

# AMENDEMENT, le 2026-10-10 — déclaré AVANT de mesurer

## ⛔ Le test tel que pré-inscrit n'est PAS RÉALISABLE

Comptage fait juste après la pré-inscription, avant toute mesure :

    120 jours : 172 trades d'or reels sur 30 jours
    dont 75 le 2026-10-09 SEUL (44 %) -- le jour qui a forme l'hypothese
    hors echantillon (avant le 05/10) : 80 trades sur 26 jours

⇒ **80 trades contre les 100 exigés.** Le critère que je venais d'écrire ne
peut pas être satisfait.

🔑 Je ne le relâche pas. J'ajoute un second test, qui a la puissance que le
premier n'a pas — et je le déclare **avant de regarder**.

## Les DEUX tests, maintenant

### Test 1 — les trades RÉELS, sous-puissant et annoncé comme tel

Les **80 trades hors échantillon**, comparaison appariée A contre B. Il
**échoue d'avance** le critère `n ≥ 100` : son résultat est **indicatif**, et
je ne pourrai pas le présenter comme un verdict, quel que soit son signe.

### Test 2 — les entrées SIMULÉES, le test qui décide

La question posée porte sur la **gestion de sortie**, pas sur les entrées. On
peut donc l'éprouver sur beaucoup plus d'entrées : celles que produisent les
**16 motifs armés sur l'or** (`MT5_BRIDGE_PATTERN_OVERRIDES["XAU/USD"]`),
détectés sur les **120 jours de bougies M1 du courtier** déjà en main.

Pour chaque détection : même entrée, même sens, même borne initiale, et on
compare

- **A** — laisser courir jusqu'à 2 € / −20 € ;
- **B** — l'échelle de gains et la protection de perte de production.

⇒ Critère de ce test 2, les **quatre** :

1. `A − B` **> 0** ;
2. **|t| > 2**, unité **LE JOUR** ;
3. **n ≥ 1 000 entrées** et **≥ 40 jours** ;
4. signe stable sur les **deux moitiés** de la période.

⚠️ Ce que le test 2 ne reproduit pas : les entrées simulées ne subissent ni la
porte d'admission, ni le plafond de positions, ni le score de confiance. Il
mesure donc la **politique de sortie dans l'abstrait**, sur un échantillon
d'entrées plus large et moins sélectif que la production.

## Ma prédiction reste la même, pour les deux tests

`A − B` **sous +0,20 € par trade**, contre +0,544 € en échantillon.

---

# VERDICT, le 2026-10-10

## ✅ LA PORTE EST FRANCHIE — le simulateur est exact

Avant tout verdict, la politique A rejouée sur la semaine du 05-09/10 :

    attendu  +44,04 EUR (92 chemins, 75 TP)
    obtenu   +44,03 EUR (92 chemins, 75 TP)   ⇒ ecart 0,0 %

⛔ Il a fallu **trois tours** pour y arriver, et les deux premiers ont échoué
cette même porte. Les défauts étaient les miens :

1. **J'avais recousu 20 pages de `/rates`.** Le décalage serveur dérive à
   chaque appel ; ma propre mémoire dit « un appel par jour, ne jamais
   recoudre les pages ». Résultat : 17 des 92 chemins alignés.
2. **Ma clé d'index mettait les secondes à zéro** alors que les horodatages du
   courtier en portent (`…T00:00:32`) : **0 ancre sur tous les jours**.
3. **Ma fenêtre `±1 jour` était trop courte.** Le décalage requis le 09/10 est
   de **+1 334 min (+22,2 h)** — il faut regarder **en avant**. Mesuré :
   `±1 j` → 1 ancre sur 75 ; `−1/+2 j` → **75 sur 75** ; `−3/+3 j` → tronqué à
   5 000 bougies, 7 sur 75.

## ⚖️ LES DEUX TESTS SE CONTREDISENT EN SIGNE

| | n | jours | A | B | **A − B** | t (par jour) | jours + |
|---|---|---|---|---|---|---|---|
| **Test 1** trades réels hors échantillon | 79 | 25 | −0,1089 | −0,7574 | **+0,6485** | **+1,34** | 12/25 |
| **Test 2** 16 motifs armés | 37 940 | 73 | −0,2844 | −0,0174 | **−0,2670** | **−7,04** | 16/73 |

⇒ **Aucun des deux n'est RETENU.**

- Test 1 échoue `|t| > 2` **et** `n ≥ 100`. **12 jours positifs sur 25** : c'est
  une pièce de monnaie. Son +0,65 € n'est pas distinguable de zéro.
- Test 2 passe quatre critères sur cinq et échoue **le premier** : l'avantage
  est **négatif**. Laisser courir est **PIRE** de 0,27 € par trade, avec
  `t = −7,04` et le signe stable sur les deux moitiés.

## 🔑 ET VOICI POURQUOI, EN UNE LIGNE D'ARITHMÉTIQUE

Politique A sur les 37 940 entrées : **32 761 objectifs contre 3 276 stops**,
soit **90,91 %** de réussite.

Le taux d'équilibre d'un objectif à 2 € contre un stop à 20 € est
`20 / 22 = 90,91 %`.

⇒ **Les deux chiffres sont identiques à la deuxième décimale.** « Laisser
courir » est une pièce qui paie **exactement sa cote** — et le spread
(0,045 €) la fait basculer du mauvais côté.

🔑 La géométrie 2 €/20 € est **auto-neutralisante sur l'or**. Ce n'est pas un
réglage à affiner : à ces bornes, il n'y a rien à gagner en laissant courir.

## MA PRÉDICTION

Posée d'avance : `A − B` sous **+0,20 € par trade**.

- ✅ **TENUE** sur le test puissant (−0,267 €).
- ⛔ **RÉFUTÉE** sur le test sous-puissant (+0,649 €), que j'avais annoncé
  comme non concluant quel que soit son signe.

## ⇒ ON N'ARME PAS

Le +44,04 € de la semaine est **réel et reproduit au centime**. Il **ne
généralise pas** : sur 73 autres jours et 37 940 entrées, la même politique
perd. C'était exactement le risque que ce test devait écarter.

⚠️ Et la limite déclarée reste entière : je ne simule pas le réemploi de la
marge. Elle ne sauve pas l'hypothèse — elle jouerait en faveur de A, mais A
perd de 0,27 € avec `t = −7,04`.
