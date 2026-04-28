# MT5 Bridge — paper-trade (phase 1)

Serveur HTTP local qui pilote MT5 Desktop Windows depuis Python.
Pour l'instant en **mode paper-trade uniquement** : reçoit des ordres,
les loggue, **n'envoie rien au broker**.

## Installation (déjà fait si tu lis ceci)

```powershell
cd C:\Scalping\mt5-bridge
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Lancer

1. **MT5 Desktop Windows doit être lancé et connecté** au compte
   (barre d'état en bas = pas "Pas de connexion").
2. Dans PowerShell avec le venv actif :
   ```powershell
   python bridge.py
   ```

Au démarrage, le bridge affiche :
- La version du package MT5
- Le login / serveur
- La clé d'API (copier la ligne `BRIDGE_API_KEY=...` dans `.env` si elle
  est autogénérée, sinon elle changera à chaque démarrage)
- L'URL d'écoute (`http://127.0.0.1:8787` par défaut)

## Tester

Dans un autre terminal (venv pas nécessaire pour les curl) :

```powershell
# 1. Ping public
curl http://127.0.0.1:8787/health

# 2. État du compte (remplace <KEY> par ta BRIDGE_API_KEY)
curl -H "X-API-Key: <KEY>" http://127.0.0.1:8787/account

# 3. Symboles dispo chez ton broker
curl -H "X-API-Key: <KEY>" http://127.0.0.1:8787/symbols

# 4. Positions ouvertes
curl -H "X-API-Key: <KEY>" http://127.0.0.1:8787/positions

# 5. Ordre PAPER (simulé, rien envoyé)
curl -X POST -H "X-API-Key: <KEY>" -H "Content-Type: application/json" `
  -d '{"pair":"EUR/USD","direction":"buy","entry":1.0823,"sl":1.0818,"tp":1.0833,"lots":0.01,"comment":"test"}' `
  http://127.0.0.1:8787/order
```

## Endpoints

| Méthode | Route | Auth | Effet |
|---|---|---|---|
| GET | `/health` | non | État du bridge + MT5 |
| GET | `/account` | oui | Balance, equity, positions count |
| GET | `/symbols` | oui | Symboles dispo (filtré forex+métaux) |
| GET | `/positions` | oui | Positions ouvertes |
| POST | `/order` | oui | Place un ordre (paper ou live) |
| POST | `/kill` | oui | Ferme toutes les positions (paper ou live) |

## Passer en LIVE plus tard

**Ne pas** mettre `PAPER_MODE=false` maintenant. Le code LIVE n'est pas
encore implémenté — le bridge refusera de placer l'ordre avec une erreur
501 explicite.

L'implémentation LIVE viendra dans la phase 2 avec les rails de sécurité :
- Max positions simultanées
- Max daily loss absolu → disable auto
- Dédup idempotency key
- Kill-switch complet (send CLOSE orders à MT5)
- Audit SQLite
- Trading hours
- Mode confirmation manuel (envoyer sur Telegram → user clique bouton
  "Approuver" → l'ordre part)

## Sécurité

- `.env` est **gitignored**, ne le committe jamais.
- Le bridge écoute sur `127.0.0.1` uniquement — pas exposé sur le réseau.
- Pour accès depuis l'EC2 plus tard : Tailscale ou Cloudflare Tunnel
  (pas d'ouverture de port direct).
- Le mot de passe MT5 démo est dans `.env` local uniquement.
