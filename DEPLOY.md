# Deploiement AWS EC2 (HTTPS gratuit via DuckDNS)

Ce projet se deploie sur **AWS EC2** avec **Docker + Nginx + Let's Encrypt** et un domaine gratuit **DuckDNS**.

## Pre-requis

1. Un compte **DuckDNS** (gratuit) : https://www.duckdns.org
2. Une instance **AWS EC2**

## 1. Configurer DuckDNS (2 minutes)

1. Aller sur https://www.duckdns.org
2. Se connecter avec GitHub, Google, Reddit ou Twitter
3. Creer un sous-domaine (ex: `scalping-radar`) → vous obtiendrez `scalping-radar.duckdns.org`
4. **Ne pas remplir l'IP** — le script la mettra a jour automatiquement
5. **Copier le token** affiche en haut de la page (format: `abc12345-6789-...`)

## 2. Creer l'instance EC2

Configuration recommandee :

- **AMI** : Ubuntu 24.04 LTS
- **Type** : `t3.micro` (free tier si eligible)
- **Storage** : 8 a 20 Go
- **Security Group** :
  - `22/tcp` — SSH
  - `80/tcp` — HTTP (redirection vers HTTPS)
  - `443/tcp` — HTTPS

## 3. Se connecter a la machine

```bash
ssh -i scalping-key.pem ubuntu@<IP_PUBLIC_EC2>
```

## 4. Recuperer le projet

```bash
git clone <URL_DU_REPO>
cd scalping
```

## 5. Lancer l'installation

```bash
sudo bash deploy/setup-ec2.sh scalping-radar.duckdns.org VOTRE_TOKEN_DUCKDNS
```

Le script va automatiquement :

1. Mettre a jour l'IP DuckDNS avec l'IP de la machine
2. Installer un cron de mise a jour IP (toutes les 5 min)
3. Installer Docker, Nginx, Certbot + plugin DNS DuckDNS
4. Copier le projet dans `/opt/scalping`
5. Creer `.env` si absent (avec DOMAIN et token sauvegardes)
6. Builder l'image Docker
7. Obtenir un certificat SSL via **DNS-01 challenge** (pas besoin du port 80)
8. Activer la config Nginx HTTPS avec tous les headers de securite
9. Installer le renouvellement automatique SSL (cron 2x/jour)
10. Demarrer le service systemd

## 6. Verifier

```bash
# Status du service
sudo systemctl status scalping.service

# Logs en temps reel
sudo journalctl -u scalping.service -f

# Verifier le certificat SSL
curl -vI https://scalping-radar.duckdns.org 2>&1 | grep 'SSL certificate'
```

## 7. Ouvrir l'application

```
https://scalping-radar.duckdns.org
```

HTTP redirige automatiquement vers HTTPS.

## Mise a jour apres un nouveau commit

```bash
cd ~/scalping
git pull
sudo bash deploy/setup-ec2.sh
```

Le domaine et le token sont lus depuis `.env`, pas besoin de les re-specifier.

## Comment ca marche

### DuckDNS (DNS gratuit)

```
scalping-radar.duckdns.org → IP de votre EC2
```

- Un cron met a jour l'IP toutes les 5 minutes
- Si l'IP EC2 change (reboot, elastic IP...), le DNS suit automatiquement

### Let's Encrypt (certificat SSL gratuit)

```
Certbot → DNS-01 challenge via DuckDNS API → certificat SSL
```

- Le challenge DNS-01 ne necessite pas le port 80 ouvert
- Le plugin `certbot-dns-duckdns` gere tout automatiquement
- Renouvellement auto tous les 60-90 jours via cron

### Securite HTTPS

| Protection | Detail |
|---|---|
| **TLS 1.2 / 1.3** | Protocoles obsoletes (TLS 1.0, 1.1, SSL) desactives |
| **HSTS** | Force HTTPS pendant 1 an (`Strict-Transport-Security`) |
| **X-Frame-Options** | Empeche l'inclusion dans des iframes (`DENY`) |
| **X-Content-Type-Options** | Empeche le MIME sniffing (`nosniff`) |
| **X-XSS-Protection** | Protection XSS navigateur |
| **OCSP Stapling** | Verification certificat optimisee |
| **HTTP → HTTPS** | Redirection 301 automatique |
| **WSS** | WebSocket securise (automatique via le proxy HTTPS) |

## Variables d'environnement

Fichier `/opt/scalping/.env` :

| Variable | Description |
|---|---|
| `DOMAIN` | Sous-domaine DuckDNS complet (ex: `scalping-radar.duckdns.org`) |
| `DUCKDNS_TOKEN` | Token DuckDNS pour la mise a jour IP et le certificat SSL |
| `HOST` | Adresse d'ecoute FastAPI (defaut: `0.0.0.0`) |
| `PORT` | Port FastAPI (defaut: `8000`) |
| `TWELVEDATA_API_KEY` | Cle API pour les donnees de marche reelles |
| `TRADING_CAPITAL` | Capital de trading pour le money management |
| `RISK_PER_TRADE_PCT` | % du capital risque par trade |
| `MIN_CONFIDENCE_SCORE` | Score minimum pour afficher un setup (0-100) |
| `WATCHED_PAIRS` | Paires surveillees |

## Depannage

### Le certificat SSL echoue

```bash
# Verifier que DuckDNS repond bien
curl -s "https://www.duckdns.org/update?domains=scalping-radar&token=VOTRE_TOKEN&ip="

# Re-tenter manuellement
sudo /opt/certbot-duckdns/bin/certbot certonly \
  --authenticator dns-duckdns \
  --dns-duckdns-credentials /etc/letsencrypt/duckdns.ini \
  --dns-duckdns-propagation-seconds 120 \
  --domain scalping-radar.duckdns.org
```

### L'IP n'est pas a jour

```bash
# Forcer la mise a jour
curl -s "https://www.duckdns.org/update?domains=scalping-radar&token=VOTRE_TOKEN&ip="

# Verifier le cron
crontab -l | grep duckdns
```

### Renouveler le certificat manuellement

```bash
sudo /opt/certbot-duckdns/bin/certbot renew --force-renewal
sudo systemctl reload nginx
```
