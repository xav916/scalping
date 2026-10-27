# Verdict — `5min` : le PREMIER signal positif du mur, et il ne paie pas

**Pré-inscription** : `2f8734c` · **Banc** : `9f0f239` puis `44e717f`
**3 prédictions sur 5.** Verdict mécanique :
**`NON_CONCLUANT_BRANCHES_EN_DESACCORD`** · `or-verdict` : **NE PAS PUBLIER**.

## Le résultat

```
n = 18 668 sur 18 668   couverture 100,00 %
controle du moteur vectorise : 18 668 / 18 668 en accord avec la production

VALIDITE                                                        valide
  n >= 15 000 ............................ 18 668
  couverture > 99 % ...................... 100,00 %
  risk median reel / placebo ............. 0,5058 % / 0,5058 %
  tirages aboutis >= 190 ................. 200 / 200

ESPERANCES (en R par setup)
  reel (convention A) ....................  +0,0014
  placebo (200 tirages) ..................  −0,0543
  convention B (resolus seuls) ...........  +0,0005
  TIMEOUT seuls ..........................  +0,1493
  cout median ............................  +0,0395

P1  esperance reelle AU-DESSUS du seuil .  seuil −0,050   PASSE
P2  |placebo| sous le seuil .............  seuil +0,050   ECHOUE
P3  tirages battus sous le seuil ........  seuil +95,00   ECHOUE
P4  |ecart A − B| sous le seuil .........  seuil +0,020   PASSE
P5  cout median AU-DESSUS du seuil ......  seuil +0,030   PASSE

t contre placebo : +6,2773      tirages battus : 100,0 %
```

## 🔑 Le fait central : un signal RÉEL, et INSUFFISANT

Le réel bat le placebo de **+0,0557 R**, avec `t = +6,28` et **200 tirages sur
200 battus**. C'est le **premier signal positif de ce mur** : l'instant d'entrée
du `5min` porte une information que des entrées tirées au hasard ne donnent
pas, sur la même géométrie, les mêmes paires, la même période et le même sens.

**Et il ne paie pas.** L'espérance nette vaut **+0,0014 R par setup** —
l'équilibre, à 28 fois le coût près. Le signal existe ; il est trop petit pour
franchir le spread.

⇒ **Les deux branches échouent** : l'admission exige `esperance > cout`
(0,0014 contre 0,0395), le rejet exige `esperance <= 0` (elle est positive) et
`t < 2` (il vaut +6,28). D'où `NON_CONCLUANT`, et `or-verdict` refuse en
nommant les trois clauses non tenues.

## ⚠️ La barre d'admission COMPTE LE COÛT DEUX FOIS — et je dois le dire

`pnl_pct_net = gross_pct − spread_slippage_pct` : **l'espérance est déjà nette
de coût**. Exiger ensuite `esperance_nette > cout_median` demande donc à
l'espérance de dépasser **un coût de plus**, soit un brut de ≈ +0,079 R.

J'avais écrit dans la pré-inscription du `1d` : « barre au-dessus de zéro **et
du coût** ». C'est une **marge de sécurité**, pas un test de point mort — et le
lecteur ne doit pas lire « échoue l'admission » comme « ne couvre pas ses
coûts ». **Elle les couvre, de justesse.**

## ⛔ P2 a échoué, et j'avais pré-écrit que ça condamnerait le BANC

Ma prédiction n°2 disait : *« Si le placebo s'en écarte franchement, c'est le
BANC qui est faux, pas une découverte. »* Le placebo vaut **−0,0543 R** contre
une barre de 0,050.

**Examen** : le placebo paie le même coût que le réel, soit **0,0395 R**. Son
brut vaut donc ≈ **−0,0148 R** — proche de zéro, et négatif comme l'attend la
règle « SL et TP dans la même bougie ⇒ SL », qui biaise systématiquement vers
le stop. Autrement dit **le niveau du placebo est celui que le coût prédit**, et
ma barre de 0,050 était posée **sous le coût lui-même** : elle ne laissait que
0,011 R de marge et ne pouvait pas être tenue.

🔑 **C'est la troisième fois que je pose un seuil impossible à satisfaire par
construction** — après l'indécidabilité du `4h` (0,01 R à `risk_pct` 0,37 %) et
la barre de taux du `1d`. Un seuil doit être confronté à l'arithmétique **avant**
d'être engagé.

⛔ **Mais je ne peux pas à la fois pré-engager une conséquence et la
réinterpréter après coup.** Cette explication est **postérieure**, donc plus
faible que si je l'avais écrite d'avance. La résolution propre n'est pas une
relecture : c'est **une mesure dédiée** — un placebo à coût nul doit rendre
≈ 0 R — et elle exige sa propre pré-inscription.

## ⚠️ Ce que le placebo teste, et ce qu'il ne teste pas

Il compare le réel à des entrées tirées **uniformément dans le temps**. Battre
cela signifie « mieux que lancer des fléchettes », **pas** « mieux qu'une règle
plus simple ». Un placebo plus exigeant — entrer à heure fixe, entrer à chaque
bougie, suivre la tendance — n'a **pas** été mesuré.

## 🔴 Ce que je recommande, et ce que je refuse de conclure

- ✅ **Le `5min` est le premier candidat sérieux de ce mur.** `t = +6,28` et
  200/200 ne s'obtiennent pas par hasard.
- ⛔ **Ce n'est pas un feu vert.** À **+0,0014 R** net, la stratégie est à
  l'équilibre : elle ne rémunère ni le risque, ni le temps, ni une erreur
  d'exécution de l'ordre du spread.
- 🔬 **La seule suite qui vaille est une mesure HORS ÉCHANTILLON.** C'est
  exactement là que les deux trouvailles du 08/10 se sont évaporées
  (`t +2,28 → +0,52` et `t +2,09 → +0,16`). Un signal mesuré sur **un seul
  régime de 68 jours**, en donnée **rattrapée**, n'est pas un signal établi.
- ⛔ **Et je ne propose pas de réarmer l'IA sur cette base.** Un signal à
  l'équilibre, non confirmé hors échantillon, ne soutient pas une remise en
  production.

## ⚠️ L'antériorité est refusée, et c'est assumé

```
1er commit du banc ............... da056c4   (ce matin)
1er commit de la pre-inscription . 2f8734c   (apres)
⇒ or-preinscription : « le banc est anterieur a sa pre-inscription »
```

Le banc est **partagé** entre trois critères : créé pour le `1d`, généralisé
pour le `4h`, seulement **adapté** pour le `5min` (`9f0f239`, postérieur à
`2f8734c`). Le fait qui compte — le critère figé avant le code qui le mesure —
est vrai de l'adaptation, faux du fichier.

⛔ **Je n'ai pas modifié la skill pour faire passer ce cas.** Décision de Xavier
(option 1) : publier avec le refus en clair et les empreintes vérifiables.

## Ce que ce verdict ne dit pas

- **Crypto uniquement** en pratique (99,85 % : 7 paires Binance ; AVAX 15 et
  SUI 13 via Twelve Data). Rien sur le forex ni les métaux.
- Donnée **rattrapée**, **un seul régime** de ~68 jours, **aucun hors
  échantillon**.
- Une seule cellule pré-spécifiée ; **aucune autre ne sera testée après coup
  sur cette donnée** — y compris le placebo à coût nul, qui attend sa propre
  pré-inscription.
