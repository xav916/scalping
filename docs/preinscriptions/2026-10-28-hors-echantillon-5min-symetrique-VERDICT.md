# Verdict — hors échantillon `5min` symétrique : **le signal RÉPLIQUE, et la stratégie PERD**

**Pré-inscription** : `d591d42` · **Banc** : `b38f899` · **`or-verdict` : PUBLIABLE**
**5 prédictions sur 5.** Première fois sur ce mur.

## Le résultat

```
n = 4 280 / 4 280      couverture 100,00 %      moteur vectorise 4 280 / 4 280
bras reel RECALCULE : 24,5 % de desaccord avec le stocke (1 048 / 4 280)

reel    -0,0593 R     placebo -0,1467 R     ECART  +0,0874 R
conv. B -0,0597 R     TIMEOUT +0,7219 R     cout   +0,0950 R
t contre placebo : +4,3184        tirages battus : 100,0 %
```

| prédit **avant** la mesure | mesuré |
|---|---|
| réel ≈ **−0,0596 R** | **−0,0593 R** |
| écart ≈ **+0,0871 R** | **+0,0874 R** |
| `t` ≈ **+4,3** | **+4,3184** |
| désaccord **≥ 20 %** | **24,5 %** |

## 🔑 Ce que la correspondance au millième prouve — et ce qu'elle ne prouve PAS

✅ **Elle valide mon diagnostic de l'artefact.** La valeur attendue venait d'une
soustraction : `+0,0902 (stocké) − 229/4 280 × 2,8 (artefact compté) = −0,0596`.
Obtenir **−0,0593** confirme que les +229 TP1 excédentaires expliquaient bien
l'essentiel des +0,2369 R du 27/10.

⛔ **Elle ne valide pas le signal.** Cette prédiction n'était pas dérivée d'une
théorie du `5min` : elle était dérivée du **résultat asymétrique moins l'artefact
mesuré**. C'est un contrôle de **cohérence comptable**, pas une prédiction
indépendante. Le soutien du signal tient aux seules clauses d'admission —
`écart > 0`, `t > 2`, `200/200` — qui étaient déjà vraies en échantillon.

## ✅ La réplication, et sa portée exacte

| | en échantillon | hors échantillon |
|---|---|---|
| période | 20/08 → 27/10 | **05 → 19/08** (disjointe) |
| `n` | 18 668 | 4 280 |
| écart réel−placebo | +0,0557 R | **+0,0874 R** |
| `t` | +6,28 | **+4,32** |
| tirages battus | 100 % | **100 %** |
| **espérance nette** | **+0,0014 R** | **−0,0593 R** |

🔑 **Le `t` a RÉTRÉCI**, de +6,28 à +4,32. C'est le comportement attendu d'un
effet réel sur un échantillon 4,4× plus petit (`6,28/√4,36 ≈ 3,0` à effet
constant). ⚠️ **C'est l'inverse exact de l'alerte du 27/10**, où le `t` avait
GRANDI à +11,71 — et c'est pourquoi je crois celui-ci et pas celui-là.

## ⛔ Et la stratégie PERD hors échantillon : **−0,0593 R**

C'était la prédiction n°3, dite d'avance : **le signal peut tenir pendant que la
stratégie perd.** Elle tient, et le mécanisme est entièrement arithmétique :

| | en échantillon | hors échantillon | rapport |
|---|---|---|---|
| `risk_pct` médian | 0,5058 % | **0,2106 %** | **÷2,40** |
| coût médian en R | +0,0395 R | **+0,0950 R** | **×2,40** |

🔑 **Le coût n'a pas augmenté : c'est le `R` qui a rétréci.** Les setups d'août
ont des stops **2,4× plus serrés**, donc le même spread pèse 2,4× plus en unités
de risque. `0,0395 × 2,40 = 0,0948` contre **0,0950** mesuré — l'égalité
tient à **0,2 %** : le coût par trade n'a pas bougé d'un cheveu, seule son
expression en `R` a changé.

⚠️ **Conséquence méthodologique que je n'avais pas vue :** comparer deux écarts
**en R** entre deux périodes dont les distances de stop diffèrent d'un facteur
2,4 **n'est pas comparer la même grandeur**. Une part de la croissance de
l'écart (+0,0557 → +0,0874) est un changement d'**unité**, pas de signal. ⇒ La
réplication porte sur le **signe et la significativité**, pas sur la **taille**.

## 🔴 `or-verdict` valide AUSSI le résultat que j'ai déclaré inutilisable

Pour que la correction du juge ne soit pas appliquée au seul cas qui m'arrange,
je l'ai rejouée sur les deux :

| résultat | `or-verdict` |
|---|---|
| asymétrique du 27/10 (**artefact**, `t = +11,71`) | **PUBLIABLE** |
| symétrique (celui-ci) | **PUBLIABLE** |

⛔ **Le juge ne distingue pas les deux.** Il vérifie la conformité d'un résultat
à son critère ; il ne voit pas que les deux bras venaient de données
différentes. **Rien dans l'outillage n'a attrapé l'artefact — c'est la
prédiction chiffrée d'avance (`t ≈ +3,0`) qui l'a attrapé.** Je compte donc le
`PUBLIABLE` de ce banc pour ce qu'il vaut : une vérification de forme, pas une
caution de fond.

### La correction du juge, et quand je l'ai faite

`abs(champ) < n` à un seul champ était illisible ; deux verdicts avaient été
refusés sur cette **forme**. ⛔ **J'ai refusé de corriger le 27/10, quand le
résultat concerné était douteux, et j'ai corrigé maintenant, quand un résultat
m'arrange.** Cet ordre est en soi suspect. Les deux garanties posées :
la correction est **appliquée aux deux résultats** (ci-dessus), et elle **ne
change aucun chiffre** — elle laisse seulement lire une forme qui aurait
toujours dû l'être.

## ⚠️ Limites, dont deux neuves

- 🔴 **Les observations ne sont PAS indépendantes.** Fenêtres de **96 h** sur des
  barres de **5 min** : deux setups consécutifs se recouvrent presque
  entièrement. Un `t = +4,32` lu comme « p < 0,0001 » **surestime** la
  certitude. ✅ Atténuation réelle : le placebo tire dans la **même** structure
  de recouvrement, donc la comparaison reste appariée — mais aucun test n'a
  mesuré ce qu'il reste d'information indépendante. **À faire.**
- ⚠️ **Asymétrie résiduelle, COMMUNE AUX DEUX MESURES** : les prix d'entrée, les
  stops et les objectifs ont été décidés en août sur des prix d'époque, et sont
  jugés sur des bougies re-téléchargées. **C'est une limite de toute la série,
  pas un défaut introduit ici**, et elle mérite son propre test.
- **Période contiguë** (05 → 19/08), immédiatement avant l'échantillon : ce
  n'est pas un régime lointain. Le **prospectif du 13 novembre** reste le test
  décisif, et sa symétrie de source y sera **native**.
- **Crypto à 99,85 %**, un seul instrument de fait. Rien n'est établi ailleurs.
- Les issues d'août **restent en base** : le recalcul a vécu en mémoire.

## Ce qui est acquis, et ce qui ne l'est pas

✅ **ACQUIS** — l'instant d'entrée du `5min` bat le hasard sur **deux périodes
disjointes**, mesuré avec les deux bras sur la même donnée. **Première
réplication de ce mur.**

⛔ **PAS ACQUIS** — que ça se gagne. **−0,0593 R hors échantillon**, **+0,0014 R
en échantillon** : sur les deux périodes mesurées, la stratégie va de
l'équilibre à la perte. Le signal existe et **ne franchit pas le coût**.

🛑 **Je ne propose pas de réarmer l'IA.** REM-002 reste `DISARMED_MANUALLY`.
