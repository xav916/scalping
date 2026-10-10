# Route `/ticks` sur le pont du VPS — DÉPLOYÉE ET VÉRIFIÉE

**Écrite et déployée le 2026-10-10.** Permission accordée explicitement par
Xavier. Le verdict de la mesure est en bas de ce fichier.

## Pourquoi cette route

Le document GOLD MICROTRADER V1 (§9) fonde un signal sur
`TickImbalance = (UpTicks − DownTicks) / (UpTicks + DownTicks)`.

🔑 C'est le **seul** élément de ce document qui n'a pas pu être réfuté le
2026-10-10, **faute de donnée** : `/rates` ne rend que `tv`, le nombre **total**
de ticks d'une bougie, jamais sa répartition. Toutes les autres pistes de
direction ont été fermées ce jour-là — 22 motifs sur M1, 248 cellules de labo
M5, 250 en M1, 37 indicateurs, le dollar, les taux, le VIX, le SPX, le
calendrier économique.

⇒ Cette route répond à **une** question mesurable : **les ticks d'un CFD sur
l'or portent-ils l'information acheteur / vendeur ?**

## Ce que la route fait, et ne fait pas

✅ **Lecture seule.** `GET /ticks?pair=&from=&to=&resume=`. Elle appelle
`mt5.copy_ticks_range` et rend du JSON. **Aucun ordre, aucune modification,
aucune écriture.** C'est la seule raison pour laquelle elle peut exister à cet
endroit.

Elle calque `/rates` ligne pour ligne : `@require_api_key`,
`ensure_mt5_connected`, `resolve_symbol`, conversion UTC → heure serveur par
`_decalage_serveur_sec()`, découpage en tranches, dédoublonnage, plafond,
`suite_from`, et le même `decalage_serveur_sec` dans la réponse.

🔑 **Elle rend DEUX classifications côte à côte** :

1. **par les drapeaux** `TICK_FLAG_BUY` / `TICK_FLAG_SELL` — le vrai sens de la
   transaction, celui du §9 ;
2. **par la variation du bid** (règle classique uptick / downtick) — toujours
   disponible, mais c'est un **substitut**.

Et un champ explicite, `resume.sens_reel_disponible`, qui dit si les drapeaux
existent. ⚠️ Sur un CFD il n'y a pas de carnet centralisé : ils peuvent ne
**jamais** apparaître, et c'est exactement ce qu'on vient vérifier. `resume=1`
rend les comptes **sans** le détail, pour répondre sans télécharger des
centaines de milliers de lignes.

## État de la préparation

| étape | état |
|---|---|
| route écrite, lecture seule | ✅ `route_ticks.py`, 7 986 octets, 189 lignes |
| calquée sur `/rates` | ✅ mêmes décorateurs, mêmes conventions, même `suite_from` |
| copie du pont vérifiée | ✅ sha256 `B85EC3B0…0309`, 214 112 octets, identique à la production |
| patch appliqué en binaire | ✅ 214 112 → **222 098** octets, soit **+7 986** exactement |
| reste du fichier intact | ✅ vérifié **octet pour octet** (début et fin) |
| syntaxe | ✅ `py_compile` passe |
| fins de ligne | ✅ le pont est en **LF pur** (0 CRLF, 4 729 LF) — mesuré, pas supposé |

⚠️ **Ce dernier point a failli tout casser** : mon premier jet réécrivait le
fichier en CRLF, ce qui aurait modifié **chaque ligne** du pont. C'est le
passage en binaire qui l'a attrapé.

## La procédure de déploiement, à exécuter

Fenêtre sûre : **marché fermé** (samedi), **0 position ouverte**, équité
517,11 €. Le pont tourne en tâche planifiée `ScalpingBridge_Live`
(`pythonw.exe C:\Scalping\mt5-bridge-live\bridge.py`).

```bash
# 1) depuis l'EC2 — recuperer le pont et verifier qu'il n'a pas bouge
cd /tmp/pontpatch
scp -i ~/.ssh/vps_bridge Administrator@100.74.160.72:'C:/Scalping/mt5-bridge-live/bridge.py' ./br4.sauf
sha256sum br4.sauf      # doit valoir b85ec3b0...0309

# 2) patcher en binaire, et verifier
python3 patcher.py      # doit dire +7986, INTACT, et compile

# 3) SAUVEGARDER sur le VPS avant de toucher
ssh -i ~/.ssh/vps_bridge Administrator@100.74.160.72 \
  'copy C:\Scalping\mt5-bridge-live\bridge.py C:\Scalping\mt5-bridge-live\bridge.py.bak-20261010'

# 4) deposer la version patchee
scp -i ~/.ssh/vps_bridge ./bridge_patche.py \
  Administrator@100.74.160.72:'C:/Scalping/mt5-bridge-live/bridge.py'

# 5) relancer la tache planifiee
ssh -i ~/.ssh/vps_bridge Administrator@100.74.160.72 \
  'schtasks /End /TN ScalpingBridge_Live && schtasks /Run /TN ScalpingBridge_Live'

# 6) VERIFIER, dans cet ordre — /health et /rates AVANT /ticks
#    (si /rates est casse, revenir au point 7 immediatement)
curl -s -H "X-API-Key: $CLE" "$PONT/health"   | head -c 200
curl -s -H "X-API-Key: $CLE" "$PONT/rates?pair=XAU/USD&timeframe=M5&from=2026-10-09T00:00:00Z&to=2026-10-09T01:00:00Z" | head -c 200
curl -s -H "X-API-Key: $CLE" "$PONT/ticks?pair=XAU/USD&from=2026-10-09T12:00:00Z&to=2026-10-09T12:05:00Z&resume=1"
```

## Le retour en arrière, en une commande

```bash
ssh -i ~/.ssh/vps_bridge Administrator@100.74.160.72 \
  'copy /Y C:\Scalping\mt5-bridge-live\bridge.py.bak-20261010 C:\Scalping\mt5-bridge-live\bridge.py && schtasks /End /TN ScalpingBridge_Live && schtasks /Run /TN ScalpingBridge_Live'
```

⛔ **Ne pas toucher** `C:\Scalping\mt5-bridge\` (sans `-live`) : c'est le pont
de la démo, dont le terminal est **parké** depuis le 2026-10-07.

## Ce que la mesure dira ensuite

Un seul appel en `resume=1` sur une heure de cotation suffit à trancher :

- `resume.sens_reel_disponible = true` ⇒ le §9 est **testable**, et c'est la
  dernière piste de direction encore ouverte ;
- `= false` ⇒ l'information acheteur / vendeur **n'existe pas** chez ce
  courtier, le §9 est **inapplicable**, et il faudra le dire ainsi : non pas
  « réfuté », mais **« impossible à éprouver sur ce compte »**.

⚠️ Et le rappel qui vaut pour toute direction trouvée : la géométrie 2 €/20 €
rend le sens **sans valeur** (49,83 % de réussite implicite à bornes
symétriques, sur 64 062 détections). Même un order flow informatif ne serait
exploitable **qu'avec un autre couple objectif/stop**.

---

# DÉPLOYÉ ET VÉRIFIÉ — le 2026-10-10 à 21h53 UTC

Permission accordée explicitement par Xavier. Procédure suivie étape par
étape, chacune vérifiée avant la suivante.

| étape | résultat |
|---|---|
| 1. pont récupéré du VPS | `b85ec3b0…0309`, 214 112 o — **identique** à ma copie |
| 2. route transférée | 7 986 o, `7892dfbb…` — **même hash** qu'en local |
| 3. patch sur l'EC2 | `29F0C6E2…` — **même hash** que mon patch local |
| 4. sauvegarde VPS | `bridge.py.bak-20261010-avant-ticks`, 214 112 o |
| 5. dépôt sur le VPS | `29F0C6E2…`, 222 098 o — **vérifié sur place** |
| 6. redémarrage | `schtasks /End` + `/Run` sur `ScalpingBridge_Live` |
| 7. `/health` | **200**, `demarre_a = 2026-10-10T21:53:31` ⇒ a bien redémarré |
| 8. `/rates` | **200**, n = 12 ⇒ **l'existant est intact** |
| 9. `/ticks` | **200**, 893 ticks sur 5 minutes |

🔑 Identité au bit près de ma machine → EC2 → VPS, vérifiée à trois reprises.

## ⛔ ET LA RÉPONSE À LA QUESTION, SANS AMBIGUÏTÉ

    893 ticks sur 5 minutes (XAU/USD, 09/10 12h00-12h05 UTC)

    drapeaux :  bid 892   ask 887   buy 0   sell 0   last 0   volume 0
    sens_reel_disponible : FALSE
    imbalance_drapeaux   : null
    imbalance_bid        : +0,0281   (458 hausses, 433 baisses, 1 égal)

⇒ **`buy = 0`, `sell = 0`, `last = 0`, `volume = 0` sur 893 ticks.**
L'information **acheteur / vendeur n'existe pas** sur ce CFD : le flux ne porte
que des mises à jour de **bid** et d'**ask**.

🔑 Le `TickImbalance` du §9, tel que le document le définit — compter des
**transactions** — est donc **impossible à éprouver sur ce compte**. Ce n'est
pas « réfuté » : c'est **inapplicable**, et il faut le dire ainsi.

🔑 Et ce qui reste disponible est exactement le **substitut** que j'avais déjà
construit et mesuré le matin même (position de la clôture dans le range), qui
échouait partout : −0,15 à +0,18, aucun |t| > 2. **La boucle est fermée.**

## ⓘ CE QUE LA ROUTE APPORTE QUAND MÊME

Deux choses qui n'existaient pas avant :

1. **la densité réelle du flux** — 893 ticks en 5 minutes, soit ~3 ticks par
   seconde sur l'or ;
2. **un imbalance calculé sur les VRAIS ticks** (+0,0281 ici), et non sur la
   position de la clôture dans une bougie. C'est un **meilleur** substitut que
   celui que j'ai mesuré le matin.

⇒ La seule chose encore testable sur cette piste : **refaire la mesure du §9
avec l'imbalance des vrais ticks**. ⚠️ Mais le rappel tient — la géométrie
2 €/20 € rend le sens sans valeur (49,83 % à bornes symétriques sur 64 062
détections), donc même un imbalance informatif ne serait exploitable qu'avec
un autre couple objectif/stop.

## Le retour en arrière reste disponible

```bash
ssh -i ~/.ssh/vps_bridge Administrator@100.74.160.72 \
  'copy /Y C:\Scalping\mt5-bridge-live\bridge.py.bak-20261010-avant-ticks C:\Scalping\mt5-bridge-live\bridge.py && schtasks /End /TN ScalpingBridge_Live && schtasks /Run /TN ScalpingBridge_Live'
```
