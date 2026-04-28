$apikey = (Get-Content C:\Scalping\mt5-bridge\.env | Select-String "BRIDGE_API_KEY").Line.Split("=")[1].Trim()
$tick = Invoke-RestMethod -Uri "http://100.122.188.8:8787/tick/EUR/USD" -Headers @{"X-API-Key"=$apikey}
$price = [double]$tick.bid
Write-Host "Prix EUR/USD : $price"

$body = @{
    pair="EUR/USD"
    direction="buy"
    entry=$price
    sl=[math]::Round($price-0.0020,5)
    tp=[math]::Round($price+0.0020,5)
    risk_money=10
    comment="smoke-test"
}

Write-Host "Payload :"
$body | Format-Table | Out-String | Write-Host

try {
    $r = Invoke-RestMethod -Uri "http://100.122.188.8:8787/order" `
        -Method Post `
        -Headers @{"X-API-Key"=$apikey} `
        -Body ($body | ConvertTo-Json -Compress) `
        -ContentType "application/json"
    Write-Host "Reponse bridge :"
    $r | Format-List | Out-String | Write-Host
} catch {
    Write-Host "ERREUR :"
    Write-Host $_.Exception.Message
    if ($_.ErrorDetails) { Write-Host $_.ErrorDetails.Message }
}
