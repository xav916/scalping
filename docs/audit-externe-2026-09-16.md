# Rapport d'audit — Scalping Radar

**Dossier de préparation à un audit externe**

| | |
|---|---|
| **Objet** | Système automatisé de détection et d'exécution de setups de trading |
| **Dépôt** | `xav916/scalping` — branche `claude/scalping-audit-report-qym1b0` |
| **Commit analysé** | `5cf5994` (2026-09-16) |
| **Date du rapport** | 2026-09-16 |
| **Périmètre** | Performance & edge · Maîtrise du risque · Architecture & sécurité IT · Gouvernance & conformité |
| **Destinataire** | Auditeur externe (technique, quantitatif ou réglementaire) |
| **Production** | `https://app.scalping-radar.online` — AWS EC2, argent réel engagé |

---

## 0. Cadrage — ce que ce document est, et ce qu'il n'est pas

### 0.1 Nature du document

Ce rapport est un **dossier d'audit**, pas un audit. Il a été produit par lecture du
dépôt et exécution de la suite de tests, sans accès à la base de production, aux
comptes courtiers, ni aux serveurs. Il vise à donner à un auditeur externe :

1. une description fidèle du système et de son état réel ;
2. les constats qu'une lecture du code et de la documentation permet d'établir ;
3. la liste des pièces et accès à réclamer pour instruire ce que cette lecture ne
   peut pas trancher.

### 0.2 Méthode

| Élément | Traitement |
|---|---|
| Code source | Lu directement. Les affirmations sur le code sont vérifiables ligne à ligne. |
| Suite de tests | **Exécutée** dans le conteneur d'audit (résultats en §5.6). |
| Chiffres de performance | **Repris de la documentation interne du projet**, non recalculés. Chaque chiffre porte sa source. |
| Base de production, comptes courtiers, logs serveur | **Non accessibles.** Tout ce qui en dépend est marqué comme à vérifier. |

### 0.3 Limites de cette inspection — à lire avant toute conclusion

- ⚠️ **Le clone analysé est *shallow*.** L'historique git disponible ne remonte qu'au
  2026-09-09 (50 commits). L'antériorité du projet — avril à septembre 2026 — n'est
  connue que par la documentation interne, non par les diffs. Un auditeur doit
  travailler sur un clone complet.
- ⚠️ **Les chiffres de performance ne sont pas reproduits.** Ils proviennent du
  journal de recherche et des rapports internes. Leur reproduction exige la base
  `trades.db` / `backtest.db` de production.
- ⚠️ **Aucun relevé de courtier n'a été consulté.** Le rapprochement entre le PnL
  interne et les relevés officiels IC Markets / Kraken / Pepperstone reste à faire —
  c'est le premier travail d'un auditeur financier (§3.7).
- ⚠️ **Ce document ne constitue pas un avis juridique.** Le §6.2 signale un risque
  réglementaire sur la base de faits techniques ; sa qualification relève d'un
  conseil habilité.

### 0.4 Un mot sur la qualité documentaire du projet

Il faut le dire d'emblée parce que c'est inhabituel et que cela change la manière
d'auditer : **ce projet documente ses propres échecs avec une rigueur supérieure à
celle de beaucoup de dispositifs audités.** Le journal de recherche interdit la
réécriture rétroactive, les prédictions sont déclarées avant d'être codées, et les
modules de recherche portent en en-tête les mesures qui les réfutent. Plusieurs des
constats les plus sévères de ce rapport ne sont pas des découvertes de l'auditeur :
**ce sont des constats que le projet a établis lui-même, chiffrés, et écrits noir sur
blanc dans son propre code.**

Cela déplace le travail d'audit. La question n'est pas « le projet se ment-il sur ses
résultats ? » — il ne se ment pas. Elle est : **les décisions opérationnelles sont-elles
alignées sur ce que le projet sait déjà de lui-même ?** C'est là que ce rapport trouve
ses écarts.

---

## 1. Résumé exécutif

### 1.1 Les dix constats

| # | Constat | Axe | Sév. |
|---|---|---|---|
| 1 | **Aucun edge statistiquement établi.** Le projet l'a mesuré lui-même : `DSR = 0,017` après correction du nombre d'essais, `PBO = 0,579`, Δ contrôle aléatoire = +0,004 R sur 29 000 trades. | Perf | **C** |
| 2 | **De l'argent réel est engagé malgré ce constat**, sur des comptes propres *et* sur le compte d'au moins un client tiers. | Gouv | **C** |
| 3 | **Écart backtest / réel de deux ordres de grandeur** : PF annoncés 1,24–5,60, Sharpe 1,59 ; réalisé sur 4 mois = **−982,67 € / 1 085 clôtures, 28,6 % de réussite**. | Perf | **C** |
| 4 | **Exécution automatique sur le compte d'un tiers** (`user:2`, offre Premium 39 €/mois), alors que les CGU déclarent ne fournir aucun conseil en investissement. Qualification réglementaire à faire instruire. | Conf | **C** |
| 5 | **Jeton d'infrastructure en clair dans le dépôt**, en valeur par défaut de 6+ scripts et publié dans la documentation opérationnelle. | Sécu | **E** |
| 6 | **Contournement du rate limiting** possible sur les endpoints sensibles (login, signup, reset) via un en-tête `X-Forwarded-For` forgé. | Sécu | **E** |
| 7 | **Aucune intégration continue n'exécute les tests**, et la suite n'est ni installable d'une source unique ni exécutable en entier sur Linux — les tests des garde-fous de risque MT5 ne tournent donc automatiquement nulle part. | IT | **E** |
| 8 | **CGU / CGV / Politique de confidentialité sont des gabarits non complétés** (`[À COMPLÉTER]` : éditeur, statut juridique, SIRET, adresse), alors que le service est ouvert et facturé. | Conf | **E** |
| 9 | **SQLite en base de production** pour des données de trading et de facturation, avec sessions et rate limiting en mémoire → mono-instance par construction, aucun redémarrage sans rupture. | IT | **M** |
| 10 | **Dispositif de garde-fous dense et de bonne facture** (17+ modules, fail-closed explicite, arbitrage humain sur dépassement) — construit *a posteriori*, incident par incident. | Risque | **Positif** |

### 1.2 Lecture d'ensemble

Le système présente un **profil atypique** : une ingénierie de contrôle du risque et
une discipline méthodologique de recherche nettement au-dessus de la moyenne, au
service d'une stratégie dont **le projet lui-même a démontré qu'elle ne bat pas le
hasard**.

Les risques matériels ne portent donc pas sur la qualité du code, qui est bonne. Ils
portent sur trois écarts :

1. **Écart décision / mesure** — de l'argent réel continue d'être engagé sur des
   configurations que le banc d'essai interne juge sous le plafond du hasard.
2. **Écart produit / statut** — une prestation d'exécution automatique sur compte de
   tiers est vendue sous un habillage contractuel d'outil informatif.
3. **Écart exploitation / criticité** — une infrastructure mono-instance, sans CI,
   avec un secret partagé en clair, opère des ordres en argent réel.

### 1.3 Recommandation de séquence

| Priorité | Action | Délai suggéré |
|---|---|---|
| **P0** | Faire qualifier juridiquement l'offre Premium (auto-exec sur compte tiers) avant toute nouvelle souscription. | Immédiat |
| **P0** | Révoquer et rotationner le jeton `shdw_…`, le sortir du dépôt et des valeurs par défaut. | 24 h |
| **P0** | Décider explicitement, et par écrit, du sort de l'argent réel au vu du `DSR = 0,017` : arrêt, réduction, ou poursuite assumée comme dépense de R&D. | 1 semaine |
| **P1** | Corriger le contournement du rate limiting (`X-Real-IP` au lieu du premier hop XFF). | 1 semaine |
| **P1** | Rendre la suite installable et exécutable sur Linux (IT-1), puis la mettre en CI bloquante. | 2 semaines |
| **P1** | Faire compléter et relire CGU / CGV / Privacy par un juriste. | 1 mois |
| **P2** | Migrer SQLite → PostgreSQL, externaliser sessions et rate limiting. | 1 trimestre |

---

## 2. Le système

### 2.1 Nature et finalité

Scalping Radar est une plateforme SaaS qui :

1. **collecte** des données de marché (prix, calendrier économique, macro, sentiment,
   carnet d'ordres, open interest, funding) sur un univers d'instruments multi-classes ;
2. **détecte** des setups de trading par un moteur de scoring à base de motifs
   chartistes et de filtres contextuels ;
3. **notifie** l'utilisateur (dashboard web, Telegram, e-mail, push navigateur) ;
4. **exécute automatiquement** ces setups sur des comptes courtiers, via des ponts
   (« bridges ») dédiés — MetaTrader 5, Kraken, Binance, Interactive Brokers.

Le point 4 est **le fait central de l'audit** : il fait passer le produit d'un outil
d'aide à la décision à un système d'exécution automatisée.

### 2.2 Chaîne de bout en bout

```
    SOURCES DE DONNÉES
    Twelve Data (prix REST + WS) · Forex Factory (calendrier) · FRED · VIX
    Binance / Kraken (carnet, OI, funding, orderflow) · COT · Reddit
    GDELT + Polymarket (géopolitique) · EIA (pétrole) · Fear & Greed
              │
              ▼
    MOTEUR D'ANALYSE  (cycle ~2 min, APScheduler)
    indicateurs → détection de motifs → scoring de confiance (0-100)
    → vetos (calendrier, earnings, géopolitique, VIX, week-end, macro)
              │
              ▼
    PORTES DE DÉCISION  (chaînées, fail-closed)
    admission de la paire · plafond journalier · plafond par trade · cooldown
    · garde-fou de corrélation · kill switch · porte de coût · banc d'essai
              │
              ▼
    DISPATCH MULTI-DESTINATIONS  (destinations_registry)
    admin_legacy (démo) · admin_live (réel) · admin_kraken (réel)
    · user:N (comptes clients)
              │
              ▼
    BRIDGES                                    NOTIFICATIONS
    MT5 (Flask, VPS Windows)                   Telegram (5 canaux)
    EA MQL5 (file mt5_pending_orders)          E-mail · WebSocket · Push
    Kraken futures / spot · Binance · IBKR
              │
              ▼
    COURTIERS  →  RÉCONCILIATION (mt5_sync, kraken_sync, positions_fermees)
```

### 2.3 Chiffres du dépôt (mesurés)

| Élément | Volume |
|---|---|
| Python total | 144 858 lignes |
| `backend/services/` | 49 067 lignes — **135 modules** |
| `backend/app.py` | 4 583 lignes — **127 routes HTTP/WS** |
| Tests | 62 383 lignes — **302 fichiers, 3 707 fonctions de test** (4 193 cas collectés après paramétrage, cf. §5.6) |
| Bridges (5) | 8 416 lignes Python |
| Expert Advisor MQL5 | 760 lignes |
| Frontend React | ~20 266 lignes TS/TSX |
| Scripts d'exploitation | 104 |
| Documentation | 65+ entrées de journal de recherche, 30+ specs, 7 plans |

**Le ratio test/production est de 1,27:1** — remarquable, et cohérent avec la
discipline documentaire constatée en §0.4.

### 2.4 Univers d'instruments

`CLAUDE.md` décrit 16 paires (forex majeurs, XAU/XAG, BTC/ETH, SPX/NDX, WTI). La
réalité opérationnelle est plus large, et deux sources internes distinctes le montrent :

- le **rapport d'admission hebdomadaire du 2026-08-07** relève 27 buckets `AUTO_EXEC`,
  22 `TELEGRAM`, 2 `PAUSED`, 1 `OBSERVED` ;
- le **dépouillement du 2026-08-26** relève **138 buckets `(paire, sens, destination)`
  distincts dans `pair_admission_state`, sur 104 couples et 49 paires**.

> 🔎 **À faire vérifier.** `CLAUDE.md` (feuille de route) et l'état réel du contrôleur
> d'admission divergent. La feuille de route affiche 16 instruments en « Phase 1
> démo restreinte » ; l'exploitation en compte 49, dont plusieurs cryptos
> (`LDO/USD`, `ETHFI/USD`, `CRV/USD`…) absentes de tout document de cadrage.
> Demander l'état courant de `pair_admission_state`.

---

## 3. Axe A — Performance et edge

### 3.1 La trajectoire de recherche

Le projet a mené, à partir du 2026-04-25, un programme de recherche structuré en
trois tracks (horizon, alt-data macro, trend-following), consigné dans un journal
d'expériences à règles strictes (hypothèse unique, critères go/no-go fixés avant
mesure, pas de réécriture rétroactive).

**Résultats annoncés à l'issue de ce programme** (source : `journal/INDEX.md`) :

| Candidat | n (24 M) | Sharpe | maxDD | Calmar | Rendement 24 M |
|---|---:|---:|---:|---:|---:|
| Track A V2_CORE_LONG XAU H4 | 601 | **1,59** | 20,0 % | 3,18 | +127 % |
| Track A V2_CORE_LONG XAG H4 | 546 | 1,55 | 25,7 % | 2,65 | +136 % |
| Track C TF LONG XAU H4 | 62 | 1,27 | **4,7 %** | **4,45** | +38 % |

Quinze expériences `closed-positive` consécutives, profit factors annoncés de **1,24
à 5,60**, qualifications internes « système prod-ready », « +509 % sur 12 M ».

### 3.2 Le résultat en argent réel

> **−982,67 € sur 1 085 clôtures — taux de réussite 28,6 %**
> *(4 mois ; source : `specs/2026-08-25-banc-essai-hors-echantillon-design.md`,
> repris en en-tête de `backend/services/research_bench.py`)*

Le détail par instrument au gate S8 (2026-07-04) :

| Paire | n | Taux de réussite | PnL USD |
|---|---:|---:|---:|
| XAU/USD | 223 | 38,4 % | **+432,54** |
| EUR/USD | 31 | 27,3 % | +110,11 |
| USD/CHF | 10 | 25,0 % | +58,40 |
| WTI/USD | 116 | 6,1 % | +49,72 |
| ETH/USD | 609 | 26,8 % | −0,89 |
| BCH/USD | 217 | 6,2 % | −11,77 |
| **XAG/USD** | 152 | 29,3 % | **−1 565,98** |
| GBP/USD | 8 | 0 % | −193 |
| EUR/JPY | 48 | 31,8 % | −143 |

Le seul instrument à edge volumique apparent est **XAU/USD**. Un seul instrument
(XAG/USD) porte à lui seul une perte supérieure au résultat net global.

### 3.3 Le diagnostic : surapprentissage, chiffré par le projet lui-même

Le projet n'attribue pas cet écart à la malchance. Il l'a instruit et chiffré.

**a) Deflated Sharpe Ratio.** Audit du 2026-08-25 : la meilleure de 75 variantes rend
un Sharpe journalier de **+0,1703**, quand le maximum attendu **sous l'hypothèse nulle
après 75 essais** vaut **+0,1925**. La meilleure variante jamais trouvée est **sous le
plafond du bruit**. `DSR = 0,350` (seuil de Bailey : 0,95).

**b) Le compteur d'essais réel.** Le dépouillement du 2026-08-26
(`journal/DEPOUILLEMENT-N.md`) établit que le nombre de configurations réellement
examinées n'est pas 75 mais **N = 1 226** — et que ce chiffre est un **plancher**
(sont comptés zéro : les rapports hebdomadaires, les ventilations internes, et tout
ce qui a été essayé sans laisser de trace). Conséquence :

| Hypothèse de calcul | N | Plafond du hasard | DSR |
|---|---:|---:|---:|
| Publié le 25/08 | 75 | +0,1925 | 0,350 |
| Après dépouillement | 1 226 | +0,2626 | **0,054** |
| Tel que le banc juge aujourd'hui | 1 226 | +0,2928 | **0,017** |

**c) Probabilité de surapprentissage.** `PBO = 0,579` sur l'argent réel — *pire que
pile ou face*.

**d) Contrôle aléatoire.** Sept motifs mesurés contre des entrées tirées au hasard :
**Δ = +0,004 R sur 29 000 trades**.

**e) Apprentissage automatique.** `AUC = 0,526`. Phase 2 ML : des entrées **pires que
le hasard**. Le modèle n'a jamais été activé.

**f) Le carnet de concepts.** `docs/concepts-trading.md` porte en tête :

> ⚠️ *Aucun concept n'a jamais atteint ✅. Sept motifs mesurés avant septembre,
> Δ = +0,004 R sur 29 000 trades. C'est l'état normal, pas un échec du dispositif —
> c'est le dispositif qui fonctionne.*

### 3.4 Le gate S6 — la validation prospective a échoué

La phase 4 (shadow log, observation live sans exécution) devait valider le candidat
principal. Résultat au gate du 2026-06-06 :

| Système | n résolus | PF | Taux de réussite | PnL |
|---|---:|---:|---:|---:|
| V2_CORE_LONG XAU H4 | 10 | 0,00 | 0,0 % | −11,2 % |
| V2_CORE_LONG XAG H4 | 6 | 0,00 | 0,0 % | −23,5 % |
| V2_WTI_OPTIMAL WTI H4 | 8 | 0,00 | 0,0 % | −36,2 % |
| V2_CORE_LONG ETH 1D | 2 | 0,00 | 0,0 % | −7,4 % |
| **Portefeuille** | **26** | **0,00** | **0,0 %** | **−78,3 %** |

Le rapport de gate note lui-même : `P(WR=0 | n=26, p_true=0,45) ≈ 1,8×10⁻⁷` — **ce
n'est pas du bruit**.

> ⚠️ **Le gate S6 n'a jamais été formellement clos.** Le document
> `2026-06-06-gate-s6-decision-pending.md` porte le statut « DÉCISION REQUISE PAR
> USER ». Le gate S8 du 2026-07-04 a recommandé de **ne pas fermer le Live** et
> d'**abaisser** le seuil de confiance de 65 à 60 pour « laisser passer un flux
> mesurable ». Un auditeur doit demander la trace écrite de la décision prise sur
> S6, et le raisonnement qui a conduit à assouplir plutôt qu'à resserrer après un
> portefeuille shadow à 0 % de réussite.

### 3.5 Le dispositif correctif — et il est de bonne qualité

Le projet a construit, après ce diagnostic, deux instruments de discipline qui
méritent d'être signalés à un auditeur comme des **points forts** :

**a) Le banc d'essai hors-échantillon** (`backend/services/research_bench.py`).
Trois règles structurantes :

1. **Le futur seul.** L'historique ayant été fouillé 65 fois, il est « brûlé ». Un
   essai n'est jugé que sur des clôtures **postérieures à sa déclaration** — et la
   borne est en SQL, pas dans un avertissement.
2. **N ne décroît jamais.** Abandonner un essai perdant ne le rend pas.
3. **La porte refuse le passage à l'argent réel** sans essai passé qui le couvre.

Un `declaration_hash` (SHA-256) est revérifié au verdict : si le sélecteur a bougé
après avoir vu les données, l'essai est nul. C'est exactement la protection dont
l'absence a produit le problème.

**b) Le laboratoire** (`backend/services/laboratoire_or.py`). Rejeu nocturne par
cellule `(échelle, motif, sens)` avec : séquentialité stricte (jamais deux trades
concurrents sur une cellule), stop testé avant objectif dans une bougie ambiguë,
spread facturé, stops « placebos » (< 0,1 % du prix) écartés, **contrôle aléatoire de
même échelle**, et un **plafond du hasard commun à tous les instruments** — pour que
multiplier les instruments ne multiplie pas les tickets de loterie.

> 🔑 Ces deux modules constituent, à eux seuls, une réponse méthodologique sérieuse au
> problème identifié. La question d'audit n'est pas leur qualité, mais leur **portée
> effective** : `RESEARCH_BENCH_GATE_ENABLED` est à `false` par défaut
> (`config/settings.py:774`), et une clause d'antériorité (`bench_legacy_grants`)
> exempte les configurations déjà en `AUTO_EXEC` au moment de l'installation.

### 3.6 Qualité des données de performance — réserves

**a) Données détruites.** Le 2026-05-18, un `rsync --delete` a détruit **trois
semaines** de données de shadow log. La baseline du gate S6 s'appuie sur W2 + W4 + W5,
W1 étant non probant et W3 inexistant.

**b) Résultats invraisemblables conservés dans les moyennes.** Le rapport
contrefactuel du 2026-09-12 (n = 971) signale sept paires crypto gagnant **100 % du
temps** (`LDO/USD`, `LINK/USD`, `ETHFI/USD`, `CRV/USD`, `BNB/USD`, `SOL/USD`,
`DOGE/USD`) quand l'ensemble gagne 50,5 %. Le rapport les qualifie d'« artefact de
log presque sûr » — **et les conserve dans les chiffres publiés**, au motif que
retirer des données est une décision de méthode revenant à l'humain. La position est
défendable et honnêtement signalée, mais **toute moyenne du système les inclut**.

**c) Stops placebos.** **155 des 181 stops de l'argent réel** étaient à moins de 0,1 %
du prix, produisant des R de plusieurs centaines. Le laboratoire les écarte désormais ;
les statistiques antérieures à ce correctif en sont contaminées.

**d) Dérive entre outil de mesure et exécution.** Le commit du 2026-09-10 note : « le
régulateur écartait des stops placebos, le laboratoire non ». Deux composants
mesuraient la même réalité différemment.

### 3.7 Ce que l'auditeur financier doit exiger

| # | Pièce | Pourquoi |
|---|---|---|
| 1 | **Relevés officiels des courtiers** (IC Markets, Kraken, Pepperstone, Binance) sur toute la période | Le PnL interne n'a jamais été rapproché d'une source externe. C'est le contrôle premier. |
| 2 | Export complet de `trades.db` / `backtest.db` | Recalculer indépendamment PF, Sharpe, DD, DSR. |
| 3 | Journal d'exécution `mt5_pushes` avec `fill_price` et `latency_ms` | Mesurer le slippage réel vs le prix du signal. |
| 4 | État courant de `bench_trials` et `bench_legacy_grants` | Savoir quelles configurations tradent en réel **sans** essai qui les couvre. |
| 5 | Trace écrite de la décision du gate S6 | Établir la gouvernance de la décision de continuer. |
| 6 | Liste des paires actives par destination | Réconcilier les 16 instruments annoncés et les 49 opérés. |

---

## 4. Axe B — Maîtrise du risque

### 4.1 Inventaire des garde-fous

Le système compte **au moins 17 mécanismes de contrôle distincts**, chacun dans son
module, chacun documenté avec l'incident qui l'a motivé.

| Module | Rôle | Défaut |
|---|---|---|
| `kill_switch` | Coupe l'auto-exec : perte journalière, rafale de stops par paire, rafale globale, manuel | Actif |
| `plafond_arbitrage` | Au dépassement du plafond journalier : **blocage immédiat** + question Telegram ; seul un `CONTINUER` explicite débloque, ancré sur la perte atteinte | Actif |
| `porte_risque_par_trade` | Refuse un trade non dimensionnable dans le budget de risque | Actif (MT5) |
| `correlation_guard` | Empêche de prendre deux fois le même pari (corrélations **mesurées**, signe traité) | **Désactivé** |
| `order_cooldown` | Délai minimum entre deux ordres sur un symbole, **par destination** | Ciblé |
| `pair_admission_controller` | Machine à états par `(paire, sens, destination)` : OBSERVED → TELEGRAM → AUTO_EXEC → PAUSED → DEMOTED | Actif |
| `pair_pnl_regulator` | Pause auto d'une paire à −3 % sur 30 trades | Actif |
| `margin_level_check` | Alerte à 70 % de niveau de marge (liquidation à 50 %) | Actif |
| `sltp_guard_check` / `kraken_sltp_guard` | Détecte et protège les positions sans stop | Actif |
| `event_blackout`, `economic_calendar_veto`, `earnings_veto`, `geopolitical_veto`, `vix_scoring` | Vetos contextuels | Variable |
| `weekend_hold_block`, `no_friday_late_open_energy` | Blocage des détentions traversant une fermeture | Actif |
| `cost_model` / porte de coût | Refuse un setup dont l'edge attendu ne couvre pas les frais | Actif |
| `bloc_risque`, `risk_eur`, `sizing` | Dimensionnement et calcul du risque en euros au notionnel réel | Actif |
| `research_bench` | Porte vers l'argent réel | **`false` par défaut** |
| `drift_detection`, `slippage_instrumentation_check` | Surveillance de dérive | Actif |
| `random_entry_control` | Contrôle par entrées aléatoires | Actif |
| `mirror_demo_to_live` | Miroir démo → réel | Configurable |

### 4.2 Qualité de conception — le fail-closed est explicite

`plafond_arbitrage` est exemplaire et mérite d'être cité tel quel :

> ⛔ **Fermé par défaut, à chaque étage.** L'absence de ligne d'arbitrage bloque. Une
> ligne en attente bloque. Une base illisible bloque. Seul un `CONTINUER` explicitement
> enregistré débloque. L'inverse ferait d'une panne — scheduler mort, Telegram muet,
> disque plein — une autorisation de trader, et c'est de l'argent réel.

Et sur l'ancrage de l'autorisation :

> 🔑 Répondre « continue » à −32 € n'autorise pas −300 €.

C'est un raisonnement de sécurité de bon niveau, rare dans des systèmes de cette taille.

### 4.3 Chronologie des incidents de risque

Chaque garde-fou existe parce qu'un incident l'a rendu nécessaire. Cette chronologie
est le meilleur indicateur du profil de risque réel.

| Date | Incident | Correctif |
|---|---|---|
| 2026-04-30 | 9 stops consécutifs XAU/XAG short, **−185,65 € en 5 h**, même motif répété sans cooldown | Cooldown, régulateur |
| 2026-05-18 | `rsync --delete` → **3 semaines de données détruites** | Protection rsync, backups S3 + EBS |
| 2026-08-04 | Short BTC + short ETH simultanés (corrélation mesurée **0,81**), 33 USD de marge sur un compte de 103 | `correlation_guard` (désactivé par défaut) |
| 2026-08-04 | **6 ordres ETH en 27 min**, dont deux de sens opposés à la même seconde | `order_cooldown` |
| 2026-08-04 | Ajout Kraken : `TRADING_CAPITAL` global appliqué à un compte de 103 USD → **ordres 20× trop gros** | `destinations_registry` |
| 2026-08-04 | Trade Kraken annonçant « Risque −0,01 € » pour **~0,57 € réels** | `risk_eur` (calcul au notionnel) |
| 2026-08-06 | Compte réel à **95,5 % de niveau de marge** (position XAU sans stop), déjà sous appel de marge | `margin_level_check` |
| 2026-09-04 | Script de sauvegarde en **deux copies divergentes** hors git, une seule tournant ; `/tmp` en tmpfs saturant le backup | Versionnement, `/var/tmp` |
| 2026-09-08 | Taille de contrat de l'argent **sous-estimée d'un facteur 10** (1 000 oz lue comme 100) | Surcharge par symbole |
| n.d. | « Correctif Kraken disparu — **13 ordres perdus** » (dérive de fichiers non versionnés) | Versionnement |

### 4.4 L'incompatibilité de paramétrage

Le constat de `porte_risque_par_trade` (2026-09-08) est le plus parlant du dossier.
Sur les **21 trades or du compte réel** depuis le 25/08 :

| Grandeur | Valeur |
|---|---|
| Cible configurée | 1 % par trade → 6,50 € |
| **Réalisé, médiane** | **2,6 % → 18,61 €** |
| **Réalisé, pire cas** | **9,2 % → 65,64 €** |
| Plafond de perte journalière | 3 % |

> ⛔ **Une seule position pouvait engager trois fois la perte maximale de la journée.**

La cause racine est structurelle et n'est pas corrigée : les 21 trades sont partis au
**lot minimum du courtier (0,01)**. Le dimensionnement calcule bien ~6,50 €, mais tombe
sous ce plancher et le bridge remonte au minimum. **Le risque n'est donc pas choisi, il
est subi** — il vaut ce que la distance du stop en fait. La seule décision restante est
binaire : prendre ou refuser.

> 🔎 **Conséquence d'audit.** Avec un capital de l'ordre de 650 €, le lot minimum du
> courtier rend le contrôle fin du risque **structurellement impossible**. La porte
> mitige en refusant, mais le problème est un problème de taille de compte, pas de code.

### 4.5 Lacunes de maîtrise du risque

| # | Lacune | Sév. |
|---|---|---|
| R-1 | `correlation_guard` **désactivé par défaut**, alors que l'incident qui l'a motivé est avéré et la corrélation mesurée à 0,81 | **E** |
| R-2 | `RESEARCH_BENCH_GATE_ENABLED=false` par défaut : la porte censée bloquer le passage à l'argent réel est **ouverte** | **E** |
| R-3 | Portes de risque **restreintes aux routes MT5** ; Kraken, Binance, IBKR ne bénéficient pas des mêmes contrôles | **E** |
| R-4 | Risque par trade **subi** (lot minimum) et non choisi ; incompatibilité 9,2 % vs plafond journalier 3 % | **E** |
| R-5 | Promotions `AUTO_EXEC` **manuelles** possibles, contournant les critères automatiques (14 transitions `admin_manual` le 2026-08-07) | **M** |
| R-6 | Promotions auto sur échantillon **complété par des signaux simulés** quand les trades réels manquent (« 0/30 requis ; complété par 30 signaux simulés ») | **M** |
| R-7 | Aucun mécanisme de limite de perte **cumulée** (le plafond est journalier et glissant) | **M** |

---

## 5. Axe C — Architecture et sécurité IT

### 5.1 Pile technique

| Couche | Technologie |
|---|---|
| Backend | Python 3.11, FastAPI 0.115.6, Uvicorn, APScheduler |
| Frontend | React 18, TypeScript, Vite, Tailwind, TanStack Query, lightweight-charts |
| Persistance | **SQLite** (`/app/data/trades.db`, `backtest.db`, `macro.db`) |
| Conteneur | Docker multi-stage (`node:20-alpine` → `python:3.11-slim`) |
| Reverse proxy | Nginx + Let's Encrypt (DNS-01) |
| Hébergement | AWS EC2 ; bridges sur VPS Windows (Lightsail) |
| Paiement | Stripe (Pro 19 €/mois, Premium 39 €/mois) |
| Notifications | Telegram (5 canaux), SMTP/Resend, WebSocket, Web Push |

### 5.2 Ce qui est bien fait

- **En-têtes de sécurité HTTP complets et stricts** : HSTS 1 an + `includeSubDomains`,
  CSP sans `unsafe-inline` sur les scripts, `X-Frame-Options: DENY`,
  `frame-ancestors 'none'`, `X-Content-Type-Options`, `Referrer-Policy`,
  `Permissions-Policy`, `Cross-Origin-Opener-Policy`, `base-uri`, `form-action`.
  TLS limité à 1.2/1.3.
- **Cookies de session** : `HttpOnly` + `Secure` + `SameSite=Strict`, SID de 256 bits
  (`secrets.token_urlsafe(32)`).
- **Mots de passe** : bcrypt cost 12.
- **Comparaisons de secrets en temps constant** (`secrets.compare_digest`) côté backend
  et côté bridges.
- **Dépendances Python épinglées** (une exception : `yfinance>=0.2.40`).
- **Bridges authentifiés** par `X-API-Key` sur tous les endpoints sensibles.
- **Sauvegardes** : S3 quotidien (23:00 UTC), snapshots EBS via DLM, **et un script de
  contrôle de restauration** (`deploy/restore-drill.sh`) — la partie que presque tout le
  monde omet.
- **Registre de destinations** comme source unique de vérité, avec un test qui échoue
  si une destination connue du dispatch n'y est pas déclarée.

### 5.3 Constats de sécurité

#### S-1 — Jeton d'infrastructure en clair dans le dépôt — **ÉLEVÉ**

Le jeton `shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg` :

- est **publié en clair** dans `docs/PHASE4_OPERATIONS_GUIDE.md` ;
- sert de **valeur par défaut** dans au moins 6 scripts d'exploitation
  (`scripts/notify_ibkr_etat.py`, `notify_position_fermee.py`,
  `fermer_metaux_avant_weekend.py`, `wti-auto-pause.py`,
  `notify_activations_equilibre.py`, `mesurer_spreads_hors_crypto.py`) ;
- figure en dur dans plusieurs tests.

Il ouvre l'endpoint public `/api/shadow/v2_core_long/public-summary` et les endpoints
de notification d'infrastructure. Le dépôt étant cloné dans des environnements
d'agents, le jeton est de fait diffusé.

**Recommandation** : révoquer, rotationner, retirer toute valeur par défaut (échec
explicite si la variable d'environnement est absente), purger l'historique git.

#### S-2 — Contournement du rate limiting — **ÉLEVÉ**

`backend/rate_limit.py` construit la clé de limitation ainsi :

```python
xff = request.headers.get("x-forwarded-for", "")
if xff:
    return xff.split(",")[0].strip()   # ← premier hop
```

Or Nginx transmet `X-Forwarded-For $proxy_add_x_forwarded_for`
(`deploy/nginx-app-scalping-online.conf:51`), directive qui **ajoute** l'IP réelle à
la valeur fournie par le client. Un client envoyant `X-Forwarded-For: 1.2.3.4` produit
donc `1.2.3.4, <ip_réelle>`, et l'application retient `1.2.3.4` — **une valeur
entièrement contrôlée par l'attaquant**.

**Impact** : le rate limiting est contournable à volonté sur `login`, `signup`,
`password-reset`, `email-verify`, `stripe-checkout`, `delete-account`. La protection
anti-force-brute des comptes est nulle en pratique.

**Correction** : utiliser `X-Real-IP` (que Nginx écrase avec `$remote_addr`), ou
prendre le **dernier** élément de la chaîne XFF.

#### S-3 — Aucune CI n'exécute les tests — **ÉLEVÉ**

Les deux seuls workflows GitHub (`ea-health-check.yml`, `ea-health-monitor.yml`) font
un contrôle de santé de l'EA quatre fois par jour. **Aucun n'exécute `pytest`, ni le
typecheck TypeScript, ni un linter.** Un projet de 145 000 lignes avec 3 707 tests, qui
opère des ordres en argent réel, n'a aucune barrière automatique avant déploiement.

#### S-4 — Données personnelles dans le dépôt — **MOYEN**

`.env.example` contient des adresses e-mail réelles d'utilisateurs identifiés
(`couderc.xavier@gmail.com`, `c.chaussis@icloud.com`), avec la structure
`AUTH_USERS=email:motdepasse`. Les mots de passe sont des placeholders, mais le
couple identité/rôle est exposé. Le fichier `docs/onboarding-cedric-bridge.md`
identifie nommément le premier client Premium, son e-mail et son identifiant interne.

#### S-5 — État applicatif en mémoire → mono-instance — **MOYEN**

- **Sessions** : dictionnaire Python en mémoire (`backend/auth.py`). Tout redémarrage
  déconnecte tout le monde ; aucune révocation centralisée ; aucune montée en charge
  horizontale possible.
- **Rate limiting** : stockage en mémoire (`slowapi`), même limite.
- **SQLite** : `isolation_level=None`, fichier unique, pour des données de trading
  **et** de facturation.

Le code documente lui-même ces limites et désigne le point de changement unique — c'est
une dette **assumée et tracée**, pas une négligence. Elle reste incompatible avec une
exploitation SaaS multi-clients.

#### S-6 — Durcissement du conteneur — **MOYEN**

- Aucune directive `USER` : le conteneur **tourne en root**.
- `COPY . .` embarque l'intégralité du dépôt dans l'image (documentation, scripts,
  tests, bridges) alors que `.dockerignore` est minimal.
- `build-essential` est installé et **non retiré** de l'image finale.
- Aucun `HEALTHCHECK`.

#### S-7 — Repli sur clé générée côté bridge — **FAIBLE**

`mt5-bridge/bridge.py` : si `BRIDGE_API_KEY` est absente, une clé aléatoire est générée
au démarrage **et écrite en clair dans les logs**. Le comportement est fail-open sur la
configuration (le bridge démarre quand même) et expose le secret dans les journaux.
Un échec explicite au démarrage serait préférable.

#### S-8 — Basic Auth en repli — **FAIBLE**

`backend/auth.py` conserve Basic Auth en repli pour « les anciens bookmarks avec auth
dans l'URL » et les scripts de monitoring. Les identifiants transitent alors dans des
en-têtes réutilisables, et potentiellement dans des URL journalisées.

### 5.4 Architecture des bridges

Cinq ponts d'exécution, 8 416 lignes :

| Bridge | Lignes | Cible | Hébergement |
|---|---:|---|---|
| MT5 | 3 941 | MetaTrader 5 (Flask) | VPS Windows |
| Kraken futures | 2 027 | Kraken Futures | — |
| Binance | 929 | Binance Futures | — |
| Kraken spot | 803 | Kraken Spot | — |
| IBKR | 716 | Interactive Brokers TWS | — |
| EA MQL5 | 760 | File `mt5_pending_orders` | MT5 Desktop client |

Deux chemins d'exécution coexistent (bridge Python pour l'admin, file + EA pour les
clients). Le routage dépend de `users.tier = 'premium' AND users.api_key_set = true`.

> 🔎 **À vérifier** : la coexistence de deux chemins d'exécution a déjà produit un
> incident de « DOUBLE ORDRE » (commit du 2026-09-15 : « un setup de chaîne non armée
> passait par la porte normale »). Demander la preuve qu'un setup ne peut pas être
> exécuté deux fois.

### 5.5 Points d'exploitation notables

- **Le VPS Windows est un point de défaillance unique** non redondé pour toute
  l'exécution MT5.
- **Le déploiement passe par `rsync`** — c'est l'outil qui a détruit trois semaines de
  données le 2026-05-18. Une protection a été ajoutée ; sa robustesse est à vérifier.
- **Des scripts d'exploitation ont vécu hors git** sur le serveur, en copies
  divergentes, causant au moins deux incidents (« correctif Kraken disparu — 13 ordres
  perdus », backup en double). Corrigé depuis le 2026-09-04.
- **104 scripts d'exploitation** dont beaucoup pilotés par cron : la surface
  opérationnelle est large et peu outillée.

### 5.6 Résultat de la suite de tests — **exécutée pour cet audit**

La suite a été exécutée dans le conteneur d'audit (Linux, Python 3.11). Trois passes
ont été nécessaires, et **c'est en soi le premier constat**.

| Passe | Installation | Résultat |
|---|---|---|
| 1 | `requirements.txt` seul | **Collecte interrompue** — `ModuleNotFoundError: MetaTrader5` |
| 2 | idem, 5 fichiers exclus | 4 031 passés · 21 ignorés · **120 erreurs** |
| 3 | `requirements.txt` **+ `Flask`**, 2 fichiers exclus | **4 193 passés · 5 ignorés · 52 erreurs · 0 échec** (156 s) |

**Décomposition des erreurs de la passe 3 :**

| Cause | n | Fichiers |
|---|---:|---|
| `ModuleNotFoundError: MetaTrader5` | 49 | `test_mt5_bridge_sltp_protection`, `test_bridge_horloge_serveur`, `test_bridge_risque_engage` (+ 2 exclus à la collecte) |
| `sqlite3.OperationalError: no such table: users` | 3 | `test_user_prefs_e2e` |

**Lecture :**

- ✅ **Zéro échec fonctionnel** (`failed = 0`) sur 4 193 tests exécutés. C'est un bon
  signal sur la santé du code testé.
- ❌ **La suite n'est pas installable depuis une source de dépendances unique.** Les
  tests des bridges importent `mt5-bridge/bridge.py`, qui dépend de **Flask** — déclaré
  dans `mt5-bridge/requirements.txt`, **absent de `requirements.txt`**. Un auditeur (ou
  un contributeur) qui suit le `README` obtient **120 erreurs** sans qu'aucune
  documentation ne l'explique. C'est une conséquence directe de l'absence de CI (S-3) :
  personne n'a jamais eu à faire fonctionner cette installation de zéro.
- ❌ **Cinq fichiers de tests sont inexécutables hors Windows**, car ils dépendent du
  module `MetaTrader5` : `test_mt5_bridge_controle_risque`, `test_mt5_bridge_margin_fit`,
  `test_mt5_bridge_sltp_protection`, `test_bridge_horloge_serveur`,
  `test_bridge_risque_engage`. **Ce sont précisément les tests des garde-fous de risque
  MT5** — contrôle du risque, ajustement à la marge, protection SL/TP, risque engagé.
  Combiné à S-3, cela signifie qu'ils ne sont **vérifiés automatiquement nulle part** :
  ni en CI (inexistante), ni sur une machine Linux, uniquement à la main sur un poste
  Windows.
- ❌ **Trois tests dépendent de l'ordre d'exécution** (`test_user_prefs_e2e` présuppose
  un schéma `users` créé par un autre test). Le commentaire du code parle de « trois
  rouges permanents » : le problème est connu et non corrigé.

> 🔎 **Constat d'audit (IT-1, ÉLEVÉ — relevé de MOYEN après mesure)** : un patrimoine de
> 4 200 tests de très bonne facture est **inexploitable comme filet de sécurité** en
> l'état. Il n'est ni installable d'une seule commande, ni exécutable en entier sur la
> plateforme de déploiement, ni hermétique à l'ordre d'exécution — et il n'est exécuté
> par aucune automatisation. Les trois corrections (déclarer Flask, abstraire
> `MetaTrader5` derrière un stub, rendre les fixtures auto-portantes) sont peu coûteuses
> et conditionnent la mise en CI.

---

## 6. Axe D — Gouvernance et conformité

### 6.1 Statut réel : démo ou argent réel ?

`CLAUDE.md` décrit un système « actuellement **en démo** ». **Ce n'est plus exact.**
Sont engagés en argent réel :

| Destination | Statut | Élément probant |
|---|---|---|
| `admin_live` | **Argent réel** — IC Markets EU (CySEC) | `2026-06-12-icmarkets-live-runbook.md`, `margin_level_check` |
| `admin_kraken` | **Argent réel** — compte ~103 USD | `order_cooldown`, `destinations_registry` |
| `user:2` | **Compte d'un client tiers** | `order_cooldown`, `mt5_bridge.py:42` |
| `admin_legacy` | Démo Pepperstone | — |

Le module `destinations_registry` traite d'ailleurs le caractère réel comme une
propriété **déclarée, jamais déduite** — bonne pratique — avec repli sur « fictive »
en cas d'ignorance.

> ⚠️ **Constat de gouvernance (G-1, ÉLEVÉ)** : le document de cadrage de référence du
> projet (`CLAUDE.md`) décrit un état — 16 instruments, démo, forex + métaux seulement
> — qui ne correspond plus à l'exploitation : 49 paires, quatre destinations dont trois
> en argent réel, cinq classes d'actifs. **Un auditeur ne doit pas se fier à
> `CLAUDE.md` comme description du système.** La mise à jour de ce document est une
> action corrective prioritaire.

### 6.2 Risque réglementaire — le point le plus sérieux du dossier

**Les faits établis :**

1. Le service est **commercialisé** : offres Stripe Pro 19 €/mois et **Premium
   39 €/mois**, cette dernière décrite comme « Tout Pro + backtest + multi-broker +
   **auto-exec MT5 bridge** » (`docs/saas-prod-setup.md`).
2. Au moins **un client tiers** est effectivement servi : `user:2`
   (`c.chaussis@icloud.com`, id 17), avec des ordres **automatiquement exécutés sur son
   propre compte MT5**. Le rythme de ses ordres est mesuré sur 30 jours
   (`order_cooldown`), ce qui atteste d'une exploitation effective, pas d'un pilote.
3. Les **CGU** (`frontend/docs/cgu.html`) déclarent :
   > *« Le Service ne fournit ni ne constitue un conseil en investissement, une
   > recommandation personnalisée, un signal d'investissement garanti, ni une offre de
   > service financier régulé. […] L'utilisateur prend toutes ses décisions de trading
   > en pleine autonomie, sous sa seule responsabilité. »*
4. Les mêmes CGU décrivent l'objet du service comme un **tableau de bord et des
   alertes** — l'exécution automatique n'y figure pas.

**L'écart :** un utilisateur dont les ordres sont générés, dimensionnés, déclenchés,
protégés (SL/TP) et clôturés par le système **ne prend pas ses décisions en pleine
autonomie**. La clause d'exonération décrit un produit qui n'est pas celui qui est
vendu.

**Ce que cela peut engager** (à faire qualifier — ceci n'est pas un avis juridique) :

- une activité de **réception-transmission d'ordres** ou de **gestion de portefeuille
  pour compte de tiers**, soumises à agrément (AMF / ACPR, directive MiFID II) ;
- l'inopposabilité de la clause d'exonération, celle-ci ne décrivant pas la prestation
  réellement fournie ;
- une exposition en responsabilité sur les pertes subies par le client.

**Élément aggravant :** le projet dispose, en interne, de la démonstration chiffrée que
la stratégie **ne bat pas le hasard** (§3.3). Vendre 39 €/mois l'exécution automatique
d'une stratégie dont on a mesuré le `DSR = 0,017` constitue un risque distinct, de
nature informationnelle.

**Élément à décharge :** le projet a rencontré et respecté une contrainte réglementaire
similaire — le 2026-06-11, un passage en réel chez Pepperstone a été **bloqué par
l'AMF** (compte MT4 seulement pour le retail français), conduisant à un pivot vers IC
Markets EU. La conscience réglementaire existe ; elle n'a simplement pas été appliquée
à la question de l'exécution pour compte de tiers.

> **Recommandation P0** : suspendre toute nouvelle souscription Premium avec auto-exec
> jusqu'à qualification par un conseil habilité en droit financier.

### 6.3 Documents contractuels — non finalisés

`frontend/docs/cgu.html` (dernière mise à jour : 23 avril 2026) porte en tête un
encart explicite :

> *« Template à personnaliser — Ce document est un gabarit. Avant le lancement public,
> il faut impérativement remplacer les mentions [À COMPLÉTER] par les vraies infos
> légales (dénomination, SIRET, adresse, etc.) et faire relire par un juriste. »*

Restent non renseignés : **éditeur, statut juridique, SIRET, adresse**. Les mêmes
réserves valent pour `cgv.html` et `privacy.html`.

Le service est pourtant ouvert, facturé via Stripe, et sert au moins un client payant.

> ⚠️ **Constat (G-2, ÉLEVÉ)** : exploitation commerciale sans mentions légales valides.
> Manquement direct aux obligations d'identification de l'éditeur (LCEN) et aux
> exigences d'information précontractuelle.

### 6.4 RGPD

| Point | État |
|---|---|
| Base de données utilisateurs | SQLite, e-mails + hash bcrypt + données Stripe |
| Suppression de compte | Endpoint dédié, rate-limité, idempotent côté Stripe ✅ |
| Vérification e-mail, reset mot de passe | Implémentés, tokens à expiration ✅ |
| Acceptation des CGU | Tracée (`test_terms_acceptance.py`) ✅ |
| Politique de confidentialité | **Gabarit non complété** ❌ |
| Registre des traitements | Non trouvé ❌ |
| DPA sous-traitants (AWS, Stripe, Resend, Telegram, Twelve Data) | Non trouvés ❌ |
| Durée de conservation | Non documentée ❌ |
| Transferts hors UE (Telegram, Twelve Data) | Non analysés ❌ |
| PII dans le dépôt | E-mails réels en clair (S-4) ❌ |

### 6.5 Traçabilité — un point fort

À porter au crédit du dispositif :

- **Journal de recherche à règles strictes** : hypothèse unique, critères go/no-go
  fixés avant mesure, **interdiction de réécriture rétroactive**, verdict en une ligne.
- **Carnet de concepts** où chaque notion est déclarée, avec sa prédiction falsifiable,
  **avant** d'être codée — et où les erreurs de l'auteur sont conservées et marquées
  (⛔ « ma première prédiction était MAL FORMÉE »).
- **Registre des rejets** (`rejection_service`) : les setups refusés sont journalisés
  avec leur motif et leur destination.
- **Journal des abandons silencieux** (`silent_drops`) : ce qui disparaît sans erreur
  est tracé — c'est exactement ce que la plupart des systèmes ratent.
- **Grand livre des pushes** (`bridge_push_ledger`) et réconciliation courtier
  (`mt5_sync`, `kraken_sync`, `shadow_reconciliation`).
- **Dépouillement du compteur d'essais** publié, justifié ligne à ligne, et
  explicitement présenté comme un **plancher**.

> 🔑 Cette traçabilité est la raison pour laquelle un audit externe de ce système est
> praticable en quelques jours plutôt qu'en plusieurs semaines.

---

## 7. Registre des constats

| Réf | Constat | Axe | Sév. | Effort |
|---|---|---|---|---|
| **P-1** | Aucun edge établi : `DSR = 0,017`, `PBO = 0,579`, Δ aléatoire +0,004 R / 29 000 trades | Perf | **C** | Décision |
| **P-2** | Argent réel engagé malgré P-1, sur comptes propres et compte client | Gouv | **C** | Décision |
| **P-3** | Écart backtest/réel : −982,67 € / 1 085 clôtures, 28,6 % de réussite | Perf | **C** | — |
| **C-1** | Exécution automatique sur compte de tiers vs CGU « aucun conseil » — qualification MiFID/AMF à instruire | Conf | **C** | Juridique |
| **P-4** | Gate S6 (0 % de réussite sur 26 setups) jamais formellement clos ; seuils **assouplis** après | Gouv | **E** | Décision |
| **S-1** | Jeton `shdw_…` en clair : docs, 6+ scripts en valeur par défaut, tests | Sécu | **E** | 1 j |
| **S-2** | Rate limiting contournable via `X-Forwarded-For` forgé | Sécu | **E** | 2 h |
| **S-3** | Aucune CI n'exécute les 3 707 tests | IT | **E** | 2 j |
| **IT-1** | Suite de tests non installable d'une source unique (Flask non déclaré), 5 fichiers inexécutables hors Windows — dont **tous les tests des garde-fous de risque MT5** —, 3 tests dépendants de l'ordre | IT | **E** | 3 j |
| **G-2** | CGU/CGV/Privacy = gabarits `[À COMPLÉTER]` sur service commercialisé | Conf | **E** | Juridique |
| **G-1** | `CLAUDE.md` décrit un système obsolète (16 paires/démo vs 49 paires/3 comptes réels) | Gouv | **E** | 1 j |
| **R-1** | `correlation_guard` désactivé malgré incident avéré (corr. 0,81) | Risque | **E** | Décision |
| **R-2** | `RESEARCH_BENCH_GATE_ENABLED=false` : la porte vers l'argent réel est ouverte | Risque | **E** | 1 h |
| **R-3** | Portes de risque limitées à MT5 ; Kraken/Binance/IBKR non couverts | Risque | **E** | 1 sem |
| **R-4** | Risque par trade subi (lot minimum) : 9,2 % observé vs plafond journalier 3 % | Risque | **E** | Structurel |
| **P-5** | Moyennes incluant des paires à 100 % de réussite, qualifiées d'artefact par le projet | Perf | **M** | 2 j |
| **P-6** | Trois semaines de données de validation détruites (rsync 2026-05-18), jamais reconstituées | Perf | **M** | — |
| **S-4** | E-mails réels d'utilisateurs dans `.env.example` et la documentation | Sécu | **M** | 1 h |
| **S-5** | Sessions + rate limiting en mémoire, SQLite en production → mono-instance | IT | **M** | 1 mois |
| **S-6** | Conteneur en root, `build-essential` conservé, `COPY . .`, pas de `HEALTHCHECK` | Sécu | **M** | 1 j |
| **R-5** | Promotions `AUTO_EXEC` manuelles contournant les critères automatiques | Risque | **M** | Process |
| **R-6** | Promotions sur échantillon complété par des signaux **simulés** | Risque | **M** | 2 j |
| **R-7** | Pas de limite de perte cumulée (seulement journalière) | Risque | **M** | 2 j |
| **G-3** | RGPD : pas de registre des traitements, pas de DPA, pas de durée de conservation | Conf | **M** | 1 sem |
| **IT-2** | VPS Windows = point de défaillance unique pour l'exécution MT5 | IT | **M** | 1 mois |
| **S-7** | Bridge : clé API générée et journalisée en clair si absente (fail-open config) | Sécu | **F** | 1 h |
| **S-8** | Basic Auth conservé en repli | Sécu | **F** | 2 h |
| **IT-3** | `yfinance>=0.2.40` non épinglé | IT | **F** | 5 min |

**Légende** — C : critique · E : élevé · M : moyen · F : faible

### 7.1 Points forts à consigner

Un audit qui n'inscrit que des manquements donne une image fausse de ce système.

| Réf | Point fort |
|---|---|
| **F-1** | Ratio test/production de 1,27:1 — 3 707 tests, aucun échec fonctionnel |
| **F-2** | Journal de recherche à règles anti-biais, sans réécriture rétroactive |
| **F-3** | Banc d'essai hors-échantillon avec `declaration_hash` et compteur d'essais monotone |
| **F-4** | Laboratoire avec contrôle aléatoire et plafond du hasard commun multi-instruments |
| **F-5** | Fail-closed explicite et raisonné sur le plafond journalier, avec arbitrage humain ancré |
| **F-6** | En-têtes de sécurité HTTP complets et CSP stricte |
| **F-7** | Sauvegardes S3 + EBS **avec contrôle de restauration** |
| **F-8** | Journalisation des rejets et des abandons silencieux |
| **F-9** | Registre de destinations comme source unique de vérité, verrouillé par un test |
| **F-10** | Corrélations, coûts et tailles de contrat **mesurés** sur données réelles, jamais supposés |

---

## 8. Ce que l'auditeur externe doit demander

### 8.1 Accès

| # | Accès | Pour |
|---|---|---|
| 1 | Clone git **complet** (non shallow) | Reconstituer l'historique avril → septembre |
| 2 | Export `trades.db`, `backtest.db`, `macro.db` | Recalculer les métriques indépendamment |
| 3 | Lecture seule sur l'EC2 de production | Vérifier configuration effective, cron, logs |
| 4 | Contenu réel du `.env` de production (anonymisé) | Vérifier quels garde-fous sont **effectivement** actifs |
| 5 | Relevés officiels des courtiers | Rapprochement du PnL |
| 6 | Accès Stripe (lecture) | Nombre de clients, revenus, remboursements |

### 8.2 Questions à poser

1. **Quelle décision a été prise au gate S6**, par qui, et sur quel raisonnement ? Où
   est-elle tracée ?
2. **Combien de clients tiers** ont aujourd'hui l'auto-exec activé, sur quels comptes,
   pour quels encours ?
3. **Quel est le PnL cumulé de ces clients** depuis l'activation ?
4. **Ces clients ont-ils été informés** du `DSR = 0,017` et du résultat de −982,67 € ?
5. **Quelles configurations tradent en argent réel** sans essai de banc qui les couvre
   (clause d'antériorité `bench_legacy_grants`) ?
6. **Pourquoi `correlation_guard` est-il désactivé** alors que l'incident est avéré ?
7. **Comment les 49 paires opérées** se réconcilient-elles avec les 16 annoncées ?
8. **Quel est le plan de reprise** en cas de perte du VPS Windows ?
9. **Qui a l'autorité** de promouvoir une paire en `AUTO_EXEC` manuellement, et sous
   quel contrôle ?
10. **Les paires à 100 % de réussite** ont-elles été instruites comme artefact de log,
    et les chiffres publiés corrigés ?

### 8.3 Contrôles à exécuter

| # | Contrôle | Méthode |
|---|---|---|
| 1 | Rapprochement PnL interne / relevés courtiers | Comparaison ticket à ticket |
| 2 | Recalcul indépendant du DSR avec N = 1 226 | Reproduire `deflated_sharpe()` |
| 3 | Mesure du slippage signal → fill | `mt5_pushes.fill_price` vs prix du signal |
| 4 | Test d'intrusion sur le contournement S-2 | Requêtes avec XFF forgé sur `/api/login` |
| 5 | Vérification que le jeton S-1 est révoqué | Appel de l'endpoint public avec l'ancien jeton |
| 6 | Exécution de la suite de tests **sur Windows** | Couvrir les 5 fichiers MT5 non testables |
| 7 | Contrôle de restauration effectif | Exécuter `deploy/restore-drill.sh` |
| 8 | Vérification de l'unicité d'exécution | Rechercher les doubles ordres dans `mt5_pushes` |

---

## Annexe A — Commandes de vérification

```bash
# Volumétrie du code
find . -name "*.py" -not -path "./.git/*" | xargs wc -l | tail -1
find backend/services -name "*.py" | xargs wc -l | tail -1
grep -c "@app\.\(get\|post\|put\|delete\|patch\|websocket\)" backend/app.py

# Suite de tests. ⚠️ requirements.txt NE SUFFIT PAS : les tests des bridges
# importent mt5-bridge/bridge.py, qui dépend de Flask (déclaré ailleurs).
pip install -r requirements.txt
pip install flask==3.0.3            # sinon 120 erreurs de collecte
python -m pytest backend/tests -q \
  --ignore=backend/tests/test_mt5_bridge_controle_risque.py \
  --ignore=backend/tests/test_mt5_bridge_margin_fit.py
# Attendu sur Linux : 4 193 passés · 5 ignorés · 52 erreurs · 0 échec
# (49 erreurs = module MetaTrader5 absent hors Windows ; 3 = ordre d'exécution)

# Constat IT-1 — Flask requis mais non déclaré dans requirements.txt
grep -i flask requirements.txt mt5-bridge/requirements.txt

# Constat S-1 — jeton en clair
grep -rn "shdw_" --include="*.py" --include="*.md" .

# Constat S-2 — clé de rate limiting vs directive nginx
sed -n '20,35p' backend/rate_limit.py
grep -n "X-Forwarded-For" deploy/nginx-app-scalping-online.conf

# Constat S-6 — durcissement du conteneur
grep -n "USER\|HEALTHCHECK" Dockerfile   # aucun résultat attendu

# Constat R-2 — état de la porte vers l'argent réel
grep -n "RESEARCH_BENCH_GATE_ENABLED" config/settings.py

# Constat G-2 — mentions légales non complétées
grep -c "À COMPLÉTER" frontend/docs/cgu.html frontend/docs/cgv.html
```

## Annexe B — Sources documentaires internes

| Document | Contenu |
|---|---|
| `backend/services/research_bench.py` | En-tête : −982,67 €, DSR 0,350, les trois règles du banc |
| `backend/services/laboratoire_or.py` | En-tête : DSR 0,35, PBO 0,579, Δ +0,004 R / 29 000 trades, AUC ML |
| `docs/superpowers/journal/DEPOUILLEMENT-N.md` | N = 1 226 ; DSR recalculé à 0,054 puis 0,017 ; 138 buckets sur 49 paires |
| `docs/superpowers/specs/2026-08-25-banc-essai-hors-echantillon-design.md` | Conception du banc ; 65 entrées de journal |
| `docs/superpowers/journal/INDEX.md` | 36 expériences, verdicts, Sharpe/PF/maxDD annoncés |
| `docs/superpowers/journal/2026-06-06-gate-s6-decision-pending.md` | Gate S6 : portefeuille à 0 % de réussite, décision en suspens |
| `docs/gate_s8_brief_2026-07-04.md` | Historique par paire en argent réel ; trois voies proposées |
| `docs/superpowers/journal/2026-09-12-track-a-veto-counterfactual.md` | n = 971 ; paires à résultat invraisemblable |
| `docs/superpowers/journal/2026-08-07-pair-admission-weekly.md` | États d'admission : 27 AUTO_EXEC, 22 TELEGRAM ; promotions manuelles |
| `docs/concepts-trading.md` | Carnet de concepts ; « aucun concept n'a jamais atteint ✅ » |
| `docs/architecture-current-state.md` | Carte des couches (⚠️ datée du 2026-04-30) |
| `docs/superpowers/journal/2026-06-11-live-test-100eur-tracker.md` | Paramètres de sécurité du compte réel ; pivot AMF |
| `frontend/docs/cgu.html` | CGU — gabarit non complété |
| `docs/saas-prod-setup.md` | Offres Stripe et leur description |

## Annexe C — Glossaire

| Terme | Définition |
|---|---|
| **DSR** (*Deflated Sharpe Ratio*) | Sharpe corrigé du nombre de configurations essayées. Seuil de Bailey : 0,95. |
| **PBO** (*Probability of Backtest Overfitting*) | Probabilité que la configuration retenue soit surapprise. 0,5 = pile ou face. |
| **PF** (*Profit Factor*) | Somme des gains / somme des pertes. |
| **R** | Résultat d'un trade exprimé en multiple du risque initial. |
| **Cellule** | Triplet `(échelle, motif, sens)` évalué par le laboratoire. |
| **Plafond du hasard** | \|t\| maximal attendu sans aucun effet, croissant avec le nombre de cellules. |
| **Destination** | Compte de trading cible (`admin_live`, `admin_kraken`, `user:N`…). |
| **Shadow log** | Journalisation d'un système observé sans exécution. |
| **Gate** | Point de décision planifié (S6, S8) sur la poursuite d'une phase. |
| **Setup** | Opportunité de trade détectée, scorée de 0 à 100. |
| **Fail-closed** | Conception où toute panne bloque l'action plutôt que de l'autoriser. |

---

*Rapport établi le 2026-09-16 sur le commit `5cf5994`. Les affirmations portant sur le
code sont vérifiables dans le dépôt ; celles portant sur la performance sont reprises
de la documentation interne du projet et n'ont pas été recalculées. Les limites de
cette inspection sont énoncées au §0.3.*
