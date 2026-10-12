# Les bancs refaits au COÛT RÉEL (+10 points de markup)

**Déclaré le 2026-10-12, AVANT d'écrire la mesure.**

Xavier : *« Refaire les bancs. »*

## D'OÙ VIENT CE BANC

Mesuré ce matin (`0e8a1ae`) : la route historique `/ticks`, dont est bâti
`ticks_courtier.db`, rend un spread **inférieur de 10 points** à la route
`/tick` que l'exécution utilise. 40 secondes appariées, écart médian
**+10,0 pts**, σ 1,2, 26 sur 40 valant exactement +10. Confirmé par les prix
d'exécution réels, qui dévient du bid/ask du magasin de **+3,5 pts (achats)**
et **+5,0 pts (ventes)** — la moitié de l'écart, exactement ce que prédit un
spread réel `= magasin + 10`.

⇒ **Tous mes bancs sur ticks ont sous-estimé le coût de 0,089 €/trade.**

## Le modèle de correction, et pourquoi celui-là

Le milieu est juste, la marge est **symétrique** :

```
bid_reel = bid_magasin - 5 points        ask_reel = ask_magasin + 5 points
```

🔑 Ce n'est pas une hypothèse de confort : la mesure d'exécution donne
**+3,5 pts** d'un côté et **+5,0** de l'autre, soit 5 par côté aux
arrondis près. ⚠️ Mais sa dispersion était énorme (p05 −48, p95 +126) à cause
de l'appariement temporel : **la première étape du banc re-mesure ce markup
proprement**, maintenant que le magasin couvre aujourd'hui, et le banc
s'arrête si la mesure ne confirme pas ~5 points par côté.

## Ce qu'on refait

| banc | question |
|---|---|
| ① validation | le markup par côté vaut-il bien ~5 points ? |
| ② plancher au spread | `B k=2` (ARMÉ ce matin) tient-il au coût réel ? |
| ③ traînage | la règle de Xavier (`k=2`) tient-elle au coût réel ? |
| ④ **l'audit de coût** | que rend la configuration ACTUELLE au coût réel, et quelle réussite exige-t-elle contre celle qu'elle obtient ? |

④ est le vrai enjeu. Les trois autres sont des contrôles.

## ⛔ LE CRITÈRE

Pour ② et ③, le critère reste celui de leurs bancs d'origine (`45b2526`,
`3cdd76e`), **inchangé** — on ne déplace pas la barre après coup.

Pour ④ il n'y a pas de critère : c'est une **description**, pas un test. Elle
ne peut rien « retenir ».

## MES PRÉDICTIONS, posées avant de coder

1. 🔑 **Les écarts APPARIÉS survivront** — c'est la prédiction qui compte,
   parce que **je l'ai affirmée ce matin sans la mesurer**. Les deux cellules
   d'une paire paient le même coût ajouté, donc `B − A` ne doit presque pas
   bouger. Je prédis **|Δ(B−A)| < 0,005 €/trade** pour les deux bancs.
   ⚠️ Et je prédis que ce ne sera pas exactement zéro : le coût plus élevé
   fait toucher le stop plus tôt, donc il change *aussi* la trajectoire, pas
   seulement le solde. Si l'écart bougeait de plus de 0,02 €, mon affirmation
   du matin serait **fausse** et je devrais la retirer.
2. ⚠️ **Le plancher `B k=2` restera retenu.** Son plancher passe de
   `2 × 8 = 16 pts` à `2 × 18 = 36 pts`, soit 0,157 → 0,246 € — toujours très
   loin des 2,00 € (224 pts) qu'il remplace.
3. ⚠️ **La règle de Xavier restera indistinguable de zéro.** Sa largeur passe
   de 0,143 à 0,232 €, donc elle coupe moins tôt, donc son effet s'atténue
   des deux côtés. Je prédis que son écart contre A **reste dans ±0,01 €**.
4. 🔴 **Le niveau absolu s'effondrera de ~0,089 €/trade**, et c'est la vraie
   nouvelle : la configuration actuelle passera d'environ **−0,001** à
   environ **−0,090 €/trade**. Sur 30 trades/5 h cela fait ~−2,7 €, à
   comparer aux **−7,26 €** réellement constatés ce matin — je prédis donc
   que le coût corrigé **explique une partie de l'écart entre banc et réel,
   sans le combler entièrement**.
5. 🔑 **Et une prédiction sur la réussite requise** : au coût réel, la
   géométrie actuelle exigera une réussite **plus haute d'environ 1,5 point**
   que ce qu'elle exigeait au coût du magasin. Si l'écart mesuré en
   production (90,39 % obtenus contre 91,11 % requis, soit **0,72 point**)
   est du même ordre, alors **le markup explique à lui seul tout l'échec de
   la géométrie** — ce serait le résultat le plus important de la journée.
6. ⛔ **Enfin, je prédis que je ne pourrai PAS conclure sur ⑤ avec ce banc
   seul**, parce que les entrées du banc sont synthétiques (toutes les 300 s)
   et non les setups réels. Je l'écris d'avance pour ne pas être tenté de
   surinterpréter un chiffre qui m'arrangerait.
