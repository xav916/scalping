"""Contrôle par entrées aléatoires — teste si une sélection de trades bat le hasard.

## Pourquoi

Les portes de promotion (`pair_admission_controller.PROMOTE_MIN_PF`,
`PROMOTE_MIN_WR_PCT`) jugent une sélection de trades sur des seuils absolus
(facteur de profit ≥ 1.3, taux de réussite ≥ 45 %). Démontré le 2026-08-05
(voir `scratchpad/test-difference-directe.md` et
`scratchpad/controle-aleatoire-etf-production.md`) : des entrées prises au
hasard, de même sens et même distribution temporelle que les vrais setups,
franchissent ces mêmes seuils sur plusieurs marchés haussiers — les seuils
absolus ne discriminent pas une vraie compétence d'une dérive de marché.

Ce module porte, en composant testé et appelable, la méthode qui répond à la
question qui compte : **cette sélection bat-elle une entrée aléatoire
comparable, de combien, et avec quelle certitude ?** — pas « dépasse-t-elle un
seuil absolu ? ».

## Méthode (portée à l'identique depuis les scripts jetables, pas réinventée)

Trois points de méthode, chacun avec sa raison d'être — voir
`test_difference_directe.py::paired_delta_bootstrap` et le rapport associé :

1. **Entrées aléatoires de même sens et même distribution temporelle** que les
   setups réels — appelant responsable (pas ce module, qui est aveugle à la
   provenance des trades). Comparer à un autre ensemble de créneaux
   comparerait deux populations différentes.
2. **Bootstrap par blocs temporels APPARIÉ** (`paired_block_bootstrap_delta`) :
   on tire des blocs de b positions consécutives dans l'axe temporel du
   domaine (= le recensement aléatoire), et pour chaque tirage on recalcule
   LES DEUX moyennes (aléatoire et pattern) sur les positions tirées, avant
   de prendre leur différence. Rééchantillonner les deux groupes
   indépendamment (`independent_block_bootstrap_delta`, conservée ici
   uniquement pour la comparaison / la preuve de non-régression) casse la
   dépendance des trades qui se chevauchent et sous-estime l'incertitude
   réelle (IC trop étroit) — voir le test dédié dans
   `backend/tests/test_random_entry_control.py`.
3. **La statistique testée est Δ = espérance(pattern) − espérance(aléatoire)**,
   avec son propre intervalle de confiance et sa propre valeur p — pas deux
   IC séparés comparés à l'œil (critère suffisant mais pas nécessaire,
   conservateur, source de faux « non tranchable »).

## Contraintes de conception

- **Module pur** : aucune dépendance à une base de données ou au réseau. Les
  fonctions ci-dessous ne prennent que des `TimedTrade` déjà en mémoire — la
  récupération des trades (DB, filtre, etc.) est la responsabilité de
  l'appelant, ailleurs.
- **Inconnu vaut `None`, jamais `0.0`** (règle du dépôt) : un échantillon
  insuffisant pour construire un intervalle de confiance rend un résultat
  explicitement indéterminé (`significant=None`, `ci95_low=None`, etc.), pas
  un delta à zéro ni un `significant=False` qui serait un faux négatif
  silencieux.
- **Aucun effet de bord** : ce module calcule, il ne décide pas et ne
  persiste rien. La décision de promotion reste ailleurs (pas dans ce
  fichier).
- **Reproductible** : chaque fonction bootstrap prend une graine explicite et
  utilise une instance `random.Random` locale — jamais l'état global de
  `random` — pour que le même appel produise toujours le même résultat.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from statistics import mean, stdev
from typing import Optional, Sequence

# Constante de l'analyse de puissance : z_(0.975) + z_(0.80) ≈ 2.80
# (voir §1.5 de test-difference-directe.md). MDE80 = écart minimum détectable
# à 80% de puissance, pour les cellules dont l'IC inclut 0.
_Z_POWER80 = 2.80

# Nombre minimum de tirages bootstrap valides (delta calculable) en dessous
# duquel la distribution empirique est jugée trop pauvre pour être fiable.
_MIN_VALID_BOOT = 50


@dataclass(frozen=True)
class TimedTrade:
    """Un trade réduit à sa clé temporelle et son R multiple.

    `key` est l'identité utilisée pour apparier pattern et domaine (même
    horodatage d'entrée dans la méthode d'origine) — n'importe quel objet
    hashable et ordonnable (datetime, int, tuple...) convient. `r_multiple`
    est le gain/perte exprimé en multiples du risque pris (R = pct / risk).
    """

    key: object
    r_multiple: float


@dataclass(frozen=True)
class RandomControlResult:
    """Résultat d'un test « cette sélection bat-elle le hasard ? ».

    Tous les champs statistiques (`delta_observed`, `ci95_low`, `ci95_high`,
    `p_value`, `significant`, `mde80`) sont `Optional` : `None` signifie
    « indéterminé avec les données fournies », jamais une valeur neutre
    déguisée. Consulter `insufficient_reason` pour savoir pourquoi.
    """

    n_pattern: int
    n_random: int
    delta_observed: Optional[float]
    ci95_low: Optional[float]
    ci95_high: Optional[float]
    p_value: Optional[float]
    significant: Optional[bool]
    mde80: Optional[float]
    n_boot_valid: int
    n_boot_requested: int
    n_boot_skipped: int
    block_size: int
    seed: int
    insufficient_reason: Optional[str] = None


def r_multiple(pct: float, risk_pct: float) -> Optional[float]:
    """R = pct / (risk_pct × 100) — formule identique aux scripts source.

    ⚠️ Déviation volontaire vis-à-vis de `test_difference_directe.py` /
    `etf_20y_random_control.py`, qui renvoyaient `0.0` quand `risk_pct <= 0`
    (risque nul ou négatif = configuration de trade invalide). Ici on
    applique la règle du dépôt : un R indéfini rend `None`, pas `0.0`, pour
    ne jamais faire passer une donnée absente pour un trade neutre.
    """
    if risk_pct <= 0:
        return None
    return pct / (risk_pct * 100)


def _resolve_block_plan(domain_len: int, block_size: int) -> int:
    """Nombre de blocs à tirer pour reconstituer une série de longueur domain_len."""
    return -(-domain_len // block_size)  # division entière arrondie au-dessus


def _draw_block_indices(rng: random.Random, domain_len: int, block_size: int, n_blocks: int) -> list[int]:
    idx: list[int] = []
    for _ in range(n_blocks):
        start = rng.randint(0, domain_len - block_size)
        idx.extend(range(start, start + block_size))
    return idx[:domain_len]


def _validate_params(block_size: int, n_boot: int) -> None:
    if block_size < 1:
        raise ValueError(f"block_size doit être >= 1, reçu {block_size}")
    if n_boot < 1:
        raise ValueError(f"n_boot doit être >= 1, reçu {n_boot}")


def _empty_result(
    n_pattern: int,
    n_random: int,
    *,
    delta_observed: Optional[float],
    block_size: int,
    n_boot: int,
    seed: int,
    reason: str,
    n_boot_valid: int = 0,
    n_boot_skipped: int = 0,
) -> RandomControlResult:
    return RandomControlResult(
        n_pattern=n_pattern,
        n_random=n_random,
        delta_observed=delta_observed,
        ci95_low=None,
        ci95_high=None,
        p_value=None,
        significant=None,
        mde80=None,
        n_boot_valid=n_boot_valid,
        n_boot_requested=n_boot,
        n_boot_skipped=n_boot_skipped,
        block_size=block_size,
        seed=seed,
        insufficient_reason=reason,
    )


def _summarize(
    deltas: list[float],
    *,
    delta_observed: float,
    n_pattern: int,
    n_random: int,
    block_size: int,
    n_boot: int,
    seed: int,
    n_skipped: int,
) -> RandomControlResult:
    B = len(deltas)
    if B < _MIN_VALID_BOOT:
        return _empty_result(
            n_pattern, n_random,
            delta_observed=delta_observed, block_size=block_size, n_boot=n_boot, seed=seed,
            reason=f"trop peu de tirages bootstrap exploitables ({B} < {_MIN_VALID_BOOT})",
            n_boot_valid=B, n_boot_skipped=n_skipped,
        )
    deltas_sorted = sorted(deltas)
    lo = deltas_sorted[int(0.025 * B)]
    hi = deltas_sorted[int(0.975 * B)]
    n_le0 = sum(1 for d in deltas_sorted if d <= 0)
    n_ge0 = sum(1 for d in deltas_sorted if d >= 0)
    p_value = min(2 * min(n_le0, n_ge0) / B, 1.0)
    sd_delta = stdev(deltas_sorted) if B >= 2 else None
    mde80 = _Z_POWER80 * sd_delta if sd_delta is not None else None
    return RandomControlResult(
        n_pattern=n_pattern,
        n_random=n_random,
        delta_observed=delta_observed,
        ci95_low=lo,
        ci95_high=hi,
        p_value=p_value,
        significant=(lo > 0 or hi < 0),
        mde80=mde80,
        n_boot_valid=B,
        n_boot_requested=n_boot,
        n_boot_skipped=n_skipped,
        block_size=block_size,
        seed=seed,
        insufficient_reason=None,
    )


def paired_block_bootstrap_delta(
    domain: Sequence[TimedTrade],
    pattern: Sequence[TimedTrade],
    *,
    block_size: int = 10,
    n_boot: int = 2000,
    seed: int = 0,
    min_domain_blocks: int = 3,
) -> RandomControlResult:
    """Δ = espérance(pattern) − espérance(domaine), avec bootstrap par blocs APPARIÉ.

    `domain` est le recensement complet des entrées aléatoires comparables
    (même sens, même grille temporelle que `pattern` — la responsabilité de
    l'appelant). `pattern` est le sous-ensemble des trades réellement
    sélectionnés, aux MÊMES clés temporelles qu'une partie de `domain` (une
    clé de `pattern` absente de `domain` est silencieusement ignorée pour le
    calcul du delta apparié par tirage, mais compte dans `delta_observed`).

    À chaque tirage : on tire des blocs de `block_size` positions
    consécutives dans l'axe temporel de `domain` (trié par `key`), on
    reconstitue une série de la même longueur, on recalcule la moyenne
    domaine sur toutes les positions tirées ET la moyenne pattern sur les
    positions tirées qui sont aussi des clés `pattern` — puis on prend la
    différence. C'est ce qui préserve la dépendance des trades qui se
    chevauchent (cf. docstring du module).

    Résultat indéterminé (`significant=None`) si `domain` a moins de
    `block_size × min_domain_blocks` positions (pas assez de blocs
    indépendants pour un bootstrap fiable), ou si moins de 50 tirages sur
    `n_boot` produisent un delta calculable (aucun trade pattern dans les
    blocs tirés cette fois-là).
    """
    _validate_params(block_size, n_boot)
    domain_sorted = sorted(domain, key=lambda t: t.key)
    M = len(domain_sorted)
    n_pattern = len(pattern)

    if M == 0 or n_pattern == 0:
        return _empty_result(
            n_pattern, M, delta_observed=None, block_size=block_size, n_boot=n_boot, seed=seed,
            reason="domaine ou pattern vide — aucun delta calculable",
        )

    delta_observed = mean(t.r_multiple for t in pattern) - mean(t.r_multiple for t in domain_sorted)

    if M < block_size * min_domain_blocks:
        return _empty_result(
            n_pattern, M, delta_observed=delta_observed, block_size=block_size, n_boot=n_boot, seed=seed,
            reason=(
                f"domaine trop petit pour un bootstrap par blocs fiable : "
                f"M={M} < block_size({block_size}) × min_domain_blocks({min_domain_blocks})"
            ),
        )

    domain_R = [t.r_multiple for t in domain_sorted]
    pattern_r_by_key: dict[object, list[float]] = {}
    for t in pattern:
        pattern_r_by_key.setdefault(t.key, []).append(t.r_multiple)
    pattern_r_by_idx = {
        idx: mean(pattern_r_by_key[t.key])
        for idx, t in enumerate(domain_sorted)
        if t.key in pattern_r_by_key
    }

    rng = random.Random(seed)
    n_blocks = _resolve_block_plan(M, block_size)
    deltas: list[float] = []
    n_skipped = 0
    for _ in range(n_boot):
        idx_sample = _draw_block_indices(rng, M, block_size, n_blocks)
        random_rs = [domain_R[k] for k in idx_sample]
        pattern_rs = [pattern_r_by_idx[k] for k in idx_sample if k in pattern_r_by_idx]
        if not pattern_rs:
            n_skipped += 1
            continue
        deltas.append(mean(pattern_rs) - mean(random_rs))

    return _summarize(
        deltas, delta_observed=delta_observed, n_pattern=n_pattern, n_random=M,
        block_size=block_size, n_boot=n_boot, seed=seed, n_skipped=n_skipped,
    )


def _block_bootstrap_means(values: list[float], block_size: int, n_boot: int, rng: random.Random) -> list[float]:
    n = len(values)
    if n < block_size:
        return []
    n_blocks = _resolve_block_plan(n, block_size)
    means: list[float] = []
    for _ in range(n_boot):
        idx_sample = _draw_block_indices(rng, n, block_size, n_blocks)
        means.append(mean(values[k] for k in idx_sample))
    return means


def independent_block_bootstrap_delta(
    domain: Sequence[TimedTrade],
    pattern: Sequence[TimedTrade],
    *,
    block_size: int = 10,
    n_boot: int = 2000,
    seed: int = 0,
    min_domain_blocks: int = 3,
) -> RandomControlResult:
    """Variante NAÏVE : rééchantillonne `pattern` et `domain` séparément.

    ⚠️ Conservée uniquement pour la comparaison et la preuve de
    non-régression (`backend/tests/test_random_entry_control.py`) — ne pas
    utiliser pour une décision de production. Chaque groupe est
    bootstrappé par blocs sur SA PROPRE série (donc sa propre taille
    effective, quasi fixe d'un tirage à l'autre), au lieu de tirer les deux
    moyennes sur le MÊME tirage de blocs du domaine. Ça casse la dépendance
    des trades qui se chevauchent entre pattern et domaine et sous-estime
    l'incertitude réelle sur Δ (voir `paired_block_bootstrap_delta`).
    """
    _validate_params(block_size, n_boot)
    domain_sorted = sorted(domain, key=lambda t: t.key)
    pattern_sorted = sorted(pattern, key=lambda t: t.key)
    M = len(domain_sorted)
    n_pattern = len(pattern_sorted)

    if M == 0 or n_pattern == 0:
        return _empty_result(
            n_pattern, M, delta_observed=None, block_size=block_size, n_boot=n_boot, seed=seed,
            reason="domaine ou pattern vide — aucun delta calculable",
        )

    delta_observed = mean(t.r_multiple for t in pattern_sorted) - mean(t.r_multiple for t in domain_sorted)

    if M < block_size * min_domain_blocks or n_pattern < block_size * min_domain_blocks:
        return _empty_result(
            n_pattern, M, delta_observed=delta_observed, block_size=block_size, n_boot=n_boot, seed=seed,
            reason=(
                f"domaine ou pattern trop petit pour un bootstrap par blocs fiable : "
                f"M={M}, n_pattern={n_pattern}, seuil=block_size({block_size}) × "
                f"min_domain_blocks({min_domain_blocks})"
            ),
        )

    domain_R = [t.r_multiple for t in domain_sorted]
    pattern_R = [t.r_multiple for t in pattern_sorted]

    # Graines distinctes et dérivées : deux tirages non couplés, exactement
    # ce que la docstring dénonce (les deux groupes ne partagent plus le
    # même tirage de blocs temporels).
    rng_domain = random.Random(seed)
    rng_pattern = random.Random(seed + 1)

    domain_means = _block_bootstrap_means(domain_R, block_size, n_boot, rng_domain)
    pattern_means = _block_bootstrap_means(pattern_R, block_size, n_boot, rng_pattern)
    deltas = [p - r for p, r in zip(pattern_means, domain_means)]

    return _summarize(
        deltas, delta_observed=delta_observed, n_pattern=n_pattern, n_random=M,
        block_size=block_size, n_boot=n_boot, seed=seed, n_skipped=0,
    )
