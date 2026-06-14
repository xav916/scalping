# launcher.ps1 — Démarre toutes les instances MT5 clients au boot du VPS.
# Tâche planifiée AtLogOn user Administrator → relance auto si reboot.
# Chaque client a son dossier C:\Scalping\clients\<NAME>\ avec un start.bat.

$ErrorActionPreference = "Continue"
$logFile = "C:\Scalping\launcher.log"

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logFile -Value "[$ts] $msg"
    Write-Host "[$ts] $msg"
}

Log "===== Launcher start ====="

# Délai au boot pour laisser le réseau / Windows finir l'init
Start-Sleep -Seconds 30

$clientsRoot = "C:\Scalping\clients"
if (-not (Test-Path $clientsRoot)) {
    Log "ERREUR : $clientsRoot n'existe pas, abort"
    exit 1
}

$clients = Get-ChildItem -Path $clientsRoot -Directory
Log "Trouvé $($clients.Count) dossier(s) client"

foreach ($client in $clients) {
    $startBat = Join-Path $client.FullName "start.bat"
    if (Test-Path $startBat) {
        try {
            Start-Process -FilePath $startBat -WindowStyle Hidden -ErrorAction Stop
            Log "  OK lancé client : $($client.Name)"
            # Délai entre clients pour éviter overload simultané
            Start-Sleep -Seconds 5
        } catch {
            Log "  ECHEC lancement $($client.Name) : $_"
        }
    } else {
        Log "  Skip $($client.Name) (pas de start.bat)"
    }
}

Log "===== Launcher end ====="
