# L'or trade sur TOUTE la fenêtre hebdo — prédiction INSCRITE AVANT le changement

**Décidé par Xavier le 2026-10-09** : « PAIR_TRADING_HOURS_UTC = {"XAU/USD":
"06-19"} : je veux que l'or trade constamment entre les horaires hebdo
indiquées. »

⛔ **Ce fichier est écrit et commité AVANT que le réglage ne change.** Sans
cela, le verdict serait relu à la lumière du résultat.

## Le changement

    PAIR_TRADING_HOURS_UTC  {"XAU/USD":"06-19"}  ->  {"XAU/USD":"00-23"}

🔑 **Pourquoi `00-23` et non la suppression de la clé.** Les deux donnent le
même comportement (`_heure_defavorable` rend `None`), mais pas le même sens :
une clé **absente** veut dire « personne n'a décidé », une clé à `00-23` veut
dire « ouvert, décidé le 2026-10-09 ». Ce dépôt a déjà perdu deux réglages
parce qu'un `.env` n'avait pas de saut de ligne final : si cette ligne
disparaît un jour, le comportement resterait juste **par accident**. On
déclare.

⇒ Les portes qui restent : **séance du courtier** et **sa fenêtre hebdo**
(lun 00h05 → ven 22h40, heure de Paris). Rien d'autre ne borne l'heure.

## Ce que ça ouvre, mesuré

| | min/semaine | heures |
|---|---|---|
| avant | 4 200 | 70,0 h |
| après | 6 875 | 114,6 h |
| **ajout** | **2 675** | **+44,6 h, soit +64 %** |

Les plages ajoutées : **22h05→06h UTC** chaque nuit (8 h) et **20h→21h UTC**
(1 h). 21h UTC reste fermé — le courtier n'y cote pas.

## ⚠️ CE QUE JE RETIRE — ET CE QUI TIENT

J'ai dit à Xavier, ce soir, qu'élargir au-delà de 19h UTC « fera payer ce
spread à chaque trade ». **C'est la GÉNÉRALISATION qui est fausse, pas le
chiffre.** Remesuré sur **35 720 bougies M5 du courtier / 180 jours** :

| h UTC | Paris | médiane | p75 | p90 | part > 0,10 $ | moyenne |
|---|---|---|---|---|---|---|
| **20h** | 22h | 0,050 | **0,400** | **0,400** | **33,1 %** | **0,1657** |
| 21h | 23h | — | — | — | — | ⛔ aucune cotation |
| 22h | 00h | 0,050 | 0,080 | 0,090 | 0,1 % | 0,0617 |
| 23h | 01h | 0,050 | 0,050 | 0,060 | 0,2 % | 0,0524 |
| 00h–05h | 02h–07h | 0,050 | 0,050 | 0,050–0,070 | 0,1–1,3 % | 0,051–0,054 |
| *12h (référence)* | *14h* | *0,050* | *0,060* | *0,080* | *0,1 %* | *0,0570* |

✅ **Le ×3,02 à 20h UTC TIENT** : moyenne 0,1657 contre 0,0570 à midi, et un
tiers des bougies au-dessus de 0,10 $. La mesure du 08/10 est **confirmée**.

🔑 **Ce qui était faux, c'est d'étendre ce chiffre aux autres heures de nuit.**
De 22h à 05h UTC le spread est **le plus BAS de la journée** — la mesure du
08/10 le disait déjà, et je ne l'avais pas relue avant de parler. Les 8 h
ajoutées chaque nuit ne coûtent **rien** de plus que midi. Une seule des
9 heures ajoutées est chère : **20h UTC**, ~0,10 €/trade de surcoût.

## ⛔ ET UN PIÈGE QUE J'AVAIS DOCUMENTÉ, PUIS FAILLI REFAIRE

Mon premier passage de ce soir n'a regardé que la **médiane** : 0,050 $ à
**toutes** les heures, rapport 1,00 partout. J'ai écrit, et dit à Xavier, que
« la médiane est plate donc le ×3,02 était un artefact de moyenne ».

**C'est exactement le piège n°1 de ma propre note du 08/10** : le courtier colle
à 5 points la plupart du temps, le plancher est **quantifié**, et toute la
variation vit dans la **QUEUE**. La médiane est l'instrument aveugle ici ; la
moyenne, les percentiles et la part au-dessus du plancher sont les bons.

⇒ Le p75/p90 à 0,400 et les 33,1 % au-dessus de 0,10 $ ont rattrapé l'erreur.
Mais je l'ai annoncée à Xavier avant de la corriger : c'est la deuxième fois
dans la session que je parle avant d'avoir relu ma propre mesure.
→ [[feedback-citer-la-source-avant-d-affirmer]]

## 🔴 LA PRÉDICTION, chiffrée

Base mesurée — or AUTO sur le compte réel, 30 j, `destination_id=admin_live` :

    n = 95 trades   total −88,06 €   PAR TRADE −0,927 €   gagnants 60,0 %
    5,94 trades/jour, confinés à 06h..19h UTC (exactement l'ancienne porte)

**Je prédis :**

1. **Le nombre de trades monte.** À densité de setups égale, ×1,64 ⇒ **~9,7
   trades/jour** (contre 5,94). ⚠️ C'est un **majorant** : les nuits sont moins
   volumineuses, donc moins de setups qualifiés. Fourchette annoncée :
   **7 à 10 trades/jour**.
2. **Le résultat se dégrade, il ne s'améliore pas.** Au −0,927 €/trade mesuré,
   les ~3,8 trades/jour ajoutés valent **−3,5 €/jour**, soit **~−17,6 €/semaine**
   de perte supplémentaire.
3. **Le spread n'y est pour presque rien.** ~0,10 €/trade sur la seule heure de
   20h UTC, soit **un ordre de grandeur sous** les 0,93 € que la stratégie perd
   déjà par trade. Le coût de cette décision n'est pas le spread, c'est le
   **volume d'une stratégie mesurée perdante**.

⛔ **Ce que je ne prédis PAS** : que les heures de nuit soient pires que le
jour. Je n'ai **aucune** donnée dessus — l'ancienne porte les interdisait,
donc 0 trade auto entre 20h et 05h UTC. C'est précisément ce que cette
ouverture va mesurer pour la première fois.

## Critère de verdict, fixé d'avance

Au bout de **10 jours de marché** :

- ✅ **Infirmée** si l'or AUTO des heures 20h–05h UTC fait **mieux que
  −0,30 €/trade** sur n ≥ 30, et que le total de l'or auto ne s'aggrave pas.
- ⛔ **Confirmée** si ces heures font **pire que −0,93 €/trade** (le niveau de
  jour) sur n ≥ 30.
- ⚖️ **Indécidable** entre les deux, ou si n < 30.

Mesure à faire par heure d'OUVERTURE (`created_at`), `is_auto=1`,
`pair='XAU/USD'`, `destination_id='admin_live'`.

## Garde-fous déjà en place, inchangés

Règle d'arrêt de l'or (60 ordres ou −50 € d'auto → alerte), plafond journalier
du courtier, plancher de marge 25 %, poche or 20 %, lot 0,01, échelle de stop
par paliers, protection des pertes toutes les 5 min, sondes P0.

⚠️ **Le plafond journalier est actuellement FRANCHI** (−181 € contre 70,18 € de
budget) : le premier ordre d'or refusé ouvrira l'arbitrage et posera la
question sur Telegram.
