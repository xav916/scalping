# Plan SaaS — transformer Scalping Radar en produit

**Date** : 2026-04-23
**Statut** : spec initiale, démarrage Chantier 1
**Objectif business** : revenu complémentaire 500-1500€/mois à 12 mois via SaaS Pro/Premium.

---

## Contexte

Le backtest 10 ans + ML training ont prouvé que le scoring actuel n'a pas
d'edge suffisant pour générer un complément de salaire via trading direct
(cf. `2026-04-22-backtest-v1-findings.md` + `2026-04-22-ml-findings.md`).

Le vrai angle monétisable : **le dashboard/cockpit/analytics lui-même est
un produit** que d'autres traders retail MT5/Pepperstone paieraient pour
utiliser. Ce chantier transforme l'app mono-utilisateur (couderc.xavier
hardcodé en .env) en SaaS multi-tenant avec tiers payants.

## Objectifs

1. **Multi-tenant complet** : chaque user a ses propres trades, configs,
   broker connexion, préférences, isolés.
2. **Signup self-service** : email + password, sans intervention admin.
3. **Tiers payants** via Stripe : Free (limité), Pro 19€/mois, Premium 39€/mois.
4. **Feature gating** : certaines fonctionnalités verrouillées par tier.
5. **Onboarding broker** : wizard pour connecter son compte MT5 via bridge
   perso ou bridge partagé.

## Non-objectifs (hors scope initial)

- Pas de trading en argent réel dans la version SaaS (démo only, pour
  protéger users et soi de responsabilité légale/financière)
- Pas de marketplace de stratégies / copy-trading
- Pas d'app mobile dédiée (PWA suffit)
- Pas de support 24/7 (self-service + email best-effort)
- Pas de SLA dur

## Tiers & pricing

| Tier | Prix | Features |
|---|---|---|
| **Free** | 0€ | Dashboard lecture, analytics 7j, 1 pair surveillée, pas d'alertes |
| **Pro** | 19€/mois | Dashboard complet, analytics illimité, 5 pairs, alertes Telegram, rejections log |
| **Premium** | 39€/mois | Tout Pro + backtest illimité sur historique + multi-broker + priorité support |

**Trial** : 14 jours Pro gratuit à l'inscription, sans carte demandée.

## Architecture SaaS

### Schéma data

```
users
  id INTEGER PK AUTOINCREMENT
  email TEXT UNIQUE NOT NULL
  password_hash TEXT NOT NULL     -- bcrypt ou argon2
  tier TEXT NOT NULL DEFAULT 'free'  -- 'free' | 'pro' | 'premium'
  stripe_customer_id TEXT
  stripe_subscription_id TEXT
  trial_ends_at TEXT
  created_at TEXT NOT NULL
  last_login_at TEXT
  broker_config TEXT              -- JSON : bridge_url, bridge_api_key, broker_name
  watched_pairs TEXT              -- JSON list, limité par tier
  settings TEXT                   -- JSON prefs (thème, timezone, notifs)
  is_active INTEGER DEFAULT 1

-- Tables existantes reçoivent user_id FK :
personal_trades.user_id → users.id
signals.user_id → users.id
signal_rejections.user_id → users.id
-- (la colonne `user` TEXT existante sert de fallback migration)
```

### Auth flow

- Session cookie signé (déjà en place via FastAPI + signing)
- Signup : POST /api/auth/signup → crée user + session + redirect onboarding
- Login : POST /api/auth/login → vérif bcrypt + session
- Logout : déjà en place
- Password reset : email magic link (à faire en chantier 4)

### Isolation des données

**Règle absolue** : chaque requête backend scope toutes les queries sur
`user_id = current_user_id`. Jamais d'accès cross-user sauf admin dashboard
(non-inclus dans le MVP).

Middleware `require_auth` injecte `user_id` dans chaque endpoint via
`request.state.user_id`. Tous les services acceptent un `user_id` param
obligatoire au lieu de lire globalement.

### Bridge MT5 : architecture multi-tenant

**Problème** : un seul bridge = tous les users partagent le même compte broker. Inacceptable.

**Options** :
1. **Chaque user héberge son propre bridge** sur son PC/VPS. L'app ne fait
   que collecter les signaux et push via leur bridge URL. Le plus propre
   légalement (nous ne manipulons jamais leur broker account).
2. **Bridge partagé démo** : on héberge un bridge Pepperstone démo unique
   pour tous les users. Simule les trades, tracking virtuel sans vrai
   exécution. Moins cher, moins légaliste, moins d'engagement user.

**Choix V1** : option 1 (user héberge son bridge). Évite les risques
juridiques (nous n'avons jamais de clés API broker d'utilisateurs). Onboarding
wizard = guide pour installer le bridge sur leur PC Windows.

## Chantiers découpés

### Chantier 1 — Users table + migration (MAINTENANT)

**Ce commit** :
- Ajouter table `users` au schéma
- Script migration : seed depuis AUTH_USERS env + mapper `user` TEXT
  existant vers `users.id`
- Helpers : `get_user_by_email`, `get_user_by_id`, `hash_password`,
  `verify_password` (bcrypt)
- Endpoint POST /api/auth/signup (inactif, pour test)
- **Ne change RIEN au comportement live** (env AUTH_USERS toujours lu en
  fallback)

Effort : 4-6h dev.

### Chantier 2 — Auth self-service + login page

- Route frontend /v2/signup (React)
- Flow complet : email/password, validation, session, redirect onboarding
- Renommer login pour supporter les users signup (pas juste env)

Effort : 4-6h dev.

### Chantier 3 — Data isolation complète

- Refactor tous services (insights_service, trade_log_service, etc.) pour
  accepter `user_id` param
- Middleware `require_auth` qui injecte `user_id` dans `request.state`
- Frontend : toutes queries react-query sont scopées via cookie session

Effort : 8-12h dev (gros refactor).

### Chantier 4 — Onboarding wizard broker

- Page `/v2/onboarding` multi-étapes
- Étape 1 : instructions installer bridge MT5 (download + config)
- Étape 2 : tester connexion bridge (saisir URL Tailscale + API key → /health)
- Étape 3 : choisir watched_pairs (limité par tier)
- Étape 4 : done, redirect dashboard

Effort : 4-8h dev.

### Chantier 5 — Stripe integration

- Plans Stripe : Pro 19€ + Premium 39€ (via Stripe Dashboard)
- Webhook endpoint POST /api/stripe/webhook (events : subscription.created,
  subscription.updated, invoice.paid, subscription.deleted)
- Frontend : bouton "Upgrade to Pro" → Stripe Checkout → redirect success
- Update `users.tier` sur webhook
- Middleware de tier : `require_tier('pro')` pour features gated

Effort : 6-10h dev.

### Chantier 6 — Feature gating + landing page publique

- Bloquer features UI selon tier (alertes Telegram = Pro+, backtest = Premium)
- Badges "Pro" visibles mais clickables avec "upgrade" CTA
- Landing page publique `/` pour visiteurs non-auth (pitch + demo + pricing)

Effort : 4-6h dev.

### Chantier 7 — Affiliate brokers

- Table `user_referrals` : user_id → broker → referral_link
- Dashboard : "Earn credits by referring friends" + lien affilié
- Tracking des conversions via webhook broker (si dispo)

Effort : 3-5h dev.

### Chantier 8 — Docs + vidéo démo + landing

- Docs utilisateur (comment installer bridge, FAQ, troubleshooting)
- Vidéo démo 3 min (Loom ou similaire)
- Landing page : hero + features + pricing + testimonials (après beta)
- Blog post de lancement sur LinkedIn + Reddit

Effort : 4-6h + effort marketing continu.

**Total dev estimé** : **40-60h réparties sur 2-3 mois** à 6-8h/semaine.

## Risques identifiés

| Risque | Proba | Impact | Mitigation |
|---|---|---|---|
| Taux d'adoption faible | Haute | Bloque revenus | MVP rapide, feedback early users, itérer |
| Users ne veulent pas héberger bridge | Moyenne | Réduit conversion | Tutoriel vidéo ultra-clair, support premium |
| Problèmes légaux/réglementaires | Moyenne | Bloquant | Pas de real-money, TOS claire, pas de conseil financier |
| Concurrence (TradingView, etc.) | Basse | Dilue valeur | Niche MT5 retail, pas premium massif |
| Support timesink | Moyenne | Bouffe temps | Self-service docs, FAQ, Discord community |

## État légal / fiscal

- **Statut auto-entrepreneur BNC** : recommandé. Plafond 77 700€ en
  prestations de services. URSSAF ~22% cotisations.
- **TVA** : sous franchise en base jusqu'à 37 500€ CA (pas de TVA à facturer
  jusque-là, simple).
- **CGU + CGV + privacy** : nécessaires avant toute facturation. Template
  open-source ou payer un avocat 200-500€ pour package.
- **Non-conflit avec ESN employeur** : vérifier clause non-concurrence.
  ESN standard n'a pas d'activité trading/retail, donc généralement OK,
  mais **information préalable à l'employeur** recommandée.

## Métriques de succès

| Métrique | 3 mois | 6 mois | 12 mois |
|---|---|---|---|
| Users signups | 20 | 100 | 300 |
| Free-to-paid conversion | 10% | 15% | 20% |
| MRR | 50€ | 400€ | 1500€ |
| Churn mensuel | <15% | <10% | <8% |

## Critères go/no-go après 3 mois

- Si **< 30 signups** malgré marketing → problème de product-market fit.
  Reconsidérer positionnement.
- Si **< 3% conversion free→paid** → pricing ou valeur mal perçue.
  Itérer pricing + features.
- Si **churn > 30%/mois** → produit pas collant. Réviser onboarding et
  valeur perçue.
- Si **MRR < 100€ à 3 mois** → réévaluer. Soit pivot, soit shutdown.

## Stack additionnel requis

- **bcrypt** (hashing password) : `pip install bcrypt` (~0.5 MB)
- **python-jose[cryptography]** (JWT si on passe au token ; session cookie
  suffit pour V1)
- **stripe** Python SDK : `pip install stripe` (~1 MB)
- Aucun autre service externe requis (email via SMTP basique ou Resend free
  tier)

## Timeline optimiste (8h/semaine)

| Mois | Focus |
|---|---|
| Mois 1 | Chantiers 1-3 (users, auth, isolation) |
| Mois 2 | Chantiers 4-5 (onboarding, Stripe) |
| Mois 3 | Chantier 6 (gating, landing) + beta fermée 5 users |
| Mois 4 | Chantier 7-8 (affiliate, marketing), launch public |
| Mois 5-6 | Itération sur feedback + marketing push |
| Mois 7-12 | Scale, content, stabilisation |
