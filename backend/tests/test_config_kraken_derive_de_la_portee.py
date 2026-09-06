"""Toute paire de la portée Kraken DOIT avoir une configuration (2026-09-06).

L'univers Kraken avait **trois sources de vérité**, éditées à la main, et rien
ne vérifiait leur accord :

```
liste codée en dur, shadow_v2_core_long   22 paires   -> produit les signaux 1 j
WATCHED_PAIRS_ADMIN_KRAKEN (.env)         29 paires   -> autorise le routage
KRAKEN_LIVE_WHITELIST_SYMBOLS (bridge)    38 symboles -> autorise l'exécution
```

⛔ Cette divergence a coûté **deux défauts dans la même journée** :

1. le matin, une portée construite depuis le mauvais univers a **coupé 11
   paires** que Kraken tradait ;
2. le soir, six paires ouvertes dans la portée et la whitelist **ne pouvaient
   produire aucun signal** — absentes de la liste du code. Annoncées ouvertes,
   muettes en réalité.

🔑 Le second est le pire des deux : **une porte ouverte sur une pièce vide se
voit moins qu'une porte fermée.** Rien ne l'aurait signalé — pas d'erreur, pas
de refus, juste une absence de trades qu'on aurait mise sur le compte du marché.

⇒ La configuration 1 jour se **dérive** désormais de la portée. Déclarer une
paire dans `WATCHED_PAIRS_ADMIN_KRAKEN` suffit ; les listes ne peuvent plus
diverger sans que ce test le dise.
"""
from __future__ import annotations

import pytest


def _portee(monkeypatch, paires):
    from config import settings
    monkeypatch.setattr(settings, "WATCHED_PAIRS_PAR_DESTINATION",
                        {"admin_kraken": frozenset(paires)})


def test_toute_paire_de_la_portee_a_une_config():
    """L'invariant, sur la configuration RÉELLE de production."""
    from backend.services.shadow_v2_core_long import SHADOW_CONFIG
    from config.settings import WATCHED_PAIRS_PAR_DESTINATION as P

    portee = set(P.get("admin_kraken") or [])
    if not portee:
        pytest.skip("aucune portée Kraken déclarée dans cet environnement")
    muettes = sorted(portee - set(SHADOW_CONFIG))
    assert not muettes, (
        "⛔ ces paires sont routables vers Kraken mais ne peuvent produire "
        f"AUCUN signal : {muettes}")


def test_une_paire_ajoutee_a_la_portee_recoit_une_config(monkeypatch):
    """Le point du correctif : declarer suffit, sans toucher au code."""
    import importlib
    from config import settings
    _portee(monkeypatch, {"BTC/USD", "ZZZ/USD"})
    mod = importlib.reload(importlib.import_module(
        "backend.services.shadow_v2_core_long"))
    try:
        assert "ZZZ/USD" in mod.SHADOW_CONFIG
        cfg = mod.SHADOW_CONFIG["ZZZ/USD"]
        assert cfg["tf"] == "1d", "l'horizon servi a Kraken, pas le 5 min"
        assert cfg["system_id"] == "V2_CORE_LONG_ZZZUSD_1D"
        assert cfg["risk_pct"] == 0.0025, "le gabarit prudent, non mesure"
    finally:
        monkeypatch.undo()
        importlib.reload(mod)


def test_la_config_HISTORIQUE_survit_a_la_derivation(monkeypatch):
    """⛔ Deriver ne doit RIEN retirer : les paires configurees a la main —
    l'or, l'argent, le WTI, les SPDR — gardent leur reglage propre."""
    import importlib
    from config import settings
    _portee(monkeypatch, {"BTC/USD"})
    mod = importlib.reload(importlib.import_module(
        "backend.services.shadow_v2_core_long"))
    try:
        for paire in ("XAU/USD", "XAG/USD", "WTI/USD", "XLI", "XLK"):
            assert paire in mod.SHADOW_CONFIG, f"{paire} perdue par la derivation"
        assert mod.SHADOW_CONFIG["XLI"]["risk_pct"] == 0.004, (
            "un reglage MESURE ne doit pas etre ecrase par le gabarit generique")
    finally:
        monkeypatch.undo()
        importlib.reload(mod)


def test_une_paire_deja_configuree_n_est_PAS_ecrasee(monkeypatch):
    """Si la portee nomme une paire deja reglee a la main, son reglage gagne.
    Le gabarit generique est un DEFAUT, pas une surcharge."""
    import importlib
    from config import settings
    _portee(monkeypatch, {"XAU/USD"})
    mod = importlib.reload(importlib.import_module(
        "backend.services.shadow_v2_core_long"))
    try:
        assert mod.SHADOW_CONFIG["XAU/USD"]["system_id"] != "V2_CORE_LONG_XAUUSD_1D" \
            or mod.SHADOW_CONFIG["XAU/USD"]["risk_pct"] != 0.0025, (
            "le reglage historique de l'or a ete remplace par le gabarit")
    finally:
        monkeypatch.undo()
        importlib.reload(mod)


def test_une_portee_ABSENTE_ne_retire_rien(monkeypatch):
    """Sans portee declaree, la configuration reste exactement l'historique."""
    import importlib
    from config import settings
    monkeypatch.setattr(settings, "WATCHED_PAIRS_PAR_DESTINATION", {})
    mod = importlib.reload(importlib.import_module(
        "backend.services.shadow_v2_core_long"))
    try:
        for paire in ("XAU/USD", "BTC/USD", "SOL/USD", "XLI"):
            assert paire in mod.SHADOW_CONFIG
    finally:
        monkeypatch.undo()
        importlib.reload(mod)
