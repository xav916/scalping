# Onboarding Cédric — bridge MT5 auto-exec Premium

> **Driver** : premier user Premium SaaS (c.chaussis@icloud.com, id=17, Mac
> niveau 0 tech). Multi-tenant bridge routing déjà déployé en prod (Phases A-D).
> Reste à monter SON bridge MT5 sur SON VPS Windows pour que ses ordres
> tombent sur SON compte Pepperstone démo.
>
> **Estimation** : 1-2 h en pair-RDP avec Cédric. Le guide ci-dessous est
> linéaire — on suit les étapes dans l'ordre, pas de saut.

## Pré-requis côté admin (toi)

Avant la session live :

- [ ] **Code bridge versionné** — actuellement `C:\Scalping\mt5-bridge\bridge.py`
  vit en local. Soit on le commit dans `mt5-bridge/` du repo (préféré, ~15 min),
  soit on le zippe et on l'envoie à Cédric par SMTP/Resend (one-shot).
- [ ] **API key dédiée Cédric** — générer une clé ≥ 16 chars, différente de
  la tienne et de celle du VPS admin. Stocker côté toi pour debug, mais
  Cédric la met juste dans son `.env` bridge sans jamais la sortir.
- [ ] **Cédric a un compte Pepperstone démo** créé sur
  https://pepperstone.com/fr/forms/demo-account/ (UK Limited si possible
  pour cohérence avec ton setup). Login + password + numéro de compte (ex:
  `62XXXXX`) à portée de main.
- [ ] **Cédric a un compte AWS Lightsail OU tu provisionnes son VPS sur ton
  compte** (~22 €/mois small_win_3_0). Décision business à trancher avant
  la session.

## Étape 1 — Provisionner le VPS Windows (15 min)

### Console Lightsail

1. Console AWS → Lightsail → Create instance
2. Plateforme : **Microsoft Windows**
3. OS-only : **Windows Server 2022**
4. Plan : **small_win_3_0** ($22/mois, 2 GB RAM, 60 GB SSD) — minimum
   viable pour MT5 + bridge.py ; le `micro_win_3_0` ($11/mois, 1 GB) est
   trop juste, MT5 swap-thrash.
5. Région : **eu-north-1** (proche de l'EC2 radar, latence bridge ↔ radar
   minimale ~1ms)
6. Nom d'instance : `cedric-bridge-vps`
7. Create instance.

### Récupérer les creds RDP

```powershell
# Côté admin (toi)
aws lightsail get-instance-access-details `
  --instance-name cedric-bridge-vps `
  --region eu-north-1 `
  --protocol rdp
```

Note l'IP publique + username `Administrator` + password généré. Stocke
dans `C:\Scalping\vps-credentials\cedric-bridge-vps.txt` (chiffré
idéalement, ou rotate après onboarding).

### Firewall

Par défaut Lightsail ouvre RDP (3389) à 0.0.0.0/0. **À restreindre
immédiatement** :

1. Lightsail console → instance → Networking
2. Custom rule TCP 3389 → restrict source : IP de Cédric (qu'il te donne
   via https://whatismyipaddress.com/)
3. Custom rule TCP 8787 → bridge port (à ouvrir UNIQUEMENT si tunnel
   public, sinon Tailscale-only suffit — voir étape 8)

## Étape 2 — RDP first login (10 min, en pair avec Cédric)

1. Cédric installe **Microsoft Remote Desktop** sur son Mac (App Store,
   gratuit).
2. New PC → Host : IP publique du VPS, User : `Administrator`, Password :
   généré.
3. Connect → accepter le warning cert (auto-signed Windows).
4. Première connexion : appliquer les Windows updates **uniquement
   urgents** (pas tout, ça prendrait 1h).
5. Désactiver Internet Explorer Enhanced Security :
   - Server Manager → Local Server → IE Enhanced Security Configuration →
     Off pour Administrators.
6. Désactiver le screensaver auto-lock (sinon les tâches planifiées
   plantent quand le RDP est fermé) :
   - `gpedit.msc` → Computer Config → Admin Templates → Control Panel →
     Personalization → Enable screen saver = Disabled.

## Étape 3 — Auto-logon Windows (5 min)

Le bridge doit redémarrer automatiquement après reboot du VPS — donc
auto-logon obligatoire (sinon les tâches planifiées au logon ne se
lancent pas).

```powershell
# Sur le VPS, en mode Administrator
netplwiz
```

Décocher "Users must enter a username and password to use this computer"
→ Apply → entrer le password Administrator deux fois → OK. Reboot pour
tester. RDP doit reconnecter, et tu verras le desktop sans entrer le
password.

Si `netplwiz` n'a pas la checkbox (Windows Server 2022 récents la
masquent par défaut) :

```powershell
reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" `
  /v AutoAdminLogon /t REG_SZ /d 1 /f
reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" `
  /v DefaultUserName /t REG_SZ /d Administrator /f
reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" `
  /v DefaultPassword /t REG_SZ /d "<password_admin>" /f
```

## Étape 4 — Installer MT5 + login Pepperstone démo (15 min)

1. Sur le VPS, ouvre Edge → télécharge MT5 Pepperstone UK :
   `https://download.mql5.com/cdn/web/pepperstone.uk.limited/mt5/pepperstone5setup.exe`
2. Exécuter l'installer → suivant suivant → Finish.
3. Au lancement de MT5, login avec :
   - **Server** : `PepperstoneUK-Demo`
   - **Login** : numéro compte démo Cédric
   - **Password** : son password démo
4. Tools → Options → Expert Advisors → cocher "Allow algorithmic trading"
   et "Allow DLL imports".
5. Vérifier que la heatmap des prix tourne (Market Watch panel).

## Étape 5 — Install Python 3.11 (5 min)

1. Edge → `https://www.python.org/downloads/windows/` → Python 3.11.x
   (PAS la 3.13 ni 3.12 : on a vu des incompatibilités avec certaines
   libs MT5 sur 3.12+).
2. Cocher **"Add Python to PATH"** au début de l'installer (CRITIQUE).
3. Customize installation → "Install for all users".
4. Vérifier dans PowerShell : `python --version` → `Python 3.11.x`.

## Étape 6 — Déployer le code bridge (15 min)

### Option A — depuis Git (préférée, si versionné)

```powershell
cd C:\
git clone https://github.com/xav916/scalping.git
cd scalping\mt5-bridge
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Option B — depuis zip (one-shot)

1. Côté admin, depuis ton VPS :
   ```powershell
   Compress-Archive C:\Scalping\mt5-bridge\* -DestinationPath C:\Scalping\mt5-bridge-cedric.zip
   ```
2. Transfer le zip à Cédric (Resend SMTP, ou Tailscale Drop si vous êtes
   au tailnet).
3. Sur le VPS Cédric : extract le zip dans `C:\Scalping\mt5-bridge\`,
   ouvre PowerShell, `cd C:\Scalping\mt5-bridge`, puis `python -m venv
   venv && .\venv\Scripts\Activate.ps1 && pip install -r requirements.txt`.

### Configurer le .env bridge

Créer `C:\Scalping\mt5-bridge\.env` :

```
BRIDGE_API_KEY=<clé_dédiée_cedric_min_16_chars>
MT5_LOGIN=<numéro_compte_démo_cédric>
MT5_PASSWORD=<password_démo>
MT5_SERVER=PepperstoneUK-Demo
PAPER_MODE=true
MAX_LOT=0.1
MAX_LOT_PER_CLASS={"forex":0.1,"metal":0.1,"crypto":0.01,"equity_index":0.05,"energy":0.1}
MAX_OPEN_POSITIONS=6
HOST=0.0.0.0
PORT=8787
```

Note : `PAPER_MODE=true` est crucial pour les premiers tests — le bridge
log les ordres sans les exécuter en MT5. À passer `false` quand validé
en pair-RDP.

## Étape 7 — Test bridge local (5 min)

```powershell
cd C:\Scalping\mt5-bridge
.\venv\Scripts\Activate.ps1
python bridge.py
```

Attendre que le bridge dise "Connected to MT5, login=XXX, server=PepperstoneUK-Demo, balance=...". Dans une autre fenêtre PowerShell :

```powershell
Invoke-WebRequest http://localhost:8787/health -Headers @{"X-API-Key"="<clé>"}
```

Doit retourner `{"ok":true,"login":...,"balance":...}`. Si erreur, voir
la console du `python bridge.py` pour le traceback.

## Étape 8 — Exposition réseau (15-30 min, le plus délicat)

Le SaaS scalping (sur EC2 dans le cloud) doit pouvoir atteindre le bridge
de Cédric pour pousser des ordres. Deux options.

### Option A — Tailscale (recommandée, plus simple)

1. Cédric installe Tailscale : https://tailscale.com/download/windows
2. Login avec un compte Google/GitHub (idéalement un compte dédié, pas
   son perso — qu'il puisse partager le node sans donner son perso).
3. Te partage un token de "node sharing" pour que ton tailnet admin puisse
   ping son node :
   - Tailscale console côté Cédric → settings → Share node → invite ton
     email Tailscale.
4. Côté admin : accepter l'invite → le node `cedric-bridge-vps` apparaît
   dans ton tailnet, IP type `100.X.Y.Z`.
5. **URL bridge** : `http://100.X.Y.Z:8787` (cette URL est ce qu'on entrera
   en Settings → Auto-exec MT5).
6. Le bridge écoute déjà sur `0.0.0.0:8787` (étape 6) → joignable depuis
   le tailnet sans config supplémentaire.

### Option B — Tunnel HTTPS public (plus complexe, requiert nom de domaine)

1. Cédric (ou toi) achète un sous-domaine `bridge-cedric.example.com`
   (Porkbun, Namecheap, ~10€/an).
2. Pointe DNS A record sur l'IP publique du VPS Lightsail.
3. Sur le VPS, install **nginx for Windows** + Let's Encrypt (via win-acme).
4. Reverse proxy `https://bridge-cedric.example.com → http://127.0.0.1:8787`
5. **URL bridge** : `https://bridge-cedric.example.com`

Recommandation : **Tailscale**. Le tunnel HTTPS est intéressant pour
production multi-user à terme mais complique le first onboarding.

## Étape 9 — Tâches planifiées au logon (10 min)

Pour que le bridge redémarre automatiquement après reboot du VPS, créer
2 tâches planifiées :

```powershell
# Tâche 1 — démarrer MT5
schtasks /create /tn "CedricMT5" /tr `
  '"C:\Program Files\Pepperstone MetaTrader 5\terminal64.exe"' `
  /sc onlogon /ru Administrator /rl HIGHEST /f

# Tâche 2 — démarrer bridge.py (avec délai +30s pour laisser MT5 boot)
schtasks /create /tn "CedricBridge" /tr `
  'powershell.exe -NoProfile -WindowStyle Hidden -Command "Start-Sleep 30; Set-Location C:\Scalping\mt5-bridge; .\venv\Scripts\python.exe bridge.py"' `
  /sc onlogon /ru Administrator /rl HIGHEST /f
```

Reboot le VPS via Lightsail console pour tester. Après 90s, faire un
`/health` depuis le tailnet → doit répondre 200.

## Étape 10 — Activer auto-exec côté SaaS (5 min)

Cédric va sur https://app.scalping-radar.online/v2/settings :

1. Section **Auto-exec MT5** → déplie.
2. **URL du bridge** : `http://100.X.Y.Z:8787` (ou `https://bridge-cedric...`)
3. **API key** : la clé du `.env` bridge.
4. Bouton **Tester** → doit afficher "Bridge joignable ✓".
5. Bouton **Enregistrer** (disabled tant que test pas OK).
6. Section **Auto-exécution** apparaît avec badge "OFF".
7. **Coche "Je confirme que ce bridge pointe vers un compte démo"**.
8. Bouton **Activer l'auto-exec**.
9. Badge passe à "ON" en vert.

## Étape 11 — Validation end-to-end (variable)

Maintenant Cédric attend qu'un setup éligible se produise sur une de ses
paires watchlist. Quand le scoring radar produit un setup avec `confidence
≥ MT5_BRIDGE_MIN_CONFIDENCE` :

- Côté SaaS : log `MT5 bridge[user:17] → XAU/USD buy ...` dans les logs
  scalping.service
- Côté bridge Cédric : POST /order reçu, MT5 place l'ordre sur son compte
  démo
- Côté Settings → Auto-exec : le toggle reste "ON"
- Côté MT5 Cédric : nouveau trade visible dans History/Positions

## Vérifications post-onboarding (toi, à distance)

```bash
ssh -i C:\Users\xav91\Scalping\scalping\scalping-key.pem ec2-user@51.21.132.216 \
  "sudo grep -E 'user:17' /var/log/scalping/scalping.log | tail -20"
```

Doit montrer les pushes du SaaS vers son bridge. Si erreur (timeout,
401, etc.), debug dans cet ordre :

1. `/api/user/broker/test` côté SaaS répond OK ? (sinon URL/key mauvais)
2. Tailscale ping `100.X.Y.Z` depuis EC2 (sinon node offline ou pas
   shared)
3. `python bridge.py` log côté Cédric (sinon le bridge a planté)
4. `_user_destinations` retourne bien sa config en SaaS ? (vérifier
   `users.broker_config` JSON contient bien `auto_exec_enabled: true`)

## Désactivation rapide en cas de souci

Cédric, depuis son téléphone Settings → Auto-exec → "Désactiver" (pas de
confirmation requise pour désactiver, c'est instantané).

Côté admin (toi) en cas d'urgence :

```bash
# UPDATE direct DB pour couper son auto-exec sans qu'il fasse rien
sudo sqlite3 /opt/scalping/data/trades.db \
  "UPDATE users SET broker_config = json_set(broker_config, '$.auto_exec_enabled', 0) WHERE id=17;"
sudo systemctl restart scalping
```

## Coûts mensuels Cédric (récap)

| Item | Coût |
|---|---|
| VPS Lightsail small_win_3_0 | ~22 €/mois |
| Tailscale (Personal plan) | gratuit (≤ 100 nodes) |
| Pepperstone démo | gratuit |
| Domaine perso (option B uniquement) | ~10 €/an |
| **Total mensuel** | **~22 €/mois** (option A) |

À facturer à Cédric ou à offrir comme test selon accord business.

## Ce qui reste à faire AVANT la session pair-RDP

- [ ] Versionner `bridge.py` dans `mt5-bridge/` du repo scalping (~15 min,
      simplifie l'étape 6)
- [ ] Générer + stocker l'API key dédiée Cédric
- [ ] Vérifier que Cédric a son compte Pepperstone démo créé
- [ ] Décider du mode de paiement VPS (toi vs lui)
- [ ] Bloquer 1h30-2h dans ton agenda et celui de Cédric
