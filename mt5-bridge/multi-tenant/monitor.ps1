# monitor.ps1 — Surveillance VPS clients avec alertes Telegram vulgarisées.
# À lancer en tâche planifiée toutes les 10 min.
# Alertes envoyées au bot @xav_scalping_infra_bot.
#
# Métriques surveillées :
#   - RAM utilisée (alerte à 80%)
#   - Disque libre (alerte si < 10%)
#   - Nombre d'instances MT5 actives vs clients configurés (alerte si écart)
#   - Uptime du VPS (info dans les alertes)
#
# Format messages : style lambda-friendly (cf. memo feedback_telegram_messages_vulgarized_2026_06_13).

$ErrorActionPreference = "Continue"
$logFile = "C:\Scalping\monitor.log"

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logFile -Value "[$ts] $msg"
}

function Send-InfraAlert($title, $body, $dedupKey, $cooldownSec = 3600) {
    $token = "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
    $url = "https://app.scalping-radar.online/api/admin/notify-infra-telegram?token=$token"
    $payload = @{
        title = $title
        body = $body
        dedup_key = $dedupKey
        cooldown_seconds = $cooldownSec
    } | ConvertTo-Json
    try {
        Invoke-RestMethod -Uri $url -Method POST -ContentType "application/json" -Body $payload -TimeoutSec 10 | Out-Null
        Log "  ALERTE envoyée : $title"
    } catch {
        Log "  ECHEC envoi alerte : $_"
    }
}

# ─── Métriques système ────────────────────────────────
$totalMemMB = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1MB
$freeMemMB = (Get-Counter "\Memory\Available MBytes" -ErrorAction SilentlyContinue).CounterSamples.CookedValue
$usedMemMB = $totalMemMB - $freeMemMB
$ramPct = [math]::Round(($usedMemMB / $totalMemMB) * 100, 1)
$totalMemGB = [math]::Round($totalMemMB / 1024, 1)
$usedMemGB = [math]::Round($usedMemMB / 1024, 2)

# Disque C:
$disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"
$diskFreeGB = [math]::Round($disk.FreeSpace / 1GB, 1)
$diskTotalGB = [math]::Round($disk.Size / 1GB, 1)
$diskUsedPct = [math]::Round((($disk.Size - $disk.FreeSpace) / $disk.Size) * 100, 1)

# Uptime
$bootTime = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
$uptime = (Get-Date) - $bootTime
$uptimeStr = if ($uptime.Days -gt 0) {
    "$($uptime.Days)j $($uptime.Hours)h"
} elseif ($uptime.Hours -gt 0) {
    "$($uptime.Hours)h $($uptime.Minutes)min"
} else {
    "$($uptime.Minutes)min"
}

# Instances MT5
$mt5Processes = Get-Process -Name "terminal64" -ErrorAction SilentlyContinue
$mt5Count = if ($mt5Processes) { $mt5Processes.Count } else { 0 }
$mt5RamMB = if ($mt5Processes) {
    [math]::Round(($mt5Processes | Measure-Object -Property WorkingSet64 -Sum).Sum / 1MB, 0)
} else { 0 }

# Clients configurés
$clientsRoot = "C:\Scalping\clients"
$clientCount = 0
$clientNames = @()
if (Test-Path $clientsRoot) {
    $clientDirs = Get-ChildItem -Path $clientsRoot -Directory
    $clientCount = $clientDirs.Count
    $clientNames = $clientDirs | ForEach-Object { $_.Name }
}

Log "RAM: $ramPct% ($usedMemGB / $totalMemGB GB) | Disque: $diskUsedPct% libre $diskFreeGB GB | MT5: $mt5Count/$clientCount | Uptime: $uptimeStr"

# ─── Alerte RAM saturée ───────────────────────────────
if ($ramPct -gt 80) {
    $clientsList = if ($clientNames.Count -gt 0) { ($clientNames -join ", ") } else { "aucun" }

    $title = "⚠️ VPS clients chargé à $ramPct%"
    $body = "📊 *État actuel*`n" +
            "RAM utilisée : $usedMemGB GB sur $totalMemGB GB`n" +
            "Robots actifs : $mt5Count clients ($clientsList)`n" +
            "Démarré il y a : $uptimeStr`n`n" +
            "ℹ️ *Pourquoi ce message ?*`n" +
            "Le VPS qui héberge les robots des clients commence à manquer de place. " +
            "Il peut continuer à fonctionner mais le risque de ralentissement (et donc " +
            "de retards d'exécution sur les ordres) augmente.`n`n" +
            "🛠️ *Que faire ?*`n" +
            "• Soit ne plus ajouter de nouveaux clients pour l'instant`n" +
            "• Soit upgrader le VPS vers une taille plus grande (Lightsail console → " +
            "instance → snapshot + nouvelle instance Medium 4 GB ou Large 8 GB). " +
            "Compte ~10 min de pause à faire en weekend."
    Send-InfraAlert $title $body "vps_clients_ram_high_$([math]::Floor($ramPct/10))"
}

# ─── Alerte disque saturé ─────────────────────────────
if ($diskUsedPct -gt 90) {
    $title = "💾 VPS clients : disque presque plein ($diskUsedPct%)"
    $body = "📊 *État actuel*`n" +
            "Disque utilisé : $($diskTotalGB - $diskFreeGB) GB sur $diskTotalGB GB`n" +
            "Libre restant : *$diskFreeGB GB*`n`n" +
            "ℹ️ *Pourquoi ce message ?*`n" +
            "Si le disque sature, les robots MT5 ne peuvent plus écrire leurs logs " +
            "et risquent de planter. Aussi, Windows peut refuser des opérations basiques.`n`n" +
            "🛠️ *Que faire ?*`n" +
            "• Vider la corbeille (clic droit sur la corbeille → Vider)`n" +
            "• Nettoyer les vieux logs dans C:\Scalping\*\logs\`n" +
            "• Supprimer les fichiers temporaires (Réglages → Stockage → Fichiers temporaires)`n" +
            "• Si rien ne libère assez : upgrader le VPS"
    Send-InfraAlert $title $body "vps_clients_disk_high"
}

# ─── Alerte robot client tombé ────────────────────────
if ($mt5Count -lt $clientCount) {
    $missing = $clientCount - $mt5Count
    $title = "🚨 Robot client tombé sur le VPS"
    $body = "⚠️ *$missing robot(s) MT5 manquant(s)*`n" +
            "Actifs : $mt5Count sur $clientCount clients configurés.`n" +
            "Clients sur ce VPS : $($clientNames -join ', ')`n`n" +
            "ℹ️ *Pourquoi ce message ?*`n" +
            "Chaque client Premium a son robot MT5 qui doit tourner en permanence " +
            "pour exécuter les ordres reçus du radar. Si un robot s'arrête, ce client " +
            "ne reçoit plus aucun trade automatique.`n`n" +
            "🛠️ *Que faire ?*`n" +
            "1. RDP au VPS (IP $((Invoke-WebRequest -Uri 'https://checkip.amazonaws.com' -UseBasicParsing -TimeoutSec 5).Content.Trim()))`n" +
            "2. Va dans C:\Scalping\clients\ et identifie le dossier sans MT5 actif`n" +
            "3. Lance le start.bat de ce client`n" +
            "4. Le robot reprend dans les 30 secondes"
    Send-InfraAlert $title $body "vps_clients_mt5_down"
}

# ─── Heartbeat hebdomadaire (lundi 9h) — confirme que le VPS va bien ───
$now = Get-Date
if ($now.DayOfWeek -eq 'Monday' -and $now.Hour -eq 9 -and $now.Minute -lt 10) {
    $title = "✅ VPS clients OK — récap hebdo"
    $body = "📊 *État du VPS*`n" +
            "RAM utilisée : $ramPct% ($usedMemGB / $totalMemGB GB)`n" +
            "Disque libre : $diskFreeGB GB / $diskTotalGB GB`n" +
            "Démarré il y a : $uptimeStr`n" +
            "Robots actifs : $mt5Count / $clientCount clients`n`n" +
            "ℹ️ Tous les robots clients tournent normalement. " +
            "Le VPS a la capacité d'accueillir environ $([math]::Max(0, [math]::Floor(($totalMemMB - $usedMemMB) / 500))) client(s) supplémentaire(s) avant saturation."
    Send-InfraAlert $title $body "vps_weekly_recap_$($now.ToString('yyyy-MM-dd'))" 0
}
