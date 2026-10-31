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

- [ ] ⏳ **NON FAIT — Tailscale, hors de ma portée.** Partiellement couvert : `status.json` lu depuis l'hôte le 2026-10-31, il rend bien 8 sondes et `bridge_local` est **absent** de `services{}`. Reste à confirmer les 6 UP depuis votre poste. `curl -s http://100.103.107.75:8090/status.json` (Tailscale-only) → confirmer 6 sondes UP, `bridge_local` absent de `services{}`
- [ ] ⏳ **NON FAIT — Tailscale.** Lire `recoveries[]` dans le même JSON → si > 0, vérifier les actions auto-recovery déclenchées (restart_systemd, docker_prune)
- [x] ✅ **VÉRIFIÉ le 2026-10-31 : 43 %** (22 G / 50 G) — mieux qu'au nettoyage (78,1 %). Vérifier `disk_root.last_probe.used_pct` < 85 % (au cleanup il était à 78,1 %)
- [x] ✅ **VÉRIFIÉ le 2026-10-31 : count = 0** dans les deux fichiers. ⚠️ L'adresse de cette commande est **périmée** — l'hôte est `13.63.77.180`, pas `51.21.132.216`. `ssh -i scalping-key.pem ec2-user@13.63.77.180 "sudo grep -cE '^BRIDGE_LOCAL_(URL|KEY)=' /opt/scalping/.env /opt/scalping-bridge-monitor/monitor.env"` → count doit rester 0
- [x] 🔴 **ÉCHEC le 2026-10-31 : 42**, pour un seuil de 5. ⇒ voir le verdict. `sudo journalctl -u scalping-bridge-monitor.service --since '7 days ago' | grep -iE 'telegram|tg_send' | wc -l` → > 5 = signal d'instabilité
- [ ] ⏳ **NON FAIT — c'est un geste qui poste dans votre canal.** À faire maintenant que le correctif est déployé : c'est précisément la réponse qui échouait. Sur Telegram, envoyer `/status` à `@xav_scalping_infra_bot` → confirmer qu'il répond avec un snapshot des sondes

---

## Comment fermer cet audit

Quand tous les checks manuels sont OK, marque-les ✅, ajoute le verdict final en bas (`✅ tout sain à J+7` ou `⚠️ à corriger : ...`), commit la mise à jour sur la même branche, et merge la PR.

---

## ⚠️ Verdict final — rendu le 2026-10-31, J+179

**⚠️ À corriger : un défaut TROUVÉ, et corrigé le jour du verdict.**

Cet audit a attendu **six mois**. Rejoué le 2026-10-31 :

### Ce qui est sain

- **Le retrait du bridge PC tient.** `BRIDGE_LOCAL` reste optionnel (6
  occurrences, même motif `.get()` + garde `if BRIDGE_LOCAL_ENABLED:` — les
  numéros de ligne ont bougé, la structure non), et `count = 0` dans les deux
  `.env`. Le journal du service dit toujours `local=(disabled)`.
- **L'IP `100.122.188.8` n'est jamais dans du code actif.** Vérifié **par
  AST** et non par `grep` : elle est dans la **docstring** de
  `mt5_bridge.py` et un **commentaire** de `settings.py`.
- **Disque à 43 %**, contre 78,1 % au nettoyage.

### 🔴 Ce qui ne l'était pas

Le contrôle n°5 **échouait : 42** mentions Telegram sur 7 jours, pour un
seuil de 5. Et ce n'était pas du bruit : **les 42 étaient la même erreur**,
la dernière le jour même à 19:04:27.

```
http=400 {"ok":false,"description":"Bad Request: can't parse entities:
          Can't find end of the entity starting at byte offset 464"}
```

⛔ **42 notifications perdues** : refusées par Telegram, donc jamais livrées.
Et **36 des 42 étaient du seul 31/10**, sans aucune transition DOWN ce
jour-là — c'étaient les réponses à `/status`.

**Cause :** `tg_send` envoie en `parse_mode="Markdown"` sans échapper les
valeurs interpolées. La sonde `disk_root` n'est pas dans la table de
traduction, son souligné partait brut, et avec les deux soulignés de
l'italique voulue du pied de message ⇒ **3, nombre impair** ⇒ entité ouverte
que rien ne ferme.

🔑 **Trois couches de silence** : le message rejeté donc jamais livré ; le
journal enregistrait la *réponse* mais **jamais le message**, rendant le
défaut indiagnosticable ; et un `warning`, donc rien ne le remontait. C'est
ainsi qu'il a vécu des mois.

### Corrigé

**PR #9** — échappement des valeurs (deux fonctions, car un span de code ne
se traite pas comme du texte libre), journalisation du message, et repli sans
`parse_mode` pour que la livraison passe avant la mise en forme.

**Déployé le 2026-10-31 à 19:32** sur `scalping-bridge-monitor` : service
`active`, 0 redémarrage forcé, import réel vérifié avec les deux
`EnvironmentFile` chargés. Deux sauvegardes conservées sur l'hôte.

### Ce qui reste

- **3 contrôles sur 6 non faits** : deux passent par Tailscale, un poste dans
  le canal Telegram. Ils restent à l'opérateur.
- ⚠️ **La commande SSH de cet audit est périmée** : `51.21.132.216` contre
  `13.63.77.180` aujourd'hui. Un audit non rejoué pourrit.
- 🔑 **La leçon de l'attente** : six mois sans rejouer, et un défaut qui
  faisait perdre des notifications d'infrastructure a vécu tout ce temps.
  Ce n'est pas l'audit qui a manqué — il posait la bonne question. C'est son
  rejeu.
