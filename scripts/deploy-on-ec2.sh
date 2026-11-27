#!/bin/bash
# deploy-on-ec2.sh — Déploiement du radar depuis l'EC2 lui-même (fallback).
#
# Utilisation normale : `deploy-v2.sh` depuis Git Bash Windows pousse le code
# via SSH. Mais quand Tailscale est en mode DERP uniquement (cf. incident
# 2026-11-26), SSH ne passe plus et deploy-v2.sh échoue. Ce script fait
# tourner la même séquence directement sur l'EC2, à exécuter depuis :
#   - EC2 Instance Connect (browser-based SSH AWS Console)
#   - Ou toute session shell sur l'EC2 (serial console, etc.)
#
# Ce qu'il fait :
#   1. Clone frais de xav916/scalping@<branche> dans /tmp/scalping-fresh
#   2. Génère deployment_manifest.json (format REM-003)
#   3. docker build -t scalping-radar:latest depuis le clone frais
#   4. Met à jour EXPECTED_GIT_COMMIT dans /opt/scalping/.env
#   5. systemctl restart scalping.service
#   6. Vérifie le container + manifest + image fraîche
#   7. Optionnel : réarmement REM-002 (si --rearm passé)
#
# Préserve :
#   - /opt/scalping/.env (seul EXPECTED_GIT_COMMIT touché)
#   - /opt/scalping/data/* (monté en volume par systemd, pas dans l'image)
#   - Tous les autres volumes systemd
#
# NE PAS utiliser pour MT5 Live. REM-002-LIVE reste verrouillé par design
# depuis l'audit 2026-10-12 (décision Xavier, pas automatisable).

set -euo pipefail

# ─── Config par défaut ─────────────────────────────────────────────────
REPO_URL="${REPO_URL:-https://github.com/xav916/scalping.git}"
BRANCH="${BRANCH:-main}"
WORK_DIR="${WORK_DIR:-/tmp/scalping-fresh}"
PROD_DIR="${PROD_DIR:-/opt/scalping}"
SERVICE="${SERVICE:-scalping.service}"
CONTAINER="${CONTAINER:-scalping-radar}"
IMAGE="${IMAGE:-scalping-radar:latest}"

REARM=0
REARM_MOTIF=""

# ─── Parse args ────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --branch) BRANCH="$2"; shift 2 ;;
    --rearm) REARM=1; shift ;;
    --rearm-motif) REARM_MOTIF="$2"; REARM=1; shift 2 ;;
    -h|--help)
      cat <<EOF
Usage: $0 [options]

Options:
  --branch <nom>          Branche à déployer (défaut: main)
  --rearm                 Réarmer REM-002 après deploy (motif générique)
  --rearm-motif "<text>"  Réarmer avec un motif explicite
  -h, --help              Cette aide

Env vars overridables: REPO_URL, BRANCH, WORK_DIR, PROD_DIR, SERVICE,
CONTAINER, IMAGE.
EOF
      exit 0 ;;
    *) echo "Option inconnue : $1" >&2; exit 2 ;;
  esac
done

if [[ $REARM -eq 1 && -z "$REARM_MOTIF" ]]; then
  REARM_MOTIF="deploy-on-ec2 $(date -u +%Y-%m-%dT%H:%M:%SZ) branche=$BRANCH"
fi

# ─── Pré-requis ────────────────────────────────────────────────────────
log() { echo "[$(date -u +%H:%M:%S)] $*"; }

if [[ $EUID -ne 0 ]]; then
  exec sudo -E "$0" "$@"
fi

command -v docker >/dev/null 2>&1 || { log "ERREUR: docker introuvable"; exit 1; }
command -v git    >/dev/null 2>&1 || { log "ERREUR: git introuvable";    exit 1; }
command -v python3 >/dev/null 2>&1 || { log "ERREUR: python3 introuvable"; exit 1; }

# ─── Étape 1 : clone frais ─────────────────────────────────────────────
log "Étape 1/7 : clone $REPO_URL (branche $BRANCH) dans $WORK_DIR"
rm -rf "$WORK_DIR"
git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$WORK_DIR" >/dev/null 2>&1
cd "$WORK_DIR"
SHA=$(git rev-parse HEAD)
SHORT=$(echo "$SHA" | cut -c1-12)
log "  commit : $SHORT ($SHA)"

# ─── Étape 2 : générer le manifest REM-003 ─────────────────────────────
log "Étape 2/7 : générer deployment_manifest.json"
env BUILD_ENVIRONMENT=ec2-prod \
  DEPLOYMENT_TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  python3 scripts/generer_manifest_deploiement.py \
  --out deployment_manifest.json --exiger-propre
CONFIG_HASH=$(python3 -c "import json; print(json.load(open('deployment_manifest.json'))['configuration_hash'])")
log "  configuration_hash : $CONFIG_HASH"

# ─── Étape 3 : docker build ────────────────────────────────────────────
log "Étape 3/7 : docker build $IMAGE"
docker build -t "$IMAGE" . >/dev/null 2>&1
log "  build OK"

# ─── Étape 4 : EXPECTED_GIT_COMMIT dans .env ──────────────────────────
log "Étape 4/7 : poser EXPECTED_GIT_COMMIT=$SHORT dans $PROD_DIR/.env"
# Protection : .env sans saut de ligne final rend tee -a dangereux
# (cf. incident 2026-10-02). Normaliser.
if [[ -f "$PROD_DIR/.env" ]] && [[ -n "$(tail -c 1 "$PROD_DIR/.env")" ]]; then
  echo "" >> "$PROD_DIR/.env"
fi
sed -i '/^EXPECTED_GIT_COMMIT=/d' "$PROD_DIR/.env"
echo "EXPECTED_GIT_COMMIT=$SHORT" >> "$PROD_DIR/.env"

# Déposer aussi le manifest dans PROD_DIR pour cohérence (facultatif mais
# utile si un script annexe le cherche là)
cp deployment_manifest.json "$PROD_DIR/deployment_manifest.json"

# ─── Étape 5 : restart systemd ─────────────────────────────────────────
log "Étape 5/7 : systemctl restart $SERVICE"
systemctl restart "$SERVICE"
sleep 20

# ─── Étape 6 : vérifs ──────────────────────────────────────────────────
log "Étape 6/7 : vérifications"
if ! docker exec "$CONTAINER" test -f /app/deployment_manifest.json 2>/dev/null; then
  log "ERREUR: manifest absent du container, arrêt"
  exit 3
fi
RUNNING_SHA=$(docker exec "$CONTAINER" python3 -c \
  "import json; print(json.load(open('/app/deployment_manifest.json'))['git_commit_sha'][:12])" 2>/dev/null)
if [[ "$RUNNING_SHA" != "$SHORT" ]]; then
  log "ERREUR: SHA container ($RUNNING_SHA) != déployé ($SHORT)"
  exit 4
fi
log "  container tourne sur $RUNNING_SHA ✓"

# ─── Étape 7 : réarm REM-002 (optionnel) ──────────────────────────────
if [[ $REARM -eq 1 ]]; then
  log "Étape 7/7 : réarmement REM-002 (motif: $REARM_MOTIF)"
  docker exec "$CONTAINER" python3 -c "
from backend.services import global_execution_switch as s
d = s.arm('$REARM_MOTIF', by='Xavier (delegation explicite)')
print(d)
"
else
  log "Étape 7/7 : réarmement REM-002 SKIP (pas de --rearm)"
  log "  pour armer manuellement :"
  log "  docker exec $CONTAINER python3 -c \"from backend.services import global_execution_switch as s; print(s.arm('<motif>', by='Xavier (delegation explicite)'))\""
fi

log "✓ Déploiement terminé. SHA : $SHORT"
