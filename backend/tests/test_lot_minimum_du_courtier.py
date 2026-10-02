"""Le lot minimum se LIT chez le courtier, il ne se suppose pas.

⛔ **Le constat du 2026-10-02.** `porte_risque_par_trade.LOT_MINIMUM` valait
`{"mt5": 0.01}` — un litteral, jamais confronte au courtier. Verifie ce jour-la
via `GET /symbol_specs/XAUUSD` : `volume_min 0.01`, `volume_step 0.01`,
`contract_size 100`. Le litteral etait **juste**.

🔑 Mais il etait juste **par chance**, et c'est le probleme : tout le calcul du
risque par trade en depend. Le risque vaut `lot x distance au stop`, et le lot
est bloque au plancher — donc un plancher faux rend un risque faux, et la porte
qui borne l'engagement par trade calculerait a cote sans qu'une seule erreur ne
soit levee. Un changement de courtier ou de type de compte suffirait.

⚠️ **L'ASYMETRIE du repli, assumee.** Si le pont est muet, on retombe sur le
litteral `0.01` — exactement le comportement d'avant, donc aucune regression.
Mais si le vrai plancher etait PLUS GRAND, ce repli sous-estime le risque. On
l'accepte parce que l'alternative — refuser de trader quand `/symbol_specs` est
injoignable — couperait tout le flux pour une panne qui n'est pas celle de la
porte. La lecture reussie, elle, rend la porte PLUS stricte si le courtier
annonce davantage.
"""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from backend.services import porte_risque_par_trade as prt


def _dest(dest_id="admin_live", url="http://pont.invalide"):
    return NS(destination_id=dest_id, bridge_url=url, bridge_api_key="k",
              bridge_type="mt5", user_id=None, symbol_map=None)


@pytest.fixture(autouse=True)
def _vide_le_cache():
    prt._specs_cache.clear()
    yield
    prt._specs_cache.clear()


@pytest.fixture
def pont(monkeypatch):
    """Ce que repond `/symbol_specs`, et combien de fois on le demande."""
    etat = {"reponse": {"volume_min": 0.01, "volume_step": 0.01}, "appels": 0}

    def _lire(dest, symbole):
        etat["appels"] += 1
        return etat["reponse"]

    monkeypatch.setattr(prt, "_lire_specs", _lire)
    return etat


# --- La lecture ----------------------------------------------------------

def test_le_plancher_du_courtier_est_respecte(pont):
    """Un courtier qui annonce 0,1 impose 0,1 — pas le litteral."""
    pont["reponse"] = {"volume_min": 0.1, "volume_step": 0.1}
    assert prt._lot_minimum(_dest(), "XAU/USD") == pytest.approx(0.1)


def test_le_plancher_lu_vaut_bien_celui_du_courtier(pont):
    pont["reponse"] = {"volume_min": 0.01, "volume_step": 0.01}
    assert prt._lot_minimum(_dest(), "XAU/USD") == pytest.approx(0.01)


def test_le_pas_PLUS_GRAND_que_le_minimum_fait_loi(pont):
    """⛔ Le premier ordre acceptable est un MULTIPLE du pas.

    Un `volume_min` de 0,01 avec un `volume_step` de 0,05 ne permet pas 0,01 :
    le plus petit ordre reel vaut 0,05. Prendre le minimum seul
    sous-estimerait le risque.
    """
    pont["reponse"] = {"volume_min": 0.01, "volume_step": 0.05}
    assert prt._lot_minimum(_dest(), "XAU/USD") == pytest.approx(0.05)


# --- Les replis ----------------------------------------------------------

def test_un_pont_muet_replie_sur_le_litteral(monkeypatch):
    """⚠️ Le comportement d'AVANT : aucune regression quand la lecture rate."""
    monkeypatch.setattr(prt, "_lire_specs", lambda dest, symbole: None)
    assert prt._lot_minimum(_dest(), "XAU/USD") == pytest.approx(0.01)


def test_une_valeur_absurde_replie_au_lieu_de_rendre_zero(pont):
    """⛔ Un plancher nul rendrait un risque NUL — donc une porte ouverte."""
    for absurde in ({"volume_min": 0}, {"volume_min": -1},
                    {"volume_min": "x"}, {}):
        prt._specs_cache.clear()
        pont["reponse"] = absurde
        assert prt._lot_minimum(_dest(), "XAU/USD") == pytest.approx(0.01), absurde


def test_une_route_sans_pont_garde_son_litteral(monkeypatch):
    """Les routes EA queue n'ont pas de pont a interroger."""
    monkeypatch.setattr(prt, "_lire_specs",
                        lambda dest, symbole: pytest.fail("ne doit pas lire"))
    assert prt._lot_minimum(_dest(url=""), "XAU/USD") == pytest.approx(0.01)


def test_un_bridge_type_inconnu_rend_None(monkeypatch):
    """`None` = la question ne se pose pas. Inchange."""
    monkeypatch.setattr(prt, "_lire_specs", lambda dest, symbole: None)
    d = NS(destination_id="x", bridge_url="", bridge_api_key="",
           bridge_type="kraken", user_id=None, symbol_map=None)
    assert prt._lot_minimum(d, "XAU/USD") is None


# --- Le cache ------------------------------------------------------------
#
# ⛔ MES TROIS PREMIERS TESTS DE CACHE ETAIENT FAUX. Ils doublaient
# `_lire_specs` — c'est-a-dire exactement la fonction qui PORTE le cache — puis
# comptaient les appels de la doublure. Ils mesuraient donc ma doublure, pas le
# systeme, et auraient passe avec un cache inexistant.
#
# 🔑 On double la couche HTTP et on compte les clients REELLEMENT construits,
# comme `test_cap_par_paire_courtier` le fait pour `/positions`.

def _client_http(reponse_json):
    from unittest.mock import MagicMock
    reponse = MagicMock()
    reponse.status_code = 200
    reponse.json.return_value = reponse_json
    client = MagicMock()
    client.__enter__ = lambda s: client
    client.__exit__ = lambda *a: False
    client.get.return_value = reponse
    return client


def test_les_specs_sont_mises_en_cache():
    """Consultees une fois par setup : sans cache, une vague de signaux ferait
    autant d'aller-retours HTTP que la porte de positions."""
    from unittest.mock import patch
    import httpx
    client = _client_http({"volume_min": 0.01, "volume_step": 0.01})
    with patch.object(httpx, "Client", return_value=client) as fabrique:
        for _ in range(5):
            assert prt._lot_minimum(_dest(), "XAU/USD") == pytest.approx(0.01)
    assert fabrique.call_count == 1


def test_le_cache_distingue_les_paires():
    from unittest.mock import patch
    import httpx
    client = _client_http({"volume_min": 0.01, "volume_step": 0.01})
    with patch.object(httpx, "Client", return_value=client) as fabrique:
        prt._lot_minimum(_dest(), "XAU/USD")
        prt._lot_minimum(_dest(), "EUR/USD")
    assert fabrique.call_count == 2


def test_le_cache_distingue_les_destinations():
    from unittest.mock import patch
    import httpx
    client = _client_http({"volume_min": 0.01, "volume_step": 0.01})
    with patch.object(httpx, "Client", return_value=client) as fabrique:
        prt._lot_minimum(_dest("admin_live"), "XAU/USD")
        prt._lot_minimum(_dest("admin_legacy"), "XAU/USD")
    assert fabrique.call_count == 2


def test_un_pont_qui_repond_500_replie_sur_le_litteral():
    """⛔ Un refus HTTP n'est pas un plancher — et ne doit pas rendre zero."""
    from unittest.mock import MagicMock, patch
    import httpx
    reponse = MagicMock()
    reponse.status_code = 500
    client = MagicMock()
    client.__enter__ = lambda s: client
    client.__exit__ = lambda *a: False
    client.get.return_value = reponse
    with patch.object(httpx, "Client", return_value=client):
        assert prt._lot_minimum(_dest(), "XAU/USD") == pytest.approx(0.01)


# --- Le bout en bout : le risque suit le plancher lu --------------------

def test_le_risque_en_euros_suit_le_plancher_du_courtier(pont, monkeypatch):
    """⛔ Ce qui compte vraiment : un plancher 10x plus grand = risque 10x.

    Sans ce test, on verifierait la lecture sans verifier qu'elle ATTEINT le
    calcul — le defaut de la doublure branchee nulle part.
    """
    vus = {}

    def _calculer(**kw):
        vus["volume"] = kw.get("volume")
        return {"risque_eur": 65.0 * (kw.get("volume") or 0) / 0.01}

    monkeypatch.setattr("backend.services.risk_eur.calculer", _calculer)
    setup = NS(pair="XAU/USD", direction="buy", entry_price=4150.0,
               stop_loss=4075.0)

    pont["reponse"] = {"volume_min": 0.01, "volume_step": 0.01}
    assert prt.risque_au_lot_minimum(setup, _dest()) == pytest.approx(65.0)
    assert vus["volume"] == pytest.approx(0.01)

    prt._specs_cache.clear()
    pont["reponse"] = {"volume_min": 0.1, "volume_step": 0.1}
    assert prt.risque_au_lot_minimum(setup, _dest()) == pytest.approx(650.0)
    assert vus["volume"] == pytest.approx(0.1)
