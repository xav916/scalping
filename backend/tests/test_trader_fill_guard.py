"""Tests du garde-fou fill guard (backend/services/trader_fill_guard.py).

Vérifie la détection des fills corrompus (entry=0, deviation excessive, etc.)
qui ont généré 217 trades buggés dans l'audit du 2026-11-13.
"""
from __future__ import annotations

from backend.services import trader_fill_guard as fg


ENTRY = 3900.0  # Prix demandé référence pour les tests


def test_fill_sane_retourne_ok():
    resp = {"ok": True, "ticket": 123, "avg_fill_price": 3900.5}
    ok, reason = fg.is_fill_price_sane(resp, ENTRY)
    assert ok is True
    assert reason == "ok"


def test_fill_price_zero_rejected():
    """Le cas directement observé dans l'audit : entry=0.0."""
    resp = {"ok": True, "ticket": 123, "avg_fill_price": 0.0}
    ok, reason = fg.is_fill_price_sane(resp, ENTRY)
    assert ok is False
    assert "<= 0" in reason


def test_fill_price_negatif_rejected():
    resp = {"ok": True, "ticket": 123, "avg_fill_price": -1.5}
    ok, reason = fg.is_fill_price_sane(resp, ENTRY)
    assert ok is False
    assert "<= 0" in reason


def test_fill_price_absent_rejected():
    """Pas de avg_fill_price dans la réponse."""
    resp = {"ok": True, "ticket": 123}
    ok, reason = fg.is_fill_price_sane(resp, ENTRY)
    assert ok is False
    assert "absent" in reason


def test_fill_price_none_rejected():
    resp = {"ok": True, "ticket": 123, "avg_fill_price": None}
    ok, reason = fg.is_fill_price_sane(resp, ENTRY)
    assert ok is False
    assert "absent" in reason


def test_fill_price_non_numerique_rejected():
    resp = {"ok": True, "ticket": 123, "avg_fill_price": "NaN"}
    ok, reason = fg.is_fill_price_sane(resp, ENTRY)
    assert ok is False
    assert "non numérique" in reason


def test_deviation_5pct_exactement_passe():
    """La limite est STRICTE au-dessus de 5% → pile 5% passe."""
    # 5% de 3900 = 195 → fill à 3900 + 195 = 4095 → écart = 5% exactement
    resp = {"ok": True, "ticket": 123, "avg_fill_price": 4095.0}
    ok, reason = fg.is_fill_price_sane(resp, ENTRY)
    assert ok is True


def test_deviation_superieure_5pct_rejected():
    """Écart > 5% = probablement un symbole différent ou bug bridge."""
    # 10% de 3900 = 390 → fill à 4290 → écart 10%
    resp = {"ok": True, "ticket": 123, "avg_fill_price": 4290.0}
    ok, reason = fg.is_fill_price_sane(resp, ENTRY)
    assert ok is False
    assert "écart" in reason
    assert "10.00%" in reason or "10.0%" in reason


def test_deviation_custom_max():
    """Permet de passer un seuil custom (ex: crypto plus volatil)."""
    resp = {"ok": True, "ticket": 123, "avg_fill_price": 4500.0}  # ~15%
    # Avec max 20%, ça passe
    ok, _ = fg.is_fill_price_sane(resp, ENTRY, max_deviation_pct=20.0)
    assert ok is True
    # Avec max 5% (défaut), ça refuse
    ok, _ = fg.is_fill_price_sane(resp, ENTRY, max_deviation_pct=5.0)
    assert ok is False


def test_requested_entry_zero_desactive_check_deviation():
    """Si on ne connaît pas requested_entry, on ne peut pas checker la deviation."""
    resp = {"ok": True, "ticket": 123, "avg_fill_price": 100.0}
    ok, _ = fg.is_fill_price_sane(resp, 0.0)
    assert ok is True  # fill > 0 ok, deviation non vérifiée


def test_fail_open_sur_exception_interne():
    """Un bug du garde-fou lui-même ne doit pas bloquer le trading."""
    # resp qui lève une exception sur .get()
    class BadResp:
        def get(self, k, default=None):
            raise RuntimeError("corrompu")
    ok, reason = fg.is_fill_price_sane(BadResp(), ENTRY)
    assert ok is True  # fail-open
    assert "garde-fou erreur" in reason
