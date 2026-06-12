# Runbook IC Markets EU Live (parallèle Demo Pepperstone) — 2026-06-12

**À exécuter** dès réception des credentials MT5 IC Markets de Xavier.
**Architecture cible** : Demo Pepperstone (port 8787) + Live IC Markets (port 8788) en parallèle sur le même VPS Stockholm.

## Pré-requis

- Credentials MT5 IC Markets EU Live Razor :
  - `MT5_LOGIN` : numéro de compte (ex. 51234567)
  - `MT5_PASSWORD` : master password
  - `MT5_SERVER` : ex. `ICMarketsEU-Live01` (à confirmer depuis l'email IC Markets)
- IC Markets MT5 installer téléchargé sur le VPS (https://www.icmarkets.eu/download-platforms/mt5)
- Confirmation "go switch" du user

## Étape 1 — VPS Stockholm : installer IC Markets MT5 dans dossier séparé (~15 min)

RDP au VPS `13.49.70.233` (Administrator).

### 1a — Télécharger IC Markets MT5 installer

```powershell
Invoke-WebRequest -Uri "https://download.mql5.com/cdn/web/icmarkets.eu/mt5/icmarketseu5setup.exe" -OutFile "C:\Users\Administrator\Downloads\icmarketseu5setup.exe" -UseBasicParsing
```

(URL exact à valider sur la page download IC Markets ; ajuster si nécessaire)

### 1b — Installer dans folder dédié

```powershell
Start-Process -FilePath "C:\Users\Administrator\Downloads\icmarketseu5setup.exe" -ArgumentList "/auto /S /DIR=`"C:\Program Files\IC Markets MT5`"" -Wait
```

Vérif :
```powershell
Test-Path "C:\Program Files\IC Markets MT5\terminal64.exe"
```

(Doit retourner `True`)

### 1c — Premier lancement MT5 IC Markets (manuel)

Sur la session RDP, double-clique sur `terminal64.exe` dans `C:\Program Files\IC Markets MT5\`. Login :
- Login : `<login_ic>`
- Password : `<password_ic>`
- Server : `ICMarketsEU-Live01` (ou ce qui est dans email)
- ✅ Save account information

Vérifie : balance 100€ affichée, ms en bas à droite, AutoTrading button **VERT**, Tools → Options → Expert Advisors → "Allow algorithmic trading" coché.

## Étape 2 — VPS : copier bridge.py dans folder Live (~5 min)

```powershell
Copy-Item -Path "C:\Scalping\mt5-bridge" -Destination "C:\Scalping\mt5-bridge-live" -Recurse -Force
```

Crée le venv Live dédié :
```powershell
cd C:\Scalping\mt5-bridge-live
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

## Étape 3 — Configurer .env Live (~5 min)

```powershell
$envLive = @"
# IC Markets EU Live config
MT5_LOGIN=<LOGIN_IC>
MT5_PASSWORD=<PASSWORD_IC>
MT5_SERVER=ICMarketsEU-Live01
MT5_SYMBOL_MAP=WTI/USD:USOIL,SPX:SP500,NDX:NAS100

# Bridge server
BRIDGE_HOST=0.0.0.0
BRIDGE_PORT=8788
BRIDGE_API_KEY=<GENERATED_32_CHARS>

# Trading safety
PAPER_MODE=false
MAX_LOT=0.02
MAX_LOT_PER_CLASS=forex:0.02,metal:0.02,energy:0.02,crypto:0.01,equity_index:0.02
MAX_OPEN_POSITIONS=2
MAX_DAILY_LOSS_PCT=3.0
DEDUP_WINDOW_SEC=300
"@

Set-Content -Path "C:\Scalping\mt5-bridge-live\.env" -Value $envLive -Encoding ASCII
```

⚠️ Remplacer `<LOGIN_IC>`, `<PASSWORD_IC>`, `<GENERATED_32_CHARS>` avant exécution.

Generate BRIDGE_API_KEY :
```powershell
-join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | ForEach-Object {[char]$_})
```

Symbol map à valider après 1er run : ouvrir MT5 IC Markets, vérifier les vrais noms broker pour WTI / SPX / NDX (IC Markets EU peut différer de Pepperstone : USOIL vs WTI, SP500 vs SPX500).

## Étape 4 — Créer tasks ScalpingMT5_Live et ScalpingBridge_Live (~5 min)

### Task ScalpingMT5_Live (lance le terminal IC Markets)

```powershell
$action = New-ScheduledTaskAction -Execute "C:\Program Files\IC Markets MT5\terminal64.exe" -Argument "/login:<LOGIN_IC> /password:<PASSWORD_IC> /server:ICMarketsEU-Live01"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "Administrator"
$principal = New-ScheduledTaskPrincipal -UserId "Administrator" -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName "ScalpingMT5_Live" -Action $action -Trigger $trigger -Principal $principal -Force
```

### Task ScalpingBridge_Live (lance bridge.py Live)

```powershell
$action = New-ScheduledTaskAction -Execute "C:\Scalping\mt5-bridge-live\venv\Scripts\pythonw.exe" -Argument "C:\Scalping\mt5-bridge-live\bridge.py" -WorkingDirectory "C:\Scalping\mt5-bridge-live"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "Administrator"
$principal = New-ScheduledTaskPrincipal -UserId "Administrator" -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName "ScalpingBridge_Live" -Action $action -Trigger $trigger -Principal $principal -Force
```

Tester :
```powershell
Start-ScheduledTask -TaskName ScalpingMT5_Live
Start-Sleep -Seconds 25
Start-ScheduledTask -TaskName ScalpingBridge_Live
Start-Sleep -Seconds 12
Invoke-WebRequest -Uri "http://localhost:8788/health" -UseBasicParsing | Select-Object -ExpandProperty Content
```

Attendu : JSON `{login:<LOGIN_IC>, server:"ICMarketsEU-Live01", paper_mode:false, ok:true}`.

## Étape 5 — Lightsail firewall : ouvrir port 8788 (~2 min)

Depuis Claude (local Windows, AWS CLI) :

```bash
aws lightsail open-instance-public-ports \
  --region eu-north-1 \
  --instance-name scalping-bridge-vps \
  --port-info "fromPort=8788,toPort=8788,protocol=tcp,cidrs=51.21.132.216/32" \
  --no-verify-ssl
```

(EC2 prod IP = `51.21.132.216`. Ne pas ouvrir 0.0.0.0/0 — restreindre au seul EC2.)

Vérif :
```bash
aws lightsail get-instance-port-states --region eu-north-1 --instance-name scalping-bridge-vps --no-verify-ssl
```

## Étape 6 — EC2 .env : activer admin_live (~3 min)

```bash
ssh -i C:/Users/xav91/Scalping/scalping/scalping-key.pem ec2-user@100.103.107.75 'sudo bash -s <<"BASH"
ENV=/opt/scalping/.env
sudo cp $ENV ${ENV}.bak-$(date -u +%Y%m%d-%H%M%S)-pre-ic-live

upsert() {
  local key=$1 val=$2
  if grep -q "^${key}=" "$ENV"; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$ENV"
  else
    echo "${key}=${val}" >> "$ENV"
  fi
}

upsert MT5_BRIDGE_LIVE_ENABLED true
upsert MT5_BRIDGE_LIVE_URL "http://100.74.160.72:8788"
upsert MT5_BRIDGE_LIVE_API_KEY "<GENERATED_32_CHARS>"
upsert MT5_BRIDGE_LIVE_MIN_CONFIDENCE 75
upsert MT5_BRIDGE_LIVE_ALLOWED_ASSET_CLASSES "forex,metal,energy,crypto"

grep -E "^MT5_BRIDGE_LIVE_" $ENV
BASH'
```

## Étape 7 — Restart container EC2 + verify (~5 min)

```bash
ssh -i C:/Users/xav91/Scalping/scalping/scalping-key.pem ec2-user@100.103.107.75 \
  "sudo systemctl restart scalping && sleep 8 && sudo systemctl is-active scalping"
```

Verify both destinations active :
```bash
ssh -i C:/Users/xav91/Scalping/scalping/scalping-key.pem ec2-user@100.103.107.75 'sudo docker exec scalping-radar python3 -c "
import sys; sys.path.insert(0, \"/app\")
from backend.services import bridge_destinations
admin_demo = bridge_destinations._admin_legacy_destination()
admin_live = bridge_destinations._admin_live_destination()
print(\"admin_legacy (Demo) :\", admin_demo.bridge_url if admin_demo else None)
print(\"admin_live (Live)   :\", admin_live.bridge_url if admin_live else None)
"'
```

Attendu : `admin_demo` pointe sur Pepperstone bridge port 8787, `admin_live` pointe sur IC Markets bridge port 8788.

## Étape 8 — Monitoring 1ères 24h

À surveiller :
1. **`mt5_pushes` table** : chaque setup doit avoir 2 lignes (1 par destination)
2. **Logs bridge.log Live** : `C:\Scalping\mt5-bridge-live\bridge.log` doit montrer des OrderSend success
3. **Comparaison Demo vs Live** : pour chaque trade, comparer fill price + PnL final
4. **Tracker live_test_100eur.md** : à compléter manuellement par trade

Endpoints pour vérification rapide :
- Demo bridge health : `http://100.74.160.72:8787/health`
- Live bridge health : `http://100.74.160.72:8788/health`
- Positions Live : `http://100.74.160.72:8788/positions`

## Rollback (si problème Live)

Désactiver Live sans toucher au Demo :
```bash
ssh ec2-user@100.103.107.75 \
  "sudo sed -i 's/^MT5_BRIDGE_LIVE_ENABLED=.*/MT5_BRIDGE_LIVE_ENABLED=false/' /opt/scalping/.env && sudo systemctl restart scalping"
```

Tâche Live VPS :
```powershell
Stop-ScheduledTask -TaskName ScalpingBridge_Live
Stop-ScheduledTask -TaskName ScalpingMT5_Live
```

Demo Pepperstone continue tranquillement.

## Timeline cible

| Étape | Durée | Cumul |
|---|---|---|
| Install IC Markets MT5 VPS | 15 min | 15 min |
| Copy bridge.py + venv | 5 min | 20 min |
| Config .env Live | 5 min | 25 min |
| Create tasks Live | 5 min | 30 min |
| Lightsail firewall port 8788 | 2 min | 32 min |
| EC2 .env + restart | 8 min | 40 min |
| Verify bout en bout | 5 min | 45 min |

**Total** : ~45 min côté Claude une fois les credentials IC Markets reçus.

## Risques opérationnels

| Risque | Probabilité | Mitigation |
|---|---|---|
| Symbol map IC Markets diffère de Pepperstone | Haute | Vérifier après 1er run, ajuster MT5_SYMBOL_MAP côté Live bridge |
| Port 8788 bloqué par antivirus VPS | Faible | Disable Windows Defender pour bridge.py (déjà fait sur Demo bridge) |
| 2 MT5 terminals saturent RAM 2GB VPS | Moyenne | Monitorer Get-Process Memory ; si saturation, fermer MT5 GUI Demo (garder bridge.py seul) |
| IC Markets EU Razor lot min différent de 0.01 | Moyenne | Vérifier lot min XAU dans MT5 Specifications → ajuster MT5_BRIDGE_LIVE_LOTS |
| Daily cap 3€ touché en quelques heures | Haute | Comportement attendu — kill_switch s'active, à observer |
