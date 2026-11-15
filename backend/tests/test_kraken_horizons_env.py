"""Les horizons admis sur Kraken sont overridables par env.

## Pourquoi

Le default `{4h, 1d}` reflète l'analyse 876-trades du 2026-08-04 (coût
0,10 % aller-retour vs edge 0.110 R = 2,6× l'edge en scalping).

L'historique 59 trades Oct 2026 (+18 USD / 55 % win rate sur 15min/30min)
montre que la politique peut être ré-évaluée. Xavier garde le contrôle
via `KRAKEN_BRIDGE_ALLOWED_HORIZONS`.

Ces tests figent :
1. unset → défaut `{"4h", "1d"}`
2. CSV → liste explicite
3. `*` → `None` = pas de filtre (tous horizons passent)
"""
from __future__ import annotations


def test_default_sans_env(monkeypatch):
    """Sans env var → politique coût 2026-08-04 préservée."""
    from backend.services import bridge_destinations as bd
    monkeypatch.delenv("KRAKEN_BRIDGE_ALLOWED_HORIZONS", raising=False)
    assert bd._kraken_horizons() == frozenset({"4h", "1d"})


def test_env_csv_liste_explicite(monkeypatch):
    """CSV → liste explicite respectée."""
    from backend.services import bridge_destinations as bd
    monkeypatch.setenv("KRAKEN_BRIDGE_ALLOWED_HORIZONS", "5min,15min,30min,1h,4h,1d")
    assert bd._kraken_horizons() == frozenset(
        {"5min", "15min", "30min", "1h", "4h", "1d"}
    )


def test_env_wildcard_desactive_filtre(monkeypatch):
    """`*` → None = aucun filtre d'horizon (tous passent)."""
    from backend.services import bridge_destinations as bd
    for v in ("*", "all", "ALL"):
        monkeypatch.setenv("KRAKEN_BRIDGE_ALLOWED_HORIZONS", v)
        assert bd._kraken_horizons() is None, f"mot-clé {v!r} devrait rendre None"


def test_env_vide_fallback_defaut(monkeypatch):
    """Env var vide équivaut à non définie."""
    from backend.services import bridge_destinations as bd
    monkeypatch.setenv("KRAKEN_BRIDGE_ALLOWED_HORIZONS", "")
    assert bd._kraken_horizons() == frozenset({"4h", "1d"})
    monkeypatch.setenv("KRAKEN_BRIDGE_ALLOWED_HORIZONS", "   ")
    assert bd._kraken_horizons() == frozenset({"4h", "1d"})
