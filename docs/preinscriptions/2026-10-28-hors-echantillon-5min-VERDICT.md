# Verdict — hors échantillon `5min` : **INUTILISABLE**, par un défaut de ma pré-inscription

**Pré-inscription** : `b907ee8` · **Banc** : `f74db88`
**3 prédictions sur 5** — et les deux échecs sont « meilleurs que prévu », ce qui
est précisément le signal d'alarme.

⛔ **Ce banc ne confirme rien et ne réfute rien. Il est INVALIDE**, pour une
raison que ma pré-inscription n'avait pas prévue : **les deux bras ne reposent
pas sur la même donnée.**

## Le résultat brut, et pourquoi il est trop beau

```
n = 4 280 / 4 280   couverture 100 %   moteur vectorise 4 280 / 4 280

reel      +0,0902 R        placebo  -0,1467 R        ECART  +0,2369 R
cout      +0,0950 R        t = +11,7112        tirages battus 100,0 %
```

| | en échantillon | hors échantillon | rapport |
|---|---|---|---|
| écart réel−placebo | +0,0557 R | **+0,2369 R** | **×4,3** |
| `t` | +6,28 | **+11,71** | **×1,9** |
| `n` | 18 668 | 4 280 | ÷4,4 |

🔑 **Un effet qui GRANDIT hors échantillon, sur un échantillon 4,4 fois plus
petit, est une signature de défaut — pas de signal.** Le `t` attendu était
**+3,0** (`6,28 / √4,36`) ; j'ai obtenu **+11,71**, soit **3,9 fois** la
prédiction. C'est ce qui m'a fait chercher l'erreur au lieu de célébrer.

## 🔴 LE DÉFAUT : asymétrie de source entre les deux bras

- Le **bras réel** porte les `pnl_pct_net` **calculés en août par la
  production**, sur les bougies qui étaient disponibles **à l'époque**.
- Le **bras placebo** est simulé sur les bougies **d'aujourd'hui**.

**En échantillon, cette asymétrie n'existait pas** : les deux bras venaient du
rattrapage du 26/10, donc des **mêmes** bougies. C'est précisément cette
symétrie qui rendait le +0,0557 R propre.

### Contrôle de provenance — 24,5 % de désaccord

J'ai recalculé l'issue des 4 280 lignes vécues avec les bougies d'aujourd'hui
et comparé à l'issue **stockée** :

```
accord    : 3 232  (75,5 %)
DESACCORD : 1 048  (24,5 %)

TP1 stocke -> SL  recalcule : 638
SL  stocke -> TP1 recalcule : 409
=> +229 TP1 EXCEDENTAIRES dans le bras reel  (5,4 % de la population)
```

🔑 **Le désaccord est ASYMÉTRIQUE et favorise le bras réel.** À une géométrie
de 1,8 R, 229 gains supplémentaires déplacent l'espérance de
`229 / 4 280 × (1,8 + 1) ≈ **+0,15 R**` — soit **l'essentiel des +0,2369 R
mesurés**. Le « signal » hors échantillon est donc **largement un artefact de
provenance**.

### Et mon contrôle du moteur ne pouvait PAS l'attraper

`controle_moteur` a rendu **4 280 / 4 280**. Il compare le moteur **vectorisé**
à `simulate_trade_forward` **sur les mêmes bougies d'aujourd'hui** : il valide
l'**instrument**, pas la **provenance** de la donnée. ⛔ Un contrôle vert sur
la mauvaise question rassure à tort.

## Ce que je retire, et ce qui tient

- ⛔ **Le hors échantillon est INUTILISABLE.** Pas « confirmé », pas
  « évaporé » : la mesure ne répond pas à la question posée.
- ✅ **Le résultat EN échantillon n'est pas touché** : ses deux bras partageaient
  la source. **+0,0557 R, `t = +6,28`, 200/200** reste le seul chiffre propre —
  et il reste **non répliqué**.
- 🔴 **Donc rien n'a changé sur le fond** : le signal `5min` est mesuré une
  fois, sur un régime, et son hors échantillon reste à faire.

## 🔬 Ce qu'il faut faire, et c'est précis

**Rétablir la symétrie des sources**, deux voies :

1. **Rejouer les issues d'août depuis les bougies d'aujourd'hui** — c'est-à-dire
   rattraper les 4 280 lignes vécues comme on a rattrapé le reste. Les deux
   bras partageraient alors la source, et la période resterait disjointe. ✅
   **C'est la voie courte, et elle est disponible maintenant.**
2. **Attendre le hors échantillon PROSPECTIF** (~4 000 setups vers le
   13 novembre). La réconciliation réparée résout désormais via Binance, donc
   la même source que le placebo : la symétrie y est **native**.

⚠️ La voie 1 cesse d'être un test du « chemin de résolution » et devient un
test de **période seule**. C'est moins, mais c'est propre — et c'était de toute
façon l'essentiel de ce que ce banc visait.

## ⚠️ Deux points d'outillage, et je ne les corrige pas maintenant

1. **`or-verdict` refuse ce résultat sur la FORME** : il ne sait pas lire
   `abs(champ) < n` à un seul champ, seulement `abs(a − b) < n`. C'est une
   lacune réelle, identique à celle du `champ_a <op> champ_b` trouvée plus tôt.
   ⛔ **Je ne la corrige pas dans le même geste qu'un résultat auquel je ne
   crois pas** : réparer un juge pour ouvrir la voie à une publication est
   exactement le mouvement dont il faut se méfier. À faire à froid.
2. **Ma pré-inscription aurait dû exiger la symétrie des sources** dans sa
   condition de validité, au même titre que l'égalité des `risk_pct`. Elle
   vérifiait que le placebo reproduisait la **géométrie** du réel, pas sa
   **provenance**. C'est la leçon à emporter.

## L'antériorité, pour mémoire

Banc partagé : `or-preinscription` refuse l'antériorité du **fichier**
(`da056c4`, créé pour le `1d`) alors que le critère `b907ee8` précède bien
l'**adaptation** (`f74db88`). Dit en clair, comme pour le `5min`.
