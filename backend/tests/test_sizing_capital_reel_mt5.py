"""Le sizing MT5 doit partir du solde RÉEL, pas d'un capital configuré.

Constaté le 2026-08-06 : `TRADING_CAPITAL` valait 3 000 € quand le compte réel
(13137475) en contenait 540. Le sizing calculait donc sur **5,5× le capital
disponible** — un ordre sur l'or sortait à 0,035 lot là où le compte pouvait en
porter 0,01. Seuls les plafonds de lot puis l'ajustement à la marge le
rattrapaient : le résultat était correct **par accident, pas par conception**.

⚠️ Deux pièges que ces tests verrouillent :

1. Les bridges ne parlent pas le même dialecte. MT5 authentifie par
   `X-API-Key` et rend `equity`/`balance` ; les bridges crypto utilisent
   `X-Bridge-Key` et `portfolio_value_usd`. Le mauvais en-tête donne un 401,
   lu comme « solde indisponible ».
2. MT5 se replie sur le capital global quand le solde est inconnu — il ne
   refuse PAS, contrairement aux bridges crypto. Refuser transformerait un
   `/account` momentanément injoignable en arrêt total du trading.
"""
import httpx
import pytest

from backend.services import sizing


class _Dest:
    def __init__(self, bridge_type="mt5", dest_id="admin_live"):
        self.bridge_type = bridge_type
        self.destination_id = dest_id
        self.bridge_url = "http://bridge"
        self.bridge_api_key = "cle"
        self.trading_capital = None
        self.user_id = None


@pytest.fixture(autouse=True)
def cache_vide():
    sizing._BALANCE_CACHE.clear()
    yield
    sizing._BALANCE_CACHE.clear()


class _Reponse:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def json(self):
        return self._p


def _client(capture, payload, status=200):
    class _C:
        async def __aenter__(self_): return self_
        async def __aexit__(self_, *a): return False
        async def get(self_, url, headers=None):
            capture["url"] = url
            capture["headers"] = headers or {}
            return _Reponse(payload, status)
    return lambda *a, **k: _C()


# ── Lecture du solde MT5 ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mt5_lit_l_equite_et_utilise_le_bon_entete(monkeypatch):
    """`equity` plutôt que `balance` : c'est le capital réellement
    disponible, positions ouvertes déduites."""
    cap = {}
    monkeypatch.setattr(httpx, "AsyncClient",
                        _client(cap, {"balance": 540.53, "equity": 411.98}))
    val = await sizing.refresh_destination_capital(_Dest())
    assert val == pytest.approx(411.98)
    assert "X-API-Key" in cap["headers"], "MT5 n'accepte pas X-Bridge-Key"


@pytest.mark.asyncio
async def test_mt5_retombe_sur_le_solde_si_l_equite_manque(monkeypatch):
    cap = {}
    monkeypatch.setattr(httpx, "AsyncClient", _client(cap, {"balance": 540.53}))
    assert await sizing.refresh_destination_capital(_Dest()) == pytest.approx(540.53)


@pytest.mark.asyncio
async def test_les_bridges_crypto_gardent_leur_dialecte(monkeypatch):
    """Régression : ne pas casser Kraken/Binance en corrigeant MT5."""
    cap = {}
    monkeypatch.setattr(httpx, "AsyncClient",
                        _client(cap, {"portfolio_value_usd": 1234.5}))
    d = _Dest(bridge_type="kraken", dest_id="admin_kraken")
    assert await sizing.refresh_destination_capital(d) == pytest.approx(1234.5)
    assert "X-Bridge-Key" in cap["headers"]


# ── Le repli, et la différence de nature avec la crypto ───────────────

def test_mt5_utilise_le_solde_cache_quand_il_existe():
    sizing._cache_put("admin_live", 411.98)
    capital, source = sizing.destination_capital(_Dest())
    assert capital == pytest.approx(411.98)
    assert source == "live"


def test_mt5_se_replie_sur_le_global_sans_solde(monkeypatch):
    """LE choix de conception : un `/account` injoignable ne doit pas arrêter
    le trading. Le sur-dimensionnement est rattrapé par l'ajustement à la
    marge côté bridge."""
    import config.settings
    monkeypatch.setattr(config.settings, "TRADING_CAPITAL", 3000.0)
    capital, source = sizing.destination_capital(_Dest())
    assert capital == pytest.approx(3000.0)
    assert source == "global"


def test_un_bridge_crypto_sans_solde_REFUSE_lui():
    """La différence de nature : pour un compte crypto le solde EST le
    capital, l'ignorer n'aurait aucun sens."""
    d = _Dest(bridge_type="kraken", dest_id="admin_kraken")
    capital, source = sizing.destination_capital(d)
    assert capital is None
    assert source == sizing.CAPITAL_UNAVAILABLE


def test_une_surcharge_explicite_l_emporte_sur_tout():
    d = _Dest()
    d.trading_capital = 750.0
    sizing._cache_put("admin_live", 411.98)
    capital, source = sizing.destination_capital(d)
    assert capital == pytest.approx(750.0)
    assert source == "destination"


# ── L'effet mesuré ────────────────────────────────────────────────────

def test_le_capital_reel_reduit_la_taille_calculee(monkeypatch):
    """Preuve chiffrée du correctif : à 540 € de capital le risque engagé est
    5,5× plus petit qu'à 3 000 €, donc la taille aussi."""
    import config.settings
    monkeypatch.setattr(config.settings, "TRADING_CAPITAL", 3000.0)
    global_cap, _ = sizing.destination_capital(_Dest())
    sizing._cache_put("admin_live", 540.53)
    reel, _ = sizing.destination_capital(_Dest())
    assert reel < global_cap
    assert global_cap / reel == pytest.approx(5.55, abs=0.1)


# ── Miroir de capital : le demo doit refleter le reel ─────────────────

def test_le_demo_emprunte_le_capital_du_compte_reel():
    """Le compte de demonstration existe pour refleter le reel. Dimensionner
    sur SON solde (652 EUR contre 415) produirait des tailles differentes,
    donc des trades non comparables — ce qui annulerait sa raison d'etre."""
    demo = _Dest(dest_id="admin_legacy")
    demo.capital_mirror = "admin_live"
    sizing._cache_put("admin_live", 415.33)
    sizing._cache_put("admin_legacy", 652.13)   # son propre solde, a IGNORER
    capital, source = sizing.destination_capital(demo)
    assert capital == pytest.approx(415.33), "le demo doit suivre le reel"
    assert source == "miroir:admin_live"


def test_le_miroir_indisponible_retombe_sur_le_global():
    """Plutot que de dimensionner sur son propre solde — ce serait produire
    silencieusement des trades non comparables, l'erreur meme qu'on corrige."""
    demo = _Dest(dest_id="admin_legacy")
    demo.capital_mirror = "admin_live"
    sizing._cache_put("admin_legacy", 652.13)
    capital, source = sizing.destination_capital(demo)
    assert source == "global"
    assert capital != pytest.approx(652.13)


def test_une_surcharge_explicite_l_emporte_sur_le_miroir():
    demo = _Dest(dest_id="admin_legacy")
    demo.capital_mirror = "admin_live"
    demo.trading_capital = 900.0
    sizing._cache_put("admin_live", 415.33)
    capital, source = sizing.destination_capital(demo)
    assert capital == pytest.approx(900.0)
    assert source == "destination"


def test_le_compte_reel_garde_son_propre_solde():
    """Le miroir ne va que dans un sens : le reel ne suit personne."""
    reel = _Dest(dest_id="admin_live")
    sizing._cache_put("admin_live", 415.33)
    capital, source = sizing.destination_capital(reel)
    assert capital == pytest.approx(415.33)
    assert source == "live"


@pytest.mark.asyncio
async def test_le_refresh_interroge_le_bridge_REFLETE(monkeypatch):
    """Sans ca le cache du miroir resterait vide et le demo retomberait
    indefiniment sur le global."""
    cap = {}
    monkeypatch.setattr(httpx, "AsyncClient", _client(cap, {"equity": 415.33}))
    reel = _Dest(dest_id="admin_live")
    reel.bridge_url = "http://bridge-live"
    demo = _Dest(dest_id="admin_legacy")
    demo.capital_mirror = "admin_live"
    demo.bridge_url = "http://bridge-demo"
    monkeypatch.setattr(
        "backend.services.bridge_destinations.admin_destinations", lambda: [reel, demo]
    )
    val = await sizing.refresh_destination_capital(demo)
    assert val == pytest.approx(415.33)
    assert "bridge-live" in cap["url"], "c'est le bridge REEL qu'il faut interroger"
    assert sizing._cache_get("admin_live") == pytest.approx(415.33)
