# Deploiement AWS EC2

Ce projet peut etre deploye simplement sur **AWS EC2** avec **Docker + systemd + Nginx**. Cette approche marche bien avec FastAPI et le WebSocket `/ws`.

## 1. Creer l'instance EC2

Configuration recommandee :

- **AMI** : Ubuntu 24.04 LTS
- **Type** : `t3.micro` (free tier si eligible)
- **Storage** : 8 a 20 Go
- **Security Group** :
  - `22/tcp` pour SSH
  - `80/tcp` pour HTTP

## 2. Se connecter a la machine

```bash
ssh -i scalping-key.pem ubuntu@<IP_PUBLIC_EC2>
```

## 3. Recuperer le projet

```bash
git clone <URL_DU_REPO>
cd scalping
```

## 4. Lancer l'installation automatique

```bash
sudo bash deploy/setup-ec2.sh
```

Le script va :

- installer Docker et Nginx ;
- copier le projet dans `/opt/scalping` ;
- creer `.env` si absent ;
- builder l'image Docker ;
- configurer Nginx comme reverse proxy ;
- installer un service `systemd` avec redemarrage automatique.

## 5. Verifier le service

```bash
sudo systemctl status scalping.service
sudo journalctl -u scalping.service -f
```

## 6. Ouvrir l'application

Dans le navigateur :

```text
http://<IP_PUBLIC_EC2>
```

## Mise a jour apres un nouveau commit

Sur la machine EC2 :

```bash
cd ~/scalping
git pull
sudo bash deploy/setup-ec2.sh
```

## Variables d'environnement utiles

Le script cree `/opt/scalping/.env` a partir de `.env.example` si le fichier n'existe pas.

Variables a verifier :

- `HOST=0.0.0.0`
- `PORT=8000`
- `TWELVEDATA_API_KEY=` pour utiliser l'API reelle au lieu du mode simule
- `WATCHED_PAIRS=` pour adapter les actifs surveilles

## Notes

- Le trafic HTTP arrive sur Nginx en port `80`, puis est proxifie vers FastAPI sur `127.0.0.1:8000`.
- Le WebSocket `/ws` est supporte par la configuration Nginx fournie.
- Si tu veux ajouter HTTPS plus tard, tu peux brancher **Certbot** sur cette config Nginx.