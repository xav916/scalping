# Rejeu des setups bloqués — juger le blackout des annonces

**Date** : 2026-09-20
**Objectif** : calculer le R qu'auraient produit les setups refusés par
`event_blackout`, afin de pouvoir dire si ce garde-fou **protège** ou **coûte** —
sans jamais deviner une issue, et sans rien armer.

**Destinataire** : Claude Code, dans le dépôt, avec la suite de tests complète.
Cette commande de travail existe parce que la session Cowork qui l'écrit ne peut
pas faire le travail : son `pytest` tourne sans `conftest.py` (faute de
`fastapi` dans le VM local) et elle n'atteint ni EC2 ni ses bases de bougies.

---

## 1. Le besoin

Jusqu'au 2026-09-20, `event_blackout` **n'avait jamais bloqué un seul ordre** :
`signal_rejections` ne contient aucune ligne `event_blackout`, depuis l'existence
du code. Cause trouvée en lisant producteur et consommateur côte à côte —
`forexfactory_service` émettait `dt.strftime("%H:%M")` (« 14:30 », sans date) et
`event_blackout` appelait `datetime.fromisoformat`, qui lève. Chaque annonce
était écartée par un `continue` muet. Réparé par `b8284e0`, `05c3cc8`, `81ce852` :
le garde-fou lit désormais `economic_events` et ses `ts_utc`.

⚠️ **Et six tests de `test_edges.py` étaient verts pendant tout ce temps** : leurs
fixtures fabriquaient `time=when.isoformat()`, un format plus capable que celui du
producteur réel. Une fixture plus riche que la production ne prouve rien.

Chaque blocage écrit maintenant, dans `signal_rejections.details` (JSON), une clé
`blackout` : `event`, `currency`, `minutes_delta`, `event_ts`, et **les niveaux du
setup refusé** — `entry`, `stop`, `tp1`.

**Ce qui manque est l'issue.** Sans elle, on saura combien d'ordres ont été
bloqués sans savoir si c'était une bonne idée. Le précédent exact est dans ce
dépôt : le veto géopolitique n'est jugeable que depuis qu'il porte
`geopolitical_features_json` dans `shadow_setups`, et son contrefactuel
hebdomadaire conclut encore `INSUFFISANT` (29 setups décisifs pour un seuil de 30,
le 2026-09-19).

## 2. Ce qui existe déjà — ne rien réécrire

| composant | état | fichier |
|---|---|---|
| la trace du blocage (niveaux + annonce) | **écrite** le 2026-09-20 | `backend/services/mt5_bridge.py`, bloc `if rejection == "event_blackout"` |
| la décision de blackout | **écrite**, lit la base | `backend/services/event_blackout.py` |
| le calendrier avec de vrais `ts_utc` | **écrit**, 170 events au 20/09 | `backend/services/economic_calendar_service.py`, base `/opt/scalping/data/scalping.db` |
| **le rejeu d'un trade sur bougies** | **écrit** | `laboratoire_or._issue(bougies, depart, entree, risque, objectif_r, sens, cout, politique)` → `(R, indice_de_sortie)` |
| les bougies 5 min | **présentes sur EC2** | `/opt/scalping/data/candles_5min.db` (739 Mo), `trades.db` |
| le modèle de coût par destination | **écrit** | `backend/services/cost_model.py` |
| **le R des setups bloqués** | **ABSENT** | — |

## 3. Ce qu'il faut écrire

`scripts/rejouer_setups_bloques.py`, en **lecture seule** (`mode=ro` partout) :

1. lire les lignes `signal_rejections` où `reason_code = 'event_blackout'` sur les
   N derniers jours (défaut 30, paramétrable) ;
2. pour chacune : extraire `details->blackout` → `entry`, `stop`, `tp1`,
   `event`, `minutes_delta` ; en déduire `risque = |entry − stop|` et
   `objectif_r = |tp1 − entry| / risque` ; le sens vient de `direction` ;
3. charger les bougies 5 min de la paire **à partir de l'horodatage du refus**, et
   appeler **`_issue`** — jamais une réimplémentation ;
4. rendre, par ligne : le R, l'annonce en cause, l'écart en minutes ; puis
   l'agrégat.

**La comparaison de référence, et elle n'est pas celle qu'on croit.** Bloquer un
ordre rend exactement **0 R**. La question n'est donc pas « les bloqués font-ils
mieux ou moins bien que les exécutés » — comparaison biaisée, puisque les exécutés
ont déjà franchi toutes les autres portes. La question est : **la moyenne des R
des setups bloqués est-elle positive** (le blackout a coûté) **ou négative** (il a
protégé) ? Le comparant est zéro.

## 4. Les pièges — chacun a déjà été payé dans ce dépôt

- ⛔ **Ne pas réimplémenter `_issue`.** Deux implémentations mesureraient deux
  choses sous un seul nom. `_R_par_politique` l'a payé le 14/09 en moyennant des
  moyennes. Et `_issue` teste le **stop avant l'objectif** dans toute politique,
  parce qu'une bougie contenant les deux ne dit pas lequel est venu en premier :
  supposer l'objectif fabriquerait de la performance.
- ⛔ **Le coût doit venir de la bonne destination et de la bonne classe d'actif.**
  Le 2026-09-20, facturer le spread du CFD altcoin MT5 à des paires exécutées chez
  Kraken a rendu **96 % des réfutations artefactuelles**, et a fabriqué les deux
  seules cellules `RETENU` de l'histoire du dispositif (contrôle aléatoire noyé à
  −1,33 R). Passer le coût explicitement à `_issue`, jamais un défaut implicite.
- ⛔ **`n < 30` → `INSUFFISANT`, sans énoncer aucun signe.** Même seuil que le
  contrefactuel géopolitique. Un écart sur 29 observations est reproduit
  régulièrement par un tirage au hasard de même taille.
- ⛔ **Une ligne `details.blackout.trace_incomplete` est inutilisable** : l'écarter
  ET la compter à part. L'ignorer en silence gonflerait le dénominateur.
- ⛔ **Aucun seuil neuf.** Tout ce qui décide doit déjà exister
  (`BLACKOUT_WINDOW_MIN`, `MAX_BOUGIES_TENUE`, `PLACEBO_PCT`).
- ⚠️ **Dire ce qu'on ne sait pas.** Si les bougies manquent pour une paire, la
  ligne sort en « non rejouable », jamais en R = 0 — `0.0` est un résultat, pas
  une absence de mesure. C'est le défaut qui s'est répété **quatre fois** ici :
  l'horizon (26/08), la chaîne (16/09), l'écart au hasard (20/09), le coût (20/09).

## 5. Critères d'acceptation — tests exigés

Dans `backend/tests/test_rejeu_setups_bloques.py`, lancés avec la suite complète :

1. un setup dont les bougies touchent TP1 avant le stop rend `R ≈ objectif_r`
   moins le coût ; le miroir avec le stop rend `R ≈ −1` moins le coût ;
2. une bougie qui contient **stop ET objectif** rend le **stop** (relire `_issue`
   et respecter sa sémantique, y compris la sortie au temps après
   `MAX_BOUGIES_TENUE`) ;
3. une ligne `trace_incomplete` est écartée et comptée séparément ;
4. sous 30 observations, le script rend `INSUFFISANT` et **aucun** signe
   directionnel — test qui échoue si une phrase du rendu affirme « coûte » ou
   « protège » ;
5. **contrôle négatif** : sur des bougies plates (ni stop ni objectif touché), le
   R rendu est celui de la sortie au temps de `_issue`, pas zéro ;
6. le script n'écrit **rien** — ouvrir les bases en `mode=ro` et le vérifier.

## 6. Ce qu'il ne faut PAS faire — refus décidés le 2026-09-20

- ⛔ **Pas de file d'attente de reprise.** `ORDER_COOLDOWN_SEC` vaut 0 et
  `cooldown_symbole` n'a jamais refusé un ordre : un setup encore valide est déjà
  ré-émis au cycle suivant, avec des niveaux **recalculés**. Rejouer les niveaux
  d'avant l'annonce serait tarifer un marché qui n'existe plus.
- ⛔ **Ne pas élargir la fenêtre de 15 à 30 min.** Le dépôt porte deux valeurs
  pour un seul concept (`event_blackout.BLACKOUT_WINDOW_MIN = 15` contre le défaut
  de 30 de `get_upcoming_events`), aucune mesurée. L'élargir parce qu'un cas l'a
  franchie de 24 minutes serait un ajustement de seuil sur une observation.
- ⛔ **Ne pas modifier `event_blackout` ni `dans_accumulation`.** Changer la règle
  d'un prédicat déjà mesuré invalide les nuits enregistrées — 856 cellules pour
  l'accumulation.
- ⛔ **Ne rien armer.** `CHAINES_AUTORISEES` reste à `chaine:sweep_avec_biais_haussier`.

## 7. Quand ce spec devient utile

Il ne rend rien tant qu'aucun ordre n'a été bloqué. Au 2026-09-20 : **zéro**, et le
rejeu du vendredi 18/09 montre que les douze trades du jour seraient tous passés
(les trois annonces HIGH de la journée étaient japonaises ; le plus proche trade
JPY était à 24 minutes). Écrire le script est donc légitime, **le lire trop tôt ne
l'est pas** : le premier verdict attendra 30 blocages, et l'audit hebdomadaire
(lundi 07:00) les compte.
