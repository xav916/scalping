# Le retour à la moyenne, HORS ÉCHANTILLON

Seconde pré-inscription sur ce motif. La première
(`2026-10-31_retour-moyenne-or.md`) a produit une mesure mais **aucun verdict
publiable**, et pour des fautes qui m'appartiennent toutes.

## ⛔ Ce qui a échoué la première fois, nommé

`or-verdict` a refusé la publication sur trois griefs, tous réels :

1. **Empreinte du critère.** La porte hache le bloc `CRITERE-MACHINE` et le
   compare à la **toute première** version commitée du fichier
   (`git log --diff-filter=A`). J'avais amendé ce bloc trois fois — chaque fois
   avant la mesure, chaque fois vers plus de sévérité, chaque fois commitée
   avec son motif. La porte ne peut pas distinguer un durcissement d'avant
   mesure d'une réécriture d'après coup, et elle a raison de ne pas essayer.
   🔑 **Conséquence tenue ici : ce bloc machine ne sera plus touché. Jamais.**
   S'il est faux, ce fichier est abandonné et un troisième est écrit.
2. **Clauses illisibles.** L'évaluateur attend ` ET ` en majuscules et
   uniquement `champ <op> nombre`, `abs(champ) <op> n`,
   `abs(a - b) <op> n` ou `champ_a <op> champ_b`. J'avais écrit « et » en
   minuscules et glissé de la prose dans le bloc (« aux deux spreads »,
   « sur les 24 »). Une clause illisible refuse ; elle ne s'ignore pas.
3. **Champs inexistants.** Mon critère engageait `non_resolus_pct`, que le
   banc **ne calculait pas**. J'avais déclaré une barre sans construire
   l'instrument. Et le résultat n'émettait ni `forme`, ni `n`, ni `t`, ni
   `valide`.

⚠️ `preinscrire.py` avait tout laissé passer : il vérifie qu'une comparaison
numérique existe, pas qu'elle soit évaluable. La seconde porte a rattrapé la
première — c'est sa fonction, et elle a fonctionné.

## Pourquoi une fenêtre NEUVE, et pas la même

La première mesure a consommé **toute** `candles_courtier.db` (99 750 bougies,
2025-05-14 → 2026-10-09) et rendu un `t_vs_hasard` maximal de **+1,586** pour
un plafond de 2,241, sur 36 cellules mesurables.

⛔ **Je connais donc la réponse sur cette fenêtre.** Réécrire un critère en la
connaissant, même à l'identique, est exactement la configuration que
`or-preinscription` existe pour interdire. Rejouer les mêmes données serait
formellement propre et scientifiquement sans valeur.

La fenêtre jugée ici n'a **jamais été lue par moi** : XAU/USD,
**2023-08-01 → 2025-05-13**, 125 845 bougies M5, soit toute la période
**antérieure** au magasin du courtier.

## ⚠️ LA LIMITE, assumée d'avance

Cette fenêtre vient de `candles_5min.db`, c'est-à-dire de **Twelve Data**, et
ce dépôt a mesuré ce que vaut ce magasin le 2026-10-10 :

- écart des clôtures contre le courtier : **0,53 à 0,76 $** de médiane au
  meilleur alignement, mais **3,807 $** sur quinze mois à décalage unique ;
- deux conventions horaires selon l'année, et une année 2026 trouée.

🔑 Et la conclusion que ce dépôt en a tirée s'applique **contre moi** ici :
*« un banc d'OBJECTIF ou de STOP : l'écart n'est PAS négligeable, et son
verdict doit être refait sur des bougies du courtier avant d'être tenu pour
acquis. »* Ce banc place une entrée, un stop et un objectif — il en dépend
donc entièrement.

⛔ **Ce verdict ne sera donc jamais présenté comme définitif.** Il ne peut
rendre qu'une seule chose utile : la **réfutation**. Si un motif ne bat pas le
hasard sur une source dégradée, cela ne prouve rien ; mais s'il ne le bat pas
non plus là où il avait déjà échoué sur des bougies propres, la conjonction
des deux est le prior le plus solide disponible. Une admission, elle, serait
suspecte par construction et exigerait une reprise sur bougies courtier.

## L'appareil

Inchangé, et c'est voulu : `laboratoire_or` avec son rejeu **séquentiel**, son
**stop testé avant** l'objectif, son **spread facturé** en R, ses **stops
placebos écartés** (< 0,1 % du prix) et son **contrôle aléatoire apparié en
nombre et en sens**. Le détecteur est celui **de production**, son seuil balayé
par `MEAN_REVERSION_SIGMA` — un seul z-score dans le dépôt.

24 cellules : 3 seuils (1,5σ / 2,0σ / 2,5σ) × 4 échelles (M5, M15, M30, M60)
× 2 sens, chacune exigée **aux deux spreads** (0,20 et 0,50). Le plafond du
hasard pour 24 cellules vaut **2,241** (`plafond_hasard(24)`).

## LE CRITÈRE

`forme: placebo` — le second bras est le contrôle aléatoire. Il n'y a aucun
rejeu d'une réalité vécue à reproduire, donc aucun `ecart_par_trade` :
`mean_reversion` n'a jamais passé le moindre ordre.

Une cellule est **retenue** quand le laboratoire la retient avec le plafond
des 24 (`t_vs_hasard > 2,241` **et** `r_moyen > 0`), que son
`delta_hasard > 0,02`, qu'elle compte `n >= 20`, et que cela tient **aux deux
spreads**. Ces seuils vivent dans le banc ; les clauses de validité ci-dessous
les y **épinglent** en les comparant aux valeurs que le banc déclare avoir
appliquées, pour qu'ils ne puissent pas dériver sous l'empreinte.

<!-- CRITERE-MACHINE
forme: placebo
admission: cellules_retenues >= 1
rejet: cellules_retenues < 1 ET cellules_mesurables >= 12
validite: non_resolus_pct < 5 ET bougies_m5 >= 120000 ET plafond_applique >= 2.241 ET min_delta_hasard_applique >= 0.02 ET min_trades_applique >= 20 ET spreads_exiges >= 2
cellules: 24
plafond: permutation_p95
-->

**Admission** — au moins une cellule retenue. Si cela arrive, ⛔ la limite
Twelve Data ci-dessus s'applique et la reprise sur bougies courtier est
obligatoire avant tout armement.

**Rejet** — aucune cellule retenue **et** au moins 12 des 24 hypothèses
réellement mesurables. La seconde clause est indispensable : sans elle,
« rien n'a été retenu » se confondrait avec « rien n'a pu être mesuré », et un
motif muet passerait pour un motif réfuté. ⚠️ En deçà de 12, ni l'admission ni
le rejet ne tiennent et la porte refuse — ce refus est alors la bonne réponse,
et il se lit « ce volume ne permet pas de trancher ».

**Validité du rejeu** — six clauses, distinctes du critère : moins de 5 % de
trades non résolus (soldés de force en fin de fenêtre de tenue, sinon les R
mesurent une liquidation et pas une issue de marché) ; au moins 120 000
bougies lues ; et les quatre seuils que le banc déclare avoir appliqués,
épinglés à leurs valeurs pré-inscrites.

## Les prédictions

1. **Aucune cellule ne sera retenue** : `cellules_retenues` vaudra 0. En
   échantillon, le `t_vs_hasard` maximal plafonnait à +1,586 contre 2,241, et
   montait régulièrement avec le nombre de trades sans jamais s'approcher de
   la barre (+0,205 / +0,515 / +0,987 / +1,586 de M60 à M5).
2. **Au moins 12 hypothèses seront mesurables**, donc le rejet sera
   prononçable. En échantillon, 36 cellules sur 48 l'étaient, sur une fenêtre
   de 99 750 bougies ; celle-ci en compte 125 845.
3. **Le `t_vs_hasard` maximal restera sous 2,0**, donc avec une marge franche
   sous le plafond — et non juste en dessous. Un maximum entre 2,0 et 2,241
   serait pour moi un signal d'alerte : c'est le régime où trois trouvailles
   de ce dépôt se sont déjà évaporées à la fenêtre suivante.
4. **L'ordre par échelle se reproduira** : le `t_vs_hasard` maximal croîtra de
   M60 vers M5, le nombre de trades commandant la statistique. Si cet ordre
   s'inverse, ma lecture du mécanisme est fausse et il faut le dire.

## Ce que le résultat décide

- **Rejet** ⇒ le motif est clos sur l'or. Conjugué à la mesure en échantillon
  sur bougies courtier, c'est le prior le plus solide que ces données
  permettent. On n'arme rien, on ne desserre rien, et `mean_reversion` reste
  où il est : détecté, journalisé, et sans ordre.
- **Admission** ⇒ reprise obligatoire sur `candles_courtier.db`, et rien
  n'est armé avant.
- **Refus de la porte** ⇒ volume insuffisant, et la question reste ouverte
  sans qu'on ait le droit de la dire tranchée.

⛔ Dans les trois cas l'argent réel est hors d'atteinte : sa liste blanche ne
porte que `range_bounce_*`, et les extras sont démo-seulement par
construction.
