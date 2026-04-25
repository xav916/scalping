# Expérience — [Titre court]

**Date début :** YYYY-MM-DD
**Date fin :** YYYY-MM-DD (ou `en cours`)
**Track :** A / B / C / hors-track
**Numéro d'expérience :** auto (compter dans INDEX.md)
**Statut :** `running` / `closed-positive` / `closed-negative` / `closed-neutral` / `abandoned`

---

## Hypothèse

**Énoncé en une phrase, falsifiable :**
> "Si X alors Y avec une probabilité supérieure à Z."

Exemple bien formulé : "Si on entraîne un classifieur RandomForest sur les 35 features V1 + 6 features macro (VIX, DXY, SPX, BTC, ES regime, DXY corr), alors l'AUC test sera ≥ 0.55 sur le test set walk-forward."

Exemple mal formulé : "Voir si les features macro améliorent le modèle." (pas mesurable, pas de seuil)

## Motivation / contexte

D'où vient l'idée ? Quel résultat antérieur la motive ? (Lien vers expérience précédente / spec / paper).

## Données

- **Source :** Twelve Data / FRED / Yahoo / Myfxbook / interne
- **Période :** YYYY-MM-DD à YYYY-MM-DD
- **Pairs/instruments :**
- **Granularité :** 1h / 4h / 1d
- **Volume :** N samples / N trades / N candles

## Protocole

1. Étape 1
2. Étape 2
3. ...

## Critère go/no-go (fixé AVANT exécution)

- **Succès** = "...." (ex: AUC test ≥ 0.55 ET prec@0.65 > 0)
- **Échec** = "...." (ex: AUC test < 0.52 sur les 3 modèles testés)
- **Indécis** = sinon → re-test avec protocole modifié ou abandon documenté

## Résultats

Tableau, chiffres, plots si pertinent. Coller la sortie brute du script en bloc code si court.

## Verdict

> Hypothèse **CONFIRMÉE / INFIRMÉE / INDÉCISE** : [résumé en une phrase + chiffre clé].

## Conséquences actées

- Pour la track : on continue / on abandonne / on pivote vers...
- Pour les autres tracks : impact / pas d'impact
- Pour le code prod : déploiement / pas de déploiement / déploiement en shadow

## Artefacts

- Scripts utilisés : `scripts/...`
- Données générées : `data/...`
- Commits : `<sha>`
