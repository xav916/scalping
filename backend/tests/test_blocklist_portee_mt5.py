"""La blocklist de paires ne doit bloquer que les bridges MT5 (2026-08-08).

`MT5_BRIDGE_BLOCKED_PAIRS` existe pour une raison réelle : `INVALID_VOLUME`
(retcode 10014) sur SOL/ADA chez **Pepperstone**, dont le `volume_step` vaut
0,1 contre 0,01 pour BTC/ETH.

⛔ Mais elle s'appliquait à **toutes** les destinations. Chez Kraken les specs
n'ont rien à voir — `contractValueTradePrecision` 2 pour PF_SOLUSD, 0 pour
PF_XRPUSD — et le dimensionnement y est valide. Un garde-fou d'un courtier
interdisait un autre courtier : 61 refus XRP et 48 SOL le 2026-08-08, dont
l'unique setup journalier produit ce jour-là.
"""
import pytest

from backend.services import mt5_bridge as mb


class _Dest:
    def __init__(self, bridge_type, dest_id="admin_kraken"):
        self.destination_id = dest_id
        self.bridge_type = bridge_type
        self.bridge_url = "http://x"
        self.bridge_api_key = "k"
        self.user_id = None
        self.min_confidence = 50.0
        self.allowed_asset_classes = frozenset({"crypto", "forex", "metal"})
        self.allowed_horizons = None
        self.extra_pairs_allowed = frozenset()


def _bloque(pair, dest):
    """Rejoue la seule condition de blocklist, telle qu'elle est livrée."""
    return (getattr(dest, "bridge_type", "mt5") == "mt5"
            and pair.upper() in mb.MT5_BRIDGE_BLOCKED_PAIRS)


@pytest.fixture(autouse=True)
def _liste(monkeypatch):
    monkeypatch.setattr(mb, "MT5_BRIDGE_BLOCKED_PAIRS",
                        frozenset({"SOL/USD", "XRP/USD", "ADA/USD"}))


def test_un_bridge_MT5_reste_bloque():
    """Le motif d'origine tient : Pepperstone rejette toujours ces volumes."""
    assert _bloque("SOL/USD", _Dest("mt5", "admin_legacy")) is True
    assert _bloque("XRP/USD", _Dest("mt5", "admin_live")) is True


def test_KRAKEN_n_est_plus_bloque():
    for p in ("SOL/USD", "XRP/USD", "ADA/USD"):
        assert _bloque(p, _Dest("kraken")) is False, (
            f"{p} bloquee sur Kraken par une contrainte Pepperstone")


def test_les_autres_bridges_non_mt5_non_plus():
    for t in ("kraken_spot", "binance"):
        assert _bloque("SOL/USD", _Dest(t)) is False


def test_une_paire_hors_liste_passe_partout():
    for t in ("mt5", "kraken"):
        assert _bloque("BTC/USD", _Dest(t)) is False


def test_le_defaut_est_mt5_donc_bloquant():
    """Une destination sans `bridge_type` doit rester traitee comme MT5 :
    fail-closed, on ne debloque pas par omission."""
    class _SansType:
        destination_id = "inconnu"
    assert _bloque("SOL/USD", _SansType()) is True
