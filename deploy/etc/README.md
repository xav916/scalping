# Configuration système de l'EC2 — copies de reprise

Ces fichiers vivent **hors du dépôt** sur le serveur. Ils sont copiés ici pour
qu'une reprise après incident ne dépende pas de la mémoire de quelqu'un.

| copie versionnée | chemin réel sur l'EC2 |
|---|---|
| `scalping.service` | `/etc/systemd/system/scalping.service` |
| `nginx.conf` | `/etc/nginx/nginx.conf` |
| `nginx-conf.d-scalping-app.conf` | `/etc/nginx/conf.d/scalping-app.conf` |
| `nginx-conf.d-scalping.conf` | `/etc/nginx/conf.d/scalping.conf` |

## ⛔ Pourquoi ces copies-ci et pas celles de `/opt/scalping/deploy/`

Ce dossier contenait déjà des copies. **Elles divergeaient toutes de ce qui
tourne**, dataient d'avril ou mai, et l'une d'elles —
`nginx-app-scalping-online.conf` — ne correspondait à **aucun fichier actif** :
nginx charge en réalité `scalping-app.conf` et `scalping.conf`.

Les versionner aurait versionné de la fiction, et donné une fausse assurance le
jour où on en aurait eu besoin. C'est le même défaut qui a laissé le backup S3
échouer cinq nuits : une copie orpheline qui a l'air officielle.

⚠️ Les fichiers de `/opt/scalping/deploy/` sont donc **périmés**. Ne pas s'en
servir.

## Vérifier que ces copies sont encore à jour

```bash
sudo md5sum /etc/systemd/system/scalping.service /etc/nginx/nginx.conf \
            /etc/nginx/conf.d/scalping-app.conf /etc/nginx/conf.d/scalping.conf
```

et comparer au contenu de ce dossier (l'en-tête de commentaire mis à part).

⚠️ **Rien ici ne se déploie tout seul.** Ces fichiers sont une référence de
reprise, pas une source de vérité appliquée automatiquement — s'ils l'étaient
sans être vérifiés, une copie périmée écraserait une prod correcte.
