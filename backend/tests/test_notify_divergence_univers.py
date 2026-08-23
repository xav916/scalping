"""Le radar vise-t-il des instruments que la destination ne sait pas tracer ?

Le 23/08 : 14 des 23 cryptos de `WATCHED_PAIRS` etaient scorees, poussees
vers Kraken, puis jetees par un `HTTP 400 unsupported pair`. L'admission
filtre par CLASSE d'actif (`{"crypto"}`), jamais par instrument — et la seule
place ou vit « ce bridge sait-il tracer cette paire » est une table en dur
dans le bridge, lue au dernier moment.

> **Une porte posee d'un seul cote n'est pas une porte.**

⛔ Le piege verrouille ici : **un bridge injoignable rendrait « TOUT est
divergent »**. Sans distinction, l'alerte crierait 23 instruments perdus a
chaque coupure reseau, deviendrait du bruit, et on cesserait de la lire —
exactement le sort du moniteur muet. `None` (muet) et `False` (refuse) sont
donc deux verdicts differents, et un test l'impose.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import urllib.error

import pytest

_SCRIPT = (pathlib.Path(__file__).resolve().parents[2]
           / "scripts" / "notify_divergence_univers.py")


@pytest.fixture()
def script():
    spec = importlib.util.spec_from_file_location("divergence", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# Le tri : traçable / refusée / muette
# --------------------------------------------------------------------------

def test_le_cas_reel_du_23_08(script):
    """9 traçables sur 23, 14 refusées — l'état mesuré en production."""
    tracables = ["BTC/USD", "ETH/USD", "SOL/USD", "ADA/USD", "XRP/USD",
                 "LTC/USD", "DOT/USD", "DOGE/USD", "LINK/USD"]
    refusees = ["BNB/USD", "XLM/USD", "SEI/USD", "ENS/USD", "HBAR/USD",
                "ARB/USD", "CRV/USD", "LDO/USD", "PAXG/USD", "ALGO/USD",
                "AAVE/USD", "MANA/USD", "UNI/USD", "ETHFI/USD"]
    verdicts = {p: True for p in tracables} | {p: False for p in refusees}

    r = script.analyser("admin_kraken", tracables + refusees, verdicts)
    assert r["attendues"] == 23
    assert len(r["tracables"]) == 9
    assert len(r["refusees"]) == 14
    assert r["muettes"] == []
    assert "ETHFI/USD" in r["refusees"]


def test_un_bridge_MUET_n_est_pas_un_bridge_qui_REFUSE(script):
    """⛔ Le piège central.

    Bridge injoignable : les 23 paires reviennent `None`. Elles doivent
    tomber dans « muettes », JAMAIS dans « refusées » — sinon l'alerte
    annonce 23 instruments perdus a chaque coupure reseau.
    """
    paires = [f"X{i}/USD" for i in range(23)]
    r = script.analyser("admin_kraken", paires, {p: None for p in paires})
    assert r["refusees"] == [], "un bridge muet a été compté comme refusant"
    assert len(r["muettes"]) == 23
    assert r["tracables"] == []


def test_melange_partiel(script):
    """Un bridge qui répond pour certaines paires et pas d'autres."""
    r = script.analyser("admin_kraken", ["A/USD", "B/USD", "C/USD"],
                        {"A/USD": True, "B/USD": False, "C/USD": None})
    assert r["tracables"] == ["A/USD"]
    assert r["refusees"] == ["B/USD"]
    assert r["muettes"] == ["C/USD"]


def test_univers_parfaitement_aligne(script):
    r = script.analyser("admin_kraken", ["A/USD", "B/USD"],
                        {"A/USD": True, "B/USD": True})
    assert r["refusees"] == [] and r["muettes"] == []


# --------------------------------------------------------------------------
# La lecture du bridge : distinguer « je ne sais pas tracer » d'une panne
# --------------------------------------------------------------------------

class _Rep:
    def __init__(self, charge):
        self._c = json.dumps(charge).encode()

    def read(self):
        return self._c

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _urlopen(script, monkeypatch, reponse):
    def _faux(rq, timeout=None):
        if isinstance(reponse, Exception):
            raise reponse
        return _Rep(reponse)
    monkeypatch.setattr(script.urllib.request, "urlopen", _faux)


def test_400_unsupported_pair_est_un_REFUS_franc(script, monkeypatch):
    """Le bridge a répondu : il ne sait pas tracer. C'est une information."""
    err = urllib.error.HTTPError(
        "u", 400, "Bad Request", {},
        __import__("io").BytesIO(
            json.dumps({"error": "unsupported pair XLM/USD",
                        "ok": False}).encode()))
    _urlopen(script, monkeypatch, err)
    assert script._tracable("http://x:8790", "k", "XLM/USD") is False


def test_500_du_bridge_n_est_PAS_un_refus(script, monkeypatch):
    """Une erreur serveur ne dit rien sur la table de symboles."""
    err = urllib.error.HTTPError(
        "u", 500, "Server Error", {},
        __import__("io").BytesIO(b'{"error": "kraken tickers not success"}'))
    _urlopen(script, monkeypatch, err)
    assert script._tracable("http://x:8790", "k", "XLM/USD") is None


def test_bridge_injoignable_rend_None(script, monkeypatch):
    _urlopen(script, monkeypatch, urllib.error.URLError("connection refused"))
    assert script._tracable("http://x:8790", "k", "XLM/USD") is None


def test_reponse_ok_rend_True(script, monkeypatch):
    _urlopen(script, monkeypatch, {"ok": True, "pair": "BTC/USD", "last": 1})
    assert script._tracable("http://x:8790", "k", "BTC/USD") is True


def test_la_paire_est_encodee_dans_l_url(script, monkeypatch):
    """`BTC/USD` contient un `/` : non encodé, il casserait la route."""
    vues = []

    def _faux(rq, timeout=None):
        vues.append(rq.full_url)
        return _Rep({"ok": True})

    monkeypatch.setattr(script.urllib.request, "urlopen", _faux)
    script._tracable("http://x:8790", "k", "BTC/USD")
    assert vues[0].endswith("/tick/BTC%2FUSD"), vues


def test_la_cle_du_bridge_est_transmise(script, monkeypatch):
    """Sans en-tête, le bridge rendrait 401 — lu à tort comme « muet »."""
    vues = []

    def _faux(rq, timeout=None):
        vues.append(rq.headers)
        return _Rep({"ok": True})

    monkeypatch.setattr(script.urllib.request, "urlopen", _faux)
    script._tracable("http://x:8790", "secret", "BTC/USD")
    assert vues[0].get("X-bridge-key") == "secret", vues
