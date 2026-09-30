# Audit J+7 — Retrait PC bridge MT5 (2026-05-05)

**Verdict provisoire :** ✅ Auto-checks OK, manuels en attente

---

## Auto-checks (agent remote)

Audit réalisé le 2026-05-05 par agent cloud (pas d'accès EC2 / Tailscale).

### 1. Commits depuis le retrait (2026-04-28)

42 commits au total. **Aucun commit suspect** (pas de réintroduction BRIDGE_LOCAL, pas de revert bridge_monitor.py). Seul commit touchant `bridge_monitor.py` :

```
7b8c125  2026-04-28  feat(monitor): version bridge_monitor.py + env template, bridge_local probe optional
```

Commits notables depuis (fonctionnels, sans lien avec le bridge) :

```
00c4987  feat(auth): toggle visibilité mot de passe sur 4 pages
5a3b824  docs(roadmap): Phase 3b — sortir de MT5 pour vraies bourses
2996b71  fix(alerts): silence Telegram pour rejections market_closed
c8cff22  feat(cockpit): badge "Marchés stars" dans Santé système
f94aecb  docs(monitoring): rapport hebdo W1 shadow log (auto)
2602815  feat(admin): dashboard auto-exec health dans /v2/admin
f80938f  feat(watchdog): persistance historique rafales + UI history
4eb5ee9  feat(admin): watchdog UI + manual unpause
4a50b16  feat(circuit-breaker): smart resume basé sur activité réelle V1
076c974  refactor(circuit-breaker): per-pair pause + global safety net
1efbd6d  feat(circuit-breaker): auto-pause/resume sur rafale stops loss
... (42 commits total, tous légitimes)
```

### 2. Occurrences `BRIDGE_LOCAL` dans les `.py`

`grep -rn "BRIDGE_LOCAL" --include="*.py"` → **6 occurrences**, toutes dans `mt5-bridge-monitor/bridge_monitor.py`, aux emplacements attendus :

| Ligne | Contenu | Statut |
|-------|---------|--------|
| 43 | `BRIDGE_LOCAL_URL = os.environ.get("BRIDGE_LOCAL_URL", "").strip()` | ✅ optionnel |
| 44 | `BRIDGE_LOCAL_KEY = os.environ.get("BRIDGE_LOCAL_KEY", "").strip()` | ✅ optionnel |
| 45 | `BRIDGE_LOCAL_ENABLED = bool(BRIDGE_LOCAL_URL and BRIDGE_LOCAL_KEY)` | ✅ flag |
| 634 | `if BRIDGE_LOCAL_ENABLED:` | ✅ guard ok |
| 635 | `probes.append(probe_bridge("bridge_local", ...))` | ✅ conditionnel |
| 957 | `BRIDGE_LOCAL_URL or "(disabled)"` | ✅ log startup |

`BRIDGE_VPS_URL/KEY` restent en `os.environ[...]` strict (lignes 46-47). ✅

### 3. Occurrence IP `100.122.188.8`

`grep -rn "100.122.188.8"` → **0 occurrence dans le code actif**. Présences uniquement dans :
- `config/settings.py:121` — commentaire
- `mt5-bridge/test-order.ps1` — script de test local PC
- `backend/services/mt5_bridge.py:4` — commentaire docstring
- `docs/pepperstone-migration.md` — documentation historique
- `docs/superpowers/specs/*.md` — specs architecture

Aucune utilisation dans du code de monitoring ou de production. ✅

### Résumé auto-checks

| Check | Résultat |
|-------|----------|
| Commits bridge_monitor.py depuis J0 | 1 seul (7b8c125, le commit du retrait lui-même) |
| Réintroduction BRIDGE_LOCAL | Aucune |
| Pattern `.get()` optionnel lignes 43-45 | Conforme |
| Guard `if BRIDGE_LOCAL_ENABLED:` ligne 634 | Conforme |
| BRIDGE_VPS strict `os.environ[...]` | Conforme |
| IP 100.122.188.8 dans code actif | 0 occurrence |

---

## Manual checks pour le user (Tailscale-only + SSH EC2)

- [ ] `curl -s http://100.103.107.75:8090/status.json` (Tailscale-only) → confirmer 6 sondes UP, `bridge_local` absent de `services{}`
- [ ] Lire `recoveries[]` dans le même JSON → si > 0, vérifier les actions auto-recovery déclenchées (restart_systemd, docker_prune)
- [ ] Vérifier `disk_root.last_probe.used_pct` < 85 % (au cleanup il était à 78,1 %)
- [ ] `ssh -i C:/Users/xav91/Scalping/scalping/scalping-key.pem ec2-user@51.21.132.216 "sudo grep -cE '^BRIDGE_LOCAL_(URL|KEY)=' /opt/scalping/.env /opt/scalping-bridge-monitor/monitor.env"` → count doit rester 0
- [ ] Sur EC2, `sudo journalctl -u scalping-bridge-monitor.service --since '7 days ago' | grep -iE 'telegram|tg_send' | wc -l` → > 5 = signal d'instabilité
- [ ] Sur Telegram, envoyer `/status` à `@xav_scalping_infra_bot` → confirmer qu'il répond avec un snapshot des sondes

---

## Comment fermer cet audit

Quand tous les checks manuels sont OK, marque-les ✅, ajoute le verdict final en bas (`✅ tout sain à J+7` ou `⚠️ à corriger : ...`), commit la mise à jour sur la même branche, et merge la PR.

---

<!-- verdict final à remplir après les checks manuels -->
