"""Kraken : l'âge d'une position ne se lit pas dans `fillTime` (2026-09-05).

`GET /api/v3/openpositions` rend, pour **chacune** des positions vivantes :

    "fillTime": "1970-01-01T00:00:00.000Z"

Ce n'est pas notre lecture qui échoue — c'est Kraken qui rend l'époque Unix.
Le bridge la recopiait telle quelle.

⛔ Une date fausse est PIRE qu'une date absente. Une règle qui calcule un âge
depuis 1970 obtient ~490 000 heures : toute porte de durée la juge éternelle,
et toute médiane de détention est empoisonnée sans le dire. Même famille que
`entry_price=0` sur le réel — **`None`, jamais une valeur qui a l'air vraie.**

🔑 La donnée existe ailleurs : `/api/v3/fills` porte de vrais horodatages.
L'ouverture se **reconstruit** en rejouant les exécutions du symbole, et ne
vaut que si le net reconstruit s'accorde avec la position réellement ouverte —
l'historique des fills est borné, un symbole plus vieux que la fenêtre rend
`None` plutôt qu'une date empruntée à la mauvaise position.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

_BRIDGE = (pathlib.Path(__file__).resolve().parents[2]
           / "kraken-bridge" / "bridge.py")


@pytest.fixture(scope="module")
def bridge():
    spec = importlib.util.spec_from_file_location("kraken_futures_bridge", _BRIDGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fill(symbol, side, size, t):
    return {"symbol": symbol, "side": side, "size": size, "fillTime": t}


def _pos(symbol, side, size):
    return {"symbol": symbol, "side": side, "size": size}


# ── La reconstruction ────────────────────────────────────────────────

def test_ouverture_simple(bridge):
    """Un achat, rien d'autre : l'ouverture est ce fill-là."""
    fills = [_fill("PF_XLMUSD", "buy", 82.0, "2026-09-05T18:42:48.004Z")]
    ages = bridge.ouvertures_par_symbole(fills, [_pos("PF_XLMUSD", "long", 82.0)])
    assert ages["PF_XLMUSD"] == "2026-09-05T18:42:48.004Z"


def test_un_renfort_ne_rajeunit_PAS_la_position(bridge):
    """⛔ Ajouter à une position ne redémarre pas son horloge : ce qui coûte
    du portage, c'est la date d'ENTRÉE, pas celle du dernier ajout."""
    fills = [
        _fill("PF_DOTUSD", "buy", 1.0, "2026-08-22T00:41:15.154Z"),
        _fill("PF_DOTUSD", "buy", 1.2, "2026-09-01T10:00:00.000Z"),
    ]
    ages = bridge.ouvertures_par_symbole(fills, [_pos("PF_DOTUSD", "long", 2.2)])
    assert ages["PF_DOTUSD"] == "2026-08-22T00:41:15.154Z"


def test_un_cycle_ferme_puis_rouvert_compte_depuis_la_REOUVERTURE(bridge):
    """Le passage par zéro coupe l'horloge. La position d'aujourd'hui n'a pas
    l'âge de celle de la semaine dernière."""
    fills = [
        _fill("PF_ETHUSD", "buy", 1.0, "2026-08-01T00:00:00.000Z"),
        _fill("PF_ETHUSD", "sell", 1.0, "2026-08-02T00:00:00.000Z"),   # à plat
        _fill("PF_ETHUSD", "buy", 3.0, "2026-09-04T12:00:00.000Z"),    # réouvre
    ]
    ages = bridge.ouvertures_par_symbole(fills, [_pos("PF_ETHUSD", "long", 3.0)])
    assert ages["PF_ETHUSD"] == "2026-09-04T12:00:00.000Z"


def test_un_retournement_compte_depuis_le_RETOURNEMENT(bridge):
    """Long puis net vendeur : c'est une AUTRE position, pas la même vieillie."""
    fills = [
        _fill("PF_SOLUSD", "buy", 2.0, "2026-08-10T00:00:00.000Z"),
        _fill("PF_SOLUSD", "sell", 5.0, "2026-09-03T09:00:00.000Z"),   # -3
    ]
    ages = bridge.ouvertures_par_symbole(fills, [_pos("PF_SOLUSD", "short", 3.0)])
    assert ages["PF_SOLUSD"] == "2026-09-03T09:00:00.000Z"


def test_les_fills_desordonnes_sont_remis_en_ordre(bridge):
    """Kraken rend les exécutions du plus récent au plus ancien."""
    fills = [
        _fill("PF_DOTUSD", "buy", 1.2, "2026-09-01T10:00:00.000Z"),
        _fill("PF_DOTUSD", "buy", 1.0, "2026-08-22T00:41:15.154Z"),
    ]
    ages = bridge.ouvertures_par_symbole(fills, [_pos("PF_DOTUSD", "long", 2.2)])
    assert ages["PF_DOTUSD"] == "2026-08-22T00:41:15.154Z"


# ── ⛔ Ce qui doit rendre None ────────────────────────────────────────

def test_historique_trop_court_rend_None(bridge):
    """⛔ Le net reconstruit (1,0) ne s'accorde pas avec la position (2,2) :
    l'ouverture est hors de la fenêtre des fills. On ne rend pas une date
    empruntée — on dit qu'on ne sait pas."""
    fills = [_fill("PF_DOTUSD", "buy", 1.0, "2026-09-01T10:00:00.000Z")]
    ages = bridge.ouvertures_par_symbole(fills, [_pos("PF_DOTUSD", "long", 2.2)])
    assert ages["PF_DOTUSD"] is None


def test_sens_contraire_rend_None(bridge):
    """Reconstruction acheteuse, position vendeuse : quelque chose manque."""
    fills = [_fill("PF_XBTUSD", "buy", 1.0, "2026-09-01T10:00:00.000Z")]
    ages = bridge.ouvertures_par_symbole(fills, [_pos("PF_XBTUSD", "short", 1.0)])
    assert ages["PF_XBTUSD"] is None


def test_aucun_fill_pour_ce_symbole_rend_None(bridge):
    ages = bridge.ouvertures_par_symbole([], [_pos("PF_XAUUSD", "long", 1.0)])
    assert ages["PF_XAUUSD"] is None


def test_l_epoque_unix_est_traitee_comme_ABSENTE(bridge):
    """⛔ Le cœur du sujet : `1970-01-01` n'est pas une date, c'est un trou."""
    fills = [_fill("PF_XLMUSD", "buy", 82.0, "1970-01-01T00:00:00.000Z")]
    ages = bridge.ouvertures_par_symbole(fills, [_pos("PF_XLMUSD", "long", 82.0)])
    assert ages["PF_XLMUSD"] is None


def test_un_fill_illisible_ne_fait_pas_tomber_la_lecture(bridge):
    """Une exécution malformée ne doit pas priver les AUTRES symboles de leur âge."""
    fills = [
        {"symbol": "PF_XLMUSD"},                                        # rien
        _fill("PF_DOTUSD", "buy", 2.2, "2026-08-22T00:41:15.154Z"),
    ]
    ages = bridge.ouvertures_par_symbole(
        fills, [_pos("PF_XLMUSD", "long", 82.0), _pos("PF_DOTUSD", "long", 2.2)])
    assert ages["PF_XLMUSD"] is None
    assert ages["PF_DOTUSD"] == "2026-08-22T00:41:15.154Z"


# ── Tolérance sur la taille ──────────────────────────────────────────

def test_un_ecart_de_taille_infime_reste_accorde(bridge):
    """Les flottants de Kraken ne tombent pas au bit près."""
    fills = [_fill("PF_DOTUSD", "buy", 2.2000000001, "2026-08-22T00:41:15.154Z")]
    ages = bridge.ouvertures_par_symbole(fills, [_pos("PF_DOTUSD", "long", 2.2)])
    assert ages["PF_DOTUSD"] == "2026-08-22T00:41:15.154Z"


# ── La ROUTE, pas seulement la fonction ──────────────────────────────
#
# ⛔ Une fonction juste jamais appelée ne protège de rien : c'est le trou du
# détecteur de positions nues, parfait et jamais branché. On teste donc le
# branchement.

def _client(bridge, monkeypatch, reponses):
    """Client Flask avec `_signed_request` remplacé par une table de réponses."""
    def _faux(methode, chemin, *a, **k):
        if chemin in reponses:
            r = reponses[chemin]
            if isinstance(r, Exception):
                raise r
            return r
        raise AssertionError(f"appel inattendu : {chemin}")

    monkeypatch.setattr(bridge, "_signed_request", _faux)
    monkeypatch.setattr(bridge, "require_bridge_key", lambda f: f)
    bridge.app.config["TESTING"] = True
    return bridge.app.test_client()


def _reponses(positions, fills):
    return {
        "/api/v3/openpositions": {"result": "success", "openPositions": positions},
        "/api/v3/fills": ({"result": "success", "fills": fills}
                          if not isinstance(fills, Exception) else fills),
    }


def test_la_route_sert_l_age_RECONSTRUIT_et_le_pnl(bridge, monkeypatch):
    pos = [{"symbol": "PF_DOTUSD", "side": "long", "size": 2.2, "price": 0.95,
            "unrealizedPnl": -0.0687, "unrealizedFunding": 2.7e-06,
            "fillTime": "1970-01-01T00:00:00.000Z"}]
    fills = [_fill("PF_DOTUSD", "buy", 2.2, "2026-08-22T00:41:15.154Z")]
    c = _client(bridge, monkeypatch, _reponses(pos, fills))

    corps = c.get("/positions", headers={"X-Bridge-Key": "x"}).get_json()
    ligne = corps["positions"][0]
    assert ligne["fill_time"] == "2026-08-22T00:41:15.154Z"
    assert ligne["unrealized_pnl_usd"] == pytest.approx(-0.0687)
    assert "fillTime" not in ligne, "⛔ la valeur brute de Kraken vaut 1970 : ne plus la servir"


def test_fills_injoignables_LAISSE_les_positions_lisibles(bridge, monkeypatch):
    """⛔ Ne pas savoir depuis QUAND ne doit pas empêcher de savoir QUOI."""
    pos = [{"symbol": "PF_XLMUSD", "side": "long", "size": 82.0, "price": 0.18,
            "unrealizedPnl": 0.03, "unrealizedFunding": 0.0}]
    c = _client(bridge, monkeypatch, _reponses(pos, RuntimeError("kraken down")))

    r = c.get("/positions", headers={"X-Bridge-Key": "x"})
    assert r.status_code == 200
    ligne = r.get_json()["positions"][0]
    assert ligne["symbol"] == "PF_XLMUSD"
    assert ligne["fill_time"] is None, "âge inconnu, pas âge invente"
    assert ligne["size"] == 82.0
