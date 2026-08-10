# Lanceur du bridge IBKR.
#
# `bridge.py` lit sa configuration dans l'environnement et n'embarque PAS
# python-dotenv : ce script lit le `.env` place a cote (jamais versionne) et
# lance l'interpreteur du venv local.
#
# Usage :  powershell -NoProfile -ExecutionPolicy Bypass -File start-bridge.ps1
#
# ⚠️ `IBKR_ALLOW_ORDERS` reste a `false` sauf decision explicite. Tant qu'il
# est faux, la session IB est ouverte en `readonly=True` et c'est le Gateway
# LUI-MEME qui refuse toute ecriture — un bug applicatif ne peut pas passer
# d'ordre.
$ErrorActionPreference = "Stop"
$racine = Split-Path -Parent $MyInvocation.MyCommand.Path

$envFile = Join-Path $racine ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $ligne = $_.Trim()
        if ($ligne -and -not $ligne.StartsWith("#") -and $ligne.Contains("=")) {
            $i = $ligne.IndexOf("=")
            $cle = $ligne.Substring(0, $i).Trim()
            $val = $ligne.Substring($i + 1).Trim()
            [Environment]::SetEnvironmentVariable($cle, $val, "Process")
        }
    }
    Write-Host "config lue depuis $envFile"
} else {
    Write-Warning "$envFile absent — le bridge demarrera sur ses valeurs par defaut"
}

$python = Join-Path $racine ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "venv absent : lancer d'abord  py -m venv .venv  puis  pip install -r requirements.txt"
}

Write-Host ("demarrage : {0}:{1} · gateway {2}:{3} · ordres={4}" -f `
    $env:IBKR_BRIDGE_HOST, $env:IBKR_BRIDGE_PORT,
    $env:IBKR_GATEWAY_HOST, $env:IBKR_GATEWAY_PORT, $env:IBKR_ALLOW_ORDERS)

& $python (Join-Path $racine "bridge.py")
