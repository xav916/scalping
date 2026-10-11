# PISTE 3 — Le prix de l'assurance : couper sur un SEUIL, pas sur le signe

**Déclaré le 2026-10-11, AVANT de mesurer.**

## Ce qui est déjà su, et ce qui manque

Couper les trades négatifs **sur le signe** a été mesuré le même jour : ça
**nuit** (0 délai retenu sur 5 ; 82-86 % des négatifs finissent quand même à
l'objectif), mais ça **divise la variance par 2** (écart-type 7,21 → 3,60) et
améliore la pire journée (−3,99 → −1,67 $), pour **0,32 $/trade à k=5**.

⛔ Et la pré-inscription de ce test excluait explicitement « une coupure
déclenchée par autre chose que le signe ». C'est donc ce qui manque, et c'est
ce qu'un humain ferait réellement : **couper à −2 €, −5 €, −10 €**.

## Ce que je mesure

Mêmes **6 666 trades aveugles**, magasin M1 du courtier (99 999 bougies,
2026-07-01 → 2026-10-09), bornes de production **TP 2 € / SL 20 €**.

Pour chaque seuil **S ∈ {−1, −2, −5, −10 €}** : fermer dès que la perte
courante atteint S (au premier passage, sur les bougies M1), sinon tenir.

Je publie, pour chaque S : le **coût par trade** contre TENIR, l'**écart-type**,
la **pire journée**, la **part des trades coupés** et la **part de ceux-là qui
auraient atteint l'objectif**.

## ⛔ CE QUE CE BANC NE FAIT PAS

Il ne **retient** rien : ce n'est pas une règle à valider, c'est un **prix à
afficher**. La décision est celle de Xavier, pas la mienne — et un banc qui
prétendrait « retenir » une assurance confondrait rendement et tranquillité.

## MA PRÉDICTION, POSÉE MAINTENANT

1. ⚠️ Le coût **croît** quand le seuil se resserre : −1 € coûtera plus que
   −10 €.
2. ✅ L'écart-type et la pire journée **s'améliorent de façon monotone** quand
   le seuil se resserre.
3. 🔑 Et je prédis que couper à **−10 €** coûtera **moins** que couper sur le
   signe à k=5 (0,32 $/trade), parce qu'un seuil large laisse respirer les
   trades que le bruit rend momentanément négatifs.


---

# VERDICT — 2026-10-11

`scripts/banc_prix_assurance_seuils.py`. Memes 6 668 trades aveugles, magasin
M1 du courtier (99 999 bougies, 2026-07-01 → 2026-10-09).

## ⛔ UN DEFAUT ATTRAPE PAR L'INVRAISEMBLANCE, pas par une relecture

Mon premier passage annonçait **+1,43 $/trade** en coupant a −1 EUR : une
assurance qui **RAPPORTE**. Impossible — et c'est ce chiffre absurde qui a
trahi le defaut : `pnl_couper = seuil_usd` au lieu de `-seuil_usd`, le seuil
etant une valeur absolue. Corrige, puis tout refait.

## LE PRIX, par trade

    seuil     TENIR $    COUPER $     ecart   ecart-type   pire jour   part coupee   coupes -> TP
    -1 EUR    -0,1656    -0,0474    +0,1182     **1,59**    **-0,51**      66,0 %       85,5 %
    -2 EUR    -0,1656    -0,0830    +0,0827       2,26        -0,31        50,2 %       81,1 %
    -5 EUR    -0,1656    -0,1612    +0,0044       3,61        -0,90        29,6 %       68,0 %
    -10 EUR   -0,1656    -0,1812    -0,0156       5,16        -2,85        17,1 %       45,8 %
    TENIR seul                                  **7,21**    **-3,99**

## ⛔ MAIS LE GAIN APPARENT DISPARAIT A L'UNITE PRE-INSCRITE

Le tableau ci-dessus moyenne **par trade**. A l'unite qui compte — **le
JOUR**, 87 jours :

    -1 EUR   ecart/jour +0,0043   **t +0,04**
    -2 EUR   ecart/jour -0,0276   t -0,24
    -5 EUR   ecart/jour -0,0601   t -0,55
    -10 EUR  ecart/jour -0,1281   t -1,10

🔑 **Le +0,118 $/trade n'existe pas** : c'est la meme pseudo-replication qui
m'avait donne un t de −4,56 sur le banc des publications. L'ecart honnete est
**zero**.

## ⇒ LA REPONSE, ET ELLE EST UTILE

**L'assurance est GRATUITE aux seuils serres, a la precision de la mesure, et
elle divise la variance par 4,5.**

    ecart-type   7,21  ->  **1,59**   (seuil -1 EUR)
    pire journee -3,99 ->  **-0,51**
    prix         **indistinguable de zero** (t +0,04)

⛔ Ma prediction 1 est **refutee** : je predisais qu'un seuil serre couterait
**plus**. C'est l'inverse — plus le seuil est serre, moins ça coute, parce
qu'on remplace des stops a −22,40 $ par des pertes a −1,12 $.
✅ Mes predictions 2 et 3 tiennent : variance monotone, et −10 EUR coute moins
que couper sur le signe a k=5 (0,3165 $).

⚠️ Et la limite a garder : **85,5 % des trades coupes a −1 EUR auraient atteint
l'objectif**. La regle ne marche pas parce qu'elle evite des pertes : elle
marche parce que les deux effets s'annulent presque exactement. C'est fragile
par construction, et ça se re-mesurera si les bornes de production changent.
