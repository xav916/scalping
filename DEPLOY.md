# Deploiement AWS EC2

## Methode rapide (1 commande)

Le script `deploy/aws-deploy.sh` automatise tout : creation de l'instance, security group, cles SSH, installation de l'app.

### Prerequis

1. **Compte AWS** : https://aws.amazon.com (free tier = 12 mois gratuit)
2. **AWS CLI** installee sur ta machine

### Etape 1 : Installer AWS CLI

**Linux :**
```bash
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
unzip awscliv2.zip && sudo ./aws/install
```

**Mac :**
```bash
brew install awscli
```

**Windows :**
Telecharge et installe https://awscli.amazonaws.com/AWSCLIV2.msi

### Etape 2 : Creer tes cles d'acces AWS

1. Va sur https://console.aws.amazon.com
2. Clique sur ton nom en haut a droite > **Security credentials**
3. Section **Access keys** > **Create access key**
4. Choisis **Command Line Interface (CLI)**
5. Copie les 2 cles (Access Key ID + Secret Access Key)

### Etape 3 : Configurer AWS CLI

```bash
aws configure
```

Reponds aux questions :
```
AWS Access Key ID:     AKIA...........   (ta cle)
AWS Secret Access Key: wJal...........   (ton secret)
Default region name:   eu-west-3         (Paris)
Default output format: json
```

### Etape 4 : Deployer

```bash
git clone https://github.com/xav916/scalping.git
cd scalping
bash deploy/aws-deploy.sh
```

C'est tout ! Le script :
- Cree une paire de cles SSH (~/.ssh/scalping-key.pem)
- Cree un Security Group (ports 22 + 80)
- Trouve la derniere AMI Ubuntu 24.04
- Lance une instance t3.micro
- Installe automatiquement Python, Nginx et l'app
- Affiche l'URL du dashboard

### Etape 5 : Acceder au dashboard

Apres ~2-3 minutes, ouvre ton navigateur :
```
http://<IP_AFFICHEE>
```

---

## Commandes utiles apres deploiement

```bash
# Se connecter en SSH
ssh -i ~/.ssh/scalping-key.pem ubuntu@<IP>

# Voir les logs de l'installation
ssh -i ~/.ssh/scalping-key.pem ubuntu@<IP> 'cat /var/log/scalping-setup.log'

# Voir les logs de l'application
ssh -i ~/.ssh/scalping-key.pem ubuntu@<IP> 'sudo journalctl -u scalping -f'

# Redemarrer l'application
ssh -i ~/.ssh/scalping-key.pem ubuntu@<IP> 'sudo systemctl restart scalping'

# Configurer la cle API Twelve Data (prix reels)
ssh -i ~/.ssh/scalping-key.pem ubuntu@<IP> 'nano /home/ubuntu/scalping/.env'

# Mettre a jour le code
ssh -i ~/.ssh/scalping-key.pem ubuntu@<IP> 'cd /home/ubuntu/scalping && git pull && sudo systemctl restart scalping'

# Detruire l'instance (arrete la facturation)
aws ec2 terminate-instances --instance-ids <INSTANCE_ID>
```

## Configuration .env

Variable importante : `TWELVEDATA_API_KEY` — pour avoir des donnees de prix reelles au lieu de simulees. Cle gratuite sur https://twelvedata.com/register

## Cout estime

| Ressource | Cout |
|-----------|------|
| EC2 t3.micro | Gratuit 12 mois (free tier) puis ~$8/mois |
| Bande passante | ~$0 (trafic minimal) |
| **Total** | **~$0 - $8/mois** |

## HTTPS (optionnel)

Pour ajouter un certificat SSL gratuit :

```bash
ssh -i ~/.ssh/scalping-key.pem ubuntu@<IP>
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d ton-domaine.com
```

Il faut un nom de domaine pointe vers l'IP de l'instance.

---

## Methode manuelle (alternative)

Si tu preferes configurer via la console AWS :

1. Va sur **AWS Console** > **EC2** > **Launch Instance**
2. Configure :
   - **Nom** : `scalping-radar`
   - **AMI** : Ubuntu Server 24.04 LTS
   - **Type** : `t3.micro`
   - **Key pair** : Creer une nouvelle paire
   - **Security Group** : Ouvrir ports 22 (SSH) et 80 (HTTP)
3. Lance l'instance
4. Connecte-toi et lance le script d'installation :

```bash
ssh -i ta-cle.pem ubuntu@<IP>
git clone https://github.com/xav916/scalping.git
cd scalping
bash deploy/setup-ec2.sh
```
