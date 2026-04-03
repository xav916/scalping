#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/scalping"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Ce script doit etre lance avec sudo ou en root."
  exit 1
fi

# ─── Detection du gestionnaire de paquets ───────────────────────────
if command -v dnf &>/dev/null; then
  PKG_MGR="dnf"
  PKG_INSTALL="dnf install -y"
elif command -v apt-get &>/dev/null; then
  PKG_MGR="apt"
  PKG_INSTALL="apt-get install -y"
else
  echo "ERREUR: Ni dnf ni apt-get trouve. OS non supporte."
  exit 1
fi
echo "Gestionnaire de paquets: ${PKG_MGR}"

# ─── Parametres ─────────────────────────────────────────────────────
DOMAIN="${1:-}"
DUCKDNS_TOKEN="${2:-}"

# Lire depuis .env si deja configure
if [[ -f "${APP_DIR}/.env" ]]; then
  [[ -z "${DOMAIN}" ]]        && DOMAIN=$(grep -oP '^DOMAIN=\K.+' "${APP_DIR}/.env" 2>/dev/null || true)
  [[ -z "${DUCKDNS_TOKEN}" ]] && DUCKDNS_TOKEN=$(grep -oP '^DUCKDNS_TOKEN=\K.+' "${APP_DIR}/.env" 2>/dev/null || true)
fi

if [[ -z "${DOMAIN}" || -z "${DUCKDNS_TOKEN}" ]]; then
  echo "Usage: sudo bash deploy/setup-ec2.sh <SOUS-DOMAINE>.duckdns.org <DUCKDNS_TOKEN>"
  echo ""
  echo "  Exemple: sudo bash deploy/setup-ec2.sh scalping-radar.duckdns.org abc12345-6789-..."
  echo ""
  echo "  1. Creer un compte sur https://www.duckdns.org (login GitHub/Google)"
  echo "  2. Creer un sous-domaine (ex: scalping-radar)"
  echo "  3. Copier le token affiche en haut de la page"
  echo "  4. L'IP sera mise a jour automatiquement par ce script"
  exit 1
fi

# Extraire le sous-domaine (scalping-radar depuis scalping-radar.duckdns.org)
DUCKDNS_SUBDOMAIN="${DOMAIN%.duckdns.org}"
DUCKDNS_SUBDOMAIN="${DUCKDNS_SUBDOMAIN%.}"

echo "Domaine:        ${DOMAIN}"
echo "Sous-domaine:   ${DUCKDNS_SUBDOMAIN}"

# ─── Installation des paquets ───────────────────────────────────────
if [[ "${PKG_MGR}" == "dnf" ]]; then
  dnf update -y
  # Amazon Linux 2023 : curl-minimal est pre-installe, ne pas installer curl (conflit)
  ${PKG_INSTALL} docker nginx git rsync python3 python3-pip cronie
  systemctl enable --now docker
  systemctl enable --now crond
  usermod -aG docker ec2-user 2>/dev/null || true
else
  apt-get update
  ${PKG_INSTALL} docker.io nginx git curl rsync python3 python3-pip python3-venv cron
  systemctl enable --now docker
  systemctl enable --now cron
fi

systemctl enable --now nginx

# ─── Mise a jour IP DuckDNS ─────────────────────────────────────────
echo "Mise a jour de l'IP DuckDNS..."
DUCKDNS_RESULT=$(curl -s "https://www.duckdns.org/update?domains=${DUCKDNS_SUBDOMAIN}&token=${DUCKDNS_TOKEN}&ip=")
if [[ "${DUCKDNS_RESULT}" == "OK" ]]; then
  echo "IP DuckDNS mise a jour avec succes."
else
  echo "ERREUR: Echec de la mise a jour DuckDNS (resultat: ${DUCKDNS_RESULT})"
  echo "Verifie le token et le sous-domaine."
  exit 1
fi

# ─── Cron DuckDNS (mise a jour IP toutes les 5 min) ────────────────
DUCKDNS_CRON="*/5 * * * * curl -s 'https://www.duckdns.org/update?domains=${DUCKDNS_SUBDOMAIN}&token=${DUCKDNS_TOKEN}&ip=' > /dev/null 2>&1"
(crontab -l 2>/dev/null | grep -v duckdns.org; echo "${DUCKDNS_CRON}") | crontab -
echo "Cron DuckDNS installe (mise a jour IP toutes les 5 min)."

# ─── Copie du projet ────────────────────────────────────────────────
mkdir -p "${APP_DIR}"
rsync -a --delete \
  --exclude '.git' \
  --exclude '__pycache__' \
  --exclude '.venv' \
  --exclude '.pytest_cache' \
  --exclude 'scalping-key.pem' \
  --exclude '.claude' \
  "${REPO_DIR}/" "${APP_DIR}/"

cd "${APP_DIR}"

# ─── .env ───────────────────────────────────────────────────────────
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Fichier .env cree depuis .env.example."
fi

# Sauvegarder DOMAIN et DUCKDNS_TOKEN dans .env
for VAR_NAME in DOMAIN DUCKDNS_TOKEN; do
  VAR_VAL="${!VAR_NAME}"
  if grep -q "^${VAR_NAME}=" .env 2>/dev/null; then
    sed -i "s|^${VAR_NAME}=.*|${VAR_NAME}=${VAR_VAL}|" .env
  else
    echo "${VAR_NAME}=${VAR_VAL}" >> .env
  fi
done

echo "Pense a renseigner TWELVEDATA_API_KEY dans .env si besoin."

# ─── Docker build ───────────────────────────────────────────────────
docker build -t scalping-radar:latest .

# ─── Certbot + plugin DNS DuckDNS ──────────────────────────────────
CERTBOT_VENV="/opt/certbot-duckdns"
if [[ ! -d "${CERTBOT_VENV}" ]]; then
  python3 -m venv "${CERTBOT_VENV}"
fi
"${CERTBOT_VENV}/bin/pip" install --upgrade pip certbot certbot-dns-duckdns > /dev/null 2>&1
CERTBOT_CMD="${CERTBOT_VENV}/bin/certbot"
echo "Certbot + plugin DNS DuckDNS installes."

# Creer le fichier credentials DuckDNS
DUCKDNS_CREDS="/etc/letsencrypt/duckdns.ini"
mkdir -p /etc/letsencrypt
cat > "${DUCKDNS_CREDS}" <<EOF
dns_duckdns_token = ${DUCKDNS_TOKEN}
EOF
chmod 600 "${DUCKDNS_CREDS}"

# ─── Nginx config HTTP temporaire ──────────────────────────────────
# Determiner le dossier de config Nginx
if [[ -d /etc/nginx/conf.d ]]; then
  NGINX_CONF="/etc/nginx/conf.d/scalping.conf"
  # Amazon Linux utilise conf.d, pas sites-available
  # Supprimer la config par defaut si elle existe
  rm -f /etc/nginx/conf.d/default.conf 2>/dev/null || true
else
  mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled
  NGINX_CONF="/etc/nginx/sites-available/scalping"
fi

cat > "${NGINX_CONF}" <<NGINX_TEMP
server {
    listen 80;
    server_name ${DOMAIN};

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600;
        proxy_send_timeout 3600;
    }
}
NGINX_TEMP

# Lien symbolique pour Ubuntu/Debian
if [[ -d /etc/nginx/sites-enabled ]]; then
  ln -sf /etc/nginx/sites-available/scalping /etc/nginx/sites-enabled/scalping
  rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
fi

nginx -t
systemctl restart nginx

# ─── Certificat SSL Let's Encrypt (DNS-01 via DuckDNS) ─────────────
CERT_DIR="/etc/letsencrypt/live/${DOMAIN}"

if [[ ! -d "${CERT_DIR}" ]]; then
  echo ""
  echo "Obtention du certificat SSL pour ${DOMAIN} (DNS-01 challenge)..."
  echo "Cela peut prendre 1-2 minutes (propagation DNS)..."
  "${CERTBOT_CMD}" certonly \
    --authenticator dns-duckdns \
    --dns-duckdns-credentials "${DUCKDNS_CREDS}" \
    --dns-duckdns-propagation-seconds 60 \
    --domain "${DOMAIN}" \
    --non-interactive \
    --agree-tos \
    --email "scalping-admin@duckdns.org" \
    --no-eff-email
  echo "Certificat SSL obtenu."
else
  echo "Certificat SSL existant pour ${DOMAIN}. Tentative de renouvellement..."
  "${CERTBOT_CMD}" renew --quiet || true
fi

# ─── Nginx config HTTPS definitive ─────────────────────────────────
cat > "${NGINX_CONF}" <<NGINX_SSL
# ─── HTTP → redirige tout vers HTTPS ────────────────────────────────
server {
    listen 80;
    server_name ${DOMAIN};

    location / {
        return 301 https://\$host\$request_uri;
    }
}

# ─── HTTPS ──────────────────────────────────────────────────────────
server {
    listen 443 ssl http2;
    server_name ${DOMAIN};

    # Certificats Let's Encrypt
    ssl_certificate     /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;

    # Protocoles et ciphers securises
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;

    # HSTS — force HTTPS pendant 1 an
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # En-tetes de securite
    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Session SSL
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    # OCSP Stapling
    ssl_stapling on;
    ssl_stapling_verify on;
    resolver 8.8.8.8 8.8.4.4 valid=300s;
    resolver_timeout 5s;

    client_max_body_size 10m;

    # Proxy vers FastAPI
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # WebSocket support (WSS)
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600;
        proxy_send_timeout 3600;
    }
}
NGINX_SSL

nginx -t
systemctl restart nginx

# ─── Renouvellement automatique SSL ────────────────────────────────
RENEW_CRON="0 3,15 * * * ${CERTBOT_CMD} renew --quiet --deploy-hook 'systemctl reload nginx'"
(crontab -l 2>/dev/null | grep -v certbot; echo "${RENEW_CRON}") | crontab -
echo "Cron de renouvellement SSL installe (2x/jour)."

# ─── Service systemd ────────────────────────────────────────────────
cp deploy/scalping.service /etc/systemd/system/scalping.service
systemctl daemon-reload
systemctl enable scalping.service
systemctl restart scalping.service

systemctl --no-pager --full status scalping.service || true

# ─── Resume ─────────────────────────────────────────────────────────
PUBLIC_IP=$(curl --connect-timeout 2 -s http://169.254.169.254/latest/meta-data/public-ipv4 || echo "<IP>")
echo ""
echo "============================================================"
echo "  DEPLOIEMENT HTTPS TERMINE (DuckDNS + Let's Encrypt)"
echo "============================================================"
echo ""
echo "  URL:        https://${DOMAIN}"
echo "  IP EC2:     ${PUBLIC_IP}"
echo "  DuckDNS:    ${DUCKDNS_SUBDOMAIN}.duckdns.org -> ${PUBLIC_IP}"
echo ""
echo "  HTTP -> redirige vers HTTPS automatiquement"
echo "  SSL:  Let's Encrypt (renouvellement auto 2x/jour)"
echo "  IP:   Mise a jour DuckDNS auto (toutes les 5 min)"
echo ""
echo "  Verifier le certificat:"
echo "    curl -vI https://${DOMAIN} 2>&1 | grep 'SSL certificate'"
echo ""
echo "  Logs:"
echo "    sudo journalctl -u scalping.service -f"
echo "============================================================"
