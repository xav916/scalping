#!/usr/bin/env bash
# Relance le terminal MT5 de la DEMO (Pepperstone), gele depuis le 05/10 00h04.
#
# ⛔ POURQUOI CE SCRIPT EXISTE PLUTOT QUE LA COMMANDE EN DIRECT
# Le classificateur du mode auto refuse a Claude d arreter un processus
# distant — y compris par fermeture propre de fenetre. C est donc Xavier qui
# lance, avec le « ! » en TOUT PREMIER caractere :
#
#     ! bash ~/Scalping/scalping/scripts/relancer_terminal_demo.sh
#
# 🔑 LE REEL N EST JAMAIS TOUCHE. Deux garde-fous :
#   1. on ne cible que le PID dont le chemin est CELUI de Pepperstone ;
#      si le chemin ne correspond pas, le script ABANDONNE ;
#   2. on ne demarre que la tache `ScalpingMT5` (Pepperstone). Jamais
#      `ScalpingMT5_Live`, qui porte le compte IC Markets 13137475.
#
# ⚠️ Rien a perdre : la demo est DEJA muette (/health ok=false, 18 511 refus
# stale_tick le 07/10). Si les identifiants demo sont perimes, le terminal
# revient sans compte — etat identique a aujourd hui.
set -euo pipefail

cd "$(dirname "$0")/.."
EC2="ec2-user@100.103.107.75"
VPS="Administrator@100.74.160.72"
ATTENDU='C:\Program Files\Pepperstone MetaTrader 5\terminal64.exe'

B64=$(python - <<'PY'
import base64
ps = r'''
$ErrorActionPreference = 'Stop'
$attendu = 'C:\Program Files\Pepperstone MetaTrader 5\terminal64.exe'

# --- 1. identifier le terminal DEMO par son CHEMIN, jamais par son PID seul ---
$demo = Get-Process terminal64 -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $attendu }
if (-not $demo) { 'ABANDON: aucun terminal Pepperstone en marche'; exit 1 }
if ($demo.Count -gt 1) { 'ABANDON: plusieurs terminaux Pepperstone'; exit 1 }
'cible : PID ' + $demo.Id + '  ' + $demo.Path

# --- 2. fermeture propre, puis forcee seulement si elle resiste ---
$null = $demo.CloseMainWindow()
Start-Sleep -Seconds 12
if (Get-Process -Id $demo.Id -ErrorAction SilentlyContinue) {
  'la fenetre resiste, arret force du SEUL PID ' + $demo.Id
  Stop-Process -Id $demo.Id -Force
  Start-Sleep -Seconds 5
}
'terminaux restants :'
Get-Process terminal64 -ErrorAction SilentlyContinue |
  ForEach-Object { '  PID=' + $_.Id + '  ' + $_.Path }

# --- 3. relancer la tache de la DEMO uniquement ---
Start-ScheduledTask -TaskName 'ScalpingMT5'
Start-Sleep -Seconds 30
'apres relance :'
Get-Process terminal64 -ErrorAction SilentlyContinue |
  ForEach-Object { '  PID=' + $_.Id + '  start=' + $_.StartTime + '  ' + $_.Path }

# --- 4. relancer le pont demo pour qu il refasse mt5.initialize() ---
Stop-ScheduledTask -TaskName 'ScalpingBridge' -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
Start-ScheduledTask -TaskName 'ScalpingBridge'
Start-Sleep -Seconds 20
'journal du terminal demo (doit porter la date du jour) :'
$logs = 'C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\73B7A2420D6397DFF9014A20F1201F97\logs'
Get-ChildItem $logs | Sort LastWriteTime -Desc | Select -First 2 Name,Length,LastWriteTime |
  Format-Table -AutoSize | Out-String
'''
print(base64.b64encode(ps.encode('utf-16-le')).decode())
PY
)

echo "== relance du terminal DEMO (le reel n est pas touche) =="
ssh -i scalping-key.pem -o StrictHostKeyChecking=no "$EC2" \
  "ssh -i ~/.ssh/vps_bridge -o BatchMode=yes -o StrictHostKeyChecking=no $VPS 'powershell -NoProfile -EncodedCommand $B64'" \
  2>&1 | grep -vE '^<Objs|WARNING:|decrypt later|needs? to be upgraded|CLIXML'

echo
echo "== /health des deux ponts =="
ssh -i scalping-key.pem -o StrictHostKeyChecking=no "$EC2" \
  'for p in 8787 8788; do printf "port %s : " "$p"; curl -s -m 10 "http://100.74.160.72:$p/health" | python3 -c "import json,sys; h=json.load(sys.stdin); print(\"ok=\", h.get(\"ok\"), \" login=\", h.get(\"login\"), \" serveur=\", h.get(\"server\"), sep=\"\")"; done' \
  2>&1 | grep -vE 'WARNING:|decrypt later|needs? to be upgraded'

echo
echo "Attendu : port 8787 ok=True login=62134158 PepperstoneUK-Demo"
echo "          port 8788 ok=True login=13137475 ICMarketsEU-MT5-5  (inchange)"
