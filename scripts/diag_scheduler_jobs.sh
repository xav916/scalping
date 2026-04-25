#!/usr/bin/env bash
# Liste les jobs apscheduler enregistrés + cherche la trace de "Cycle d'analyse"
# dans les logs depuis le démarrage du service.
set -u
KEY="C:/Users/xav91/Scalping/scalping/scalping-key.pem"
HOST="ec2-user@100.103.107.75"

echo "=== service uptime ==="
ssh -o StrictHostKeyChecking=no -i "$KEY" "$HOST" "sudo systemctl show scalping --property=ActiveEnterTimestamp,SubState"

echo
echo "=== jobs scheduler enregistrés (depuis logs Scheduler démarré) ==="
ssh -i "$KEY" "$HOST" "sudo journalctl -u scalping --since '40 minutes ago' --no-pager | grep -iE 'Scheduler démarré|Added job|Cycle d.analyse|Cycle terminé' | tail -30"

echo
echo "=== tout ce qui contient 'analysis_cycle' ou 'Cycle d.analyse' (40 min) ==="
ssh -i "$KEY" "$HOST" "sudo journalctl -u scalping --since '40 minutes ago' --no-pager | grep -iE 'analysis_cycle|cycle.+analyse|run_analysis' | tail -30"

echo
echo "=== erreurs au démarrage (40 min) ==="
ssh -i "$KEY" "$HOST" "sudo journalctl -u scalping --since '40 minutes ago' --no-pager | grep -iE 'error|exception|traceback|failed' | tail -30"

echo
echo "=== query state scheduler (live) ==="
ssh -i "$KEY" "$HOST" "sudo docker exec scalping-radar python -c \"
from backend.services.scheduler import _scheduler
if _scheduler is None:
    print('SCHEDULER NOT INITIALIZED')
else:
    print('running:', _scheduler.running)
    for j in _scheduler.get_jobs():
        print(f'  id={j.id} name={j.name!r} trigger={j.trigger} next={j.next_run_time}')
\""

echo
echo "=== MATAF_POLL_INTERVAL valeur live ==="
ssh -i "$KEY" "$HOST" "sudo grep -i MATAF_POLL_INTERVAL /opt/scalping/.env || echo 'pas dans .env (utilise default)'"
