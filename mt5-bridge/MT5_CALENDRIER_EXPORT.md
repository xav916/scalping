# Rattraper l'historique du calendrier économique

## Ce qu'on répare

`refresh_calendar()` effaçait tout événement de plus de **7 jours** « pour
garder la table légère ». La purge est retirée le 2026-10-04 (`2508207`), donc
l'historique **s'accumule désormais** — mais le passé, lui, est perdu : au
moment du correctif le plus ancien événement en base datait du **27/09**.

Ce qui disparaissait, c'est l'**étiquette**, pas les prix. Les bougies restent
disponibles chez le courtier à la demande. Ce qu'on perdait, c'est « ce jour-là
à 12h30, publication de l'emploi américain, consensus 9,0K, réel −41,7K ».
Sans elle, une hypothèse événementielle est **inéprouvable rétroactivement**.

Le terminal MT5 embarque la base calendrier de MetaQuotes, avec `actual`,
`forecast` et `previous` sur **plusieurs années**. C'est la seule source de
rattrapage disponible.

> ⛔ **Le binding Python n'expose aucune fonction calendrier.** Vérifié, pas
> supposé, sur le binding `5.0.5735` installé :
> `[n for n in dir(MetaTrader5) if 'calendar' in n.lower()]` → `[]`.
> D'où le détour obligatoire par MQL5.

## La chaîne

| # | Pièce | État |
|---|---|---|
| 1 | `mt5-bridge/CalendrierExport.mq5` | écrit, ⚠️ **jamais compilé** |
| 2 | compilation sur le VPS | **à faire** |
| 3 | exécution dans le terminal | **à faire** — demande un geste humain |
| 4 | rapatriement du `.tsv` | à faire |
| 5 | `backend/services/import_calendrier_mql5.py` | écrit, 28 tests verts |
| 6 | `scripts/importer_calendrier_mql5.py` | écrit, testé |

## 1. Déposer et compiler — sans interface graphique

La compilation ne demande **pas** de RDP :

```powershell
# sur le VPS, dans le dossier de données du terminal de DÉMO
metaeditor64.exe /compile:"...\MQL5\Scripts\CalendrierExport.mq5" /log
```

> ⚠️ **À faire sur le terminal de DÉMO, pas celui du réel.** La base calendrier
> vient de MetaQuotes : elle est la **même** quel que soit le compte. Le pont
> Python tient la session MT5 du compte réel, et un conflit de session y est
> documenté (`feedback_mt5_bridge_session_conflict`). Aucune raison de risquer
> le réel pour une donnée identique.

> ⚠️ **Non vérifié : tous les serveurs ne servent pas le calendrier.** Le
> calendrier est téléchargé depuis MetaQuotes, et certains serveurs de courtier
> ne le relaient pas. Si c'est le cas du serveur de démo, l'export sortira à
> **zéro valeur** — et le dira : le script imprime
> `export termine : N valeurs, M mois parcourus, K mois en ECHEC`. Un zéro se
> voit, il ne passe pas pour un succès. Le repli serait alors d'exporter depuis
> le terminal du réel, en acceptant le risque de session.

## 2. L'exécuter — ⛔ le seul point qui demande un geste humain

Un **script** MQL5 se lance en le glissant sur un graphique. Il n'existe pas de
commande pour le déclencher à distance. Deux voies :

- **a. RDP, une fois** : ouvrir le terminal de démo, glisser
  `CalendrierExport` sur n'importe quel graphique, valider les dates. ~2 min.
- **b. `terminal64.exe /config:x.ini`** avec une section `[StartUp]
  Script=...` — mais cela **redémarre un terminal**. Acceptable sur la démo,
  **pas** sur le réel.

### Pourquoi je ne l'ai pas fait moi-même

- Mon poste ne joint pas le VPS : `ssh … 100.74.160.72` rend
  `Permission denied` **au niveau réseau** — ProtonVPN bloque `100.64.0.0/10`.
- La route **EC2 → VPS existe** : port 22 ouvert, `sshpass` présent sur l'EC2
  (vérifié le 04/10). Mais l'accès au fichier de mots de passe du VPS est
  refusé en mode automatique, et je ne contourne pas ce garde-fou.

👉 **Le geste de Xavier** : soit autoriser cette lecture, soit lancer le script
lui-même en RDP. Tout le reste de la chaîne est prêt et testé.

## 3. Importer — ⚠️ le fuseau se mesure, il ne se devine pas

```bash
# 1. regarder, sans rien écrire
python scripts/importer_calendrier_mql5.py --fichier calendrier_export.tsv

# 2. écrire, au fuseau que la mesure a retenu
python scripts/importer_calendrier_mql5.py --fichier … --ecrire
```

Un serveur MT5 typique tourne en **EET/EEST : UTC+2 l'hiver, UTC+3 l'été**. Un
décalage **fixe** appliqué à cinq ans d'historique se trompe donc d'une heure
la moitié de l'année — l'erreur déjà commise trois fois dans ce projet (spread
d'un instant appliqué à un banc entier, dérive du pont lue sur un tick périmé,
taux EUR/USD figé à 1,155). L'import mesure donc un **fuseau**, et `zoneinfo`
applique les vraies règles d'heure d'été instant par instant.

### ⛔ La fenêtre de recouvrement actuelle ne tranche pas

27/09 → aujourd'hui ne traverse **pas** le changement d'heure du **25
octobre**. Sur cette fenêtre, `Europe/Helsinki` (+3 l'été) et `Etc/GMT-3` (+3
toute l'année) apparient **exactement** les mêmes lignes — et divergent d'une
heure sur tout janvier. L'outil **refuse d'écrire** et nomme la ligne sur
laquelle les candidats se contredisent.

Deux sorties, les deux légitimes :

1. **attendre le 25 octobre** — la couverture ForexFactory traversera le
   changement d'heure et la mesure tranchera seule. Un test le prouve
   (`test_la_mesure_TRANCHE_des_que_la_fenetre_passe_le_25_octobre`).
2. **imposer le fuseau** en connaissance de cause :
   `--fuseau Europe/Helsinki` — l'outil annonce alors que la mesure est
   contournée.

## Les règles que l'import s'impose

- **Il n'écrit que le passé strictement antérieur** à la plus ancienne ligne
  ForexFactory. Celle-ci possède sa fenêtre et tout ce qui suit ; écrire
  par-dessus créerait le même événement sous deux identifiants différents
  (`mql5_<value_id>` contre `<ts>_<devise>_<titre>`) — un doublon invisible.
- **La provenance est inscrite** dans une colonne `source`, et les lignes
  ForexFactory existantes sont étiquetées au passage. Un chiffre dont on ne
  connaît pas la source est un chiffre d'air.
- **Un `actual` vide reste vide.** Le convertir en zéro confondrait « pas de
  chiffre publié » et « zéro », et fabriquerait des surprises nulles là où il
  n'y a aucune donnée.
- **Un export tronqué est refusé** : le nombre de champs est vérifié ligne par
  ligne. Le `/rates` du pont avait exactement ce défaut — il tronquait en
  silence, en gardant les bougies les plus **anciennes**.
- **Un réimport ne duplique pas** : les `value_id` du terminal sont stables.

## ⛔ Ce que ce chantier ne dit PAS

Il rend l'historique **éprouvable**, il ne prouve rien. Aucune hypothèse
événementielle n'est validée par le fait d'avoir les données : elle devra être
**pré-enregistrée** puis passée au banc comme les autres, et le laboratoire a
rendu 0 retenu sur 4 580 cellules pour l'or et 0 sur 493 pour le WTI.
