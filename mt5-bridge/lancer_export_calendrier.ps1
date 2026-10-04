# Lance l'export du calendrier MT5 dans une session INTERACTIVE.
#
# ⛔ POURQUOI UNE TACHE PLANIFIEE ET PAS UN SIMPLE Start-Process
#
# Tentative du 2026-10-05 a 22h35 UTC, lancee par SSH :
#
#     MDI create failed ... create frame from resource 131 failed
#     open chart 'XAUUSD' failed for '' / 'CalendrierExport'
#
# Un script MQL5 a besoin d'un GRAPHIQUE, un graphique d'une FENETRE, et une
# fenetre d'un BUREAU. Une session SSH n'en a aucun. Les deux terminaux de
# production tournent en session 1 — celle qui a un bureau.
#
# 🔑 Une tache planifiee avec `-LogonType Interactive` demarre DANS cette
# session 1. C'est le seul moyen d'obtenir un graphique sans RDP.
#
# ⛔ ET POURQUOI LE COMPTE DEMO
#
# Le terminal generique porte `Login=13137475` (le compte REEL) mais ses
# identifiants sont perimes :
#
#     '13137475': authorization on ICMarketsEU-MT5-5 failed (Invalid account)
#
# On le pointe donc explicitement sur le DEMO. La base calendrier vient de
# MetaQuotes : elle est IDENTIQUE quel que soit le compte. Risque nul pour le
# reel.
#
# 🔑 Le mot de passe est lu SUR LE VPS, dans le `.env` du pont demo. Il ne
# transite jamais par la machine de Claude, ni par la conversation.
#
# ⚠️ Peut deloger la session du pont DEMO (port 8787). Impact faible, et le
# pont se reconnecte seul.

$ErrorActionPreference = 'Continue'
$donnees = "$env:APPDATA\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075"
$ini     = 'C:\Windows\Temp\export_cal.ini'
$tache   = 'ExportCalendrierMT5'
$sortie  = Join-Path $donnees 'MQL5\Files\calendrier_export.tsv'

# ─── 1. Identifiants du demo, lus sur place ────────────────────────────────
$env_demo = 'C:\Scalping\mt5-bridge\.env'
if (-not (Test-Path $env_demo)) { Write-Output "⛔ $env_demo introuvable"; exit 2 }
$conf = @{}
Get-Content $env_demo | Where-Object { $_ -match '^\s*MT5_(LOGIN|PASSWORD|SERVER)\s*=' } |
  ForEach-Object {
    $p = $_ -split '=', 2
    $conf[$p[0].Trim()] = $p[1].Trim().Trim('"').Trim("'")
  }
foreach ($k in 'MT5_LOGIN','MT5_PASSWORD','MT5_SERVER') {
  if (-not $conf[$k]) { Write-Output "⛔ $k absent du .env demo"; exit 2 }
}
if ($conf['MT5_LOGIN'] -eq '13137475') {
  Write-Output '⛔ le .env demo porte le compte REEL — je refuse'; exit 2
}
Write-Output ("compte utilise : " + $conf['MT5_LOGIN'] + " @ " + $conf['MT5_SERVER'])

# ─── 2. Configuration de demarrage ─────────────────────────────────────────
$txt = "[Common]`r`nLogin=$($conf['MT5_LOGIN'])`r`nPassword=$($conf['MT5_PASSWORD'])`r`n" +
       "Server=$($conf['MT5_SERVER'])`r`n`r`n" +
       "[StartUp]`r`nScript=CalendrierExport`r`nSymbol=EURUSD`r`nPeriod=H1`r`n" +
       "ShutdownTerminal=1`r`n"
[IO.File]::WriteAllText($ini, $txt, [Text.Encoding]::Unicode)
Write-Output "ini ecrit      : $ini"

if (Test-Path $sortie) { Remove-Item $sortie -Force }

# ─── 3. Tache planifiee INTERACTIVE ────────────────────────────────────────
Unregister-ScheduledTask -TaskName $tache -Confirm:$false -ErrorAction SilentlyContinue
$action = New-ScheduledTaskAction -Execute 'C:\Program Files\MetaTrader 5\terminal64.exe' `
                                  -Argument "/config:$ini"
# ⛔ `-UserId "$env:USERDOMAIN\$env:USERNAME"` ECHOUE ici :
#
#     Register-ScheduledTask : No mapping between account names and security IDs
#
# En session SSH, `USERDOMAIN` vaut `WORKGROUP` et Windows ne sait pas resoudre
# `WORKGROUP\administrator`.
#
# 🔑 On ne devine pas : les quatre taches QUI MARCHENT deja sur ce VPS
# (ScalpingMT5, ScalpingMT5_Live, ScalpingBridge, ScalpingBridge_Live) portent
# toutes `UserId=Administrator` tout court, `LogonType=Interactive`,
# `RunLevel=Highest`. On copie leur configuration exacte.
$princ  = New-ScheduledTaskPrincipal -UserId 'Administrator' `
                                     -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName $tache -Action $action -Principal $princ -Force | Out-Null
Start-ScheduledTask -TaskName $tache
Write-Output 'tache lancee dans la session interactive, attente (240 s max)...'

# ─── 4. Attente de l'export ────────────────────────────────────────────────
$fini = $false
for ($i = 0; $i -lt 80; $i++) {
  Start-Sleep -Seconds 3
  if (Test-Path $sortie) {
    $a = (Get-Item $sortie).Length
    Start-Sleep -Seconds 5                      # laisser l'ecriture finir
    $b = (Get-Item $sortie).Length
    if ($b -eq $a -and $b -gt 0) {
      Write-Output ("✅ EXPORT PRODUIT : $b octets apres " + ($i * 3) + ' s')
      $fini = $true
      break
    }
  }
}
if (-not $fini) { Write-Output '⛔ AUCUN FICHIER produit dans le delai' }

# ─── 5. Ce que le terminal a dit ───────────────────────────────────────────
Write-Output ''
Write-Output '=== journal MT5 (lignes utiles) ==='
$jour = (Get-Date).ToString('yyyyMMdd')
Get-Content (Join-Path $donnees ('logs\' + $jour + '.log')) -ErrorAction SilentlyContinue |
  Select-String 'CalendrierExport|export termine|authorization|failed|Calendar' |
  Select-Object -Last 10 | ForEach-Object { Write-Output ('  ' + $_.Line) }

# ─── 6. Menage : le terminal, la tache, et le fichier qui porte le secret ──
Write-Output ''
Write-Output '=== menage ==='
Get-Process -Name 'terminal64' -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -eq 'C:\Program Files\MetaTrader 5\terminal64.exe' } |
  ForEach-Object { Write-Output ("  arret PID " + $_.Id); Stop-Process -Id $_.Id -Force }
Unregister-ScheduledTask -TaskName $tache -Confirm:$false -ErrorAction SilentlyContinue
Remove-Item $ini -Force -ErrorAction SilentlyContinue
Write-Output '  tache retiree, ini supprime (il portait le mot de passe)'
Write-Output ''
Write-Output '=== terminaux encore en marche ==='
Get-Process -Name 'terminal64' -ErrorAction SilentlyContinue |
  ForEach-Object { Write-Output ('  ' + $_.Path) }
