<#
.SYNOPSIS
    Chercher ou MetaTrader 5 range les messages des canaux MQL5. LECTURE SEULE.

.DESCRIPTION
    Vous etes abonne au canal « Orvion » : ses messages arrivent donc deja sur
    cette machine. S'ils sont sur le disque, un lecteur local suffit — pas de
    scraping du site, pas d'identifiants MQL5 deposes dans un service, pas de
    conditions d'utilisation a contourner. On lit ce qu'on a recu, chez soi.

    ⛔ Je NE SAIS PAS ou MT5 les range, et je ne l'invente pas. Cette sonde le
    DECOUVRE : elle parcourt les dossiers de donnees MT5 et signale les fichiers
    qui contiennent le nom du canal.

    ⛔ Elle n'ecrit RIEN, n'ouvre aucune connexion, ne lit aucun identifiant.
    Elle rend des CHEMINS et des COMPTES d'occurrences — jamais le contenu des
    fichiers, qui pourrait porter autre chose que des messages de canal.

    ⚠️ Si rien n'est trouve, l'information est utile aussi : cela voudra dire que
    le canal n'est suivi que sur le mobile. Il faudra alors s'y abonner AUSSI
    depuis le terminal de bureau pour que les messages atterrissent ici.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\sonde-mt5.ps1
    powershell -ExecutionPolicy Bypass -File .\sonde-mt5.ps1 -Motif "Orvion"
#>
[CmdletBinding()]
param(
    [string] $Motif = "Orvion",
    # ⚠️ Un plafond, parce qu'un dossier de donnees MT5 contient des historiques
    # de bougies de plusieurs gigaoctets. Les messages d'un canal sont petits.
    [int] $TailleMaxMo = 64
)

$ErrorActionPreference = "Continue"

function Contient-Motif {
    <#
        Cherche le motif en ASCII *et* en UTF-16LE. MT5 est une application
        Windows native : ses fichiers peuvent porter l'un ou l'autre, et ne
        chercher qu'en ASCII raterait la moitie des cas sans le dire.
    #>
    param([string] $Chemin, [string] $Motif)
    try {
        $octets = [System.IO.File]::ReadAllBytes($Chemin)
    } catch { return $null }

    $resultats = @()
    foreach ($encodage in @("ASCII", "Unicode")) {
        $aiguille = [System.Text.Encoding]::$encodage.GetBytes($Motif)
        $n = 0; $i = 0
        while ($i -le ($octets.Length - $aiguille.Length)) {
            $trouve = $true
            for ($j = 0; $j -lt $aiguille.Length; $j++) {
                if ($octets[$i + $j] -ne $aiguille[$j]) { $trouve = $false; break }
            }
            if ($trouve) { $n++; $i += $aiguille.Length } else { $i++ }
        }
        if ($n -gt 0) { $resultats += "$encodage x$n" }
    }
    if ($resultats.Count -gt 0) { return ($resultats -join ", ") }
    return $null
}

$racine = Join-Path $env:APPDATA "MetaQuotes\Terminal"
Write-Host "=== Dossiers de donnees MT5 ===" -ForegroundColor Cyan
if (-not (Test-Path $racine)) {
    Write-Host "  $racine : ABSENT." -ForegroundColor Yellow
    Write-Host "  MT5 de BUREAU n'est pas installe pour cet utilisateur." -ForegroundColor Yellow
    Write-Host "  (L'application mobile ne depose rien sur ce disque.)" -ForegroundColor Yellow
    exit 0
}
$terminaux = Get-ChildItem $racine -Directory -ErrorAction SilentlyContinue
foreach ($t in $terminaux) { Write-Host "  $($t.FullName)" }

Write-Host "`n=== Recherche de « $Motif » (lecture seule, <= $TailleMaxMo Mo) ===" -ForegroundColor Cyan
$plafond = $TailleMaxMo * 1MB
$examines = 0; $touches = 0

foreach ($t in $terminaux) {
    Get-ChildItem $t.FullName -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Length -le $plafond -and $_.Length -gt 0 } |
        ForEach-Object {
            $examines++
            $ou = Contient-Motif -Chemin $_.FullName -Motif $Motif
            if ($ou) {
                $touches++
                Write-Host ("  TROUVE  {0}" -f $_.FullName) -ForegroundColor Green
                Write-Host ("          {0} | {1:N0} octets | modifie {2}" -f `
                            $ou, $_.Length, $_.LastWriteTime)
            }
        }
}

Write-Host "`n=== Bilan ===" -ForegroundColor Cyan
Write-Host "  fichiers examines : $examines"
Write-Host "  fichiers portant le motif : $touches"
if ($touches -eq 0) {
    Write-Host "`n  Rien trouve. Deux lectures possibles :" -ForegroundColor Yellow
    Write-Host "   1. Le canal n'est suivi que sur le MOBILE. S'y abonner aussi"
    Write-Host "      depuis le terminal de bureau, puis relancer cette sonde."
    Write-Host "   2. MT5 ne conserve pas les messages sur le disque (cache memoire"
    Write-Host "      seul, ou base chiffree). Dans ce cas, la lecture locale est"
    Write-Host "      sans issue et il faut demander un flux a l'auteur du canal."
} else {
    Write-Host "`n  Envoyez-moi ces chemins et les tailles. Je regarde si le format" -ForegroundColor Green
    Write-Host "  est exploitable avant d'ecrire quoi que ce soit."
}
