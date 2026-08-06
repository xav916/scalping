"""Levée à usage unique du filtre de patterns (2026-08-06).

Posée pour observer l'alignement démo → réel sur UN trade, sans attendre les
~10 jours que la porte de coût impose quand seul `range_bounce` passe.

⚠️ Ce que ces tests verrouillent, c'est la **fermeture automatique**. Une
fenêtre ouverte « le temps de voir » reste toujours ouverte plus longtemps que
prévu, parce que personne ne revient la refermer. Le quota doit se réarmer
seul, et un compteur illisible doit maintenir le filtre — pas l'ouvrir.
"""
import sqlite3

import pytest

from backend.services import mt5_bridge as mb


@pytest.fixture
def base(tmp_path, monkeypatch):
    f = tmp_path / "trades.db"
    with sqlite3.connect(f) as c:
        c.execute("CREATE TABLE mt5_pushes (id INTEGER PRIMARY KEY, "
                  "destination_id TEXT, date TEXT)")
    monkeypatch.setattr("backend.services.trade_log_service._DB_PATH", f)
    return f


def _pousse(f, n, dest="admin_legacy", jour=None):
    from datetime import date
    jour = jour or date.today().isoformat()
    with sqlite3.connect(f) as c:
        for _ in range(n):
            c.execute("INSERT INTO mt5_pushes (destination_id, date) VALUES (?,?)",
                      (dest, jour))


def _quota(monkeypatch, n):
    import config.settings
    monkeypatch.setattr(config.settings, "PATTERN_FILTER_BYPASS_PUSHES", n)


# ── L'ouverture, puis la fermeture automatique ────────────────────────

def test_quota_nul_le_filtre_reste_actif(base, monkeypatch):
    """Comportement par défaut : aucune levée."""
    _quota(monkeypatch, 0)
    assert mb._bypass_pattern_filter_restant() is False


def test_avec_un_quota_de_1_la_porte_est_ouverte(base, monkeypatch):
    _quota(monkeypatch, 1)
    assert mb._bypass_pattern_filter_restant() is True


def test_le_filtre_SE_REARME_apres_le_premier_push(base, monkeypatch):
    """LE test qui compte : sans réarmement automatique, la fenêtre resterait
    ouverte jusqu'à ce que quelqu'un y repense."""
    _quota(monkeypatch, 1)
    _pousse(base, 1)
    assert mb._bypass_pattern_filter_restant() is False


def test_seuls_les_pushes_du_compte_PILOTE_consomment_le_quota(base, monkeypatch):
    """La copie vers le réel ne passe pas par cette porte : un trade doit
    consommer un seul jeton, pas deux."""
    _quota(monkeypatch, 1)
    _pousse(base, 3, dest="admin_live")
    _pousse(base, 2, dest="user:2")
    assert mb._bypass_pattern_filter_restant() is True


def test_les_pushes_d_hier_ne_consomment_pas_le_quota_du_jour(base, monkeypatch):
    _quota(monkeypatch, 1)
    _pousse(base, 5, jour="2026-01-01")
    assert mb._bypass_pattern_filter_restant() is True


# ── Le doute doit fermer, pas ouvrir ──────────────────────────────────

def test_compteur_illisible_MAINTIENT_le_filtre(monkeypatch, tmp_path):
    """Un doute ne doit pas ouvrir la vanne."""
    _quota(monkeypatch, 1)
    monkeypatch.setattr("backend.services.trade_log_service._DB_PATH", tmp_path)
    assert mb._bypass_pattern_filter_restant() is False


# ── L'effet sur la porte du dispatch ──────────────────────────────────

def test_un_pattern_hors_whitelist_passe_pendant_la_levee(base, monkeypatch):
    _quota(monkeypatch, 1)
    monkeypatch.setattr(mb, "MT5_BRIDGE_ALLOWED_PATTERNS",
                        frozenset({"range_bounce_up"}))

    class S:
        pair = "XAU/USD"; direction = "buy"; signal_pattern = "momentum_up"
    assert mb._pattern_value(S()) not in mb.MT5_BRIDGE_ALLOWED_PATTERNS
    assert mb._bypass_pattern_filter_restant() is True


def test_apres_le_quota_le_meme_pattern_est_refuse(base, monkeypatch):
    _quota(monkeypatch, 1)
    _pousse(base, 1)
    monkeypatch.setattr(mb, "MT5_BRIDGE_ALLOWED_PATTERNS",
                        frozenset({"range_bounce_up"}))
    assert mb._bypass_pattern_filter_restant() is False
