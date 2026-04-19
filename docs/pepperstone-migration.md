# Migration bridge MetaQuotes-Demo → Pepperstone-Demo

**Date** : 2026-04-19
**Motif** : passer à un broker multi-assets (forex + crypto + indices + commodities) pour auto-trader toutes les classes détectées par le radar.

---

## Nouveau compte

| Propriété | Valeur |
|---|---|
| Broker | Pepperstone (FCA UK + CySEC + ASIC) |
| Serveur | `PepperstoneUK-Demo` (mt5-demo02.pepperstone.com) |
| Login | 62119130 |
| Mot de passe | *dans C:\Scalping\mt5-bridge\.env (jamais commité)* |
| Devise | EUR |
| Levier | 1:30 |
| Type | Razor demo (raw spread + commission) |

## Backup existant

Le `.env` MetaQuotes-Demo est sauvegardé dans `C:\Scalping\mt5-bridge\.env.metaquotes-backup-20260419` au cas où.

## Actions à exécuter par l'utilisateur

### 1) Télécharger et installer MT5 Pepperstone

Pepperstone distribue une version personnalisée de MT5 :
https://pepperstone.com/en/trading-platforms/metatrader-5/

- Télécharge `mt5-pepperstone.exe`
- Installe-le à côté de MT5 officiel (chemin différent, ex : `C:\Program Files\MetaTrader 5 Pepperstone\`)
- À la 1ère ouverture, choisir **File > Login to Trade Account**
- Saisir :
  - Login : `62119130`
  - Password : *(celui donné en chat)*
  - Server : **PepperstoneUK-Demo**
- **Cocher "Save account information"** (important pour l'auto-login au boot)
- Activer le bouton **"AutoTrading"** (doit être vert)

### 2) Couper le bridge actuel

Dans la fenêtre PowerShell qui fait tourner le bridge : **Ctrl+C**.

### 3) Mettre à jour le path MT5 dans start_all.ps1 (si nouveau chemin)

Si tu as installé Pepperstone MT5 à un autre endroit que `C:\Program Files\MetaTrader 5\`, édite `C:\Scalping\start_all.ps1` ligne 22 :

```powershell
Start-Process "C:\Program Files\MetaTrader 5 Pepperstone\terminal64.exe"
```

### 4) Relancer le bridge

```powershell
cd C:\Scalping\mt5-bridge
.\venv\Scripts\Activate.ps1
python bridge.py
```

**Logs attendus** :

```
MT5 connected balance=XXX EUR login=62119130 server=PepperstoneUK-Demo
Running on http://0.0.0.0:8787
```

Si erreur `10013 Invalid account` → vérifier qu'AutoTrading est actif dans MT5 Pepperstone, que le login est bien sélectionné ("File > Login to Trade Account").

### 5) Autoriser les nouveaux asset classes côté EC2

Sur l'EC2, ajouter la nouvelle variable au `.env` et redémarrer :

```bash
# Autoriser forex + metal + crypto + indices + energy pour l'auto-exec
echo "MT5_BRIDGE_ALLOWED_ASSET_CLASSES=forex,metal,crypto,equity_index,energy" | sudo tee -a /opt/scalping/.env

sudo systemctl restart scalping
```

### 6) Vérifier la nouvelle connectivité

Depuis ton PC :

```powershell
curl.exe -s -H "X-API-Key: d_2xWPHA12KP98G-uV_LFTXSEsXH1Udo" http://100.122.188.8:8787/health
curl.exe -s -H "X-API-Key: d_2xWPHA12KP98G-uV_LFTXSEsXH1Udo" http://100.122.188.8:8787/account
```

Doit renvoyer `"ok": true` + `"balance": XXX` + `"server": "PepperstoneUK-Demo"`.

Et vérifier que les nouveaux symboles sont accessibles :

```powershell
$r = curl.exe -s -H "X-API-Key: d_2xWPHA12KP98G-uV_LFTXSEsXH1Udo" http://100.122.188.8:8787/symbols | ConvertFrom-Json
$r.symbols | Where-Object { $_ -match "BTC|ETH|SPX|NDX|WTI|XAG" }
```

Doit lister BTCUSD, ETHUSD, SPX500, NAS100, etc. (les noms exacts peuvent varier).

### 7) Ajuster le MT5_SYMBOL_MAP si nécessaire

Pepperstone utilise probablement des noms légèrement différents de Twelve Data. Exemples typiques :

| Twelve Data (dans WATCHED_PAIRS) | Pepperstone MT5 (probable) |
|---|---|
| BTC/USD | BTCUSD |
| ETH/USD | ETHUSD |
| XAU/USD | XAUUSD |
| XAG/USD | XAGUSD |
| WTI/USD | WTI ou USOIL |
| SPX | SPX500 ou US500 |
| NDX | NAS100 ou US100 |
| EUR/USD | EURUSD |

Quand tu auras confirmé les noms exacts via la commande ci-dessus, mettre à jour sur EC2 :

```bash
echo 'MT5_SYMBOL_MAP="XAU/USD:XAUUSD,EUR/USD:EURUSD,GBP/USD:GBPUSD,USD/JPY:USDJPY,EUR/GBP:EURGBP,USD/CHF:USDCHF,AUD/USD:AUDUSD,USD/CAD:USDCAD,EUR/JPY:EURJPY,GBP/JPY:GBPJPY,BTC/USD:BTCUSD,ETH/USD:ETHUSD,XAG/USD:XAGUSD,WTI/USD:USOIL,SPX:SPX500,NDX:NAS100"' | sudo tee -a /opt/scalping/.env
sudo systemctl restart scalping
```

Les mappings qu'il faut confirmer côté Pepperstone :
- Oil : `USOIL` ou `WTI` ou `WTIUSD` ?
- Indices : `SPX500` vs `US500` vs `S&P500` ?
- Crypto : suffixe `.i` parfois sur compte islamic, sinon vanille

### 8) Observer 1ère journée

- **Dashboard** : https://scalping-radar.duckdns.org → tu devrais voir les setups sur les nouvelles classes
- **Bridge logs** : surveiller `bridge.log` sur ton PC pour les filled/rejected
- **Telegram** : push setups sur toutes les classes confondues

### 9) Cap MAX_LOT si crypto actif

Crypto a une valeur notionnelle bien plus grosse que du forex. 0.1 lot BTC = 0.1 BTC ≈ $6000 notionnel, ce qui peut déclencher trop de risque. Pour sécuriser, garder `MAX_LOT=0.01` pour crypto en v1.

Après quelques trades de validation, on pourra implémenter un MAX_LOT par asset class dans une prochaine session.

## Rollback si problème

1. Arrêter le bridge (Ctrl+C)
2. Restaurer l'ancien .env :
   ```powershell
   copy C:\Scalping\mt5-bridge\.env.metaquotes-backup-20260419 C:\Scalping\mt5-bridge\.env
   ```
3. Relancer MT5 MetaQuotes (pas Pepperstone) et le bridge

## Checklist finale

- [ ] MT5 Pepperstone installé, connecté, AutoTrading vert
- [ ] Bridge .env mis à jour (déjà fait par Claude)
- [ ] Bridge relancé, logs `server=PepperstoneUK-Demo` visibles
- [ ] EC2 `MT5_BRIDGE_ALLOWED_ASSET_CLASSES=forex,metal,crypto,equity_index,energy` ajouté
- [ ] EC2 `MT5_SYMBOL_MAP` mis à jour avec les noms Pepperstone
- [ ] `/health` + `/account` OK via Tailscale
- [ ] `/symbols` montre BTC, SPX, etc.
