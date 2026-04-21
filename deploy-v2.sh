#!/usr/bin/env bash
# Deploy rapide EC2 prod : git push local + git pull EC2 + docker build + systemd restart.
# Cette EC2 tourne via systemd (scalping.service), pas docker-compose.
# Usage : bash deploy-v2.sh
set -euo pipefail

KEY="C:/Users/xav91/Scalping/scalping/scalping-key.pem"
HOST="ec2-user@100.103.107.75"

# Push les commits locaux AVANT le pull distant — sinon l'EC2 ne récupère rien
# et le docker build réutilise le cache de l'ancien react-builder (bundle JS
# identique → toutes les nouvelles features absentes en prod).
echo "=== git push local ==="
git push origin main

ssh -i "$KEY" -o StrictHostKeyChecking=no "$HOST" bash <<'REMOTE'
set -euo pipefail
cd /home/ec2-user/scalping
echo "=== git pull ==="
sudo git pull
echo "=== docker build ==="
sudo docker build -t scalping-radar:latest .
echo "=== systemd restart ==="
sudo systemctl restart scalping
sleep 3
echo "=== service status ==="
sudo systemctl status scalping --no-pager | head -15
echo "=== container status ==="
sudo docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
REMOTE
