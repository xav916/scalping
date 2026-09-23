# Migrer le bridge MT5 sur une instance Windows EC2

Rédigé le 2026-09-23, après la perte d'accès RDP au VPS Windows.

> ⚠️ **Cette procédure touche la machine qui passe les ordres en argent réel.**
> Lisez la section « Bascule » avant de lancer quoi que ce soit : le seul risque
> sérieux du chantier est d'avoir **deux bridges vivants en même temps** sur la même
> destination, ce qui doublerait les positions.

---

## 0. Pourquoi, et ce que ça répare vraiment

La panne du 2026-09-23 a révélé un couplage. `mt5-bridge/multi-tenant/launcher.ps1` :

```powershell
# Tâche planifiée AtLogOn user Administrator → relance auto si reboot.
```

**`AtLogOn` lie le démarrage du bridge à l'ouverture d'une session interactive.** En
pratique, à une connexion RDP. Donc :

- RDP tombe → plus personne n'ouvre de session ;
- la machine redémarre (mise à jour Windows, incident hôte) → le lanceur ne se
  déclenche pas ;
- **le bridge ne revient jamais**, et rien ne le signale (cf. R-23 : le contrôle de
  santé ne regarde pas les destinations de l'exploitant).

Le chantier répare trois choses :

| | Avant | Après |
|---|---|---|
| Accès | RDP exposé, filtré par liste d'IP | **SSM Fleet Manager**, aucun port 3389 ouvert |
| Démarrage | `AtLogOn` — dépend d'un humain qui se connecte | **Ouverture de session automatique** + `AtLogOn`, aucun humain requis |
| Réseau bridge | Port exposé vers l'extérieur | **IP privée**, joignable du seul backend |

Ce qu'il ne répare **pas** : `IT-2`. Le bridge reste une machine unique, donc un point
de défaillance unique pour l'exécution MT5. Il est seulement mieux tenu.

---

## 1. Dimensionner et lancer l'instance

- **AMI** : Windows Server 2022 Base (l'agent SSM y est préinstallé).
- **Type** : `t3.large` (2 vCPU, 8 Gio) recommandé. `t3.medium` (4 Gio) est le plancher
  et devient juste avec MT5 ouvert sur 16 à 49 symboles plus le bridge Python.
- **Disque** : 50 Gio `gp3`. Windows en consomme ~30 à lui seul.
- **Région** : **la même que l'EC2 backend.** À vérifier dans la console, pas à deviner.
- **VPC** : **le même que l'EC2 backend.** C'est ce qui permet de ne jamais exposer le
  bridge sur Internet.
- **Paire de clés** : nécessaire au lancement pour déchiffrer le mot de passe
  Administrator, même si l'accès courant passera par SSM.

### Profil IAM — indispensable pour SSM

Attacher à l'instance un rôle portant la politique gérée
**`AmazonSSMManagedInstanceCore`**. Sans lui, Fleet Manager ne verra jamais la machine.

Vérifier ensuite dans **Systems Manager → Fleet Manager** que l'instance apparaît. Si
elle n'apparaît pas au bout de cinq minutes, c'est le rôle ou la sortie HTTPS.

---

## 2. Groupes de sécurité — aucun port d'administration ouvert

**Instance Windows (bridge)**

| Sens | Port | Source / Destination | Motif |
|---|---|---|---|
| Entrant | **8787** | le *security group* de l'EC2 backend | le backend pousse les ordres |
| Entrant | — | *rien d'autre* | **aucune règle 3389** |
| Sortant | 443 | `0.0.0.0/0` | SSM, MT5, mises à jour |

> ⛔ **Ne pas ouvrir 3389, même « temporairement vers mon IP ».** C'est exactement le
> dispositif qui vient de lâcher : une liste d'IP se périme dès que votre IP change.
> Fleet Manager fait du RDP **par SSM**, sans port entrant.

**EC2 backend** : autoriser le sortant vers 8787 du groupe Windows.

---

## 3. Premier accès

1. **EC2 → Instances → Connect → RDP client → Get password**, déchiffré avec le `.pem`
   de la paire de clés. Notez ce mot de passe dans votre gestionnaire.
2. **Systems Manager → Fleet Manager → l'instance → Node actions → Connect with
   Remote Desktop**, identifiants Windows. C'est la voie d'accès normale désormais.

---

## 4. Installer la pile

Conventions du dépôt (`mt5-bridge/README.md`) : tout sous `C:\Scalping\`.

```powershell
# 1. Python 3.11 (le paquet MetaTrader5 fournit des wheels pour cette version)
#    winget install Python.Python.3.11   — ou l'installeur python.org

# 2. Le depot
git clone https://github.com/xav916/scalping.git C:\Scalping\repo
New-Item -ItemType Directory -Force C:\Scalping\mt5-bridge
Copy-Item C:\Scalping\repo\mt5-bridge\* C:\Scalping\mt5-bridge\ -Recurse

# 3. L'environnement
cd C:\Scalping\mt5-bridge
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt     # MetaTrader5, Flask 3.0.3, python-dotenv
```

Puis **MT5 Desktop** : installeur du courtier (IC Markets pour `admin_live`), connexion
au compte, et l'EA selon `mt5-bridge/MT5_EA_INSTALL.md`.

### ⛔ Le piège de la clé d'API

`mt5-bridge/README.md` le dit : si `BRIDGE_API_KEY` n'est pas dans le `.env`, le bridge
**en génère une nouvelle à chaque démarrage** et la journalise en clair (c'est le constat
`S-7`). Sur une machine neuve, cela signifie que le backend ne s'authentifiera pas.

**Reprenez la valeur existante** depuis le `.env` de l'ancien VPS, ou posez-en une
nouvelle des deux côtés en même temps — dans le `.env` du bridge **et** dans la
configuration de destination du backend.

### Le reste du `.env`

Partez de `mt5-bridge/multi-tenant/.env.example`. Les variables qui décident :

```
LISTEN_HOST=0.0.0.0        # ⚠️ defaut 127.0.0.1 : le backend ne pourrait PAS joindre
LISTEN_PORT=8787
BRIDGE_API_KEY=<la meme que cote backend>
MT5_LOGIN= / MT5_PASSWORD= / MT5_SERVER=
MT5_TERMINAL_PATH=
MT5_SYMBOL_MAP=            # ⚠️ voir R-19/§4.6.10 : le symbole WTI d'IC Markets
PAPER_MODE=                # laisser en paper jusqu'a la validation (section 6)
TRAIL_DISTANCE_POINTS=0    # ⛔ DOIT rester a 0 (cf. bridge.py:2310)
```

> ⛔ Les identifiants MT5 se saisissent sur cette machine uniquement. Ils n'ont à
> transiter par aucun ticket, aucun dépôt, aucune conversation.

---

## 5. Démarrage sans humain — la correction du couplage

Deux réglages, et c'est leur **conjonction** qui compte.

**a) Ouverture de session automatique.** MT5 est une application graphique : le paquet
`MetaTrader5` s'attache à un terminal qui tourne dans une vraie session interactive. On
ne peut donc pas simplement en faire un service. La solution est que Windows ouvre la
session tout seul au démarrage.

```powershell
# Sysinternals Autologon, ou la cle de registre equivalente
# HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon
#   AutoAdminLogon = 1 ; DefaultUserName ; DefaultPassword
```

> ⚠️ Le mot de passe est alors stocké dans le registre. C'est acceptable **parce que**
> aucun port d'administration n'est ouvert et que l'accès passe par SSM/IAM. Les deux
> décisions vont ensemble : l'ouverture automatique sans la fermeture du 3389 serait
> une régression, pas un progrès.

**b) La tâche `AtLogOn` existante** (`launcher.ps1`) fonctionne alors sans personne :
la session s'ouvre seule au boot, la tâche part, le bridge démarre.

**Éprouvez-le** : redémarrez l'instance, **sans ouvrir de session**, et vérifiez depuis
l'EC2 backend que le bridge répond :

```bash
curl -s http://<ip-privee-windows>:8787/health
```

Tant que ce test n'est pas passé, le couplage n'est pas corrigé.

---

## 6. Bascule — la seule partie risquée

> ⛔ **Deux bridges vivants simultanément sur la même destination doubleraient les
> positions.** C'est le seul danger réel du chantier. Tout le reste est réversible.

1. **Choisir le moment** : marchés fermés (week-end), ou `admin_live` mis en pause.
2. **Arrêter l'ancien bridge** — et vérifier qu'il est arrêté, pas seulement supposé
   l'être. Tant que vous n'avez pas récupéré RDP, considérez qu'il **peut** tourner :
   coupez plutôt l'accès réseau au port 8787 côté fournisseur.
3. **Nouvelle machine en `PAPER_MODE`**, puis les contrôles :
   ```powershell
   .\test-order.ps1              # deja dans mt5-bridge/, ne pas reinventer
   ```
   Et depuis l'EC2 : `curl http://<ip-privee>:8787/health`, puis un `/tick/XAU%2FUSD`
   — c'est aussi l'occasion de trancher la divergence de prix du WTI (§4.6.10).
4. **Pointer le backend** : `MT5_BRIDGE_URL=http://<ip-privee-windows>:8787` dans le
   `.env` de l'EC2, puis `sudo systemctl restart scalping`.
5. **Un seul ordre sur la démo** (`admin_legacy`) avant de repasser `admin_live` en
   exécution. Vérifier le ticket des deux côtés.
6. **Ne supprimez l'ancien VPS qu'après une semaine** de fonctionnement propre.

---

## 7. Coût

Ordres de grandeur en région européenne, tarif à la demande, licence Windows comprise —
**à vérifier sur le calculateur AWS, ils varient par région** :

| | ~ / mois |
|---|---|
| `t3.medium` Windows | ~55 à 65 € |
| `t3.large` Windows | ~110 à 125 € |
| 50 Gio `gp3` | ~4 € |

C'est vraisemblablement plus cher que le VPS actuel. Ce que l'écart achète : la
suppression du port d'administration exposé, le redémarrage sans humain, et le bridge
sur un réseau privé avec le backend.

Une réservation d'un an (*Savings Plan*) réduit d'environ 30 % si la machine est
destinée à durer.

---

## 8. Après la bascule

- **R-23** reste entier : rien ne surveille encore `admin_live`. Le rapport `bridge` de
  `deploy/diag-lecture-seule.sh` le fait à la demande ; il ne remplace pas une alerte.
- **IT-2** reste entier : une seule machine pour l'exécution MT5.
- Mettre à jour `CLAUDE.md` — l'architecture y décrit encore « bridge MT5 sur PC
  Windows ».
