# Setup prod : Stripe + SMTP + flip signup

Guide pas-à-pas pour ouvrir le signup SaaS au public. Cible : 30 min
environ, dont ~20 min côté Stripe KYB.

## 1 — Resend (SMTP, ~5 min)

Resend est un SMTP moderne, free tier 3 000 mails/mois, pas besoin de
domain verification pour commencer.

1. Aller sur https://resend.com/signup
2. S'inscrire avec `pascal.p.couderc@gmail.com`
3. Menu **API Keys** → **Create API Key** → nom `scalping-radar-prod` →
   permission **Sending access** → copier la clé `re_xxx...`
4. (Optionnel, recommandé) Menu **Domains** → **Add Domain** →
   `scalping-radar.duckdns.org` → suivre les instructions DNS TXT/MX.
   Tant que le domain n'est pas vérifié, les mails doivent partir de
   `onboarding@resend.dev` (sandbox Resend, pas ton domain).

**À me donner** :
- `RESEND_API_KEY` (valeur `re_xxx...`)
- `EMAIL_FROM` : soit `onboarding@resend.dev` (immédiat, mais l'user voit
  l'adresse Resend), soit `no-reply@<ton-domain-verifié>` (pro).

## 2 — Stripe (checkout + webhook, ~20 min)

Stripe peut tourner en **mode test** sans KYB au début. Les cartes de
test (`4242 4242 4242 4242`) permettent de tester le flow complet.
Passage en **mode live** (activation du business) se fait plus tard,
après validation end-to-end en test mode.

### 2a. Compte Stripe

1. Aller sur https://dashboard.stripe.com/register
2. S'inscrire, activer email, accepter conditions
3. Le Dashboard s'ouvre en **mode Test** par défaut (toggle en haut à droite)

### 2b. Produits + prix (4 SKUs)

Pour créer les 4 produits manuellement (alternatif au script automatisé
de la section 2d) :

1. Menu **Products** → **+ Add product**
2. **Produit 1 — Scalping Radar Pro**
   - Description : "Dashboard complet, 5 paires, alertes Telegram, analytics illimitées"
   - Prix 1 : Recurring monthly, **19.00 EUR** → Save
   - Prix 2 sur le même produit : Recurring yearly, **190.00 EUR** (2 mois offerts)
3. **Produit 2 — Scalping Radar Premium**
   - Description : "Tout Pro + backtest + multi-broker + auto-exec MT5 bridge"
   - Prix 1 : Recurring monthly, **39.00 EUR**
   - Prix 2 : Recurring yearly, **390.00 EUR**

Copier les **4 Price IDs** qui s'affichent (format `price_1XXX...`) : on
en aura besoin pour `.env` EC2.

### 2c. Secret keys

1. Menu **Developers** → **API keys**
2. **Secret key** (mode test) → révéler → copier `sk_test_xxx...`

### 2d. Webhook endpoint

1. Menu **Developers** → **Webhooks** → **+ Add endpoint**
2. URL : `https://scalping-radar.duckdns.org/api/stripe/webhook`
3. Events à écouter : `checkout.session.completed`,
   `customer.subscription.updated`, `customer.subscription.deleted`,
   `invoice.payment_succeeded`, `invoice.payment_failed`
4. Créer → copier le **Signing secret** (`whsec_xxx...`)

**À me donner** :
- `STRIPE_SECRET_KEY` (`sk_test_xxx...`)
- `STRIPE_WEBHOOK_SECRET` (`whsec_xxx...`)
- `STRIPE_PRICE_PRO_MONTHLY` (`price_xxx...`)
- `STRIPE_PRICE_PRO_YEARLY` (`price_xxx...`)
- `STRIPE_PRICE_PREMIUM_MONTHLY` (`price_xxx...`)
- `STRIPE_PRICE_PREMIUM_YEARLY` (`price_xxx...`)

### 2d bis (alternative) — Auto-création via script

Si tu préfères skip les 8 clicks Stripe Dashboard, je peux créer les 4
produits automatiquement. Il suffit que tu aies la `STRIPE_SECRET_KEY`,
puis je lance :

```bash
./venv/Scripts/python.exe scripts/setup_stripe_products.py --secret-key sk_test_xxx
```

Le script print les 4 Price IDs à copier dans `.env`.

## 3 — Ce que je fais avec tes clés (automatique)

Une fois que tu me files :
- `RESEND_API_KEY`
- `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, 4 × `STRIPE_PRICE_*`

Je fais :
1. Backup `.env` EC2 timestamped
2. Upsert les 8 variables dans `/opt/scalping/.env` EC2
3. Ajoute `EMAIL_SMTP_HOST=smtp.resend.com`, `EMAIL_SMTP_PORT=465`,
   `EMAIL_SMTP_USER=resend`, `EMAIL_SMTP_PASSWORD=$RESEND_API_KEY`
4. Ajoute `STRIPE_ENABLED=true`
5. `sudo systemctl restart scalping`
6. Smoke tests :
   - `/api/config` signup_enabled toujours false (flip manuel en dernier)
   - Signup via whitelist alias → email welcome arrive
   - Checkout Stripe test → URL checkout valide → carte 4242... → webhook reçu
7. Si tout est vert, flip `SAAS_SIGNUP_ENABLED=true` → signup public ouvert

## 4 — Mode live (plus tard, quand prêt à charger de vrais users)

1. Dashboard Stripe → toggle **Activate account** (KYB : SIREN, IBAN,
   justificatifs)
2. Basculer toggle **Test** → **Live** en haut à droite
3. Récupérer les nouvelles keys `sk_live_xxx...` + nouveau webhook
   secret
4. Me les filer, je patche `.env` EC2, restart, done.

Entre mode test et mode live : zéro différence côté code. Juste des
clés différentes.

## 5 — Monitoring post-launch

- **Resend** : Dashboard → Logs. Chaque mail envoyé/delivered/bounced.
- **Stripe** : Dashboard → Payments + Subscriptions. Revenue tracker en
  live.
- **Backoffice Scalping** : https://scalping-radar.duckdns.org/v2/admin
  → MRR estimé, signups 7j/30j, trials actifs, users par tier.

## 6 — Si tu veux revenir en arrière

- `SAAS_SIGNUP_ENABLED=false` dans `/opt/scalping/.env` → signup public
  refermé, rien d'autre ne change (les users Pro/Premium continuent de
  fonctionner normalement)
- `STRIPE_ENABLED=false` → plus aucun nouveau checkout possible, les
  users existants gardent leur abonnement Stripe tant qu'ils ne
  l'annulent pas
- Backups `.env` dans `/opt/scalping/.env.backup.YYYYMMDD_HHMMSS`
