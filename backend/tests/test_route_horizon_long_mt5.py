"""Ouverture opt-in des horizons longs sur les routes MT5 (2026-08-07).

Contexte mesuré le jour même. À 5 minutes, la porte de coût refuse ~28 setups
XAU par jour : les frais dépassent 30 % de l'espérance. Sur les 118 setups
``XAU/USD 4h`` des 90 derniers jours, **aucun** n'a un stop sous le seuil de
viabilité de 0,33 % (médiane 1,81 %). L'horizon long fait donc passer la porte
de coût — c'est la seule raison d'être de cette route.

⚠️ Ce que ces tests verrouillent, c'est le danger de l'autre côté : au lot
minimum, ce même stop médian coûte 77,87 USD, soit 20 % de l'``equity`` réelle
constatée (350,68 EUR). Ouvrir cette route sur le compte réel sans capital
suffisant joue le compte sur cinq trades. D'où :
  - fermé par défaut, sur les deux routes ;
  - ouvrable route par route, jamais globalement ;
  - le miroir démo→réel respecte la porte d'horizon du RÉEL, sinon il
    contournerait la seule protection en place.
"""
import pytest

from backend.services import bridge_destinations as bd
from backend.services import mt5_bridge as mb
from backend.services.horizon import LONG_HORIZONS


@pytest.fixture(autouse=True)
def _scalping_5min(monkeypatch):
    """CANDLE_INTERVAL=5min : l'horizon de base des routes MT5."""
    import config.settings
    monkeypatch.setattr(config.settings, "CANDLE_INTERVAL", "5min")


# ── La route est fermée par défaut ────────────────────────────────────

def test_aucune_route_longue_sans_reglage(monkeypatch):
    monkeypatch.delenv("MT5_LONG_HORIZON_ROUTES", raising=False)
    assert bd._mt5_long_horizon_routes() == frozenset()
    assert bd._mt5_horizons("admin_legacy") == frozenset({"5min"})
    assert bd._mt5_horizons("admin_live") == frozenset({"5min"})


def test_une_valeur_vide_ne_compte_pas(monkeypatch):
    """`MT5_LONG_HORIZON_ROUTES=" , "` ne doit pas ouvrir une route ''."""
    monkeypatch.setenv("MT5_LONG_HORIZON_ROUTES", " , ")
    assert bd._mt5_long_horizon_routes() == frozenset()


# ── Ouverture route par route ─────────────────────────────────────────

def test_ouvrir_le_demo_ajoute_4h_et_1d_sans_retirer_le_scalping(monkeypatch):
    monkeypatch.setenv("MT5_LONG_HORIZON_ROUTES", "admin_legacy")
    h = bd._mt5_horizons("admin_legacy")
    assert h == frozenset({"5min"}) | LONG_HORIZONS
    assert "4h" in h and "1d" in h
    assert "5min" in h, "le scalping ne doit pas disparaître en ouvrant le long"


def test_ouvrir_le_demo_n_ouvre_PAS_le_reel(monkeypatch):
    """Le danger est sur le réel : l'ouverture doit être strictement nominative."""
    monkeypatch.setenv("MT5_LONG_HORIZON_ROUTES", "admin_legacy")
    assert bd._mt5_horizons("admin_live") == frozenset({"5min"})


def test_les_deux_routes_ouvrables_ensemble(monkeypatch):
    monkeypatch.setenv("MT5_LONG_HORIZON_ROUTES", "admin_legacy,admin_live")
    for dest in ("admin_legacy", "admin_live"):
        assert LONG_HORIZONS <= bd._mt5_horizons(dest)


# ── Fail-safe sur un CANDLE_INTERVAL illisible ────────────────────────

def test_horizon_de_base_illisible_reste_sans_filtre(monkeypatch):
    """`None` = aucun filtre. L'élargir produirait une porte à moitié ouverte.

    Si on ne sait pas lire l'horizon de base, on ne sait pas non plus ce que
    « base + long » veut dire. Renvoyer `{4h, 1d}` refuserait alors TOUT le
    scalping — le mode de défaillance silencieux qu'on cherche à éviter.
    """
    import config.settings
    monkeypatch.setattr(config.settings, "CANDLE_INTERVAL", "30min")
    monkeypatch.setenv("MT5_LONG_HORIZON_ROUTES", "admin_legacy,admin_live")
    assert bd._mt5_scalping_horizons() is None
    assert bd._mt5_horizons("admin_legacy") is None


# ── Le miroir respecte la porte d'horizon du RÉEL ─────────────────────

class _Dest:
    def __init__(self, horizons):
        self.destination_id = "admin_live"
        self.bridge_url = "http://live"
        self.bridge_api_key = "cle"
        self.symbol_map = None
        self.user_id = None
        self.allowed_horizons = horizons


def _setup_4h():
    class S: pass
    s = S()
    s.pair = "XAU/USD"; s.direction = "sell"; s.horizon = "4h"
    s.entry_price = 4305.87; s.stop_loss = 4383.81; s.take_profit_1 = 4150.0
    s.take_profit_2 = None; s.confidence_score = 71.0
    return s


@pytest.fixture
def miroir(monkeypatch):
    import config.settings
    monkeypatch.setattr(config.settings, "MIRROR_DEMO_TO_LIVE_ENABLED", True)

    trace = {"envoye": False, "refus": []}

    class _C:
        async def __aenter__(self_): return self_
        async def __aexit__(self_, *a): return False
        async def post(self_, url, json=None, headers=None):
            trace["envoye"] = True
            trace["payload"] = json
            class _R:
                status_code = 200
                text = ""
                def json(self_r): return {"ok": True, "ticket": 42,
                                          "volume": json.get("lots")}
            return _R()

    monkeypatch.setattr(mb.httpx, "AsyncClient", lambda *a, **k: _C())
    monkeypatch.setattr("backend.services.rejection_service.record_rejection",
                        lambda **k: trace["refus"].append(k))
    monkeypatch.setattr("backend.services.mt5_pushes_service.try_register_push",
                        lambda *a, **k: True)
    monkeypatch.setattr("backend.services.mt5_pushes_service.update_push_result",
                        lambda *a, **k: None)
    monkeypatch.setattr("backend.services.mt5_pushes_service.discard_push",
                        lambda *a, **k: None)
    return trace


@pytest.mark.asyncio
async def test_le_miroir_ne_copie_pas_un_4h_vers_un_reel_qui_ne_le_sert_pas(
    monkeypatch, miroir
):
    """Le cœur du garde-fou : 20 % de l'equity par trade sinon."""
    monkeypatch.setattr(bd, "_admin_live_destination",
                        lambda: _Dest(frozenset({"5min"})))
    await mb._mirror_fill_to_live(
        _setup_4h(), {"risk_money": 3.0}, {"volume": 0.01, "ticket": 1},
        "admin_legacy")

    assert miroir["envoye"] is False, "aucun ordre ne doit partir vers le réel"
    assert len(miroir["refus"]) == 1, "le refus doit être tracé, pas silencieux"
    refus = miroir["refus"][0]
    assert refus["reason_code"] == "horizon_not_allowed"
    assert refus["destination_id"] == "admin_live"
    assert refus["details"]["miroir"] is True, "traçable comme venant du miroir"


@pytest.mark.asyncio
async def test_le_miroir_copie_le_4h_une_fois_le_reel_ouvert(monkeypatch, miroir):
    """Un seul interrupteur : ouvrir `admin_live` suffit, sans toucher au code."""
    monkeypatch.setattr(bd, "_admin_live_destination",
                        lambda: _Dest(frozenset({"5min"}) | LONG_HORIZONS))
    await mb._mirror_fill_to_live(
        _setup_4h(), {"risk_money": 3.0}, {"volume": 0.01, "ticket": 1},
        "admin_legacy")

    assert miroir["envoye"] is True
    assert miroir["payload"]["lots"] == pytest.approx(0.01)
    assert not miroir["refus"]


@pytest.mark.asyncio
async def test_le_scalping_passe_toujours_le_miroir(monkeypatch, miroir):
    """Non-régression : la route 5min ne doit pas être affectée."""
    monkeypatch.setattr(bd, "_admin_live_destination",
                        lambda: _Dest(frozenset({"5min"})))
    s = _setup_4h()
    s.horizon = "5min"
    await mb._mirror_fill_to_live(
        s, {"risk_money": 3.0}, {"volume": 0.01, "ticket": 1}, "admin_legacy")

    assert miroir["envoye"] is True
    assert not miroir["refus"]
