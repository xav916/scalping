"""Démo et réel décident chacun pour soi (2026-09-04).

Depuis le 2026-08-06, deux miroirs liaient les deux comptes, et il fallait
couper les DEUX pour qu'ils soient réellement autonomes :

  1. **Miroir de TRADES** — un fill confirmé en démo ouvrait la position
     correspondante sur le réel (`_mirror_fill_to_live`). Comme la dédup porte
     sur `(date, paire, sens, entrée)`, cette copie ne pouvait pas doubler un
     signal déjà traité par l'aiguillage direct : elle n'ajoutait des ordres
     que là où les portes **propres à `admin_live` avaient refusé**. Le miroir
     contournait donc les portes du compte réel, par construction.

  2. **Miroir de CAPITAL** — la démo dimensionnait sur le solde du RÉEL
     (`capital_mirror="admin_live"`). Mesuré le 04/09 : 750,50 € au lieu de ses
     569,01 €, soit **+32 %**. Couper le seul miroir de trades aurait laissé la
     démo trader à la taille du compte réel avec de l'argent qui n'existe pas —
     et ses résultats seraient restés inexploitables comme témoin.

⚠️ Ce que ces tests protègent surtout : que **couper l'un n'a pas l'air de
suffire**. Le premier se coupe par l'`.env`, le second vit dans le code — un
lecteur pressé qui voit `MIRROR_DEMO_TO_LIVE_ENABLED=false` conclurait que les
comptes sont séparés alors que la démo dimensionne encore sur le réel.

🔑 L'enjeu n'est pas seulement le risque : une démo qui copie le réel n'est
**pas un échantillon indépendant**. Tant que les miroirs tournaient, le banc
d'essai et les calculs DSR/PBO travaillaient sur deux séries corrélées par
construction.
"""
from __future__ import annotations

import pytest

from backend.services import bridge_destinations as bd
from backend.services import mt5_bridge as mb
from backend.services import sizing


def _armer_le_reel(monkeypatch):
    """`_admin_live_destination` lit `config.settings`, pas `mt5_bridge`."""
    from config import settings as st
    for cle, val in (
        ("MT5_BRIDGE_LIVE_ENABLED", True),
        ("MT5_BRIDGE_LIVE_URL", "http://live:8788"),
        ("MT5_BRIDGE_LIVE_API_KEY", "cle"),
        ("MT5_BRIDGE_LIVE_MIN_CONFIDENCE", 42.0),
        ("MT5_BRIDGE_LIVE_ALLOWED_ASSET_CLASSES", ["forex", "metal", "energy"]),
    ):
        monkeypatch.setattr(st, cle, val, raising=False)


@pytest.fixture()
def demo_configuree(monkeypatch):
    """La destination démo telle que la prod la construit."""
    monkeypatch.setattr(mb, "MT5_BRIDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(mb, "MT5_BRIDGE_URL", "http://demo:8787", raising=False)
    monkeypatch.setattr(mb, "MT5_BRIDGE_API_KEY", "cle", raising=False)
    dest = bd._admin_legacy_destination()
    assert dest is not None, "la démo doit être configurable dans ce test"
    return dest


# ── 1. Le miroir de CAPITAL est coupé ─────────────────────────────────────

def test_la_demo_ne_declare_plus_de_miroir_de_capital(demo_configuree):
    """Le câblage, pas le mécanisme.

    `capital_mirror` reste un dispositif générique et testé ailleurs — ce qui
    est vérifié ici, c'est qu'`admin_legacy` ne s'en sert plus.
    """
    assert getattr(demo_configuree, "capital_mirror", None) is None


def test_la_demo_dimensionne_sur_SON_propre_solde(demo_configuree, monkeypatch):
    """569,01 € (son solde) et non 750,50 € (celui du réel)."""
    import time

    monkeypatch.setattr(sizing, "_BALANCE_CACHE", {
        "admin_legacy": (569.01, time.monotonic() + 300),
        "admin_live": (750.50, time.monotonic() + 300),
    }, raising=False)

    capital, source = sizing.destination_capital(demo_configuree)

    assert capital == pytest.approx(569.01)
    assert source == "live", "son propre solde, lu chez SON courtier"
    assert not str(source).startswith("miroir")


def test_le_reel_garde_son_propre_solde(monkeypatch):
    """La coupure ne doit rien changer au compte réel."""
    import time

    _armer_le_reel(monkeypatch)
    live = bd._admin_live_destination()
    assert live is not None

    monkeypatch.setattr(sizing, "_BALANCE_CACHE", {
        "admin_live": (750.50, time.monotonic() + 300),
    }, raising=False)

    capital, source = sizing.destination_capital(live)
    assert capital == pytest.approx(750.50)
    assert source == "live"


# ── 2. Le miroir de TRADES est coupé ──────────────────────────────────────

def test_le_miroir_de_trades_est_desarme_par_defaut():
    """`MIRROR_DEMO_TO_LIVE_ENABLED` vaut désormais `false` en configuration.

    ⚠️ Le défaut du code compte : la prod le pose dans son `.env`, mais un
    environnement neuf (test de persistance, machine de reprise, poste d'un
    futur utilisateur Premium) hériterait du défaut. Le laisser à `true`
    rebrancherait le miroir sans que personne ne l'ait demandé.
    """
    import importlib

    import config.settings as settings
    importlib.reload(settings)
    assert settings.MIRROR_DEMO_TO_LIVE_ENABLED is False


@pytest.mark.asyncio
async def test_aucun_ordre_reel_ne_part_d_un_fill_demo(monkeypatch):
    """Le chemin complet, pas seulement le drapeau."""
    import config.settings

    monkeypatch.setattr(config.settings, "MIRROR_DEMO_TO_LIVE_ENABLED", False)

    parti = {}

    class _C:
        async def __aenter__(self_): return self_
        async def __aexit__(self_, *a): return False
        async def post(self_, url, json=None, headers=None):
            parti["url"] = url
            raise AssertionError("aucun POST ne doit partir vers le réel")

    monkeypatch.setattr(mb.httpx, "AsyncClient", lambda *a, **k: _C())

    class S: pass
    s = S()
    s.pair = "XAU/USD"; s.direction = "buy"
    s.entry_price = 4473.0; s.stop_loss = 4464.0; s.take_profit_1 = 4490.0
    s.take_profit_2 = None; s.confidence_score = 70.0

    await mb._mirror_fill_to_live(
        s, {"risk_money": 7.5}, {"volume": 0.01, "ticket": 1}, "admin_legacy")

    assert "url" not in parti


# ── 3. Le réel garde son aiguillage direct ────────────────────────────────

def test_le_reel_reste_une_destination_de_plein_droit(monkeypatch):
    """⛔ Le point qui décide si la coupure est sûre.

    Si `admin_live` n'était atteint QUE par le miroir, couper celui-ci
    arrêterait le compte réel. `resolve_destinations` doit continuer de le
    servir directement, avec ses propres portes.
    """
    monkeypatch.setattr(mb, "MT5_BRIDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(mb, "MT5_BRIDGE_URL", "http://demo:8787", raising=False)
    monkeypatch.setattr(mb, "MT5_BRIDGE_API_KEY", "cle", raising=False)
    _armer_le_reel(monkeypatch)

    class S: pass
    s = S()
    s.pair = "XAU/USD"; s.direction = "buy"
    s.entry_price = 4473.0; s.stop_loss = 4464.0; s.take_profit_1 = 4490.0
    s.confidence_score = 70.0; s.horizon = "4h"

    ids = [getattr(d, "destination_id", None) for d in bd.resolve_destinations(s)]
    assert "admin_live" in ids, (
        "le compte réel doit rester servi directement, miroir ou pas")
