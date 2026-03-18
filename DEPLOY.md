# Deploiement AWS EC2

## Prerequis

1. Un compte AWS (https://aws.amazon.com)
2. Git installe sur ta machine locale

## Etape 1 : Creer une instance EC2

1. Va sur **AWS Console** > **EC2** > **Launch Instance**
2. Configure :
   - **Nom** : `scalping-radar`
   - **AMI** : Ubuntu Server 24.04 LTS (free tier eligible)
   - **Type** : `t3.micro` (free tier) ou `t3.small` si besoin
   - **Key pair** : Creer une nouvelle paire de cles (`scalping-key.pem`)
   - **Security Group** : Creer un nouveau groupe avec ces regles :
     - SSH (port 22) — ton IP uniquement
     - HTTP (port 80) — 0.0.0.0/0 (acces depuis partout)
     - HTTPS (port 443) — 0.0.0.0/0 (optionnel, pour plus tard)
3. Clique **Launch Instance**

## Etape 2 : Se connecter a l'instance

```bash
# Rendre la cle privee
chmod 400 scalping-key.pem

# Se connecter
ssh -i scalping-key.pem ubuntu@<IP_PUBLIQUE>
```

L'IP publique est visible dans la console EC2.

## Etape 3 : Installer l'application

### Option A : Script automatique (recommande)

Depuis ta machine locale :

```bash
scp -i scalping-key.pem deploy/setup-ec2.sh ubuntu@<IP_PUBLIQUE>:/tmp/
ssh -i scalping-key.pem ubuntu@<IP_PUBLIQUE> 'bash /tmp/setup-ec2.sh'
```

### Option B : Installation manuelle

```bash
# Sur l'instance EC2
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv nginx git

# Cloner le projet
git clone https://github.com/xav916/scalping.git
cd scalping

# Environnement Python
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configuration
cp .env.example .env
nano .env  # Ajouter ta cle TWELVEDATA_API_KEY si tu en as une

# Service systemd
sudo cp deploy/scalping.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable scalping
sudo systemctl start scalping

# Nginx
sudo cp deploy/nginx.conf /etc/nginx/sites-available/scalping
sudo ln -sf /etc/nginx/sites-available/scalping /etc/nginx/sites-enabled/scalping
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

## Etape 4 : Verifier

Ouvre ton navigateur sur `http://<IP_PUBLIQUE>` — le dashboard devrait s'afficher.

## Commandes utiles

```bash
# Statut du service
sudo systemctl status scalping

# Logs en temps reel
sudo journalctl -u scalping -f

# Redemarrer apres un changement
sudo systemctl restart scalping

# Mettre a jour le code
cd /home/ubuntu/scalping
git pull
sudo systemctl restart scalping
```

## Configuration .env

Edite `/home/ubuntu/scalping/.env` pour personnaliser :

```bash
nano /home/ubuntu/scalping/.env
```

Variable importante : `TWELVEDATA_API_KEY` — pour avoir des donnees de prix reelles au lieu de simulees. Cle gratuite sur https://twelvedata.com/register

## Cout estime

| Ressource | Cout |
|-----------|------|
| EC2 t3.micro | Gratuit 12 mois (free tier) puis ~$8/mois |
| Bande passante | ~$0 (trafic minimal) |
| **Total** | **~$0 - $8/mois** |

## HTTPS (optionnel)

Pour ajouter un certificat SSL gratuit avec Let's Encrypt :

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d ton-domaine.com
```

Il faut un nom de domaine pointe vers l'IP de l'instance.
