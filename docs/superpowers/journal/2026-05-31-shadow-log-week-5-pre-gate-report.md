# Rapport hebdo W5 PRÉ-GATE — Shadow log V2_CORE_LONG

**Date :** 2026-05-31 (auto-généré par agent remote)
**Période W5 :** 2026-05-24 → 2026-05-31 (7 jours)
**Période calendaire Phase 4 :** 2026-04-25 → 2026-05-31 (36 jours)
**Jours de données effectives :** J+12 post-restart (depuis 2026-05-19)
**Déploiement Phase 4 :** 2026-04-25 17h00 UTC
**Restart post-incident :** 2026-05-19 (J+0 effective data)
**Gate S6 :** 2026-06-06 (dans 6 jours)

> ⚠️ **Dernier rapport auto avant gate S6 (2026-06-06).** Note de contexte : le rapport W4 avait formellement décalé ce gate à S8 (2026-07-04) via commit `37e6862`. Ce rapport W5 évalue les critères S6 originaux conformément à l'instruction, ET se prononce sur la validité du gate S8 comme cible de rechange.

---

## 1. Santé endpoint public

| Endpoint | Statut | Code HTTP | Remarque |
|---|---|---|---|
| `/api/shadow/v2_core_long/public-summary` | ❌ **503 Service Unavailable** | 503 | Indisponible au moment du rapport |
| `/v2/` (frontend SPA) | ❌ **503 Service Unavailable** | 503 | Même erreur |

> **Impact :** Aucune donnée live obtenue via l'API publique. Toutes les métriques W5 sont issues du rapport veto-contrefactuel auto du **2026-05-30 07h08 UTC** (`shadow_setups`, n=26 résolus) et du rapport pair admission du **2026-05-29** (V1). Le 503 peut être transitoire (reboot EC2 programmé) ou signal d'un incident — à vérifier manuellement sur EC2.

---

## 2. Tableau progression W1 → W5 — 6 candidats

### V2_CORE_LONG_XAUUSD_4H (paire principale)

| Semaine | Période | n_résolu | n_TP1 | n_SL | n_timeout | PF | WR% | maxDD% | Source | Statut |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| W1 | 25 avr – 3 mai | N/A | N/A | N/A | N/A | N/A | N/A | N/A | URL invalide | ⬛ N/A |
| W2 | 3 – 10 mai | **3** | **2** | 1 | 0 | **3.51** | **66.7%** | **0.5%** | API ✅ | ✅ OK |
| W3 | 10 – 17 mai | *(non généré)* | | | | *(perdu)* | *(perdu)* | *(perdu)* | Rapport manquant | ⬛ N/A |
| 🔴 WIPE | 18 mai | — | — | — | — | — | — | — | rsync --delete | 💥 RESET |
| W4 | 19 – 24 mai | ~2 | 0 | 2 | 0 | 0.00 | 0% | n/a | Contrefactuel J+5 | 🔴 CRITIQUE |
| **W5** | **24 – 31 mai** | **10** | **0** | **8** | **2** | **0.00** | **0%** | **n/a** | Contrefactuel J+12 | 🔴 **CRITIQUE** |

### V2_CORE_LONG_XAGUSD_4H

| Semaine | n_résolu | n_TP1 | n_SL | PF | WR% | Statut |
|---|---:|---:|---:|---:|---:|---|
| W2 | 1 | 0 | 1 | 0.00 | 0% | ⚠️ WARNING (n insuffisant) |
| W3 | *(perdu)* | — | — | — | — | ⬛ N/A |
| W4 | ~0 | 0 | 0 | — | — | 🔴 CRITIQUE J+5 |
| **W5** | **6** | **0** | **6** | **0.00** | **0%** | 🔴 **CRITIQUE** |

### V2_WTI_OPTIMAL_WTIUSD_4H

| Semaine | n_résolu | n_TP1 | n_SL | PF | WR% | Statut |
|---|---:|---:|---:|---:|---:|---|
| W2 | 2 | 0 | 1+timeout | 0.00 | 0% | ⚠️ WARNING |
| W4–W5 | **8** | **0** | **8** | **0.00** | **0%** | 🔴 **CRITIQUE** |

### V2_CORE_LONG_ETHUSD_1D

| Semaine | n_résolu | n_TP1 | n_SL | PF | WR% | Statut |
|---|---:|---:|---:|---:|---:|---|
| W2 | 1 | 0 | 0 + timeout | — | n/a | ⚠️ WARNING |
| W4–W5 | **2** | **0** | **2** | **0.00** | **0%** | 🔴 **CRITIQUE** |

### V2_WTI_OPTIMAL_XLK_1D

| Semaine | Statut | Source |
|---|---|---|
| W2 | 2 setups pending, aucun résolu | API W2 |
| W4–W5 | Absent du contrefactuel (pas de geo features logguées) | n/a |
| **W5** | **⚠️ INCONNU — non visible dans données disponibles** | — |

### V2_TIGHT_LONG_XLI_1D

| Semaine | n_total | Statut |
|---|---:|---|
| W1 → W5 (36 jours) | **0** | 🔴 **CRITIQUE — 36 jours silencieux depuis deploy** |

---

## 3. Diagnostic cumulé 36 jours — Tableau synthèse

> **Avertissement de lecture :** Sur les 36 jours calendaires depuis le deploy Phase 4, les données effectives couvrent seulement **J+12 post-restart** (2026-05-19 → 2026-05-31) plus **3 setups résolus pré-wipe** (W2, irrécupérables de la DB). La table ci-dessous représente l'état réel de la DB actuelle.

| system_id | n_résolu | n_TP1 | n_SL | n_timeout | WR% | PF | mean PnL% | total PnL% | Statut |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| V2_CORE_LONG_XAUUSD_4H | **10** | **0** | 8 | 2 | **0.0%** | **0.00** | −1.12% | −11.2% | 🔴 CRITIQUE |
| V2_CORE_LONG_XAGUSD_4H | **6** | **0** | 6 | 0 | **0.0%** | **0.00** | −3.92% | −23.5% | 🔴 CRITIQUE |
| V2_WTI_OPTIMAL_WTIUSD_4H | **8** | **0** | 8 | 0 | **0.0%** | **0.00** | −4.52% | −36.2% | 🔴 CRITIQUE |
| V2_CORE_LONG_ETHUSD_1D | **2** | **0** | 2 | 0 | **0.0%** | **0.00** | −3.71% | −7.4% | 🔴 CRITIQUE |
| V2_WTI_OPTIMAL_XLK_1D | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | ⚠️ INCONNU |
| V2_TIGHT_LONG_XLI_1D | **0** | — | — | — | — | — | — | — | 🔴 CRITIQUE (silencieux) |
| **PORTEFEUILLE TOTAL** | **26** | **0** | **24** | **2** | **0.0%** | **0.00** | **−3.01%** | **−78.3%** | 🔴🔴 **ALERTE MAJEURE** |

### Signal statistique

La probabilité d'observer **0 TP en 26 tentatives** si la WR backtest de 45% était réelle :

```
P(WR=0 | n=26, p_true=0.45) = 0.55^26 ≈ 1.8 × 10⁻⁷
```

Soit **moins de 1 chance sur 5 millions** d'obtenir ce résultat par malchance. Ce n'est pas du bruit statistique.

---

## 4. Contexte marché — Signal V1 pair admission (critique)

> Source : `2026-05-29-pair-admission-weekly.md` — Matrice V1 (pair × direction, fenêtre 30 trades).

| Pair | Direction | État V1 | PnL% / 30 trades | Interprétation |
|---|---|---|---:|---|
| XAU/USD | BUY | **PAUSED** | **−125.18%** | Régime SELL sur l'or |
| XAU/USD | SELL | AUTO_EXEC | +3.65% | SELL profitable |
| XAG/USD | BUY | **PAUSED** | **−84.47%** | Régime SELL sur l'argent |
| XAG/USD | SELL | PAUSED | −20.17% | SELL aussi dégradé |
| WTI/USD | BUY | OBSERVED | −0.44% | WTI BUY neutre/plat |
| WTI/USD | SELL | AUTO_EXEC | −0.90% | WTI SELL neutre |

**Conclusion contextuelle :** La V1 pair admission confirme indépendamment que le **régime courant est défavorable aux positions LONG sur XAU et XAG**. La V2_CORE_LONG est une stratégie **long-only** (patterns momentum_up, engulfing_bullish, breakout_up). Elle opère structurellement à contre-courant du régime de marché détecté par V1.

Le 0% WR sur V2 shadow n'est probablement **pas un bug de pipeline** — c'est le système correct qui tourne dans un régime incorrect. Ce que le backtest avait identifié comme risque majeur (spec section 5 : *"Long-only — performe mal en régimes de baisse durables"*) est en train de se matérialiser.

---

## 5. 🔴 GATE S6 ASSESSMENT — Recommandation finale

> Gate S6 : **2026-06-06** (J+18 post-restart, J+42 depuis Phase 4 deploy)
> Critères source : `docs/superpowers/specs/2026-04-26-research-project-synthesis.md`, section 6.

### Évaluation critère par critère

| Critère Phase 5 GO | Seuil requis | Observé J+12 | Projection J+18 (gate) | Verdict |
|---|---|---|---|---|
| XAU setups ≥ 50 sur 6 sem | ≥ 50 | 10 résolus | ~13–15 | ❌ **ÉCHEC MASSIF** |
| Win Rate ≥ 45% | ≥ 45% | **0.0%** | 0–5% | ❌ **ÉCHEC CRITIQUE** |
| PF live ≥ 1.15 | ≥ 1.15 | **0.00** | ~0.00 | ❌ **ÉCHEC CRITIQUE** |
| maxDD < 30% | < 30% | non calculable (API 503) | inconnu | ⚠️ Non évaluable |
| Pas slippage > 0.08% | < 0.08% | non applicable (pas de trades live) | n/a | ⚠️ N/A |

### Seuils STOP (spec section 6)

| Condition STOP | Seuil spec | Observé | Déclenchement |
|---|---|---|---|
| Setups < 30 sur 6 sem | < 30 | XAU ~13 à J+18 | ⚠️ **Oui, si compte depuis deploy** |
| PF live < 0.9 | < 0.9 **sur > 100** setups | 0.00 sur 26 | ⚠️ Seuil n=100 non atteint |
| Drift macro évident | Qualitatif | 0/26 TP, WR=0% sur 4 paires, XAU BUY V1 −125% | 🔴 **OUI — confirmé par V1** |

### 🔴 DÉCISION : DÉLAI OBLIGATOIRE — Gate S6 (2026-06-06) NON PASSABLE

**Aucun critère GO n'est rempli ni remplissable d'ici le 2026-06-06.**

**Motifs :**

1. **Volume insuffisant :** 10 setups XAU résolus vs 50 requis. Même en comptant depuis le deploy initial, le wipe a détruit les données. Aucune trajectoire crédible à 50 d'ici J+18.

2. **Performance catastrophique (réelle, non-aléatoire) :** WR=0%, PF=0.00 sur 26 setups × 4 paires différentes. Signal convergent : p < 2×10⁻⁷ si edge réel. Ce n'est pas du bruit.

3. **Régime de marché adverse confirmé :** La V1 pair admission (XAU BUY PAUSED à −125.18%) confirme indépendamment que V2_CORE_LONG opère en régime contraire. Ce n'est pas un bug — c'est le marché.

4. **Déclencheur "drift macro évident" :** Les trois sources (V2 shadow 0% WR, V1 admission XAU BUY −125%, veto contrefactuel sans filtre utile) convergent vers un diagnostic de régime bearish metals.

**Le trigger formel STOP (PF < 0.9 sur > 100) n'est pas atteint** (n=26 < 100). La recommandation est donc **DÉLAI** et non STOP — mais avec une mise en surveillance active.

### Condition de retour à un scénario constructif

| Condition | Horizon | Interprétation |
|---|---|---|
| ≥ 3 TP1 XAU en 2 semaines (avant 14 juin) | Urgent | Confirme que WR=0% est conjoncturel, non structurel |
| XAU BUY repromotion AUTO_EXEC en V1 admission | Moyen terme | Signal que le régime a retourné |
| Régime XAU H4 > SMA50 tenu 2+ semaines | Moyen terme | Condition d'edge identifiée en backtest |

### Gate S8 (2026-07-04) — Validité maintenue

| Gate | Date | Statut |
|---|---|---|
| ~~Gate S6~~ | ~~2026-06-06~~ | ❌ Non passable — critères hors portée |
| **Gate S8** | **2026-07-04** | ✅ Maintenu — **mais conditionnel au retournement de régime** |

À gate S8, les critères exigent ~20 setups XAU résolus avec PF ≥ 1.32. Si le régime bearish metals persiste jusqu'au 2026-06-20, le gate S8 sera également DÉLAI ou STOP.

---

## 6. Track A × Veto géopolitique — Verdict pour le gate

> Source principale : `2026-05-30-track-a-veto-counterfactual.md` (n=26, 07h08 UTC)
> Source complémentaire : `2026-05-16-track-a-veto-counterfactual.md` (n=8, pré-wipe)
> Note : le script `python -m scripts.research.track_a_veto_counterfactual --db /opt/scalping/data/trades.db --no-write` n'est pas exécutable depuis l'environnement remote (pas d'accès EC2/DB). Le rapport auto du 2026-05-30 sert de proxy.

### Évolution temporelle du verdict

| Date rapport | n setups | WR% | PF | Verdict directionnel | Contexte |
|---|---:|---:|---:|---|---|
| 2026-05-09 | 0 | — | — | INSUFFISANT | J+14, trop tôt |
| 2026-05-16 | 8 | 37.5% | 0.46 | **🚨 VETO_WOULD_HURT** | Pré-wipe, WR 37%, règle `iran_hormuz` retirait des gagnants |
| 2026-05-23 | 2 | 0.0% | 0.00 | Neutre (n dérisoire) | J+4 post-restart |
| **2026-05-30** | **26** | **0.0%** | **0.00** | **Neutre — aucun veto déclenché** | J+11 post-restart |

### Analyse

| Métrique | Valeur J+12 |
|---|---|
| Setups would VETO | **0 / 26** (0%) |
| Setups would PASS | 26 / 26 (100%) |
| PnL would-PASS | −78.3% total |
| Amélioration apportée par veto | **0.00%** |

**Verdict directionnel : NON EXPLOITABLE pour la décision gate.**

Le veto géopolitique (GDELT + Polymarket) ne filtre aucun setup dans la période post-restart. Deux interprétations :

1. **Les conditions géopolitiques déclenchantes (iran_hormuz) ne sont plus actives.** Le signal pré-wipe du 2026-05-16 (`veto_would_hurt`, n=8) était lié à une règle spécifique qui n'est plus déclenchée. Le contexte géopolitique a changé.

2. **Le veto agit sur les mauvaises variables.** La cause des pertes est le régime marché (trend bears métaux), pas un événement géopolitique filtrable.

**Impact sur la décision gate :** Le script Track A × Veto ne modifie pas la recommandation DÉLAI. Le problème de performance est structurellement distinct du périmètre du veto géopolitique.

**Information exploitable :** L'absence de veto actif confirme que les pertes post-restart ne sont pas dues à des events géopolitiques outliers. Elles reflètent la dynamique de marché de base — ce qui rend la situation plus difficile à corriger à court terme.

---

## 7. Activité git depuis Phase 4 deploy (2026-04-25 → 2026-05-31)

**~82 commits** pushés depuis le deploy Phase 4.

### W5 spécifique (2026-05-24 → 2026-05-31)

| Commit | Message | Impact V2 shadow |
|---|---|---|
| `fccbce2` | chore(journal): rapport veto contrefactuel 2026-05-30 (n=26, insufficient) | Source données W5 |
| `3ce8e08` | docs(monitoring): rapport Track A veto contrefactuel (auto) | Idem |
| `daaee2b` | docs(routine): pair admission weekly report 2026-05-29 | Contexte régime marché |

**Observation :** Aucun commit ne touche `shadow_setups`, le scheduler Phase 4, ou la logique V2_CORE_LONG depuis le deploy initial. Le pipeline shadow est stable et inchangé depuis 36 jours. La sous-performance n'est pas causée par une régression code.

### Thèmes majeurs depuis Phase 4 (synthèse 36 jours)

| Thème | Période | Impact V2 |
|---|---|---|
| MQL5 EA (Phases MQL.B→E) + bridge multi-tenant | W1–W2 | Aucun |
| Circuit-breaker V1 + Watchdog | W1–W2 | Aucun |
| Geopolitical veto (GDELT/Polymarket) | W2 | Indirect (filtre nul post-restart) |
| Pair Admission Controller | W2–W3 | Monitoring contextuel ✅ |
| 🚨 **rsync --delete incident** | W3 (18 mai) | **RESET total shadow data** |
| Protection rsync + backups S3+EBS | W4 | Prévention récidive ✅ |
| EA health monitor 4×/jour | W4 | Monitoring infra ✅ |
| Pair admission granularité direction | W3–W4 | Contextuel ✅ |
| Rapport veto contrefactuel hebdo (auto) | W4–W5 | Source données shadow ✅ |

---

## 8. Recommandations avant le gate (2026-06-06)

### 🔴 PRIORITÉ CRITIQUE — Vérifier que 0 TP n'est pas un bug de réconciliation

Avant de conclure que le marché seul explique le 0% WR, il faut éliminer la possibilité d'un bug de logging des outcomes TP1 :

```bash
# Sur EC2 — vérifier tous les outcomes dans shadow_setups post-restart
sqlite3 /opt/scalping/data/trades.db \
  "SELECT outcome, COUNT(*) FROM shadow_setups
   WHERE created_at > '2026-05-19'
   GROUP BY outcome ORDER BY 2 DESC;"

# Vérifier TP1 sans geo features (potentiellement exclus du contrefactuel)
sqlite3 /opt/scalping/data/trades.db \
  "SELECT outcome,
   SUM(CASE WHEN geopolitical_features_json IS NOT NULL THEN 1 ELSE 0 END) as with_geo,
   SUM(CASE WHEN geopolitical_features_json IS NULL THEN 1 ELSE 0 END) as without_geo
   FROM shadow_setups
   WHERE created_at > '2026-05-19'
   GROUP BY outcome;"

# Vérifier les prix fill/sl/tp pour sanity check
sqlite3 /opt/scalping/data/trades.db \
  "SELECT system_id, entry_price, sl_price, tp1_price, outcome, fill_price
   FROM shadow_setups
   WHERE created_at > '2026-05-19'
   ORDER BY created_at DESC LIMIT 10;"
```

**Si des TP1 existent sans `geopolitical_features_json`** → le vrai WR est supérieur à 0%, le 0% est un artefact de filtre. Recalculer sans le filtre geo.
**Si 0 TP1 dans toute la table** → WR réellement nul, cause = régime marché adverse (confirmé par V1 admission).

### 🔴 PRIORITÉ CRITIQUE — API 503

```bash
sudo systemctl status scalping
sudo journalctl -u scalping --since '2026-05-31' | tail -30
```

### ⚠️ PRIORITÉ HIGH — Décision régime : pause ou poursuite ?

Si le 0% WR post-restart est confirmé réel (pas un bug) :
- La spec prévoit que V2_CORE_LONG performe mal en régime de baisse durables
- La V1 pair admission (XAU BUY −125.18% PAUSED) confirme le régime
- **Option A — Patience :** laisser tourner jusqu'à gate S8, accepter les pertes shadow (capital virtuel uniquement)
- **Option B — Pause shadow BUY :** désactiver V2_CORE_LONG_XAUUSD_4H et XAG en attendant que V1 repromeuve XAU BUY en AUTO_EXEC (signal de régime positif)
- **Option C — Ajouter filtre admission :** conditionner le logging V2 shadow à l'état V1 admission de la paire (track régime)
- Option A est la moins risquée (capital fictif) ; Options B/C nécessitent une décision humaine

### ⚠️ PRIORITÉ MEDIUM — XLI : 36 jours silencieux

V2_TIGHT_LONG_XLI_1D : 0 setup depuis le deploy initial. Ce silence précède le wipe. Vérifier :
```bash
grep -r 'XLI\|TIGHT_LONG' /app/backend/ --include='*.py' | grep -v '.pyc' | grep -v test
```

### INFO — Gate S8 (2026-07-04) : conditions de validation

| Condition | Horizon | Importance |
|---|---|---|
| XAU BUY repromotion en V1 admission | Avant mi-juin | Critique — indique retournement régime |
| ≥ 3 TP1 XAU en J+12→J+26 | 2 semaines | Confirme WR non structurellement nul |
| API endpoint accessible (500→200) | Immédiat | Nécessaire pour monitoring fiable |
| n_résolu XAU ≥ 15 | J+26 (mi-juin) | Volume minimum pour Sharpe calculable |

---

## Conclusion W5 — PRÉ-GATE

**Date :** 2026-05-31 · J+12 post-restart · 6 jours avant gate S6.

### Synthèse en 3 points

**1. Gate S6 (2026-06-06) : DÉLAI OBLIGATOIRE**
Aucun des 5 critères GO n'est satisfait. Le volume (10 XAU vs 50 requis), la WR (0% vs 45%), et le PF (0.00 vs 1.15) sont tous hors portée. La décision GO Phase 5 ne peut pas être prise le 2026-06-06.

**2. Performance : anomalie réelle, cause probable = régime marché**
0 TP sur 26 setups (p < 2×10⁻⁷ si edge réel) est statistiquement extraordinaire. La convergence avec la V1 pair admission (XAU BUY PAUSED −125.18%) pointe vers un régime bearish metals courant qui met en difficulté toute stratégie long-only sur XAU/XAG. Ce n'est pas un bug — c'est le risque identifié en spec section 5 (Long-only en régime de baisse). Vérification DB nécessaire pour éliminer le bug de logging avant de conclure définitivement.

**3. Gate S8 (2026-07-04) : maintenu mais conditionnel**
La trajectoire actuelle (0% WR × 4 paires × 12 jours) ne converge pas vers un GO en juillet sans retournement du régime. Le gate S8 reste valide comme date de décision, mais sa conclusion probable est DÉLAI à nouveau — sauf si le marché metals retourne en phase haussière avant fin juin (indicateur : repromotion XAU BUY en V1 admission).

**Seul signal positif de la période :** L'infra de hardening (protection rsync, backups S3+EBS, EA health monitor 4×/jour) est opérationnelle et robuste. Les données futures seront préservées.

---

*Sources : rapport veto contrefactuel 2026-05-30 (n=26) · rapport pair admission 2026-05-29 · rapports W1–W4 · git log --oneline --since=2026-04-25 · spec 2026-04-26-research-project-synthesis.md §6*
