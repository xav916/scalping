# PISTE 1 — La main de Xavier bat-elle le fait de ne RIEN faire ?

**Déclaré le 2026-10-11, AVANT de mesurer.** Demande de Xavier : « faire les
pistes numéro 1, numéro 2 et numéro 3 ».

## ⛔ CE QUE J'AI D'ABORD VOULU MESURER, ET POURQUOI C'EST INTESTABLE

Je voulais comparer ses trades **à la main** à ceux de l'automatique. Mais
`personal_trades` ne contient que **43 trades à la main, tous du 09/10** : le
trou de la main n'a été bouché que ce jour-là. Un seul jour ne généralise
pas — je viens de le démontrer en perdant le « 40 % de vendredi ».

## ⛔ ET LE PIÈGE SUIVANT, ÉCARTÉ AUSSI

Le ledger offre `human_intervention`, avec 5 mois d'historique :

    intervention = 1 : 223 trades, **+317,18 €**, +1,4223 €/trade, **0 SL**
    intervention = 0 : 1 293 trades, **-570,46 €**, -0,4412 €/trade, **891 SL**

🔑 Tentant, et **tautologique** : `intervention=1` équivaut exactement à
`close_reason = MANUAL` (223 sur 223), et `=0` à « jamais MANUAL ». Les deux
groupes sont donc définis **par leur issue**, pas par une décision comparable.
Comparer « ce qu'il a fermé » à « ce qui a touché son stop » mesure la
**sélection**, pas la compétence. Je ne publierai pas ce chiffre comme un
résultat.

## CE QUE JE MESURE À LA PLACE — le contrefactuel sur les MÊMES trades

Pour chaque trade où **il est intervenu**, sur XAU/USD, juillet → 9 octobre
2026 (la fenêtre du magasin M1 du courtier, 99 999 bougies) :

- **LUI** : son `net_pnl` réellement réalisé ;
- **RIEN** : le même trade laissé courir jusqu'à **ses propres bornes**
  (`stop` / `take_profit` du ledger), ou à défaut les bornes de production
  **2 € / 20 €** ; plafond 24 h puis sortie au prix du marché.

⇒ Comparaison **appariée, trade par trade**, l'unité statistique étant **le
JOUR**.

Et je publie les deux chiffres qui disent *pourquoi* : parmi ses sorties,
**quelle part aurait fini au stop** s'il n'avait rien fait, et **quelle part
aurait fini plus haut**.

## ⛔ LE CRITÈRE, POSÉ AVANT DE REGARDER

Sa main est retenue si elle réunit **les quatre** :

1. P&L **LUI** > P&L **RIEN** sur les mêmes trades ;
2. **|t| > 2,5**, l'unité étant le jour — barre relevée parce que je regarde
   deux géométries de repli et trois sous-ensembles, soit ~6 cellules ;
3. **n ≥ 100** trades ;
4. signe de l'écart **stable sur les deux moitiés** de la période.

⚠️ Et une restriction d'honnêteté : je publie séparément les trades dont
l'argent est **vérifié chez le courtier** (`src_argent = courtier`, 668 lignes
sur 1 530) — le reste vient du stock et vaut moins.

## MA PRÉDICTION, POSÉE MAINTENANT

1. ✅ **LUI** sera **positif** contre **RIEN** — il coupe avant le stop, et le
   stop est le seul endroit où ce système saigne (66 stops = −436,72 €).
2. ⛔ Mais **le critère 2 échouera** : `|t| < 2,5`. Motif : la mesure
   précédente de sa main donnait déjà **t = +1,59** contre une barre à 2,0, et
   je n'attends pas que trois mois de plus fassent franchir 2,5.
3. ⚠️ Et je prédis que **la majorité de ses sorties n'auraient PAS fini au
   stop** — donc qu'une partie de sa valeur est de l'argent **laissé sur la
   table**, pas du risque évité.

⇒ Si les quatre passent, sa main est le premier avantage établi du projet, et
le système doit être « il ouvre et ferme, la machine garde ».


---

# VERDICT — 2026-10-11

`scripts/banc_la_main_contrefactuel.py`. **80 trades** ou il est intervenu
(XAU, juillet → 9 octobre 2026), **tous a argent verifie chez le courtier**,
contrefactuel calcule sur les 99 999 bougies M1 du courtier.

## ⛔ MA PREDICTION 1 EST REFUTEE : sa main NE BAT PAS le fait de ne rien faire

    LUI    **+2,26 EUR/trade**   total **+180,85 EUR**
    RIEN   **+5,89 EUR/trade**   total **+470,94 EUR**
    ecart par JOUR  -12,44 EUR   t **-0,91**   (20 jours)

⇒ **Ne rien faire aurait rapporte +290 EUR de plus** sur ces 80 trades.

Les quatre criteres : **1 echoue** (LUI < RIEN), **2 echoue** (|t| 0,91 < 2,5),
**3 echoue** (n = 80 < 100), 4 passe. ⇒ **SA MAIN N'EST PAS RETENUE.**

⚠️ Et il faut le dire proprement : avec t = −0,91, « sa main nuit » n'est **pas
etabli** non plus. Le resultat est **INDECIDABLE**, avec une estimation
ponctuelle clairement contre elle.

## ✅ MA PREDICTION 3 EST JUSTE, ET C'EST LE MECANISME

Issues qu'auraient eues ses trades s'il n'avait rien fait :

    objectif atteint   **45 sur 80  (56 %)**
    sa cloture         23
    stop touche        **12 sur 80  (15 %)**

🔑 **Seules 15 % de ses sorties evitaient un stop ; 56 % auraient atteint
l'objectif.** Sa main n'est donc pas un garde-fou : c'est de l'**argent laisse
sur la table**.

⚠️ Le dommage est concentre sur la **premiere moitie** (−36,07 EUR/jour contre
−0,02 ensuite), et un seul trade y pese lourd : une vente du 05/08 tenue
**six jours** a travers une hausse de 308 $, soldee **−265,11 EUR**, dont le
stop declare etait a 6,89 $.

## Ce que ca dit du semi-automatique

Sa proposition etait « je lance, tu arretes » ; puis j'ai propose l'inverse,
« il ouvre, la machine garde ». ⇒ La mesure soutient le **second** sur un point
precis : ce sont les **bornes** qui gagnent, pas les sorties humaines. Mais
elle ne soutient PAS l'idee que sa main apporte quoi que ce soit, et c'est
contre ma propre prediction.
