"""Alerte de niveau de marge sur les comptes réels.

Le piège de ce genre de contrôle n'est pas de détecter un compte en danger : il
est de crier sur un compte sain. Un compte **sans position** a une marge nulle,
et lire 0 / 0 comme « 0 %, donc critique » produirait une alerte quotidienne que
personne ne lirait plus le jour où elle compte vraiment.
"""
import pytest

from backend.services import margin_level_check as mlc


class _Reponse:
    def __init__(self, payload, status=200):
        self._p = payload
        self.status_code = status

    def json(self):
        return self._p


@pytest.fixture
def bridge(monkeypatch):
    monkeypatch.setattr(mlc, "_bridges", lambda: [("live", "http://x", "k")])
    monkeypatch.delenv("MARGIN_ALERT_LEVEL_PCT", raising=False)

    def _poser(payload, status=200):
        monkeypatch.setattr(mlc.httpx, "get", lambda *a, **k: _Reponse(payload, status))
    return _poser


def _compte(equity, margin, positions=1):
    return {"balance": 300.0, "equity": equity, "margin": margin,
            "margin_free": equity - margin, "positions_count": positions}


# ── Le cas qui a motivé le contrôle ───────────────────────────────────

def test_compte_proche_de_la_liquidation_alerte(bridge):
    """Situation réelle du 2026-08-06 aggravée : équité 110 € pour 177 € de
    marge = 62 %, sous le seuil de 70 % et en route vers la liquidation."""
    bridge(_compte(equity=110.0, margin=177.68))
    r = mlc.run()
    assert r["alerte"] is True
    assert r["comptes"]["live"]["niveau_marge_pct"] == pytest.approx(61.9, abs=0.1)


def test_appel_de_marge_sans_urgence_immediate_n_alerte_pas(bridge):
    """95,5 % : sous l'appel de marge (100 %) mais loin de la liquidation.
    C'est exactement l'état accepté sciemment — il ne doit pas déclencher."""
    bridge(_compte(equity=169.61, margin=177.68))
    r = mlc.run()
    assert r["comptes"]["live"]["niveau_marge_pct"] == pytest.approx(95.5, abs=0.1)
    assert r["alerte"] is False


def test_compte_confortable_n_alerte_pas(bridge):
    bridge(_compte(equity=500.0, margin=100.0))
    assert mlc.run()["alerte"] is False


# ── Le piège : ne pas crier sur un compte sain ────────────────────────

def test_compte_sans_position_n_alerte_jamais(bridge):
    """Marge nulle = aucune position. Le ratio n'existe pas ; le lire comme
    0 % transformerait le contrôle en alarme quotidienne inutile."""
    bridge(_compte(equity=564.5, margin=0.0, positions=0))
    r = mlc.run()
    assert r["comptes"]["live"]["niveau_marge_pct"] is None
    assert r["alerte"] is False


def test_bridge_injoignable_n_invente_pas_de_niveau(bridge, monkeypatch):
    def _boom(*a, **k):
        raise ConnectionError("VPS éteint")
    monkeypatch.setattr(mlc.httpx, "get", _boom)
    r = mlc.run()
    assert r["comptes"]["live"]["joignable"] is False
    assert r["comptes"]["live"]["niveau_marge_pct"] is None
    assert r["alerte"] is False, "injoignable n'est pas dangereux, c'est inconnu"


def test_reponse_http_en_erreur_est_signalee_sans_alerte(bridge):
    bridge({}, status=401)
    r = mlc.run()
    assert r["comptes"]["live"]["erreur"] == "HTTP 401"
    assert r["alerte"] is False


def test_aucun_bridge_configure_ne_plante_pas(monkeypatch):
    monkeypatch.setattr(mlc, "_bridges", lambda: [])
    r = mlc.run()
    assert r["comptes"] == {}
    assert r["alerte"] is False


# ── Réglage ───────────────────────────────────────────────────────────

def test_seuil_reglable(bridge, monkeypatch):
    monkeypatch.setenv("MARGIN_ALERT_LEVEL_PCT", "96")
    bridge(_compte(equity=169.61, margin=177.68))   # 95,5 %
    assert mlc.run()["alerte"] is True


def test_seuil_illisible_retombe_sur_le_defaut(bridge, monkeypatch):
    monkeypatch.setenv("MARGIN_ALERT_LEVEL_PCT", "pas-un-nombre")
    bridge(_compte(equity=169.61, margin=177.68))
    r = mlc.run()
    assert r["seuil_alerte_pct"] == mlc.DEFAULT_ALERT_LEVEL
    assert r["alerte"] is False
