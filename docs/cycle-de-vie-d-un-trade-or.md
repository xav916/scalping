# Le cycle de vie d'un trade d'or — document d'alignement

**Établi le 2026-10-11 avec Xavier, après une journée de mesures.** Ce document
dit, étape par étape, ce qui arrive à un trade d'or de sa détection à sa
fermeture, et **quelle règle agit quand**.

Chaque étape porte son état :

| | |
|---|---|
| 🟢 | **en production aujourd'hui** |
| 🟡 | **construit et testé, livré DÉSARMÉ** |
| 🔵 | **à écrire** |

---

## ① LA DÉTECTION

🔵 **La boucle légère.** Elle lit `/tick/XAU-USD` chez IC Markets toutes les
~200 ms (**5,8 ms** mesurées par appel), met à jour **en mémoire** la bougie M5
**en cours**, et appelle `detect_patterns` (**1,40 ms**). Budget total d'un
passage : **≈ 7 ms**, soit **3,5 %** de charge à 200 ms. ⇒ On voit la figure
**se construire**.

🟡 **Les 49 bougies fermées** viennent du **pont IC Markets** — une seule
`/rates` par bougie close (**53 ms**), et **plus de cache**.
⛔ Aujourd'hui elles viennent de **Twelve Data** avec un cache de **200
secondes** : la détection décide sur une photo vieille de plus de trois minutes,
prise sur une source qui s'écarte du courtier de **0,53 à 0,76 $**.

🟢 **Les détecteurs.** 17 fonctions, **16 motifs armés** sur l'or. Ils lisent au
plus **31 bougies M5** (2 h 35) ; `poc_return` est le seul à lire les 50.
En dessous de **20 bougies**, `detect_patterns` ne rend **rien**.

🔵 **Le réveil.** Sur un motif **nouveau dans cette bougie** — et seulement là —
la boucle légère réveille la chaîne lourde (0,5 à 1,9 s pour l'or seul).

---

## ② L'ADMISSION — 🟢

Le setup traverse la chaîne. **28 motifs de refus** ont réellement mordu sur
l'or ces 30 derniers jours. Les plus fréquents :

    horizon_not_allowed       43 045      pattern_not_allowed       20 136
    verdict_blocker           30 030      pair_auto_paused          12 468
    execution_globale_fermee  24 236      stale_tick                 6 907
    below_confidence          23 477      kill_switch                4 844
    heure_spread_defavorable  20 273      max_positions_per_pair     4 408

Et deux qui portent sur **les bornes** :

- **`sl_too_close`** (431 refus) — le stop d'ouverture doit être à **≥ 0,05 %**
  du prix, soit **2,075 $** ;
- **`fees_exceed_edge`** (1 238 refus) — plancher de viabilité **13,83 $**.
  ⚠️ C'est lui qui interdit un départ à −9 € : 9 € vaut **10,09 $**, sous le
  plancher. L'or a déjà été **muet trois jours** pour cette raison.

---

## ③ L'OUVERTURE

🟢 **Le stop** : **0,35 % du prix**, soit **≈ 14,5 $ ≈ 13 €** à un or à 4 150 $.
Au-dessus des deux planchers. Lot **0,01**.

🟡 **Aucun objectif.** `take_profit = 0.0` — la convention MT5 pour « pas de
cible », exactement ce que portaient 2 des 3 positions ouvertes à la main le
09/10, que le courtier a tenues sans broncher.
⛔ Aujourd'hui un objectif de **2 €** est posé, et il ferme le trade avant que
le traînage ait la parole.

---

## ④ LA VIE, CÔTÉ NÉGATIF — 🟡

1. **Rien pendant 60 secondes** (âge minimal).
2. Il faut être **négatif depuis 30 secondes** consécutives.
3. Puis, **toutes les 60 secondes** : `stop = (stop + perte) / 2`, **plancher
   absolu −2 €**, **cliquet seul** (jamais de desserrage).
4. Exemple depuis 13 € avec 3 € de perte : **8 → 5,5 → 4,25 → …** jusqu'à −2 €.

⛔ Aujourd'hui : cron **toutes les 5 minutes**, avec 5 min d'âge et 2 min 30 de
négativité. Mesuré : passer à la minute fait tomber la pire journée de
**−1,75 € à −0,60 €** et le stop de départ touché de **20 à 1** sur 6 668, pour
un écart de rendement **indistinguable de zéro** (t ≤ 0,37).

---

## ⑤ LA VIE, CÔTÉ POSITIF — 🟡

1. **Rien sous +0,50 €** de profit.
2. À **+0,50 €** : le stop passe à **0** — le trade ne peut plus perdre.
3. Ensuite **en continu et SANS PLAFOND** : `stop = profit − 0,50 €`.
   1,90 → **1,40** · 3,10 → **2,60** · 30 → **29,50** · 41 → **40,50**.
4. Sondé à **1 seconde** sur le **cours réel** (`price_current`), **cliquet**,
   et un **pas minimal de 0,10 €** pour ne pas inonder le courtier.

✅ **Et c'est posable** : `/tick` publie `stops_level_points = 0` ⇒ **le courtier
n'impose aucune distance minimale**. Le seul plancher est le nôtre, et il ne
concerne que l'ordre d'ouverture.

---

## ⑥ LES SIX SORTIES

| sortie | part mesurée |
|---|---|
| **stop suiveur, devenu positif** | **65 %** |
| protection côté perte | 24 % |
| point mort (stop à l'entrée) | — |
| stop de départ | **1,1 %** |
| vendredi avant la clôture (`fermer_metaux_avant_weekend`) | — |
| à la main dans le terminal | — |

⇒ **Le stop est la seule sortie.** Il n'y a plus d'objectif.

---

## ⑦ CE QUI PEUT TOUT ARRÊTER — 🟢

Ces gardes bloquent l'**ouverture**, jamais la sortie :

- **plafond journalier** : 3 % du compte, 10 % sur l'or ;
- **règle d'arrêt de l'or** : 60 ordres ou −50 € d'automatique ;
- **REM-002** : au moindre déploiement, `DENY / NEW_DEPLOYMENT` — le
  réarmement est la décision de Xavier ;
- **kill switch**, marge libre ≥ 25 %, poche or 20 %, 5 positions métal maximum,
  budget de 800 ordres.

---

## ⚠️ CE QUE CE CYCLE FAIT, ET CE QU'IL NE FAIT PAS

⛔ **Il ne crée aucun avantage.** Sept zéros indépendants mesurés le même jour
disent que la direction n'existe **à aucune échelle et à aucun instant** :

    les motifs        0/22 · 0/28 · 2/30 ANTI-predictifs
    l'echelle         jusqu'au tick, 0/16
    l'instant         live contre cloture, 0/4
    la microstructure series de ticks, 0/16

✅ **Il retire quatre défauts réels**, et c'est tout son intérêt :

1. décider sur des prix **vieux de 200 secondes** venus d'une **autre source**
   que celle qui exécute ;
2. un **objectif à 2 €** qui plafonne les gagnants (mesuré : **−0,1015 €/jour**,
   `t = −6,85`, contre pas d'objectif) ;
3. un stop de départ qui **ne bouge pas** pendant cinq minutes ;
4. une pire journée de **−3,99 €** qu'on ramène à **−0,51 €** pour un prix
   **indistinguable de zéro**.

🔑 **La phrase à retenir** : ce cycle ne gagne pas d'argent, **il arrête d'en
perdre bêtement**.
