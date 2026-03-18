#!/bin/bash
#
# Script de deploiement automatique sur AWS EC2
# Usage: bash deploy/aws-deploy.sh
#
# Prerequis:
#   1. Compte AWS cree
#   2. AWS CLI installee (voir ci-dessous)
#   3. Credentials configurees (voir ci-dessous)
#
set -e

# =====================================================
# CONFIGURATION - Modifie ces valeurs si besoin
# =====================================================
INSTANCE_TYPE="t3.micro"          # Free tier eligible
REGION="eu-west-3"                # Paris (change si tu preferes)
KEY_NAME="scalping-key"           # Nom de la paire de cles
SG_NAME="scalping-sg"             # Nom du security group
INSTANCE_NAME="scalping-radar"    # Nom de l'instance
REPO_URL="https://github.com/xav916/scalping.git"

# =====================================================
# COULEURS
# =====================================================
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[ERREUR]${NC} $1"; exit 1; }

# =====================================================
# VERIFICATIONS
# =====================================================
echo ""
echo "========================================"
echo "  SCALPING RADAR - Deploiement AWS EC2"
echo "========================================"
echo ""

# Verifier AWS CLI
if ! command -v aws &> /dev/null; then
    echo ""
    warn "AWS CLI n'est pas installee."
    echo ""
    echo "Pour l'installer :"
    echo ""
    echo "  Linux/Mac :"
    echo "    curl \"https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip\" -o awscliv2.zip"
    echo "    unzip awscliv2.zip && sudo ./aws/install"
    echo ""
    echo "  Mac (alternative) :"
    echo "    brew install awscli"
    echo ""
    echo "  Windows :"
    echo "    Telecharge https://awscli.amazonaws.com/AWSCLIV2.msi"
    echo ""
    exit 1
fi
ok "AWS CLI installee ($(aws --version 2>&1 | head -1))"

# Verifier credentials
if ! aws sts get-caller-identity &> /dev/null; then
    echo ""
    warn "AWS CLI n'est pas configuree avec tes credentials."
    echo ""
    echo "Etapes :"
    echo "  1. Va sur https://console.aws.amazon.com"
    echo "  2. Clique sur ton nom en haut a droite > 'Security credentials'"
    echo "  3. Section 'Access keys' > 'Create access key'"
    echo "  4. Lance cette commande et colle tes cles :"
    echo ""
    echo "     aws configure"
    echo ""
    echo "     AWS Access Key ID:     <ta-cle>"
    echo "     AWS Secret Access Key: <ton-secret>"
    echo "     Default region name:   ${REGION}"
    echo "     Default output format: json"
    echo ""
    echo "  5. Relance ce script : bash deploy/aws-deploy.sh"
    echo ""
    exit 1
fi
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ok "Connecte au compte AWS: ${ACCOUNT_ID}"

# Configurer la region
export AWS_DEFAULT_REGION="${REGION}"
info "Region: ${REGION}"

# =====================================================
# ETAPE 1 : Creer la paire de cles SSH
# =====================================================
echo ""
info "Etape 1/5 : Paire de cles SSH..."

KEY_FILE="${HOME}/.ssh/${KEY_NAME}.pem"
mkdir -p "${HOME}/.ssh"

if aws ec2 describe-key-pairs --key-names "${KEY_NAME}" &> /dev/null; then
    if [ -f "${KEY_FILE}" ]; then
        ok "Paire de cles '${KEY_NAME}' existe deja"
    else
        warn "La cle '${KEY_NAME}' existe sur AWS mais pas en local."
        warn "Suppression de l'ancienne cle sur AWS..."
        aws ec2 delete-key-pair --key-name "${KEY_NAME}"
        aws ec2 create-key-pair \
            --key-name "${KEY_NAME}" \
            --query 'KeyMaterial' \
            --output text > "${KEY_FILE}"
        chmod 400 "${KEY_FILE}"
        ok "Nouvelle paire de cles creee: ${KEY_FILE}"
    fi
else
    aws ec2 create-key-pair \
        --key-name "${KEY_NAME}" \
        --query 'KeyMaterial' \
        --output text > "${KEY_FILE}"
    chmod 400 "${KEY_FILE}"
    ok "Paire de cles creee: ${KEY_FILE}"
fi

# =====================================================
# ETAPE 2 : Creer le Security Group
# =====================================================
echo ""
info "Etape 2/5 : Security Group..."

# Recuperer le VPC par defaut
VPC_ID=$(aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" --query 'Vpcs[0].VpcId' --output text)
if [ "${VPC_ID}" = "None" ] || [ -z "${VPC_ID}" ]; then
    error "Pas de VPC par defaut. Cree-en un dans la console AWS."
fi

# Creer ou recuperer le security group
SG_ID=$(aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=${SG_NAME}" "Name=vpc-id,Values=${VPC_ID}" \
    --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null)

if [ "${SG_ID}" = "None" ] || [ -z "${SG_ID}" ]; then
    SG_ID=$(aws ec2 create-security-group \
        --group-name "${SG_NAME}" \
        --description "Scalping Radar - SSH + HTTP" \
        --vpc-id "${VPC_ID}" \
        --query 'GroupId' --output text)

    # SSH depuis partout (tu peux restreindre a ton IP plus tard)
    aws ec2 authorize-security-group-ingress \
        --group-id "${SG_ID}" \
        --protocol tcp --port 22 --cidr 0.0.0.0/0 > /dev/null

    # HTTP depuis partout
    aws ec2 authorize-security-group-ingress \
        --group-id "${SG_ID}" \
        --protocol tcp --port 80 --cidr 0.0.0.0/0 > /dev/null

    ok "Security Group cree: ${SG_ID} (SSH + HTTP ouverts)"
else
    ok "Security Group existe deja: ${SG_ID}"
fi

# =====================================================
# ETAPE 3 : Trouver l'AMI Ubuntu
# =====================================================
echo ""
info "Etape 3/5 : Recherche AMI Ubuntu..."

AMI_ID=$(aws ec2 describe-images \
    --owners 099720109477 \
    --filters \
        "Name=name,Values=ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*" \
        "Name=state,Values=available" \
    --query 'Images | sort_by(@, &CreationDate) | [-1].ImageId' \
    --output text)

if [ "${AMI_ID}" = "None" ] || [ -z "${AMI_ID}" ]; then
    # Fallback : chercher avec ssd au lieu de ssd-gp3
    AMI_ID=$(aws ec2 describe-images \
        --owners 099720109477 \
        --filters \
            "Name=name,Values=ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*" \
            "Name=state,Values=available" \
        --query 'Images | sort_by(@, &CreationDate) | [-1].ImageId' \
        --output text)
fi

if [ "${AMI_ID}" = "None" ] || [ -z "${AMI_ID}" ]; then
    error "Impossible de trouver une AMI Ubuntu. Verifie ta region (${REGION})."
fi
ok "AMI Ubuntu: ${AMI_ID}"

# =====================================================
# ETAPE 4 : Lancer l'instance EC2
# =====================================================
echo ""
info "Etape 4/5 : Lancement de l'instance EC2..."

# Verifier si une instance scalping existe deja
EXISTING_ID=$(aws ec2 describe-instances \
    --filters \
        "Name=tag:Name,Values=${INSTANCE_NAME}" \
        "Name=instance-state-name,Values=running,pending" \
    --query 'Reservations[0].Instances[0].InstanceId' \
    --output text 2>/dev/null)

if [ "${EXISTING_ID}" != "None" ] && [ -n "${EXISTING_ID}" ]; then
    warn "Une instance '${INSTANCE_NAME}' tourne deja: ${EXISTING_ID}"
    EXISTING_IP=$(aws ec2 describe-instances \
        --instance-ids "${EXISTING_ID}" \
        --query 'Reservations[0].Instances[0].PublicIpAddress' \
        --output text)
    echo ""
    ok "Dashboard deja accessible sur http://${EXISTING_IP}"
    echo ""
    echo "Pour te connecter en SSH :"
    echo "  ssh -i ${KEY_FILE} ubuntu@${EXISTING_IP}"
    echo ""
    echo "Pour terminer et relancer :"
    echo "  aws ec2 terminate-instances --instance-ids ${EXISTING_ID}"
    echo "  bash deploy/aws-deploy.sh"
    echo ""
    exit 0
fi

# User data : script d'installation automatique au demarrage
USER_DATA=$(cat <<'USERDATA'
#!/bin/bash
set -e
exec > /var/log/scalping-setup.log 2>&1
echo "=== Debut de l'installation ==="

# Mise a jour
apt update && apt upgrade -y

# Dependances
apt install -y python3.11 python3.11-venv python3-pip nginx git

# Cloner le projet
cd /home/ubuntu
sudo -u ubuntu git clone REPO_PLACEHOLDER scalping
cd scalping

# Environnement Python
sudo -u ubuntu python3.11 -m venv venv
sudo -u ubuntu bash -c 'source venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt'

# Configuration
sudo -u ubuntu cp .env.example .env

# Service systemd
cp deploy/scalping.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable scalping
systemctl start scalping

# Nginx
cp deploy/nginx.conf /etc/nginx/sites-available/scalping
ln -sf /etc/nginx/sites-available/scalping /etc/nginx/sites-enabled/scalping
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo "=== Installation terminee ==="
USERDATA
)

# Injecter l'URL du repo
USER_DATA="${USER_DATA//REPO_PLACEHOLDER/${REPO_URL}}"

# Encoder en base64
USER_DATA_B64=$(echo "${USER_DATA}" | base64 -w 0)

# Lancer l'instance
INSTANCE_ID=$(aws ec2 run-instances \
    --image-id "${AMI_ID}" \
    --instance-type "${INSTANCE_TYPE}" \
    --key-name "${KEY_NAME}" \
    --security-group-ids "${SG_ID}" \
    --user-data "${USER_DATA_B64}" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${INSTANCE_NAME}}]" \
    --query 'Instances[0].InstanceId' \
    --output text)

ok "Instance lancee: ${INSTANCE_ID}"

# =====================================================
# ETAPE 5 : Attendre et afficher les infos
# =====================================================
echo ""
info "Etape 5/5 : En attente du demarrage..."

aws ec2 wait instance-running --instance-ids "${INSTANCE_ID}"
ok "Instance en cours d'execution"

# Recuperer l'IP publique
PUBLIC_IP=$(aws ec2 describe-instances \
    --instance-ids "${INSTANCE_ID}" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text)

echo ""
echo "========================================"
echo -e "  ${GREEN}DEPLOIEMENT REUSSI !${NC}"
echo "========================================"
echo ""
echo "  Instance : ${INSTANCE_ID}"
echo "  IP       : ${PUBLIC_IP}"
echo "  Region   : ${REGION}"
echo ""
echo -e "  ${YELLOW}Dashboard : http://${PUBLIC_IP}${NC}"
echo ""
echo "  (L'installation de l'app prend ~2-3 minutes.)"
echo "  (Si le dashboard ne charge pas, attends un peu.)"
echo ""
echo "  Commandes utiles :"
echo "  ──────────────────"
echo "  SSH :           ssh -i ${KEY_FILE} ubuntu@${PUBLIC_IP}"
echo "  Logs install :  ssh -i ${KEY_FILE} ubuntu@${PUBLIC_IP} 'cat /var/log/scalping-setup.log'"
echo "  Logs app :      ssh -i ${KEY_FILE} ubuntu@${PUBLIC_IP} 'sudo journalctl -u scalping -f'"
echo "  Redemarrer :    ssh -i ${KEY_FILE} ubuntu@${PUBLIC_IP} 'sudo systemctl restart scalping'"
echo "  Config .env :   ssh -i ${KEY_FILE} ubuntu@${PUBLIC_IP} 'nano /home/ubuntu/scalping/.env'"
echo ""
echo "  Pour detruire l'instance :"
echo "  aws ec2 terminate-instances --instance-ids ${INSTANCE_ID}"
echo ""
