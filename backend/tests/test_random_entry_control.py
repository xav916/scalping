"""Tests du contrôle par entrées aléatoires (backend/services/random_entry_control.py).

Porte en module testé la méthode validée dans les scripts jetables
`scratchpad/test_difference_directe.py` (bootstrap par blocs APPARIÉ sur
Δ = espérance(pattern) − espérance(aléatoire)) — voir le rapport
`scratchpad/module-controle-aleatoire.md` pour la fidélité méthodologique.

Aucun accès réseau ni base de données : toutes les données sont des
`TimedTrade` construits en mémoire, avec des générateurs pseudo-aléatoires
locaux à graine fixe (reproductible, ne touche pas `random` global).
"""
from __future__ import annotations

import random

import pytest

from backend.services.random_entry_control import (
    RandomControlResult,
    TimedTrade,
    independent_block_bootstrap_delta,
    paired_block_bootstrap_delta,
    r_multiple,
)


# ─── Générateurs de fixtures déterministes ──────────────────────────────


def _make_domain(n: int, *, seed: int, mean_r: float = 0.0, sd_r: float = 0.6) -> list[TimedTrade]:
    """Domaine (= recensement RANDOM_ALL) : n trades datés 0..n-1, R ~ bruit gaussien-like."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        # bruit borné, pas besoin de vraie gaussienne pour ces tests
        noise = (rng.random() - 0.5) * 2 * sd_r
        out.append(TimedTrade(key=i, r_multiple=mean_r + noise))
    return out


def _pattern_no_effect(domain: list[TimedTrade], *, frac: float, seed: int) -> list[TimedTrade]:
    """Sous-ensemble choisi uniformément au hasard dans le domaine, MÊME distribution
    (aucun offset injecté) : par construction, aucune différence d'espérance."""
    rng = random.Random(seed)
    n_pick = max(1, int(len(domain) * frac))
    picked = rng.sample(domain, n_pick)
    return sorted(picked, key=lambda t: t.key)


def _pattern_with_effect(domain: list[TimedTrade], *, frac: float, offset: float, seed: int) -> list[TimedTrade]:
    """Sous-ensemble uniforme du domaine, mais R systématiquement décalé de `offset`
    (= un pattern qui bat vraiment le hasard de `offset` R en moyenne)."""
    rng = random.Random(seed)
    n_pick = max(1, int(len(domain) * frac))
    picked = rng.sample(domain, n_pick)
    shifted = [TimedTrade(key=t.key, r_multiple=t.r_multiple + offset) for t in picked]
    return sorted(shifted, key=lambda t: t.key)


# ─── r_multiple : petite fonction pure, règle None ≠ 0.0 ────────────────


def test_r_multiple_formule_standard():
    # Formule identique aux scripts source : R = pct / (risk_pct * 100)
    assert r_multiple(pct=2.0, risk_pct=0.01) == pytest.approx(2.0)


def test_r_multiple_risque_nul_est_none_pas_zero():
    # Règle du dépôt : inconnu = None, jamais 0.0 (déviation volontaire du
    # script jetable, qui renvoyait 0.0 pour risk_pct <= 0).
    assert r_multiple(pct=1.0, risk_pct=0.0) is None
    assert r_multiple(pct=1.0, risk_pct=-0.01) is None


# ─── 1. Aucun effet injecté → Δ non significatif ────────────────────────


def test_aucun_effet_delta_non_significatif():
    domain = _make_domain(600, seed=1)
    pattern = _pattern_no_effect(domain, frac=0.15, seed=2)

    result = paired_block_bootstrap_delta(
        domain, pattern, block_size=5, n_boot=1500, seed=42,
    )

    assert result.significant is False
    assert result.ci95_low is not None and result.ci95_high is not None
    assert result.ci95_low < 0 < result.ci95_high  # 0 dans l'IC
    assert result.p_value is not None and result.p_value > 0.05


# ─── 2. Effet franc injecté → Δ significatif, proche de l'effet injecté ─


def test_effet_franc_delta_significatif_et_proche_de_leffet_injecte():
    domain = _make_domain(600, seed=1)
    offset = 0.5
    pattern = _pattern_with_effect(domain, frac=0.15, offset=offset, seed=2)

    result = paired_block_bootstrap_delta(
        domain, pattern, block_size=5, n_boot=1500, seed=42,
    )

    assert result.significant is True
    assert result.ci95_low is not None and result.ci95_low > 0  # exclut totalement 0
    assert result.delta_observed == pytest.approx(offset, abs=0.15)
    assert result.p_value is not None and result.p_value < 0.05


# ─── 3. Échantillon trop petit → indéterminé, PAS un faux négatif ───────


def test_echantillon_trop_petit_rend_indetermine_pas_faux_negatif():
    # M=10 trades, block_size=5, min_domain_blocks=3 → 10 < 5*3=15 : insuffisant.
    domain = _make_domain(10, seed=1)
    pattern = _pattern_with_effect(domain, frac=0.5, offset=2.0, seed=2)  # gros effet, sample minuscule

    result = paired_block_bootstrap_delta(
        domain, pattern, block_size=5, n_boot=1500, seed=42, min_domain_blocks=3,
    )

    # Le point est justement que même avec un effet ÉNORME injecté, un
    # échantillon trop petit ne doit JAMAIS produire significant=False
    # (un faux négatif silencieux) : il doit produire None (indéterminé).
    assert result.significant is None
    assert result.ci95_low is None
    assert result.ci95_high is None
    assert result.p_value is None
    assert result.insufficient_reason is not None


def test_domaine_ou_pattern_vide_rend_tout_none():
    result_empty_domain = paired_block_bootstrap_delta([], [], block_size=5, n_boot=100, seed=1)
    assert result_empty_domain.delta_observed is None
    assert result_empty_domain.significant is None

    domain = _make_domain(50, seed=1)
    result_no_pattern = paired_block_bootstrap_delta(domain, [], block_size=5, n_boot=100, seed=1)
    assert result_no_pattern.delta_observed is None
    assert result_no_pattern.significant is None
    assert result_no_pattern.insufficient_reason is not None


# ─── 4. Reproductibilité à graine fixée ──────────────────────────────────


def test_reproductible_a_graine_fixee():
    domain = _make_domain(600, seed=1)
    pattern = _pattern_with_effect(domain, frac=0.15, offset=0.3, seed=2)

    r1 = paired_block_bootstrap_delta(domain, pattern, block_size=5, n_boot=800, seed=123)
    r2 = paired_block_bootstrap_delta(domain, pattern, block_size=5, n_boot=800, seed=123)

    assert r1 == r2  # dataclass frozen, comparaison exacte


def test_graines_differentes_donnent_des_resultats_differents():
    domain = _make_domain(600, seed=1)
    pattern = _pattern_with_effect(domain, frac=0.15, offset=0.3, seed=2)

    r1 = paired_block_bootstrap_delta(domain, pattern, block_size=5, n_boot=800, seed=1)
    r2 = paired_block_bootstrap_delta(domain, pattern, block_size=5, n_boot=800, seed=2)

    # Les tirages diffèrent → au moins l'IC ou le p ne sont pas identiques
    assert (r1.ci95_low, r1.ci95_high, r1.p_value) != (r2.ci95_low, r2.ci95_high, r2.p_value)


# ─── 5. Appariement : IC plus large que deux bootstraps indépendants ────


def _make_clustered_scenario(seed: int):
    """Domaine dense (200 positions), pattern concentré dans UNE seule zone
    (positions 40-79 sur 200) : sous ce régime, un tirage de blocs par-blocs
    sur le domaine capture tantôt beaucoup, tantôt très peu de trades pattern
    selon que le tirage retombe ou non sur cette zone — c'est exactement la
    dépendance que l'appariement doit préserver (et que l'indépendant casse
    en resamplant le pattern comme sa propre série de taille ~fixe)."""
    domain = _make_domain(200, seed=seed, mean_r=0.10, sd_r=0.5)
    cluster = [t for t in domain if 40 <= t.key < 80]
    rng = random.Random(seed + 100)
    pattern = [
        TimedTrade(key=t.key, r_multiple=t.r_multiple + 0.2)
        for t in cluster
        if rng.random() < 0.7  # sous-échantillonne un peu la zone, garde le clustering
    ]
    return domain, sorted(pattern, key=lambda t: t.key)


def test_appariement_donne_un_ic_plus_large_que_bootstrap_independant():
    domain, pattern = _make_clustered_scenario(seed=7)

    paired = paired_block_bootstrap_delta(
        domain, pattern, block_size=8, n_boot=3000, seed=99,
    )
    independent = independent_block_bootstrap_delta(
        domain, pattern, block_size=8, n_boot=3000, seed=99,
    )

    assert paired.ci95_low is not None and paired.ci95_high is not None
    assert independent.ci95_low is not None and independent.ci95_high is not None

    width_paired = paired.ci95_high - paired.ci95_low
    width_independent = independent.ci95_high - independent.ci95_low

    # C'est le test qui mord : une implémentation naïve (rééchantillonnage
    # indépendant des deux groupes) sous-estime l'incertitude sur données
    # corrélées/clusterisées — l'IC apparié doit être strictement plus large.
    assert width_paired > width_independent


# ─── Robustesse d'API : erreurs explicites sur paramètres invalides ─────


def test_block_size_invalide_leve():
    domain = _make_domain(50, seed=1)
    with pytest.raises(ValueError):
        paired_block_bootstrap_delta(domain, domain, block_size=0, n_boot=100, seed=1)


def test_n_boot_invalide_leve():
    domain = _make_domain(50, seed=1)
    with pytest.raises(ValueError):
        paired_block_bootstrap_delta(domain, domain, block_size=5, n_boot=0, seed=1)


def test_result_est_bien_le_type_documente():
    domain = _make_domain(600, seed=1)
    pattern = _pattern_no_effect(domain, frac=0.15, seed=2)
    result = paired_block_bootstrap_delta(domain, pattern, block_size=5, n_boot=500, seed=1)
    assert isinstance(result, RandomControlResult)
    assert result.n_pattern == len(pattern)
    assert result.n_random == len(domain)
    assert result.block_size == 5
    assert result.seed == 1
    assert result.n_boot_requested == 500
