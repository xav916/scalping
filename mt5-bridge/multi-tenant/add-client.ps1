# add-client.ps1 — Onboard un nouveau client Premium sur ce VPS.
# Crée la structure C:\Scalping\clients\<NAME>\ avec :
#   - MT5 portable copié depuis le template
#   - api_key.txt et broker.txt (référence, pas auto-utilisé par MT5)
#   - start.bat qui lance MT5 portable
#
# Action manuelle restante après ce script :
#   1. RDP au VPS, lancer manuellement le start.bat du nouveau client
#   2. Login MT5 avec le compte broker (le script ne peut pas saisir le password)
#   3. Drag l'EA ScalpingRadarEA sur un chart, saisir l'api_key, AutoTrading ON
#   4. Vérifier smiley vert + premier poll dans les logs Experts
#
# Usage:
#   .\add-client.ps1 -ClientName "jeanmarc" `
#                    -ApiKey "abcDEF123..." `
#                    -BrokerLogin "62124567" `
#                    -BrokerServer "PepperstoneUK-Demo"

param(
    [Parameter(Mandatory=$true)][string]$ClientName,
    [Parameter(Mandatory=$true)][string]$ApiKey,
    [Parameter(Mandatory=$true)][string]$BrokerLogin,
    [Parameter(Mandatory=$true)][string]$BrokerServer
)

$ErrorActionPreference = "Stop"

# Validation
if ($ClientName -match "[^\w-]") {
    Write-Error "ClientName doit contenir uniquement lettres, chiffres, underscore et tiret"
    exit 1
}
if ($ApiKey.Length -lt 16) {
    Write-Error "ApiKey trop court (min 16 chars)"
    exit 1
}

$baseDir = "C:\Scalping\clients\$ClientName"
$templateDir = "C:\Scalping\shared\MT5-Template"

if (Test-Path $baseDir) {
    Write-Error "Le client $ClientName existe déjà à $baseDir. Utiliser un autre nom ou supprimer manuellement."
    exit 1
}
if (-not (Test-Path $templateDir)) {
    Write-Error "Template MT5 manquant : $templateDir. Installer MT5 dans ce dossier d'abord."
    exit 1
}

Write-Host "[add-client] Création de $baseDir..."
New-Item -ItemType Directory -Path $baseDir -Force | Out-Null

# Copie du template MT5 portable
Write-Host "[add-client] Copie du template MT5 (peut prendre ~1 min)..."
Copy-Item -Path "$templateDir\*" -Destination "$baseDir\MT5" -Recurse -Force

# Fichiers de configuration (informatifs, pour ton suivi admin)
Set-Content -Path "$baseDir\api_key.txt" -Value $ApiKey
Set-Content -Path "$baseDir\broker.txt" -Value "$BrokerLogin@$BrokerServer"
Set-Content -Path "$baseDir\onboarded_at.txt" -Value (Get-Date -Format "yyyy-MM-dd HH:mm:ss")

# start.bat qui lance MT5 portable
$startBat = @"
@echo off
REM Lance MT5 portable pour le client $ClientName
cd /d "$baseDir\MT5"
start "" terminal64.exe /portable
"@
Set-Content -Path "$baseDir\start.bat" -Value $startBat

Write-Host ""
Write-Host "✓ Client $ClientName créé : $baseDir" -ForegroundColor Green
Write-Host ""
Write-Host "Étapes manuelles restantes :" -ForegroundColor Yellow
Write-Host "  1. Lance start.bat ou cd $baseDir\MT5 + terminal64.exe /portable"
Write-Host "  2. Dans MT5, login compte broker : $BrokerLogin sur $BrokerServer"
Write-Host "  3. Tools → Options → Expert Advisors → Allow WebRequest → ajouter https://app.scalping-radar.online"
Write-Host "  4. Drag ScalpingRadarEA sur un chart, saisir InpApiKey = $ApiKey"
Write-Host "  5. Cocher Allow Algo Trading, vérifier smiley vert"
Write-Host "  6. Au prochain reboot VPS, launcher.ps1 démarrera automatiquement ce client"
