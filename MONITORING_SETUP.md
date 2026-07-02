# MT5 Bridges Health Monitoring

## Quick Start

The monitoring script checks the health of both MT5 bridges (legacy and live) every hour and sends Telegram alerts to `@xav_scalping_infra_bot` if any bridge is down.

### Manual Execution

```bash
python3 /home/user/scalping/scripts/monitor-mt5-bridges.py
```

### Automatic Scheduling (crontab)

Add this line to your crontab (runs at xx:37 UTC every hour):

```bash
37 * * * * /home/user/scalping/scripts/monitor-mt5-bridges.py >> /var/log/scalping-monitor.log 2>&1
```

**To edit crontab:**
```bash
crontab -e
```

Then paste the line above. Save and exit.

### Automatic Scheduling (systemd timer — preferred for cloud)

Create `/etc/systemd/system/mt5-monitor.service`:
```ini
[Unit]
Description=MT5 Bridges Health Monitor
After=network-online.target

[Service]
Type=oneshot
ExecStart=/home/user/scalping/scripts/monitor-mt5-bridges.py
StandardOutput=journal
StandardError=journal
SyslogIdentifier=mt5-monitor
```

Create `/etc/systemd/system/mt5-monitor.timer`:
```ini
[Unit]
Description=MT5 Bridges Health Monitor (hourly at :37)
Requires=mt5-monitor.service

[Timer]
OnCalendar=*-*-* *:37:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable mt5-monitor.timer
sudo systemctl start mt5-monitor.timer
sudo systemctl status mt5-monitor.timer
```

View logs:
```bash
journalctl -u mt5-monitor -f
```

## Alert Details

- **Dedup key**: `bridge_legacy_down` or `bridge_live_down`
- **Cooldown**: 3 hours (10800 seconds) — same alert suppressed during this period
- **Channel**: `@xav_scalping_infra_bot` (Telegram)
- **Action**: RDP to cedric-mt5-bridge VPS and restart the bridge via `.\\venv\\Scripts\\python.exe .\\bridge.py`

## Bridge Endpoints

- **Legacy** (Pepperstone Demo): `http://100.74.160.72:8787`
- **Live** (IC Markets): `http://100.74.160.72:8788`

Health endpoint: `https://app.scalping-radar.online/api/admin/mt5-bridges-health?token=...`

## Troubleshooting

If the monitor stops working:

1. Check the script is executable: `ls -la /home/user/scalping/scripts/monitor-mt5-bridges.py`
2. Check it can reach the endpoints: `curl -sk https://app.scalping-radar.online/api/admin/mt5-bridges-health?token=shdw_...`
3. Check cron/timer is running: `systemctl status mt5-monitor.timer` or `crontab -l`
4. Check recent logs: `journalctl -u mt5-monitor -n 20` or `tail -f /var/log/scalping-monitor.log`

## Incident History

- **2026-06-18**: Bridge IC Markets Live (port 8788) fell silent without monitoring — discovered next morning by absence of trades in `admin_live` account.
- **2026-07-02 13:37:50**: Monitoring activated. First issue detected: legacy bridge (8787) unreachable. Alert sent to Telegram with 3h dedup cooldown.
