#!/bin/bash
# Script d'installation sur une instance EC2 Ubuntu
# Usage: ssh ubuntu@<IP> 'bash -s' < deploy/setup-ec2.sh

set -e

echo "=== Mise a jour du systeme ==="
sudo apt update && sudo apt upgrade -y

echo "=== Installation des dependances ==="
sudo apt install -y python3.11 python3.11-venv python3-pip nginx git

echo "=== Clone du projet ==="
cd /home/ubuntu
if [ -d "scalping" ]; then
    cd scalping && git pull
else
    git clone https://github.com/xav916/scalping.git
    cd scalping
fi

echo "=== Creation de l'environnement virtuel ==="
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "=== Configuration ==="
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo ">>> IMPORTANT: Edite /home/ubuntu/scalping/.env pour configurer tes cles API"
    echo ">>>   nano /home/ubuntu/scalping/.env"
    echo ""
fi

echo "=== Installation du service systemd ==="
sudo cp deploy/scalping.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable scalping
sudo systemctl start scalping

echo "=== Configuration Nginx ==="
sudo cp deploy/nginx.conf /etc/nginx/sites-available/scalping
sudo ln -sf /etc/nginx/sites-available/scalping /etc/nginx/sites-enabled/scalping
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

echo ""
echo "=== Installation terminee ! ==="
echo "Dashboard accessible sur http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo '<IP_PUBLIQUE>'):80"
echo ""
echo "Commandes utiles :"
echo "  sudo systemctl status scalping    # Voir le statut"
echo "  sudo journalctl -u scalping -f    # Voir les logs"
echo "  sudo systemctl restart scalping   # Redemarrer"
