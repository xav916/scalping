# Le DOLLAR ou les TAUX donnent-ils un biais directionnel à l'or ?

**Déclaré le 2026-10-10, AVANT de mesurer.** Décision de Xavier : « les 2 »,
après la fermeture des motifs et du calendrier.

## Ce que j'ai trouvé en base, et ce que ça change

⚠️ `fred_tips_yields` et `vix_snapshot` ont **n = 1** : ce sont des caches de
valeur courante, **pas des historiques**. La piste « taux réels » telle que je
l'avais annoncée n'existe donc pas en base.

✅ Mais `macro.db → macro_daily` porte **8 904 lignes** de vraie série
journalière, du **2024-01-02** à hier :

    dxy      701 jours      tnx (10 ans US)  696      vix  698
    spx      696            eurusd 727       usdjpy   729
    usdchf   727            gbpusd 726       audusd   730
    usdcad   730            nzdusd 730       btc     1014

⇒ La piste devient : **le dollar et les taux donnent-ils un biais de DIRECTION
à l'or, à l'échelle du JOUR ?**

## ⛔ CE QU'UN RÉSULTAT POSITIF ACHÈTERAIT — et ce qu'il n'achèterait pas

À dire **avant** de mesurer, pour ne pas se raconter d'histoire après :

Un biais journalier donnerait un **sens**, pas une rentabilité. Or la mesure du
jour a montré que la géométrie 2 €/20 € rend le sens **sans valeur** : à bornes
symétriques, 64 062 détections donnent **49,83 %**, et aux bornes de production
le bon sens rend **+0,0024 $** par trade.

⇒ Même retenu, ce biais ne serait exploitable **qu'avec un autre couple
objectif/stop**. Je le dis maintenant pour que la suite ne devienne pas un
argument rétroactif en faveur d'un changement de bornes.

## LA PORTE DE VALIDITÉ, posée d'avance

🔑 La relation **or / dollar du MÊME JOUR** est l'une des mieux établies de la
macro : elle doit être **négative**. Si mon appariement de données est juste,
je dois la retrouver.

⇒ **Porte : la corrélation contemporaine or / DXY doit être négative avec
|r| > 0,20.** Sinon mon appariement est faux et **aucun verdict n'est rendu**.

⚠️ Cette corrélation contemporaine n'est **pas** exploitable : elle relie deux
choses connues au même instant. Elle ne sert qu'à valider la donnée.

## CE QUE JE MESURE ENSUITE

L'or vient du magasin **du courtier** (`candles_courtier.db`, bâti aujourd'hui,
vérifié à 97/97 ancres et dont la coupure hebdomadaire reproduit l'horaire réel
du marché). Rendement journalier pris de **clôture 21h00 UTC à clôture 21h00
UTC**, proche de la clôture réelle de l'or (vendredi 20h55).

Pour chaque prédicteur parmi **dxy, tnx, vix, spx, eurusd, usdjpy** et chaque
décalage de **1 et 2 jours**, la corrélation entre le rendement du prédicteur
et le rendement **SUIVANT** de l'or.

⇒ **12 cellules.** Plafond du hasard du laboratoire à 12 cellules :
**|t| > 1,957**.

## ⛔ LE CRITÈRE, POSÉ AVANT DE REGARDER

Un prédicteur est retenu s'il réunit **les quatre** :

1. corrélation **non nulle** ;
2. **|t| > 1,957** (le plafond à 12 cellules) ;
3. **n ≥ 200** jours communs ;
4. signe **stable sur les deux moitiés** de la période.

⇒ Un seul qui manque, et le prédicteur n'est pas retenu.

## MA PRÉDICTION, POSÉE MAINTENANT

**0 prédicteur retenu en décalé.** Motif : la prévisibilité journalière de l'or
par le dollar est l'une des relations les plus étudiées au monde ; si un
décalage d'un jour y portait de l'information, elle serait arbitrée.

✅ Et je prédis que la porte **PASSE** : la corrélation contemporaine or/DXY
sera négative, autour de **−0,3 à −0,6**.

⇒ Si un prédicteur décalé est retenu, ma prédiction est réfutée.

## Ce que cette mesure ne tranche PAS

- Rien sur une échelle **intrajournalière** : `macro_daily` est quotidien.
- Rien sur les **taux réels** (TIPS), absents en base — seul `tnx`, le nominal,
  est disponible.
- Elle ne construit aucune règle.

## ⓘ ET LA PISTE DES TICKS, mesurée et BLOQUÉE

Sondé le même jour : `/ticks`, `/tick`, `/copyticks`, `/order_flow`, `/flux`
répondent tous **404** sur le pont. Seuls `/health`, `/positions`, `/limits`,
`/account` et `/rates` existent.

⇒ Le vrai order flow (ticks hausse/baisse) **demande une route neuve sur le
pont du VPS**. C'est du code qui tourne à côté de l'argent réel : je ne le
déploie pas sans décision explicite. La clé d'accès existe
(`~/.ssh/vps_bridge`), donc le chantier est faisable.
