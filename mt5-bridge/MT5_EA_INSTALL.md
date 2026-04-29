# Installation de Scalping Radar EA dans MT5

> **5 minutes**, aucun code à exécuter, fonctionne sur Windows et Mac (MT5 a
> une version Mac officielle Pepperstone).

## Prérequis

- MT5 Desktop installé et connecté à ton compte broker (démo recommandé pour
  les premiers tests)
- Tu as un compte Premium sur https://app.scalping-radar.online
- Tu as ton api_key (Settings → Auto-exec MT5 → "Voir mon api_key")

## Étape 1 — Récupérer le fichier EA

Soit :
- Depuis le SaaS : Settings → Auto-exec MT5 → "Télécharger ScalpingRadarEA.ex5"
- Depuis GitHub : https://github.com/xav916/scalping/blob/main/mt5-bridge/ScalpingRadarEA.mq5
  (tu devras le compiler dans MetaEditor → menu File → Compile)

## Étape 2 — Drop dans MT5

1. Dans MT5, menu File → **Open Data Folder**
2. Une fenêtre Explorer s'ouvre — navigue dans `MQL5/Experts/`
3. Glisse `ScalpingRadarEA.ex5` dans ce dossier
4. Retour à MT5, F5 ou clic droit "Refresh" sur le panel Navigator (Ctrl+N
   si pas visible)
5. Dans Navigator → Expert Advisors → tu vois "ScalpingRadarEA"

## Étape 3 — Autoriser les requêtes HTTP du EA

MT5 bloque les requêtes externes par défaut. Pour autoriser :

1. **Tools → Options → Expert Advisors**
2. Coche **"Allow WebRequest for listed URL"**
3. Clic dans la zone, ajoute `https://app.scalping-radar.online`
4. OK

## Étape 4 — Drag l'EA sur un chart

1. Drag l'EA depuis Navigator vers n'importe quel chart (peu importe la
   pair, il fonctionne en background sur tous les ordres reçus)
2. Une popup d'inputs s'ouvre :
   - **InpApiKey** : ton api_key (copy-paste depuis Settings)
   - **InpServerUrl** : `https://app.scalping-radar.online` (laisse défaut)
   - **InpPollingIntervalSec** : 30 (peut descendre à 10 si besoin de réactivité)
   - **InpDefaultLot** : 0.01 (taille fixe pour V1, sizing dynamique en V2)
   - **InpMagicNumber** : 20260429 (peut laisser défaut, identifie tes
     trades EA dans History)
   - **InpDeviationPoints** : 20 (slippage max accepté)
   - **InpDryRun** : false (mettre true au tout début pour tester sans
     passer d'ordres réels)
3. Onglet "Common" → coche **Allow Algo Trading** + **Allow live trading**
4. OK

## Étape 5 — Activer AutoTrading

Dans la barre d'outils MT5, clic sur le bouton **AutoTrading** (ou Ctrl+E).
Il doit passer **vert**. C'est le master-switch global de MT5 — sans ça
aucun EA ne peut trader.

## Vérifier que ça tourne

Onglet **Experts** en bas de MT5 (à côté de Trade, History, etc.) → tu
dois voir des logs type :

```
ScalpingRadarEA initialized — server=https://app.scalping-radar.online polling=30s default_lot=0.01 magic=20260429 dry_run=false
```

Et toutes les 10 minutes :

```
ScalpingRadarEA alive — polls=20 exec=0 fail=0
```

Quand un ordre est exécuté :

```
ScalpingRadarEA order_id=42 EXECUTED ticket=123456789 EURUSD buy
```

## Arrêter l'EA

- **Temporairement** : décoche AutoTrading (bouton rouge)
- **Définitivement** : clic droit sur l'EA dans le chart → **Remove**
- **Côté SaaS** : Settings → Auto-exec MT5 → "Désactiver" (le SaaS arrête
  d'enqueuer les ordres ; même si l'EA tourne il ne reçoit plus rien)

## Troubleshooting

### "ERREUR WebRequest : URL non whitelistée"

Tu n'as pas fait Étape 3. Tools → Options → Expert Advisors → ajoute
`https://app.scalping-radar.online` dans la liste.

### "HttpGet 401 — api_key invalide"

Vérifie ton api_key dans Settings → Auto-exec MT5. Doit être ≥ 16 chars.

### "HttpGet 403 — Premium tier requis"

Ton compte n'est pas Premium. Subscribe via /pricing ou contacte l'admin.

### L'EA tourne mais 0 ordre depuis 1h

C'est probablement normal — le radar génère un setup éligible quand le
scoring le décide, pas en continu. Vérifie sur le dashboard SaaS si des
setups sont générés sur tes paires watchlist.

### "OrderSend FAILED retcode=10016"

`INVALID_STOPS` — le SL ou TP est trop proche du prix actuel. Le SaaS
filtre déjà ça en amont (`min_sl_distance_pct`), si tu vois cette erreur
c'est probablement un timing slip. Skip et attends le prochain setup.

## Sécurité

- L'api_key transite en HTTPS uniquement
- L'EA ne peut PAS placer d'ordre au-delà de `InpDefaultLot` (0.01 par défaut)
- L'EA ne peut PAS toucher aux positions ouvertes manuellement (magic_number
  différent → ignoré)
- Tu peux désactiver AutoTrading à tout moment depuis MT5
- Côté SaaS, le toggle "auto_exec_enabled" coupe l'enqueuing sans rien
  toucher côté MT5
