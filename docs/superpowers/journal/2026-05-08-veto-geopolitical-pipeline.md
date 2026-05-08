# Pipeline géopolitique → veto scoring → analyse contrefactuelle

**Date :** 2026-05-08
**Statut :** `closed-positive` — pipeline complet en prod, en attente d'observation 4-6 semaines pour validation
**Lien gate S6 :** L'agent du gate (2026-06-06) doit lire ce journal pour comprendre comment la décision GO/DELAI/STOP doit intégrer le verdict du veto contrefactuel Track A.

---

## Hypothèse session

> "La géopolitique mesurée objectivement (Polymarket prediction markets + GDELT news sentiment) doit être intégrée au décisionnel scoring trade — pas en shadow seulement comme c'était le cas avant ce jour."

User a explicitement demandé l'intégration au scoring : "comme c'est du trading test, je souhaite que la geopolitique soit incorporée dans le décisionnel du scoring de trade".

## Architecture posée — pipeline en 6 couches

```
┌─────────────────────────────────────────────────────────────┐
│ COUCHE 1 : Sources géopolitiques (déjà déployées en shadow) │
│  - Polymarket Gamma API (5 min refresh)                      │
│  - GDELT Doc API (1h refresh, 4 thèmes)                      │
└──────────────────────┬───────────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────────┐
│ COUCHE 2 : Veto branché scoring V1 (nouveau, commit 8a270a8) │
│  4 règles toggleables individuellement env vars :            │
│  - IRAN_HORMUZ : Polymarket Iran peace prob ≥30% à <14j      │
│  - FED_DOVISH : Polymarket Fed cut prob ≥70% à <14j          │
│  - RECESSION : Polymarket recession prob ≥50%                │
│  - GDELT_HIGH_STRESS : GDELT geopolitical theme = high       │
│  Hook : analysis_engine.enrich_trade_setup après macro_veto  │
└──────────────────────┬───────────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────────┐
│ COUCHE 3 : Observabilité veto (commit 77e89bf)               │
│  Dashboard `/v2/admin > Geopolitical Veto activity` :        │
│  - Count par règle / par pair / par jour                     │
│  - 20 derniers vetos + reason                                │
│  Backend : /api/admin/geopolitical-veto-stats               │
└──────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ COUCHE 4 : Capture snapshot Track A (commit 3ac0d70)         │
│  À chaque nouveau setup persisté dans shadow_setups, capture │
│  geopolitical_features_json :                                │
│  - Polymarket : iran_peace_max_prob, fed_cut_max_prob, ...   │
│  - GDELT : overall_stress, geopolitical_stress, ...          │
│  - VERDICT CONTREFACTUEL : would_veto pour ce setup          │
│  Track A reste lecture seule (pas filtré).                   │
└──────────────────────┬───────────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────────┐
│ COUCHE 5 : Analyse contrefactuelle (commit 2f63cc1)          │
│  scripts/research/track_a_veto_counterfactual.py :           │
│  Croise les outcomes Track A réconciliés avec leur snapshot  │
│  → groupe "would VETO" vs "would PASS"                       │
│  → verdict directionnel (aurait aidé / nui / égal)           │
│  Verdict qualitatif sample : DÉRISOIRE/INSUFFISANT/...       │
│  Génère rapport Markdown auto-daté.                          │
└──────────────────────┬───────────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────────┐
│ COUCHE 6 : Visibilité Cockpit (commit e40847a)               │
│  Carte Track A shadow log dans /v2/cockpit Analyse           │
│  6 systèmes côte à côte (XAU/XAG H4, WTI H4, ETH 1D,         │
│  XLI 1D, XLK 1D) + 5 derniers setups                         │
└──────────────────────────────────────────────────────────────┘
```

## Commits posés (chronologique)

| # | Commit | Sujet |
|---|---|---|
| 1 | `907e3dd` | fix routing EA-only Premium (drop bridge_url requirement) |
| 2 | `22fabbd` | feat Polymarket card cockpit |
| 3 | `feda080` | fix event_slug deep-link Polymarket |
| 4 | `8a270a8` | **feat geopolitical veto rules (4 règles, hook scoring V1)** |
| 5 | `77e89bf` | **feat admin veto activity dashboard** |
| 6 | `3ac0d70` | **feat shadow log géopol capture (counterfactual data)** |
| 7 | `1864a73` | fix GDELT throttle (4/4 thèmes, fallback per-theme) |
| 8 | `2f63cc1` | **feat script Track A × veto contrefactuel** |
| 9 | `e40847a` | feat Cockpit Track A shadow mini-card |
| 10 | `1dcede1` | chore hygiene final (gitignore + deploy prune) |

## Routines RemoteTrigger fixées

5 routines pointaient vers l'ancienne URL `scalping-radar.duckdns.org` qui ne résout plus correctement (héritage avant migration `app.scalping-radar.online`). Le rapport W1 du 2026-05-03 a échoué à cause de ça (conclusion "0 setup confirmé" alors qu'il y en avait 24).

| Routine | Fire | ID | Note |
|---|---|---|---|
| W2 | 2026-05-10 | `trig_0141MLnzHHwtooW9DPPgi7uW` | URL fixée, scope 6 systèmes |
| W3 | 2026-05-17 | `trig_01P4AurEvssEAZnbqd3SjFdS` | URL fixée |
| W4 | 2026-05-24 | `trig_01G5CrP9xfqTuneVQ2HxNqwM` | URL fixée |
| W5 | 2026-05-31 | `trig_014CCcBCyNahwxnDySpUpMjy` | URL fixée + intègre script veto contrefactuel |
| **Gate S6** | 2026-06-06 | `trig_01UZwcijDY7TVKNH23BNHAge` | URL fixée + intègre script veto contrefactuel dans la décision finale |

## Configuration veto en prod au 2026-05-08

`/opt/scalping/.env` :
```
GEOPOLITICAL_VETO_ENABLED=true
GEOPOLITICAL_VETO_IRAN_HORMUZ_DAYS=30
```

`GEOPOLITICAL_VETO_IRAN_HORMUZ_DAYS=30` étendu de 14j (default) à 30j pour matcher l'event "US x Iran permanent peace deal by June 30, 2026" (52% prob, 23j d'ici à l'activation). Sans cette extension, aucun veto ne mordrait sur le snapshot actuel — la fenêtre 14j par défaut était trop restrictive. Décision tactique pour observer le mécanisme en charge ; à remonter à 14j quand le contexte Iran évolue.

Concrètement, ce soir, **les longs XAU/USD, XAG/USD, WTI/USD sont skip** par le radar (rejection_code=`geopolitical_veto`).

## Sample shadow log Track A au 2026-05-08

Pré-pipeline géopolitique :
- 24 setups loggés (XAU, XAG, WTI, ETH, XLK)
- 3 réconciliés (XAU SL, XAG SL, WTI TIMEOUT) — 0 win
- 21 jeunes (timeout pas atteint, normal)
- XLI : 0 setup, pattern V2_TIGHT_LONG pas matché sur 12 daily candles (pas un bug)

Post-pipeline géopolitique :
- 0 setup avec `geopolitical_features_json` populé (commit fait à 10h Paris, marchés FX fermés vendredi 22h UTC)
- **Premier capture attendu lundi 03h Paris (Sydney ouverture)**

## Verdict contrefactuel pour le gate S6

**Pour l'agent gate S6 (2026-06-06) :**

Lance `python -m scripts.research.track_a_veto_counterfactual --db /opt/scalping/data/trades.db --no-write`. Le script retourne un rapport Markdown avec :

1. **Sample size verdict** :
   - DÉRISOIRE (n<10) → ignorer la conclusion veto, décider sur Track A pure
   - INSUFFISANT (n<30) → mentionner mais ne pas trancher
   - EXPLOITABLE (n<100) → intégrer comme signal directionnel
   - CRÉDIBLE (n≥100) → intégrer comme signal fort

2. **Verdict directionnel** :
   - "Le veto aurait AIDÉ" → signal pour brancher veto sur Track A en mode filtered
   - "Le veto aurait NUI" → signal pour neutraliser le veto sur Track A
   - "ÉGAL" → laisser le veto en place, c'est neutre

Si verdict EXPLOITABLE+ "aurait aidé", c'est un **argument fort** pour passer Track A en mode **filtered** au gate S6 (variante de Phase 5 : Track A V2_CORE_LONG XAU H4 + filtre veto géopolitique).

Si verdict EXPLOITABLE+ "aurait nui", **garder le veto seulement sur V1**, ne pas l'étendre à Track A.

## Hygiène infra appliquée

- EC2 disk : 84% → **76%** (640MB libérés)
- `journalctl --vacuum-time=7d` : 315MB libérés
- `journald SystemMaxUse=200M` permanent : 360MB de plus + plafond futur
- `deploy-v2.sh` : `image prune -f` → `image prune -a -f` (purge `<none>:<none>` orphelines avec layers parentes)

## Pour reprise

Si user revient sur ce projet après plusieurs jours/semaines :

- Lire `project_geopolitical_shadow_live.md` (auto memory) pour l'état général
- Vérifier `/v2/admin > Geopolitical Veto activity` pour voir combien de vetos ont mordu
- Vérifier `/v2/cockpit > Track A shadow log` pour la perf des 6 systèmes
- Lire le dernier rapport hebdo `docs/superpowers/journal/2026-05-XX-shadow-log-week-X-report.md`
- Si gate S6 est passé : lire `2026-06-06-gate-s6-decision-pending.md`

## Insight session

Le pipeline a été posé en boucle complète en une session :
- Observation (Polymarket card) → décision branchement scoring → veto (4 règles) → observabilité (admin dashboard) → capture pour analyse différée (snapshot shadow log) → outil d'analyse (script contrefactuel) → routines auto pré-câblées → carte Cockpit pour visibilité directe

**C'est rare d'avoir un cycle complet bout-à-bout en une session.** L'élément déclencheur a été une question simple du user : "comme c'est du trading test, je souhaite que la geopolitique soit incorporée dans le décisionnel du scoring de trade". À partir de là, le pipeline s'est construit en cherchant à ce que chaque livrable arme le suivant.
