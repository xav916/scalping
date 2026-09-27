# Un second terminal MT5, isolé, pour la copie de signaux MQL5

Conception du 2026-09-27. Objectif : s'abonner à un fournisseur MQL5 Signals
**sans qu'aucune de ses positions ne touche le système de scalping**.

---

## 0. Pourquoi l'isolation n'est pas une précaution, mais une nécessité

`R-29` : **le bridge ne distingue pas ses positions de celles d'un tiers.**
`MAGIC_NUMBER` est écrit sur chaque ordre envoyé et n'est jamais relu — `.magic`
n'apparaît dans aucun chemin de lecture, et les trois `positions_get()` sont sans
filtre. Une position copiée sur le même compte serait donc traitée comme sienne :

| Ligne | Ce qu'une position étrangère déclenche |
|---|---|
| `bridge.py:664` | elle compte dans le drawdown journalier et le plafond — donc peut ouvrir un `plafond_arbitrage` |
| `bridge.py:784` | elle consomme le budget de `_risque_engage_par_poche`, donc **bloque les ordres du système** |
| `bridge.py:1868` | elle entre dans la boucle de surveillance : **le bridge déplacerait ses stops** et la clôturerait partiellement |

Le dernier désynchroniserait la copie, ce que MQL5 Signals n'attend pas.

> 🔑 **L'isolation porte sur le COMPTE, pas sur le terminal.** Deux terminaux sur
> le même compte n'isolent rien : le solde, la marge, la perte journalière et le
> risque engagé sont des propriétés du compte. C'est le compte séparé qui
> protège ; le second terminal n'est que le moyen de l'exploiter.

---

## 1. Ouvrir un second compte IC Markets

Un compte **distinct**, dédié à la copie. Dimensionnez-le comme une expérience :
ce que vous êtes prêt à perdre en entier pour savoir ce que vaut le fournisseur.

⚠️ Contraintes du service, lues dans les règles MQL5 :

- levier plafonné à **1:500** ;
- un fournisseur ne peut pas diffuser depuis un compte **démo ou cent** — au
  moins risque-t-il de l'argent réel ;
- il est **recommandé** (pas obligatoire) que fournisseur et abonné soient sur le
  **même serveur de trading**, pour limiter les échecs d'exécution.

---

## 2. Installer un second terminal — le mode PORTABLE

MT5 range ses données dans `%APPDATA%\MetaQuotes\Terminal\<hash>`, partagé entre
instances. Le mode portable les range **dans le dossier d'installation**, ce qui
rend les deux terminaux réellement indépendants.

```powershell
# 1. Installer une SECONDE copie dans un dossier distinct
#    (l'installeur IC Markets, en changeant le repertoire cible)
#    ex. C:\MT5-Copie\   a cote de l'installation existante

# 2. Lancer CE terminal en mode portable, et seulement lui
C:\MT5-Copie\terminal64.exe /portable
```

Créez un raccourci portant `/portable` et utilisez **toujours** celui-là. Un
lancement sans le drapeau ferait retomber ce terminal sur les données partagées.

---

## 3. ⛔ Le réglage qui évite l'accident : `MT5_TERMINAL_PATH`

C'est le point le plus dangereux du chantier, et le dépôt l'a déjà rencontré le
2026-06-12 :

> « Sans path, le Python lib attache au **1er terminal trouvé via registry**, ce
> qui crée un conflit. Avec `MT5_TERMINAL_PATH` set, chaque `bridge.py` attache à
> son propre terminal. »
> — `mt5-bridge/bridge.py:74-78`

Dès qu'il existe **deux terminaux**, `MT5_TERMINAL_PATH` cesse d'être optionnel :

```
MT5_TERMINAL_PATH=C:\Program Files\MetaTrader 5 IC Markets\terminal64.exe
```

Le chemin du terminal **de trading**, jamais celui de la copie. Sans lui, le
bridge peut s'attacher au terminal de copie et envoyer vos ordres sur le mauvais
compte.

**Éprouvez-le** : au démarrage, le bridge journalise le compte auquel il s'est
attaché.

```
MT5 connecté : login=<...> server=<...> balance=<...>
```

Vérifiez que ce `login` est bien celui du compte de **trading**. Tant que ce
n'est pas vérifié, ne relancez pas l'exécution automatique.

---

## 4. Le terminal de copie ne porte RIEN du système

- **aucun Expert Advisor** — pas de `ScalpingRadarEA.mq5`, pas de `.ex5` dans
  `MQL5\Experts\` ;
- **aucun `bridge.py`** attaché ;
- il n'apparaît dans **aucune** destination du registre.

Le seul automatisme autorisé sur ce terminal est la copie du signal.

---

## 5. S'abonner et régler la taille

Dans le terminal de copie : onglet **Signals**, choisir le fournisseur,
s'abonner, puis régler dans les options de copie :

- **le pourcentage d'équité** à engager. C'est le réglage qui décide de votre
  exposition — la copie se met à l'échelle de votre compte, pas de celui du
  fournisseur ;
- autoriser le trading automatique sur ce terminal.

⚠️ **Le terminal doit rester connecté en permanence.** Les règles MQL5 sont
explicites : un signal n'est copié que si la plateforme est connectée au serveur.
Une machine qui redémarre sans ouverture de session automatique manque les
signaux, en silence.

C'est le même couplage que `R-24`, sur un autre terminal : voir
`deploy/bridge-windows-ec2.md` §5 pour l'ouverture de session automatique.

---

## 6. Vérifier l'isolation, avant de laisser tourner

| Vérification | Attendu |
|---|---|
| `login` journalisé par le bridge | celui du compte de **trading** |
| Positions visibles dans le terminal de trading | **aucune** venant du signal |
| Rapport `bridge` (`deploy/diag-lecture-seule.sh`) | positions ouvertes inchangées |
| Solde du compte de copie | évolue seul, sans effet sur le plafond journalier du compte de trading |

---

## 7. Ce que ça ne résout pas

**Le choix du fournisseur.** Votre propre `PBO = 0,579` chiffre la sélection sur
historique affiché comme perdante six fois sur dix. Les trois chiffres à lire, et
pas dans l'ordre où la page les présente :

1. **semaines de trading** — sous six mois, il n'y a rien à lire ;
2. **drawdown en ÉQUITÉ**, pas en solde. L'écart entre les deux trahit les
   positions perdantes laissées ouvertes : signature de la martingale, qui donne
   une courbe lisse jusqu'au jour où elle ne l'est plus ;
3. **la distribution des trades**, pas leur moyenne. Beaucoup de petits gains et
   de rares pertes énormes est le profil qui ruine, et il produit les plus belles
   statistiques jusqu'au dernier jour.

Et le coût : **5 à 5 000 $/mois**, la plupart entre 30 et 50 $, dont 20 % pour
MetaQuotes.
