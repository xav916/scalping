# Pré-inscription — `5min` hors échantillon PROSPECTIF, à prix exécutable

**Figée le 2026-10-31. Fenêtre de mesure : 2026-10-28 → 2026-11-13.**
Rien n'est mesuré avant le 13/11 : ce document existe pour que la décision
soit prise **avant** de voir le résultat.

## La question, et pourquoi elle est encore ouverte

Le `5min` a été **retiré le 28/10** (`644fded`) comme **NON ÉTABLI — pas
réfuté**. Le motif n'était pas l'absence d'information : c'était que le bras
réel se remplissait à un prix **non exécutable**.

```
entry_price n'est ni une ouverture ni une cloture dans 87,8 % des cas,
et tombe HORS de sa bougie dans 50,2 %.

bras STOCKE (le publie)      ecart +0,091961 R   t +4,386   100,0 % battus
bras FILL A L'OUVERTURE      ecart -0,046533 R   t -2,219     1,5 % battus
```

🔑 **Les deux bras n'avaient jamais partagé leur MODÈLE D'EXÉCUTION.** Le
retrait vaut aussi pour `c5c68dc` — la réplication hors échantillon, qui
reposait sur le même fill.

⇒ La question *« le `5min` porte-t-il de l'information à un prix qu'on peut
réellement obtenir ? »* **n'a jamais été tranchée**. Un hors échantillon
**prospectif** la tranche, parce que la symétrie d'exécution y est **native** :
on ne peut pas remplir un trade futur à un prix qui n'existe pas.

## Protocole

| | |
|---|---|
| population | `shadow_setups`, `timeframe=5min`, `detected_at >= 2026-10-28`, dénoué |
| bras réel | fill à l'**OUVERTURE de la bougie suivant la détection** |
| placebo | entrées tirées au hasard dans **la même fenêtre**, **les mêmes paires**, **la même géométrie** (`risk_pct` réutilisé setup par setup), et le **même modèle d'exécution** |
| graine | `20261113`, déclarée — un placebo non reproductible ne peut pas être re-vérifié |
| tirages | 200 |
| coût | `cout_execution.cout_spread_relatif` au tick de l'instant pour l'or ; **hypothèse de classe refusée** pour un niveau absolu (`exiger_mesure`) |

⛔ **Le bras réel et le placebo doivent partager leur source, leur géométrie
ET leur modèle d'exécution.** C'est la condition dont le non-respect a produit
+0,15 R d'artefact en août et invalidé le résultat d'octobre. Le banc doit
**s'arrêter** si les deux arms n'ont pas le même nombre de fills exécutables.

## Prédictions — ce qui peut me contredire

1. **L'écart sera négatif ou indiscernable.** Les trois horizons mesurés le
   sont (`1d` pire que le hasard, `4h` indiscernable, `5min` retiré), et le
   bras à fill symétrique donnait déjà **−0,0465 R**.
2. Le coût mesuré de l'or restera proche de **0,0000450** — s'il s'en écarte
   de plus de 20 %, c'est l'instrument qu'il faut regarder, pas le marché.
3. Au moins **300 setups** seront dénoués : la cadence observée est de
   ~7 100 setups `5min` sur 30 jours.

⚠️ Si la prédiction 1 est démentie — écart positif, `t > +2`, plus de 97,5 %
des tirages battus — **le signal est admis**, et je dois le dire aussi
clairement que je dis les refus.

## Critère

<!-- CRITERE-MACHINE
statistique: esperance_R_5min_prospectif_fill_executable
forme: placebo
horizon: 5min
population: timeframe=5min AND detected_at>=2026-10-28 AND outcome IS NOT NULL
fenetre_debut: 2026-10-28
fenetre_fin: 2026-11-13
modele_execution: open_bougie_suivante
graine: 20261113
tirages: 200
cellules: 1
reference_ecart_fill_symetrique_R: -0.046533
reference_t_fill_symetrique: -2.219
reference_cout_or_relatif: 0.0000450
validite: setups_denoues >= 300 ET fills_executables_pct == 100 ET bras_partagent_execution == 1
admission: ecart_R > 0.02 ET t > 2.0 ET tirages_battus_pct > 97.5
rejet: ecart_R <= 0.0 OU t < -2.0
P1_ecart_R_max: 0.02
P2_t_max: 2.0
P3_setups_denoues_min: 300
P4_cout_or_relatif_min: 0.000036
P5_cout_or_relatif_max: 0.000054
P6_fills_executables_pct_min: 100.0
-->

## Ce que ce document ne fait pas

- il ne réarme rien : **REM-002 reste `DISARMED_MANUALLY`**, et la mesure
  porte sur le vivier d'**observation**, pas sur des ordres réels ;
- il ne rouvre pas `1d` ni `4h`, dont les verdicts tiennent ;
- il ne promet aucun avantage : il rend la question **décidable**, ce qu'elle
  n'est pas aujourd'hui.
