# Multi-tenant MT5 sur VPS Windows

Outils pour héberger plusieurs MT5 clients sur un même VPS Windows en mode portable.

## Structure cible sur le VPS

```
C:\Scalping\
├── shared\
│   └── MT5-Template\          ← Template MT5 portable (1 install à copier)
├── clients\
│   ├── cedric\
│   │   ├── MT5\               ← Instance MT5 portable de Cédric
│   │   ├── api_key.txt        ← API key SaaS de Cédric
│   │   ├── broker.txt         ← login@serveur broker
│   │   └── start.bat          ← Lance MT5 portable de Cédric
│   ├── client-2-prenomNom\
│   └── ...
├── launcher.ps1               ← Lance toutes les instances au boot
├── add-client.ps1             ← Onboard un nouveau client
└── monitor.ps1                ← Surveille RAM et alerte Telegram
```

Chaque client a son dossier isolé, son login MT5, sa session EA. Lancé en `/portable`,
chaque MT5 vit dans son propre sandbox sans interférer.

## Usage

### Setup initial (1 fois)

1. RDP au VPS, ouvrir PowerShell Admin
2. Cloner ce dossier dans `C:\Scalping\` :
   ```powershell
   git clone https://github.com/xav916/scalping C:\Scalping\repo
   Copy-Item -Path C:\Scalping\repo\mt5-bridge\multi-tenant\*.ps1 -Destination C:\Scalping\
   ```
3. Préparer le template MT5 :
   - Installer MT5 du broker dans `C:\Scalping\shared\MT5-Template\`
   - Lancer 1 fois pour générer les fichiers
   - Désinstaller proprement (ou garder, copie-coller marche)
4. Configurer la tâche planifiée :
   ```powershell
   $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -File C:\Scalping\launcher.ps1"
   $trigger = New-ScheduledTaskTrigger -AtLogOn -User Administrator
   Register-ScheduledTask -TaskName "ScalpingClientsLauncher" -Action $action -Trigger $trigger -RunLevel Highest
   ```
5. Migrer Cédric (déplacer son MT5 actuel vers `C:\Scalping\clients\cedric\MT5\`)

### Ajouter un nouveau client

```powershell
.\add-client.ps1 -ClientName "jeanmarc" `
                 -ApiKey "abcDEF123..." `
                 -BrokerLogin "62124567" `
                 -BrokerServer "PepperstoneUK-Demo"
```

Le script :
- Crée `C:\Scalping\clients\jeanmarc\` avec MT5 portable
- Génère son `start.bat`
- Ajoute au launcher
- **Action manuelle restante** : RDP, lancer MT5 du client 1 fois pour login broker + attache l'EA sur un chart

### Monitoring

`monitor.ps1` tourne en tâche planifiée toutes les 10 min :
- Compte les instances MT5 actives
- Calcule la RAM utilisée
- Si RAM > 80% → alerte Telegram `@xav_scalping_infra_bot`

```powershell
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -File C:\Scalping\monitor.ps1"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName "ScalpingClientsMonitor" -Action $action -Trigger $trigger -RunLevel Highest
```

## Capacité par bundle Lightsail Windows

| Bundle | RAM | Coût/mois | Clients confort. |
|---|---|---|---|
| small_win_3_0 | 2 GB | 22 USD | 2-3 |
| medium_win_3_0 | 4 GB | 40 USD | 5-6 |
| large_win_3_0 | 8 GB | 70 USD | 10-12 |
| xlarge_win_3_0 | 16 GB | 120 USD | 20-25 |

## Upgrade bundle (downtime ~10 min)

1. AWS Lightsail console → instance → onglet "Snapshots" → créer snapshot
2. Créer nouvelle instance depuis ce snapshot, choisir bundle plus grand
3. Détacher IP statique de l'ancienne instance, la réattacher à la nouvelle
4. Supprimer ancienne instance
5. RDP à la nouvelle → vérifier que toutes les instances MT5 démarrent OK

À planifier en weekend (forex fermé). Crypto continue 24/7 — accepter le downtime.
