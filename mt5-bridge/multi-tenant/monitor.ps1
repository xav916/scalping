# monitor.ps1 — Surveille RAM/CPU du VPS clients + nb instances MT5.
# Si RAM > 80% sur le VPS, alerte Telegram @xav_scalping_infra_bot.
# À lancer en tâche planifiée toutes les 10 min.

$ErrorActionPreference = "Continue"
$logFile = "C:\Scalping\monitor.log"

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logFile -Value "[$ts] $msg"
}

# Métriques VPS
$totalMem = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1MB
$freeMem = (Get-Counter "\Memory\Available MBytes").CounterSamples.CookedValue
$usedMem = $totalMem - $freeMem
$ramPct = [math]::Round(($usedMem / $totalMem) * 100, 1)

# Instances MT5
$mt5Processes = Get-Process -Name "terminal64" -ErrorAction SilentlyContinue
$mt5Count = if ($mt5Processes) { $mt5Processes.Count } else { 0 }
$mt5RamMB = if ($mt5Processes) {
    [math]::Round(($mt5Processes | Measure-Object -Property WorkingSet64 -Sum).Sum / 1MB, 0)
} else { 0 }

# Clients configurés
$clientsRoot = "C:\Scalping\clients"
$clientCount = 0
if (Test-Path $clientsRoot) {
    $clientCount = (Get-ChildItem -Path $clientsRoot -Directory).Count
}

Log "RAM: $ramPct% ($([math]::Round($usedMem,0))/$([math]::Round($totalMem,0)) MB) | MT5: $mt5Count instances ($mt5RamMB MB) | Clients configurés: $clientCount"

# Alerte si RAM > 80% OU si nombre MT5 < nombre clients (instance crashée)
$shouldAlert = $false
$alertReason = ""

if ($ramPct -gt 80) {
    $shouldAlert = $true
    $alertReason = "RAM saturée ($ramPct%)"
}

if ($mt5Count -lt $clientCount) {
    $shouldAlert = $true
    $alertReason = "$($clientCount - $mt5Count) instance(s) MT5 manquante(s) ($mt5Count actives sur $clientCount clients)"
}

if ($shouldAlert) {
    $hostname = $env:COMPUTERNAME
    $title = "[VPS clients] Anomalie : $alertReason"
    $body = "Hôte : $hostname\n\n" +
            "RAM utilisée : $ramPct% ($([math]::Round($usedMem,0))/$([math]::Round($totalMem,0)) MB)\n" +
            "Instances MT5 actives : $mt5Count (sur $clientCount clients configurés)\n" +
            "RAM MT5 cumulée : $mt5RamMB MB\n\n" +
            "ℹ️ Si RAM > 80% : envisager upgrade bundle Lightsail (Small→Medium→Large).\n" +
            "Si instance manquante : RDP au VPS et relancer start.bat du client concerné."

    $token = "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
    $url = "https://app.scalping-radar.online/api/admin/notify-infra-telegram?token=$token"
    $payload = @{
        title = $title
        body = $body
        dedup_key = "vps_clients_anomaly_$alertReason"
        cooldown_seconds = 3600
    } | ConvertTo-Json

    try {
        Invoke-RestMethod -Uri $url -Method POST -ContentType "application/json" -Body $payload -TimeoutSec 10 | Out-Null
        Log "  ALERTE envoyée Telegram : $alertReason"
    } catch {
        Log "  ECHEC envoi Telegram : $_"
    }
}
