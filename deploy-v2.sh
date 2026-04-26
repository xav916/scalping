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
echo "=== generate changelog.json (.git absent in image) ==="
sudo python3 - <<'PY'
import json, re, subprocess
result = subprocess.run(
    ["git", "log", "--pretty=format:%H|%ad|%s", "--date=iso-strict", "-50"],
    capture_output=True, text=True, timeout=10,
)
commits = []
for line in result.stdout.split("\n"):
    if not line.strip():
        continue
    parts = line.split("|", 2)
    if len(parts) < 3:
        continue
    h, date, subject = parts
    m = re.match(r"^(\w+)(?:\(([^)]+)\))?(?:!)?:\s*(.+)$", subject)
    if m:
        ctype, cscope, cmsg = m.group(1), m.group(2), m.group(3)
    else:
        ctype, cscope, cmsg = "other", None, subject
    commits.append({"hash": h[:7], "date": date[:10], "type": ctype,
                    "scope": cscope, "subject": cmsg[:200]})
with open("docs/changelog.json", "w", encoding="utf-8") as f:
    json.dump({"commits": commits}, f, ensure_ascii=False, indent=2)
print(f"Generated docs/changelog.json with {len(commits)} commits")
PY
echo "=== docker build ==="
sudo docker build -t scalping-radar:latest .
echo "=== prune dangling ==="
# Supprime les images orphelines créées par ce build (anciennes layers
# remplacées par les nouvelles). Sans ce prune, chaque deploy laisse
# ~509MB d'image <none>:<none> → remplit les 8GB d'EBS en ~15 deploys.
sudo docker image prune -f
sudo docker builder prune -f --filter "until=24h"
echo "=== systemd restart ==="
sudo systemctl restart scalping
sleep 3
echo "=== service status ==="
sudo systemctl status scalping --no-pager | head -15
echo "=== container status ==="
sudo docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
REMOTE
