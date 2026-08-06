"""Branchement du flux long-horizon sur le dispatch (Kraken).

Jusqu'au 2026-08-06, `run_shadow_log` n'appelait jamais `send_setup` : le flux
4h/1d produisait des setups que personne ne pouvait exécuter. Kraken n'a donc
jamais tradé, alors qu'il est configuré pour ces horizons.

⚠️ Le vrai danger de ce branchement n'est pas qu'il ne marche pas : c'est qu'il
marche **dans la mauvaise direction**. `enrich_trade_setup` estampille
`setup.horizon` depuis `CANDLE_INTERVAL` (5min). Sans correction, un setup
journalier — stop à 7 % du prix — serait marqué « 5min » et routé vers MT5,
la route scalping. Ces tests verrouillent l'estampille.
"""
import pytest

from backend.services import shadow_v2_core_long as shadow
from backend.services.horizon import is_long, normalize


# ── L'estampille d'horizon ────────────────────────────────────────────

def test_enrich_estampille_le_mauvais_horizon():
    """Établit le fait qui rend la correction nécessaire — si ce test casse,
    c'est que `enrich_trade_setup` a changé et que la correction mérite
    d'être revue plutôt que conservée par superstition."""
    from backend.services.analysis_engine import enrich_trade_setup
    from config.settings import CANDLE_INTERVAL

    class _Setup:
        horizon = None
        confidence_score = 0
        pattern = None
        direction = None

    s = _Setup()
    try:
        enrich_trade_setup(s, None, None, [])
    except Exception:
        pytest.skip("enrich_trade_setup exige un setup plus complet ici")
    assert s.horizon == normalize(CANDLE_INTERVAL)
    assert not is_long(s.horizon), "CANDLE_INTERVAL est un horizon court"


@pytest.mark.parametrize("pair,cfg", sorted(shadow.SHADOW_CONFIG.items()))
def test_tous_les_systemes_long_sont_bien_en_horizon_long(pair, cfg):
    """Le flux ne doit contenir que du 4h/1d. Un système 1h ou 5min qui s'y
    glisserait serait dispatché vers MT5 avec un sizing pensé pour le long
    terme."""
    tf = normalize(cfg.get("tf"))
    assert tf is not None, f"{pair} : timeframe '{cfg.get('tf')}' hors vocabulaire"
    assert is_long(tf), f"{pair} est en {tf}, pas un horizon long"


def test_eth_est_le_seul_couple_crypto_et_il_est_journalier():
    """ETH/USD est la seule crypto du flux long, donc le seul setup qui peut
    atteindre Kraken. Au journalier, 100 % de ces setups passent la porte de
    coût (mesuré) — c'est ce qui rend Kraken viable."""
    cryptos = {p: c for p, c in shadow.SHADOW_CONFIG.items()
               if p.split("/")[0] in ("BTC", "ETH", "XBT")}
    assert set(cryptos) == {"ETH/USD"}
    assert normalize(cryptos["ETH/USD"]["tf"]) == "1d"


# ── Le drapeau ────────────────────────────────────────────────────────

def test_dispatch_actif_par_defaut():
    """Un drapeau par défaut inactif produirait zéro push ET zéro rejet —
    le mode de défaillance le plus coûteux du projet."""
    assert shadow._dispatch_long_horizon_actif() is True


def test_drapeau_relu_a_chaque_appel(monkeypatch):
    """Jamais figé dans une constante de module : sinon un changement de
    configuration n'aurait d'effet qu'au redémarrage."""
    import config.settings
    monkeypatch.setattr(config.settings, "LONG_HORIZON_DISPATCH_ENABLED", False)
    assert shadow._dispatch_long_horizon_actif() is False
    monkeypatch.setattr(config.settings, "LONG_HORIZON_DISPATCH_ENABLED", True)
    assert shadow._dispatch_long_horizon_actif() is True


# ── Le routage, tel que les portes le décideront ──────────────────────

@pytest.mark.parametrize("horizon,mt5_ok,kraken_ok", [
    ("5min", True, False),
    ("1h", False, False),
    ("4h", False, True),
    ("1d", False, True),
])
def test_les_portes_d_horizon_routent_seules(horizon, mt5_ok, kraken_ok):
    """Aucune destination n'est choisie dans le flux long : le routage repose
    entièrement sur `allowed_horizons`. Ce test verrouille cette répartition,
    puisque c'est elle qui garantit qu'un setup journalier ne partira jamais
    sur la route scalping."""
    from backend.services import bridge_destinations as bd

    mt5_h = bd._mt5_scalping_horizons()
    kraken_d = bd._admin_kraken_destination()
    kraken_h = getattr(kraken_d, "allowed_horizons", None) if kraken_d else None

    if mt5_h is not None:
        assert (horizon in mt5_h) is mt5_ok
    if kraken_h is not None:
        assert (horizon in kraken_h) is kraken_ok


def test_un_setup_journalier_est_refuse_par_mt5():
    """La garantie qui compte : le stop d'un setup journalier vaut ~7 % du
    prix. L'envoyer sur MT5 ouvrirait une position calibrée pour une autre
    échelle de temps."""
    from backend.services.mt5_bridge import _horizon_rejection
    from backend.services import bridge_destinations as bd

    class _S:
        horizon = "1d"

    dest = bd._admin_live_destination()
    if dest is None:
        pytest.skip("destination Live non configurée dans cet environnement")
    assert _horizon_rejection(_S(), dest) == "horizon_not_allowed"
