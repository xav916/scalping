#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/scalping"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Ce script doit etre lance avec sudo ou en root."
  exit 1
fi

apt-get update
apt-get install -y docker.io nginx git curl rsync
systemctl enable --now docker

mkdir -p "${APP_DIR}"
rsync -a --delete \
  --exclude '.git' \
  --exclude '__pycache__' \
  --exclude '.venv' \
  --exclude '.pytest_cache' \
  "${REPO_DIR}/" "${APP_DIR}/"

cd "${APP_DIR}"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Fichier .env cree depuis .env.example. Pense a renseigner TWELVEDATA_API_KEY si besoin."
fi

docker build -t scalping-radar:latest .

cp deploy/scalping.service /etc/systemd/system/scalping.service
cp deploy/nginx.conf /etc/nginx/sites-available/scalping
ln -sf /etc/nginx/sites-available/scalping /etc/nginx/sites-enabled/scalping
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl restart nginx

systemctl daemon-reload
systemctl enable scalping.service
systemctl restart scalping.service

systemctl --no-pager --full status scalping.service || true

echo
PUBLIC_IP=$(curl --connect-timeout 2 -s http://169.254.169.254/latest/meta-data/public-ipv4 || true)
echo "Deployment termine. Ouvre http://${PUBLIC_IP:-<IP_EC2>}"