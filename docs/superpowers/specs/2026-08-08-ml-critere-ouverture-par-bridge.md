# Critère Machine Learning dans l'équation d'ouverture, par bridge

**Date** : 2026-08-08
**Objectif** : produire un score appris, calculé par destination, qui entre dans la
décision d'ouverture de trade — après l'avoir mesuré en aveugle et sans jamais bloquer
tant qu'il n'a pas franchi une porte annoncée d'avance.

---

## 1. Le besoin

Aujourd'hui, la décision d'ouvrir repose sur un motif qui choisit une bougie, un score
de confiance codé à la main, une pile de vetos, et une porte de coût. Rien de tout cela
n'a démontré battre une entrée au hasard.

La demande est d'ajouter un critère **appris** sur les données de marché des instruments
réellement tradables, branché à chaque bridge, et pris en compte dans l'équation
d'ouverture.

## 2. Ce qui existe déjà — le squelette est complet

| composant | état | fichier |
|---|---|---|
| extraction de variables | **écrit** — RSI, ADX, stoch., EMA/SMA, corps/mèche, session, macro historique, COT | `backend/services/ml_features.py` |
| prédicteur | **écrit** — `is_available()`, `predict_win_proba()`, `model_meta()` | `backend/services/ml_predictor.py` |
| crochet dans le cycle | **actif, en shadow** — appelle le prédicteur par setup et logue `ml_proba` | `backend/services/scheduler.py:202` |
| entraînement | **écrit** | `scripts/ml_train.py`, `ml_extract_features.py`, `ml_backtest_v3.py` |
| archive d'apprentissage | **active** — persiste TOUS les signaux, y compris rejetés | `backtest_service.record_signals` |
| **modèle entraîné** | **ABSENT** — `/app/data/ml_model.joblib` inexistant, `is_available() → False` | — |

Il manque donc : un modèle, un critère **par destination**, et le branchement décisionnel.

## 3. Le constat qui structure ce design

Une tentative sérieuse a échoué le 2026-08-05 : 59 801 exemples, 11 paires, H1,
2020-2026, variables VIX/DXY/SPX/TNX/BTC réelles, découpe temporelle propre, deux
modèles. **Le meilleur résultat consistait à ne rien sélectionner.** R² négatifs,
Spearman ≈ 0, le gradient boosting ne battant pas la régression linéaire.

⛔ **Et la cause est structurelle, pas statistique.** En construisant le jeu,
l'appariement d'un vrai trade avec un trade aléatoire **sur la même bougie** a donné un
excès **exactement nul sur 59 801 lignes, identique au bit près**.

`calculate_trade_setup` (`pattern_detector.py:306-331`) construit entrée, stop et
objectif à partir du **seul sens**, jamais du motif. Deux setups différents sur la même
bougie produisent un trade mathématiquement identique.

> **Conséquence : tout sélecteur — humain ou appris — ne peut que choisir QUAND entrer.
> Et ce choix a été mesuré sans effet.**

Reprendre `excess_r_causal` comme cible reviendrait à demander à un modèle de battre un
écart nul par construction. **C'est le piège que ce design évite.**

## 4. La décision de conception : ce que le modèle prédit

**Cible retenue : l'excursion favorable maximale** (`mfe_pct`), colonne ajoutée à
`shadow_setups` le 2026-08-07 (commit `93a61ca`).

Trois raisons :

1. **Elle n'est pas invariante par bougie.** Deux setups partageant une entrée ont des
   excursions différentes selon la fenêtre de détention. Le mur de la §3 ne s'applique
   pas.
2. **Elle répond à la question qui décide** : ce setup ira-t-il assez loin pour couvrir
   ses frais ? C'est exactement la forme du critère demandé.
3. **Elle prépare le chantier des cibles** au lieu de le concurrencer. Le même modèle
   sert à décider d'ouvrir *et* à calibrer l'objectif.

**Cible témoin obligatoire** : un tirage à pile ou face entraîné dans le même pipeline.
S'il obtient un score non nul, le pipeline apprend du bruit et tout le reste est à jeter.

## 5. Périmètre par route

| route | instruments | horizon | volume estimé | verdict |
|---|---|---|---|---|
| `admin_legacy` / `admin_live` scalping | 10 forex + XAU | 5 min | ~100 000 | viable |
| MT5 long | XAU + forex H4 | 4 h | ~5 000 | **limite** |
| `admin_kraken` | ETH, BTC, SOL, XRP | 1 j | **~8 000** | **limite** |

⚠️ Une route sous **5 000 exemples** ne peut pas porter un modèle propre. Kraken et MT5
long sont à la limite : la décision de les inclure se prend en Phase 1, sur les volumes
réels, **pas après avoir vu les résultats**.

---

## 6. Phases, livrables et portes de sortie

### Phase 1 — Fondation de données · 2 j

- Un jeu par famille de route, découpe **temporelle** (jamais aléatoire).
- Chaque variable vérifiée **non constante** et **causale** — contrôle de fuite champ par
  champ. C'est ce contrôle qui a rendu le verdict précédent décidable.
- Comptage réel des exemples par route.

**Porte** : route < 5 000 exemples ⇒ exclue du chantier, décision consignée.

### Phase 2 — Cible et référence · 1 j

- `mfe_pct` comme cible, cible témoin aléatoire en parallèle.
- Établir la **référence hasard** : excursion moyenne d'entrées aléatoires de même sens
  et même distribution temporelle, par route.

**Porte** : la cible témoin doit donner un score nul. Sinon, arrêt.

### Phase 3 — Entraînement et validation hors échantillon · 3 j

- Régression linéaire **et** gradient boosting. Si le complexe ne bat pas le simple, il
  n'y a pas de signal — c'est le diagnostic qui a tranché en août.
- Découpe : entraînement sur la période ancienne, validation intermédiaire, **test sur la
  période la plus récente**, jamais vue.

⛔ **Porte de réussite, annoncée AVANT de voir les résultats** :

```
Δ en R contre le hasard, hors échantillon,
borne basse de l'IC 95 % > 0,073 R
```

`0,073 R` = frais 0,022 R ÷ la règle des 30 % de la porte de coût. **Pas l'AUC, pas le
R², pas la significativité seule** — Δ contre le hasard, borne basse.

**Si la porte n'est pas franchie, le chantier s'arrête ici.** Écrit d'avance pour que la
décision ne se négocie pas après coup.

### Phase 4 — Déploiement en shadow, par bridge · 2 j

- `ML_SHADOW_ROUTES` (CSV de destinations, **vide par défaut**).
- Le score est calculé et **persisté à côté de chaque signal**, avec un **snapshot du
  seuil et de la version du modèle** au moment du log.
- **Aucun changement de comportement.** Le crochet `scheduler.py:202` existe : il passe
  par destination et écrit en base.

⚠️ Sans le snapshot de version, un réentraînement rend tous les scores historiques
inintelligibles — la leçon du veto funding.

### Phase 5 — Mesure en aveugle · 4 à 8 semaines

Comparer ce que le score **aurait** filtré à ce qui s'est réellement produit — même
méthode que le verdict contrefactuel des vetos.

**Porte** : le score doit séparer sur des données **postérieures à son entraînement**,
avec la même borne qu'en Phase 3.

### Phase 6 — Activation dans l'équation · 1 j

- `ML_MIN_SCORE_<DESTINATION>`, **opt-in, vide par défaut**.
- Évalué **après** la porte de coût, jamais avant : le coût est fondé sur des grandeurs
  mesurées, le score sur des grandeurs estimées.
- Test verrouillant qu'un seuil absent ne bloque rien.

### Phase 7 — Entretien · récurrent

- Réentraînement mensuel, versionné.
- Alerte de dérive si la distribution des variables s'éloigne de celle d'entraînement.
- Le rapport d'évaluation **appelle la règle**, ne recopie pas ses seuils, et **sait
  s'arrêter** quand le verdict est rendu.

---

## 7. Coût et honnêteté

**~9 jours de travail, plus 4 à 8 semaines d'observation avant toute activation.**

Le chantier précédent a échoué avec **7× plus de données** et de **meilleures variables**.
Ce qui change ici n'est ni le modèle ni le volume : **c'est la cible.** Prédire
l'excursion plutôt que la sélection est le seul angle qui échappe au mur démontré en §3.

⚠️ Ce design ne promet pas un avantage. Il promet une **réponse décidable** : soit la
Phase 3 franchit la porte, soit elle ne la franchit pas, et dans les deux cas on saura.

**Si une seule phase devait être retenue, c'est la Phase 2.**

---

## 8. Références

- Verdict ML du 2026-08-05 — pourquoi la sélection ne marche pas
- Contrôle par entrées aléatoires du 2026-08-05 — Δ=+0,004 R sur 29 000 trades
- Excursions `mfe_pct` / `mae_pct` — commit `93a61ca`, la donnée qui rend ce design possible
- Porte de coût — `backend/services/cost_model.py`, seul composant fondé sur des grandeurs mesurées
