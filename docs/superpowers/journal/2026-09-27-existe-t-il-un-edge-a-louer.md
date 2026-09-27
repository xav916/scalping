# Existe-t-il un edge à louer ? — 2026-09-27

Question posée : *« Est-ce qu'il y aura un jour un trader qui saura nous faire
gagner de l'argent en copiant ses trades ? Est-ce qu'un edge a jamais été
démontré pour un trader particulier, ou est-ce une utopie ? »*

Contrepartie théorique de
[l'analyse des fournisseurs MQL5 Signals](2026-09-27-analyse-fournisseurs-mql5-signals.md),
qui avait mesuré **quinze fournisseurs, zéro survivant**. Ce document-ci explique
*pourquoi* ce résultat était prévisible avant la première mesure — et pourquoi il
ne s'agit ni d'un accident d'échantillonnage, ni d'une accusation de malhonnêteté.

> ✅ **L'edge individuel n'est pas une utopie : il est documenté, mesuré, et vit
> chez environ 1 % des traders particuliers.**
> ⛔ **L'edge *en vente* est une autre chose, et l'arithmétique de la capacité
> interdit structurellement qu'il soit sur le marché à 30 €/mois.**

---

## 1. Ce qui est démontré : l'edge individuel existe, et il est rare

Trois études sur **populations entières**, pas sur échantillons auto-déclarés.
C'est la distinction décisive : ces travaux partent des registres du régulateur
ou de la bourse, donc ils ne souffrent pas du biais de survie qui contamine tout
témoignage volontaire de trader.

| Étude | Population | Résultat |
|---|---|---|
| Chague, De-Losso & Giovannetti (2020), Brésil | 19 646 particuliers débutant le day trading sur futures mini-Ibovespa, 2013-2015, suivis jusqu'en 2017 (registres CVM) | **97 %** de ceux qui persistent > 300 jours perdent de l'argent. **1,1 %** gagnent plus que le salaire minimum brésilien. **0,5 %** gagnent plus qu'un employé de guichet bancaire débutant — « all with great risk ». |
| Barber, Lee, Liu & Odean, Taïwan | Ensemble des day traders de la bourse de Taïwan, 15 ans | **Moins de 1 %** des particuliers qui font du day trading sur une année sont *durablement* profitables. Performance agrégée **−23,9 points de base par jour** net de frais, négative dans **14 des 15 années**. 74 % du volume est produit par des traders à historique perdant. |
| AMF (2014), France — **notre classe d'actif** | 14 779 traders français sur CFD et forex, 2009-2013 | **Plus de 89 %** de clients perdants sur 4 ans. Espérance de perte **−10 900 €**. Résultat cumulé **−161 115 493 €**. CFD : 78 % de clients actifs perdants ; forex : 84 %. |

**Le point que l'on lit mal.** Le chiffre intéressant n'est pas « 97 % perdent ».
C'est que chez Barber *et al.*, la profitabilité du décile supérieur est
**statistiquement persistante d'une année sur l'autre**. Un pur hasard ne
produirait pas de persistance détectable. Donc l'edge individuel est réel ; il
est simplement concentré dans un pour cent de la population.

**Réponse à la première moitié de la question : ce n'est pas une utopie.**

---

## 2. Ce qui n'est pas démontré : l'edge *en vente*

Ici l'argument n'est pas moral, il est arithmétique. Trois mécanismes
indépendants, qui pointent tous dans le même sens.

### 2.1 L'edge de scalping est une ressource à capacité finie

Un edge de scalping capture une inefficience de quelques dixièmes de pip sur un
carnet d'ordres d'épaisseur donnée. Si N copieurs envoient le même ordre dans la
même seconde, ils **mangent l'inefficience et dégradent le fill du fournisseur
lui-même**. La capacité n'est pas un détail d'implémentation, c'est une propriété
de la stratégie : *un edge de scalping ne se scale pas.*

Conséquence directe : **se vendre, c'est se détruire.**

### 2.2 L'arithmétique interdit l'offre

Un fournisseur qui gagnerait 3 % par mois sur 100 000 € de capital propre gagne
3 000 €/mois. Pour égaler cela en abonnements à 30 €/mois, il lui faut **100
abonnés** — dont l'arrivée dégrade précisément le fill dont dépendent les 3 %.

L'option rationnelle, pour qui détient un vrai edge de scalping, n'est pas de le
vendre : c'est de le **lever**. Donc ce qui est *en vente* est, **par
construction**, sélectionné parmi ce qui n'a pas d'edge — ou parmi ce dont l'edge
ne dépend pas de la capacité, et alors on ne parle plus de scalping.

C'est un marché de « lemons » au sens d'Akerlof : les bonnes voitures ne passent
pas par le concessionnaire, non parce que les concessionnaires sont malhonnêtes,
mais parce que leurs propriétaires ont un meilleur usage à en faire.
**Aucune intention de tromper n'est requise pour produire ce résultat.**

### 2.3 La préférence révélée, là où l'edge existe vraiment

Le fonds Medallion de Renaissance Technologies a produit environ **66 % brut /
39 % net annualisés de 1988 à 2018**. Ce qu'il a fait de cet edge :

- **fermé aux investisseurs extérieurs depuis 1993** ;
- **encours plafonnés** (~15 Md$), l'excédent étant distribué chaque année ;
- **jamais vendu un signal.**

Même logique du côté des firmes de trading pour compte propre : elles ne vendent
pas de signaux, elles **recrutent et paient**. Quand quelqu'un a un edge, le
marché le paie, *lui*. Quand quelqu'un vend un edge, c'est qu'il n'a pas trouvé
d'acheteur disposé à le payer pour l'exercer.

---

## 3. L'arithmétique de la chance — pourquoi le crible ne trouvait rien

### 3.1 Le dénominateur est caché, donc le numérateur est illisible

MQL5 **ne publie pas le nombre total de fournisseurs**. Ce n'est pas un détail
cosmétique : sans dénominateur, une courbe spectaculaire n'est pas interprétable.
Le nombre de fournisseurs sans aucun talent qu'il faut pour en attendre un seul
affichant N mois consécutifs positifs, à pile ou face équilibré :

| Mois consécutifs positifs | Probabilité par fournisseur | Fournisseurs nécessaires pour en attendre 1 |
|---|---|---|
| 12 | 2⁻¹² = 1/4 096 | **4 096** |
| 18 | 2⁻¹⁸ | 262 144 |
| 24 | 2⁻²⁴ | 16 777 216 |

### 3.2 Et le modèle « pile ou face » est beaucoup trop favorable

Une grille ou une martingale n'a pas 50 % de mois gagnants : elle en a 90 ou
95 %, parce qu'elle encaisse de petits gains réguliers et concentre le risque
dans une queue rare. Pour un tel système à espérance **nulle ou négative** :

| Taux de mois gagnants | P(12 mois parfaits) | Part des fournisseurs sans edge affichant une année parfaite |
|---|---|---|
| 0,50 | 0,00024 | 1 sur 4 096 |
| 0,90 | 0,282 | **plus d'un quart** |
| 0,95 | 0,540 | **plus de la moitié** |

**Un historique de douze mois parfaits ne porte donc presque aucune information
sur une stratégie à queue cachée.** Or c'est exactement la famille identifiée par
le crible : `World PEACE`, le signal le plus souscrit, est une grille admise,
dont la fiche déclare elle-même *« Severe loss, account stop-out, or eventual
account failure cannot be excluded »*.

### 3.3 Le haut du classement est l'endroit où la chance s'accumule

Un tri sur performance passée dans un grand échantillon remonte mécaniquement en
tête les tirages les plus chanceux, avec le plus d'abonnés, la plus belle courbe
et le tarif le plus élevé. Ce n'est pas un biais du site, c'est une propriété du
tri. C'est le même objet que le **PBO = 0,579** mesuré sur notre propre banc :
la probabilité qu'un optimum apparent soit un artefact de sélection.

---

## 4. Ce qui serait crédible — et pourquoi ça n'est pas ici

Ce n'est pas une utopie, c'est un **mauvais marché**. Un fournisseur crédible
existerait, et il aurait ces traits :

| Trait | Pourquoi il est discriminant |
|---|---|
| Rémunération **à la performance**, pas à l'abonnement | Un abonnement paie l'échec exactement autant que le succès. Aucun alignement d'intérêts. |
| **Capacité plafonnée** — il *ferme* les souscriptions | Le signal le plus fiable qui existe, parce qu'il est **coûteux à imiter** : personne ne renonce à du chiffre d'affaires pour faire joli. |
| **Capital propre engagé** à taille significative, mêmes conditions | Transforme la promesse en exposition. |
| Track record **audité par un tiers**, sur **équité** et non sur solde | Le rapport DD équité / DD solde est le critère qui a fait tout le travail dans le crible. |
| Transparence sur la **stratégie**, pas seulement sur la courbe | Une courbe ne permet pas de distinguer edge et martingale ; une description le permet. |

Ces traits existent : comptes gérés audités, CTA enregistrés, fonds UCITS,
certaines structures de compte propre. C'est réglementé, cher, lent à ouvrir.
**Presque aucun n'est présent sur MQL5** — et ce n'est pas un oubli : abonnement
mensuel fixe, souscriptions non plafonnées, auto-déclaration, classement par
croissance passée. Le modèle économique de la place **sélectionne mécaniquement
l'inverse du cahier des charges**.

---

## 5. Verdict

**Sur la première question** — un edge de trader particulier a-t-il jamais été
démontré ? **Oui.** Environ 1 %, de façon persistante et mesurable, sur
populations entières. Ce n'est pas une utopie.

**Sur la seconde** — pourra-t-on un jour le louer 30 €/mois en copiant ses
trades ? **Structurellement non**, pour le scalping : la capacité finie rend
l'offre irrationnelle, ce qui fait de l'offre existante un échantillon
adversement sélectionné, dont les historiques visibles sont dominés par la
chance et les queues cachées. Chercher là est chercher au bon endroit une chose
qui, par construction, ne s'y trouve pas.

**Et l'observation utile pour ce projet.** Le système de ce dépôt perd
actuellement de l'argent : **−982,67 € sur 1 085 clôtures**, DSR = 0,017,
contrefactuel or à **−0,689 R**. Il échouerait au crible qu'il a lui-même servi
à appliquer aux quinze fournisseurs. Mais ce qui le distingue des quinze n'est
pas le résultat — c'est qu'il possède **l'instrument qui le lui dit** : un banc
pré-enregistré capable de réfuter ses propres hypothèses, comme il l'a fait pour
`preenr-1` le 2026-09-26 (« l'écart s'effondre d'un facteur 7 hors
échantillon »).

> Aucun des quinze fournisseurs criblés ne possède un tel instrument, et la place
> de marché n'a ni les moyens ni l'intérêt de le leur fournir. C'est cet
> instrument qu'il faut alimenter — pas un abonnement.

---

## Sources

Études sur populations entières :

- Chague, De-Losso & Giovannetti, *Day Trading for a Living?* — [SSRN 3423101](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3423101)
- Barber, Lee, Liu & Odean, *Do Day Traders Rationally Learn About Their Ability?* — [UC Berkeley Haas (PDF)](https://faculty.haas.berkeley.edu/odean/papers/Day%20Traders/Day%20Trading%20and%20Learning%20110217.pdf)
- Barber, Lee, Liu & Odean, *Do Individual Day Traders Make Money? Evidence from Taiwan* — [Yale (PDF)](http://www.econ.yale.edu/~shiller/behfin/2004-04-10/barber-lee-liu-odean.pdf)
- AMF, *Étude des résultats des investisseurs particuliers sur le trading de CFD et de forex en France* (2014) — [amf-france.org (PDF)](https://www.amf-france.org/sites/institutionnel/files/contenu_simple/rapport_etude_analyse/epargne_prestataire/Etude%20des%20resultats%20des%20investisseurs%20particuliers%20sur%20le%20trading%20de%20CFD%20et%20de%20Forex%20en%20France.pdf)

Référence de capacité :

- Medallion / Renaissance Technologies, 66 % brut / 39 % net 1988-2018, fermé aux extérieurs depuis 1993, encours plafonnés — [PWL Capital](https://pwlcapital.com/renaissance-technologies-medallion-fund-an-exception-to-the-indexing-rule/)

Interne :

- [Analyse des fournisseurs MQL5 Signals — 2026-09-27](2026-09-27-analyse-fournisseurs-mql5-signals.md) (quinze fournisseurs, zéro survivant)
- [Pré-enregistrement sweep avec biais haussier — 2026-09-25](2026-09-25-preenregistrement-sweep-avec-biais-haussier.md) (`preenr-1`, réfutée le 26/09)

### Note de méthode

MQL5 ne publiant pas son nombre total de fournisseurs, les tableaux du §3 sont
donnés **en fournisseurs nécessaires**, jamais en nombre attendu : on ne calcule
pas une espérance sur un dénominateur inconnu. L'absence de ce dénominateur est
elle-même un résultat du crible, pas une lacune de ce document.
