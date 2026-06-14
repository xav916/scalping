# Procédure d'activation multi-tenant — VPS Cédric (eu-west-3)

Guide step-by-step pour transformer le VPS Cédric actuel (1 client : Cédric)
en VPS multi-tenant capable d'héberger plusieurs clients Premium.

À exécuter **dans l'ordre**. Compte ~45 min total, dont ~10 min de pause sur Cédric.

⚠️ **Choisir le bon créneau** : weekend (marchés forex fermés) ou nuit. Cédric va arrêter
de trader pendant ~10 min lors de la migration de son MT5.

---

## 📋 Pré-requis (avant de commencer)

- [ ] Tes credentials RDP du VPS Cédric (`51.44.111.156`, user `Administrator`)
- [ ] Lightsail console ouverte sur l'instance `cedric-mt5-bridge` (pour snapshot avant migration)
- [ ] Confirmer que Cédric n'a aucun trade ouvert (vérifier via MT5 ou via Telegram)
- [ ] L'EA Cédric à proximité (api_key `Q9jP304MgQWCvrtEoGDyCDOpe3Fxi3IN`)

---

## 🛡️ Étape 0 — Snapshot de sécurité (5 min)

Avant TOUTE modification, snapshot l'instance pour pouvoir rollback.

1. AWS Lightsail console → instance `cedric-mt5-bridge` → onglet **Snapshots**
2. Bouton **Create snapshot** → nom : `cedric-vps-pre-multitenant-2026-06-14`
3. Attendre la fin (~5-10 min en arrière-plan)
4. Quand "Status: Available" → tu peux continuer en parallèle des étapes suivantes

---

## 🗂️ Étape 1 — Préparer la structure de dossiers (~5 min)

RDP au VPS Cédric. Ouvrir PowerShell Admin.

```powershell
# Crée la structure
New-Item -ItemType Directory -Path "C:\Scalping\clients" -Force
New-Item -ItemType Directory -Path "C:\Scalping\shared" -Force
New-Item -ItemType Directory -Path "C:\Scalping\shared\MT5-Template" -Force

# Vérifie
Get-ChildItem C:\Scalping\
```

---

## 📥 Étape 2 — Télécharger les 3 scripts admin (~2 min)

Depuis PowerShell :

```powershell
cd C:\Scalping
$base = "https://raw.githubusercontent.com/xav916/scalping/main/mt5-bridge/multi-tenant"
Invoke-WebRequest -Uri "$base/launcher.ps1" -OutFile "launcher.ps1"
Invoke-WebRequest -Uri "$base/monitor.ps1" -OutFile "monitor.ps1"
Invoke-WebRequest -Uri "$base/add-client.ps1" -OutFile "add-client.ps1"

# Vérifie
ls *.ps1
```

---

## 📋 Étape 3 — Préparer le template MT5 (~10 min)

Le template est une install MT5 propre qui servira de point de départ pour chaque
nouveau client. Pour Pepperstone (le cas par défaut), on télécharge l'installer
Pepperstone UK depuis leur site.

1. Sur le VPS, ouvre un browser et télécharge :
   `https://download.mql5.com/cdn/web/pepperstone.uk.limited/mt5/pepperstone5setup.exe`
2. Lance l'installer
3. **Important** : pendant l'install, change le dossier cible vers :
   `C:\Scalping\shared\MT5-Template\`
4. Finalise l'install MAIS **ne lance pas MT5 à la fin** (décoche la case)
5. **Ne login PAS dans ce template** — il doit rester "vierge", chaque client login dans son propre dossier copié

---

## 🔄 Étape 4 — Migrer Cédric vers la nouvelle structure (~10 min, **downtime ici**)

Cédric est actuellement dans le dossier MT5 par défaut. Il faut le déplacer
dans `C:\Scalping\clients\cedric\MT5\`.

### 4.1 — Arrêter MT5 + EA de Cédric

```powershell
# Stop tous les processus MT5
Get-Process terminal64 -ErrorAction SilentlyContinue | Stop-Process -Force
# Confirme qu'il n'y a plus rien
Get-Process terminal64 -ErrorAction SilentlyContinue
# Devrait être vide
```

### 4.2 — Identifier le dossier MT5 actuel de Cédric

```powershell
# Le dossier ressemble à C:\Program Files\Pepperstone MetaTrader 5\
# Ou %APPDATA%\MetaQuotes\Terminal\<hex>\
ls "$env:APPDATA\MetaQuotes\Terminal" | Where-Object { $_.PSIsContainer -and $_.Name -match '^[A-F0-9]{32}$' }
```

Note le nom du dossier hex (par exemple `D0E8209F77C8CF37AD8BF550E51FF075`).

### 4.3 — Copier l'installation MT5 Cédric vers son nouveau emplacement

```powershell
# Crée le dossier cible Cédric
New-Item -ItemType Directory -Path "C:\Scalping\clients\cedric" -Force

# Copie le binaire MT5 + tous les fichiers de config
$mt5InstallPath = "C:\Program Files\Pepperstone MetaTrader 5"  # adapter si différent
Copy-Item -Path "$mt5InstallPath\*" -Destination "C:\Scalping\clients\cedric\MT5" -Recurse -Force

# Copie aussi le dossier de données du terminal (hex) qui contient l'EA + configs
$hexDir = "<METTRE LE NOM HEX ICI>"  # ex: D0E8209F77C8CF37AD8BF550E51FF075
Copy-Item -Path "$env:APPDATA\MetaQuotes\Terminal\$hexDir\*" `
          -Destination "C:\Scalping\clients\cedric\MT5" -Recurse -Force
```

### 4.4 — Créer start.bat pour Cédric

```powershell
$startBat = @"
@echo off
cd /d "C:\Scalping\clients\cedric\MT5"
start "" terminal64.exe /portable
"@
Set-Content -Path "C:\Scalping\clients\cedric\start.bat" -Value $startBat
```

### 4.5 — Fichiers info Cédric

```powershell
Set-Content -Path "C:\Scalping\clients\cedric\api_key.txt" -Value "Q9jP304MgQWCvrtEoGDyCDOpe3Fxi3IN"
Set-Content -Path "C:\Scalping\clients\cedric\broker.txt" -Value "62123089@PepperstoneUK-Demo"
Set-Content -Path "C:\Scalping\clients\cedric\onboarded_at.txt" -Value "2026-05-09 (migration vers multi-tenant 2026-06-14)"
```

### 4.6 — Lance Cédric depuis sa nouvelle structure

```powershell
& "C:\Scalping\clients\cedric\start.bat"
Start-Sleep -Seconds 30
# Vérifie que terminal64 tourne
Get-Process terminal64
```

Si MT5 s'ouvre et reprend les positions/charts comme avant → migration OK.
Si ça râle (compte déconnecté, EA pas attaché) → ouvre manuellement le terminal64,
re-login compte 62123089, re-attache l'EA sur un chart avec l'api_key.

### 4.7 — Vérifier le heartbeat backend EC2

```powershell
# Depuis ton PC perso (pas le VPS)
ssh ec2-user@100.103.107.75 "sudo sqlite3 /opt/scalping/data/trades.db 'SELECT json_extract(broker_config, \"$.last_ea_heartbeat\") FROM users WHERE id=2;'"
```

Le timestamp doit être < 2 min. Si OK → Cédric est en place sur la nouvelle structure ✓

### 4.8 — Cleanup ancien dossier MT5 Cédric (optionnel, sécuritaire de garder 1 semaine)

À faire après 1 semaine de stabilité, pas tout de suite.

---

## ⚙️ Étape 5 — Configurer le launcher au démarrage (~5 min)

```powershell
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -File C:\Scalping\launcher.ps1"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User Administrator
$principal = New-ScheduledTaskPrincipal -UserId "Administrator" -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName "ScalpingClientsLauncher" `
    -Action $action -Trigger $trigger -Principal $principal -Force

# Vérifie
Get-ScheduledTask -TaskName "ScalpingClientsLauncher"
```

---

## 📡 Étape 6 — Configurer le monitor toutes les 10 min (~3 min)

```powershell
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -File C:\Scalping\monitor.ps1"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 10) `
    -RepetitionDuration (New-TimeSpan -Days 365)
$principal = New-ScheduledTaskPrincipal -UserId "Administrator" -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName "ScalpingClientsMonitor" `
    -Action $action -Trigger $trigger -Principal $principal -Force

# Test immédiat (devrait pas envoyer d'alerte car tout va bien)
& "C:\Scalping\monitor.ps1"
Get-Content C:\Scalping\monitor.log -Tail 5
```

---

## 🔄 Étape 7 — Test reboot complet (~10 min)

Le test ultime : redémarrer le VPS et vérifier que tout se relance auto.

```powershell
Restart-Computer -Force
```

Attendre 2 min. Re-RDP au VPS.

```powershell
# MT5 Cédric devrait être lancé
Get-Process terminal64
# Le launcher.log doit montrer "OK lancé client : cedric"
Get-Content C:\Scalping\launcher.log -Tail 5
# Heartbeat backend EC2 doit reprendre dans les 2 min suivantes
```

Vérifie aussi depuis ton PC :
```powershell
ssh ec2-user@100.103.107.75 "sudo sqlite3 /opt/scalping/data/trades.db 'SELECT json_extract(broker_config, \"$.last_ea_heartbeat\") FROM users WHERE id=2;'"
```

Timestamp < 2 min après le reboot → 🎉 multi-tenant opérationnel.

---

## ➕ Étape 8 — Onboarder le 1er nouveau client (à faire quand un Premium s'inscrit)

```powershell
cd C:\Scalping
.\add-client.ps1 -ClientName "jeanmarc" `
                 -ApiKey "abcDEF123ghi456..." `
                 -BrokerLogin "62124567" `
                 -BrokerServer "PepperstoneUK-Demo"
```

Le script crée la structure. **Étapes manuelles ensuite** :
1. `& "C:\Scalping\clients\jeanmarc\start.bat"` (lance MT5 portable du nouveau)
2. Dans MT5 : File → Login to Trade Account → saisir login + password broker + serveur
3. Tools → Options → Expert Advisors → Allow WebRequest → ajouter `https://app.scalping-radar.online`
4. Drag ScalpingRadarEA sur un chart, saisir InpApiKey, Allow Algo Trading, OK
5. Vérifier smiley vert + premier poll dans les logs Experts

---

## 🚨 Rollback en cas de problème

**Si la migration Cédric ne marche pas** :

1. Stop tous les MT5 :
   ```powershell
   Get-Process terminal64 | Stop-Process -Force
   ```

2. Restaurer le snapshot Lightsail (étape 0) :
   - Lightsail console → Snapshots → snapshot pre-multitenant
   - Bouton "Create new instance from snapshot"
   - Réattacher la static IP `51.44.111.156` à la nouvelle instance
   - Supprimer l'instance multi-tenant qui a échoué

3. Cédric revient à son état pré-migration en ~15 min.

---

## 📊 Capacité par bundle après migration

| Bundle actuel | RAM | Clients confort. | Coût/mois |
|---|---|---|---|
| **Small (actuel)** | 2 GB | 2-3 (Cédric + 1-2 nouveaux) | 22 USD |
| Medium (upgrade quand 3e arrive) | 4 GB | 5-6 | 40 USD |
| Large (au-delà de 6 clients) | 8 GB | 10-12 | 70 USD |

---

## 🛠️ Maintenance courante

| Quand | Action |
|---|---|
| Toutes les 10 min | `monitor.ps1` auto, alertes Telegram si RAM/disque/MT5 down |
| Tous les lundis 9h | Recap hebdo automatique sur Telegram (état OK + capacité restante) |
| Quand alerte RAM > 80% | Décider : refuser le prochain client OU upgrader bundle |
| Quand alerte disque > 90% | Nettoyer logs vieux clients + corbeille |
| Quand alerte robot tombé | RDP + relancer le `start.bat` du client concerné |

---

## ✅ Checklist finale après activation

- [ ] Snapshot Lightsail créé (étape 0)
- [ ] Structure dossiers en place (étape 1)
- [ ] 3 scripts téléchargés (étape 2)
- [ ] Template MT5 dans `C:\Scalping\shared\MT5-Template\` (étape 3)
- [ ] Cédric migré dans `C:\Scalping\clients\cedric\` + start.bat OK (étape 4)
- [ ] Heartbeat Cédric < 2 min depuis migration (étape 4.7)
- [ ] Launcher tâche planifiée active (étape 5)
- [ ] Monitor tâche planifiée active (étape 6)
- [ ] Reboot test passé (étape 7)
- [ ] Prêt pour ajout 1er nouveau client (étape 8)

Quand tous les ✅ → tu peux ouvrir le signup au prochain Premium en toute confiance.
