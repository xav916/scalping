# Brancher un canal Telegram sur l'ingestion de signaux tiers

Conception du 2026-09-24. Demande : *« interpréter les conseils d'un canal Telegram
et trader en automatique avec l'outil »*.

## 0. Ce qui existe déjà, et ce qu'il reste à écrire

**Presque tout existe.** La conception du 2026-08-26 (`external_signals`) a posé la
question générale — *comment juger la sélection d'un tiers dans nos conditions* — et y
a répondu :

- `POST /api/signals/external` : route d'entrée, jeton en en-tête, motif de refus
  toujours rendu, rejeu traité en 200.
- `external_signals.ingerer()` : valide, dédoublonne sur `(source, external_id)`,
  construit le setup, et le passe à `send_setup()`.
- **Toutes les portes existantes s'appliquent ensuite** : admission, whitelist,
  confiance, horizon, motifs, coût, corrélation, plafond de risque, banc.

**Ce qu'il reste à écrire est un relais**, hors du backend : un service qui lit le
canal, interprète le message, et poste sur la route existante.

```
Canal Telegram ──► relais (interprétation) ──► POST /api/signals/external
                                                      │
                                                      ▼
                                          ingerer() ─► send_setup() ─► les portes
```

> 🔑 **L'interprétation vit dans le relais, jamais dans le backend.** La route attend
> du JSON structuré ; le parsing est une préoccupation séparée, avec son propre mode de
> panne. Les mettre ensemble ferait qu'une erreur d'interprétation corromprait le
> contrat HTTP, et qu'on ne pourrait plus mesurer l'un sans l'autre.

## 1. ⛔ Le préalable bloquant : `is_real_money`

**Ne branchez rien avant d'avoir corrigé R-25.**

`resolve_destinations` écarte les destinations réelles pour un setup externe :

```python
destinations = [d for d in destinations if not is_real_money(...)]
```

Mais `is_real_money('user:2')` rend **`False`**. Le verrou barre donc `admin_live` et
**laisse passer les comptes clients**. Brancher un canal tiers aujourd'hui, c'est
ouvrir l'exécution des appels d'un inconnu sur l'argent d'un client.

Correctif au même endroit que R-17 : « inconnue ⇒ fictive » est un défaut sûr pour une
notification et s'inverse pour une porte. Et un test qui fige le comportement, sinon le
défaut reviendra.

## 2. Le contrat, tel que le valide `external_signals`

| Champ | Obligatoire | Contrainte |
|---|---|---|
| `source` | ✅ | doit être une clé de `EXTERNAL_SIGNAL_TOKENS` |
| `external_id` | ✅ | unicité sur le **couple** `(source, external_id)` |
| `pair` | ✅ | — |
| `direction` | ✅ | `buy` ou `sell`, rien d'autre |
| `entry_price` | ✅ | numérique |
| `stop_loss` | ✅ | numérique |
| `take_profit` | ❌ | numérique si présent |

En-tête : `X-Signal-Token: <jeton de la source>`.

> 🔑 **`stop_loss` est obligatoire, et c'est une chance.** Un « conseil » qui ne porte
> pas de stop ne produit rien. La contrainte est déjà écrite : ne la contournez pas en
> déduisant un stop à la place de l'auteur.

> 🔑 **`external_id` = l'identifiant du message Telegram.** L'idempotence est alors
> gratuite : une re-livraison du même message ne peut pas produire un second ordre.

## 3. L'interprétation — la seule partie vraiment difficile

Le texte d'un canal est une **entrée non fiable qui produit des ordres**. Deux risques
distincts, à traiter séparément :

- **L'ambiguïté** — « XAU long, stop sous le range » n'a pas de stop numérique.
- **L'adversaire** — un canal compromis, usurpé, ou qui publie un message piégé.

### Les règles qui rendent ça tenable

1. **⛔ Refuser plutôt que deviner.** Un champ obligatoire absent ou ambigu ⇒ aucun
   signal émis, et une ligne de journal disant pourquoi. Jamais d'inférence de stop,
   d'entrée ou de sens.
2. **Whitelist des paires.** Le relais traduit les symboles du canal vers vos
   `WATCHED_PAIRS`. Symbole inconnu ⇒ refus. Pas de correspondance approximative.
3. **Bornes de vraisemblance, dans le relais :**
   - `stop_loss` du bon côté de `entry_price` selon le sens — une inversion est
     l'erreur de parsing la plus coûteuse ;
   - distance au stop dans une plage plausible pour l'instrument (le seuil placebo à
     0,1 % existe déjà en aval, mais R-16 montre qu'il n'est pas transposable) ;
   - `entry_price` cohérent avec le prix courant. La porte `price_divergence` le
     revérifiera à 0,5 % (§4.6.10), mais un refus tôt est plus lisible qu'un refus tard.
4. **Messages édités.** Telegram émet `edited_message`. **Les ignorer**, et les
   journaliser : un ordre déjà parti ne se dé-envoie pas. Une édition n'est pas un
   nouveau signal.
5. **Plafond par source.** Un canal qui déverse cinquante messages ne doit pas produire
   cinquante ordres. La route limite à 120/min ; posez un plafond par heure et par
   source dans le relais, plus bas.
6. **Si l'interprétation passe par un modèle de langage :** sortie en JSON strict contre
   un schéma, et **tout ce qu'il produit repasse par la validation numérique**. Du texte
   libre n'atteint jamais le chemin d'ordre. Une interprétation peu sûre ⇒ refus, pas
   une estimation.

## 4. La montée en charge, par étapes

| Étape | Ce qu'on fait | Ce qu'on apprend |
|---|---|---|
| **0** | Corriger `is_real_money` (R-25) + test | le verrou tient vraiment |
| **1** | Relais en place, source déclarée, paire en `OBSERVED` | **la qualité du parsing**, sans qu'un euro bouge |
| **2** | `declare()` au banc, puis démo | la sélection du canal vaut-elle quelque chose |
| **3** | 30 clôtures, contrefactuel, `bilan()` | le verdict |
| **4** | `set_state()` vers `TELEGRAM`, puis `AUTO_EXEC` — ou abandon | la décision |

> ⛔ **L'étape 1 n'est pas une formalité.** Mesurez d'abord le parsing : combien de
> messages produisent un signal, combien sont refusés, et combien sont **mal** traduits.
> Ce dernier chiffre demande de relire à la main un échantillon, et il ne s'obtient pas
> autrement. Un canal correctement interprété à 90 % dont les 10 % restants inversent le
> sens est pire qu'un canal inutilisable.

> ⛔ **Déclarer avant de mesurer.** Un canal est une nouvelle source de sélection : c'est
> un essai, il coûte +1 à `N` (1 237 aujourd'hui), et le déclarer après avoir vu le
> résultat c'est R-5 et R-8 une fois de plus.

## 5. Ce que la machine à états fait pour vous

`send_setup()` consulte `pair_admission_state`. Une paire en **`OBSERVED`** est
journalisée sans être exécutée — c'est exactement le mode « mesure seule » de
l'étape 1, et il n'y a rien à écrire pour l'obtenir.

`OBSERVED → TELEGRAM → AUTO_EXEC` est le chemin prévu. Le sauter serait remplacer une
mesure par une intuition.

## 6. Deux questions hors technique

- **Les conditions du canal.** S'il s'agit d'un service payant, exécuter
  automatiquement ses appels n'est pas toujours permis. À vérifier avant d'écrire le
  relais, pas après.
- **C-1.** Interpréter les conseils d'un tiers et les exécuter sur le compte d'un
  client est très exactement la configuration que le constat C-1 signale comme à
  qualifier au regard de MiFID/AMF. Sur vos propres comptes, la question ne se pose pas
  de la même façon.

## Références

- `backend/services/external_signals.py` — ingestion, conception du 2026-08-26
- `backend/app.py:2609` — `POST /api/signals/external`
- `backend/services/bridge_destinations.py:956` — le verrou d'argent réel
- `docs/audit-externe-2026-09-16.md` — R-25 (le verrou fuit), R-17, R-16, §4.6.10
