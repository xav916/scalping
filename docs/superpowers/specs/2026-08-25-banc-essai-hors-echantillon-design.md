# Banc d'essai hors-échantillon — conception

**Date** : 2026-08-25
**Statut** : validé, en implémentation
**Origine** : audit DSR/PBO du 2026-08-25 — la meilleure des 75 variantes rend un
Sharpe journalier de +0,1703 quand le plafond attendu sous H₀ après 75 essais vaut
+0,1925. `DSR = 0,350`.

---

## Le problème qu'il résout

Le journal de recherche compte **65 entrées**. Les quinze premières s'enchaînent en
`closed-positive` avec des profit factors annoncés de 1,24 à 5,60, un Sharpe de 1,59,
« système prod-ready », « +509 % sur 12M ». Le résultat en argent réel sur quatre
mois : **−982,67 €** sur 1 085 clôtures, taux de réussite 28,6 %.

L'écart entre ces deux chiffres **est** la mesure du surapprentissage. Il ne vient pas
d'une erreur de calcul dans un backtest : il vient de ce que soixante-cinq hypothèses
ont été essayées sur le même historique, et que la meilleure a été retenue parce
qu'elle était la meilleure.

> ⛔ **Sans compteur d'essais, la 76ᵉ variante paraîtra bonne pour exactement la
> raison qui a fait paraître bonnes les 75 précédentes.**

Le banc n'a pas pour objet de trouver un edge. Il a pour objet de rendre chaque
hypothèse future **jugeable**, et de refuser qu'une configuration passe en argent réel
sur la foi d'un chiffre qui ne survit pas au nombre de fois où on l'a cherché.

---

## Les trois décisions structurantes

### 1. La frontière hors-échantillon : le futur seul

Tout l'historique disponible a déjà été fouillé soixante-cinq fois. Une tranche
« scellée » de cet historique serait un mensonge : la période 2023 apparaît déjà
nommément dans les expériences 10, 11 et 15 du journal.

**Un essai ne peut être jugé que sur des clôtures postérieures à sa déclaration.**
Ce n'est pas une consigne, c'est une borne SQL : le banc refuse de servir l'antérieur.

Le coût est assumé — un verdict demande des semaines. C'est le prix du seul
hors-échantillon honnête qui reste.

### 2. Le compteur N : les variantes déclarées

`N = Σ variants_declared` sur **tous** les essais, y compris abandonnés et perdants.

Compter une entrée de journal pour un essai sous-estimerait N d'un ordre de grandeur :
l'expérience 8 à elle seule balayait neuf dimensions. C'est la définition de Bailey —
le plafond du hasard monte avec le nombre de configurations *essayées*, pas avec le
nombre de rapports *écrits*.

**N ne décroît jamais.** Abandonner un essai ne le rend pas.

### 3. La porte : elle refuse le passage à l'argent réel

Le banc rend un verdict consultatif sur tout, et bloque durement une seule chose :
promouvoir une configuration en `AUTO_EXEC` sur une destination qui engage de l'argent
réel, sans essai passé qui la couvre.

---

## Modèle de données

### `bench_trials` — le registre

| colonne | rôle |
|---|---|
| `id`, `slug` | identité |
| `declared_at` | **la frontière** : seules les clôtures postérieures comptent |
| `author` | qui déclare |
| `hypothesis` | l'affirmation, en clair |
| `selector` | JSON : `pairs`, `direction`, `min_confidence`, `destinations` |
| `variants_declared` | combien de configurations ce test balaie — alimente N |
| `min_sample` | clôtures requises avant tout verdict (défaut 30) |
| `declaration_hash` | SHA-256 des champs de déclaration |
| `status` | `open` \| `spent` \| `abandoned` \| `legacy` |
| `verdict`, `dsr`, `sr`, `n_obs`, `verdict_at` | écrits **une seule fois** |

**Pourquoi le hash.** Sans lui, on ajuste le sélecteur après avoir vu les données et
on recrée exactement le défaut qu'on prétend corriger. Le hash est revérifié au
verdict ; s'il a bougé, l'essai est nul.

### `bench_legacy_grants` — la clause d'antériorité

Une ligne par (paire, sens, destination) déjà en `AUTO_EXEC` au moment de
l'installation.

> ⚠️ **Sans cette clause, installer le banc arrête tout le trading** : rien
> aujourd'hui ne dispose d'un essai passé. C'est ce qui rend le banc installable sans
> rien casser — et c'est aussi sa limite : **il ne juge pas rétroactivement
> l'existant.**

---

## La porte — et le piège qu'elle doit éviter

La porte s'interpose dans `pair_admission_controller.set_state()`, sur l'acte de
promotion, pas sur chaque ordre.

Refuse si, cumulativement : `new_state == AUTO_EXEC` **et** la destination engage de
l'argent réel **et** aucun essai `spent`+`passed` ne couvre le couple **et** aucune
clause d'antériorité ne le couvre.

> ⛔ **`destination=None` signifie « toutes les destinations », donc INCLUT l'argent
> réel.** `destinations_registry.is_real_money(None)` rend `False` — c'est correct
> pour son usage (ne jamais supposer sur l'argent), et ce serait un trou béant ici :
> une promotion globale contournerait la porte en silence. Le dépôt a déjà payé ce
> défaut exact le 2026-08-04, quand `_normalize_destination` repliait une destination
> inconnue sur `None` et **élargissait** les permissions au lieu de les restreindre.
>
> **Pour la porte : `None` ⇒ argent réel.** Un test verrouille ce point.

Sortie de secours : `transitioned_by="admin_override"` passe, en journalisant en
`WARNING`. Une porte sans issue documentée est contournée par un `sed` sur la base,
et alors plus personne ne sait.

---

## Le verdict

Sur les clôtures éligibles — `closed_at > declared_at`, filtrées par le `selector` —
le banc calcule le rendement journalier rapporté au capital, puis :

- `SR` journalier, `T`, dissymétrie, aplatissement
- `SR0` attendu sous H₀ : `sqrt(var_SR) · [(1−γ)·Z⁻¹(1−1/N) + γ·Z⁻¹(1−1/(N·e))]`
- `DSR = Φ( (SR−SR0)·sqrt(T−1) / sqrt(1 − skew·SR + (kurt−1)/4·SR²) )`
- `passed = DSR > 0,95`

`var_SR` est la variance des Sharpe entre les variantes déclarées de l'essai ; à
défaut d'observation par variante, le banc reprend la variance mesurée sur la grille
de référence du 25/08 (0,006286) et l'inscrit dans le verdict comme telle.

Tant que `n_obs < min_sample`, statut `open` et **aucun chiffre rendu** — pas même à
titre indicatif. Un chiffre indicatif est un chiffre qui sera lu.

Le verdict est écrit une fois. `spent` est terminal.

---

## Périmètre

**Dans** : le registre, le compteur, la borne temporelle, le verdict DSR, la porte, un
CLI, l'amorçage du compteur depuis le journal.

**Hors** : aucune UI, aucun hook `scheduler`, aucune notification Telegram, aucun
rejeu d'historique. Le banc sert à savoir, pas à notifier.

---

## Ce que les tests verrouillent

1. Un essai ne peut pas être jugé sur des clôtures antérieures à sa déclaration.
2. Un sélecteur modifié après déclaration invalide l'essai.
3. `N` ne décroît pas ; abandonner un essai ne rend pas ses variantes.
4. Un essai `spent` ne se rejoue pas.
5. Sous `min_sample`, aucun chiffre n'est rendu.
6. La porte refuse une promotion `AUTO_EXEC` en argent réel non couverte.
7. **La porte traite `destination=None` comme de l'argent réel.**
8. La porte laisse passer une configuration couverte par la clause d'antériorité.
9. La porte n'entrave pas les états non-`AUTO_EXEC` ni les destinations fictives.
10. Le DSR reproduit la valeur de référence du 25/08 : `0,350` à `N = 75`.

---

## Ce que le banc ne fait pas

Il ne trouve pas d'edge, il n'en promet pas, et il ne dit pas si le moteur peut en
avoir un. Il rend seulement impossible d'en affirmer un sans l'avoir mesuré sur des
données que personne n'avait vues au moment où l'hypothèse a été écrite.

Il reste possible qu'il n'y ait pas d'edge à trouver sur ces instruments, à ces
horizons, pour un compte de cette taille chez un courtier retail. Le banc est
précisément ce qui permettra de le constater au lieu de continuer à chercher.
