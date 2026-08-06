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
                  "destination_id TEXT, date TEXT, pushed_at TEXT)")
    monkeypatch.setattr("backend.services.trade_log_service._DB_PATH", f)
    return f


ARME = "2026-08-06T20:00:00+00:00"


def _pousse(f, n, dest="admin_legacy", quand="2026-08-06T21:00:00+00:00"):
    with sqlite3.connect(f) as c:
        for _ in range(n):
            c.execute("INSERT INTO mt5_pushes (destination_id, date, pushed_at) "
                      "VALUES (?,?,?)", (dest, quand[:10], quand))


def _quota(monkeypatch, n, depuis=ARME):
    import config.settings
    monkeypatch.setattr(config.settings, "TRADE_DEROGATION_PUSHES", n)
    monkeypatch.setattr(config.settings, "TRADE_DEROGATION_SINCE", depuis)


# ── L'ouverture, puis la fermeture automatique ────────────────────────

def test_quota_nul_le_filtre_reste_actif(base, monkeypatch):
    """Comportement par défaut : aucune levée."""
    _quota(monkeypatch, 0)
    assert mb._jeton_derogation_restant() is False


def test_avec_un_quota_de_1_la_porte_est_ouverte(base, monkeypatch):
    _quota(monkeypatch, 1)
    assert mb._jeton_derogation_restant() is True


def test_le_filtre_SE_REARME_apres_le_premier_push(base, monkeypatch):
    """LE test qui compte : sans réarmement automatique, la fenêtre resterait
    ouverte jusqu'à ce que quelqu'un y repense."""
    _quota(monkeypatch, 1)
    _pousse(base, 1)
    assert mb._jeton_derogation_restant() is False


def test_seuls_les_pushes_du_compte_PILOTE_consomment_le_quota(base, monkeypatch):
    """La copie vers le réel ne passe pas par cette porte : un trade doit
    consommer un seul jeton, pas deux."""
    _quota(monkeypatch, 1)
    _pousse(base, 3, dest="admin_live")
    _pousse(base, 2, dest="user:2")
    assert mb._jeton_derogation_restant() is True


def test_les_pushes_ANTERIEURS_a_l_armement_ne_consomment_rien(base, monkeypatch):
    """Le cas reel : 8 pushes le matin ne doivent pas consommer un quota arme
    le soir. Compter par jour calendaire l'aurait epuise d'avance."""
    _quota(monkeypatch, 1)
    _pousse(base, 8, quand="2026-08-06T09:00:00+00:00")
    assert mb._jeton_derogation_restant() is True


def test_sans_instant_d_armement_le_filtre_est_MAINTENU(base, monkeypatch):
    """On ne compte pas depuis une base inconnue."""
    _quota(monkeypatch, 1, depuis="")
    assert mb._jeton_derogation_restant() is False


# ── Le doute doit fermer, pas ouvrir ──────────────────────────────────

def test_compteur_illisible_MAINTIENT_le_filtre(monkeypatch, tmp_path):
    """Un doute ne doit pas ouvrir la vanne."""
    _quota(monkeypatch, 1)
    monkeypatch.setattr("backend.services.trade_log_service._DB_PATH", tmp_path)
    assert mb._jeton_derogation_restant() is False


# ── L'effet sur la porte du dispatch ──────────────────────────────────

def test_un_pattern_hors_whitelist_passe_pendant_la_levee(base, monkeypatch):
    _quota(monkeypatch, 1)
    monkeypatch.setattr(mb, "MT5_BRIDGE_ALLOWED_PATTERNS",
                        frozenset({"range_bounce_up"}))

    class S:
        pair = "XAU/USD"; direction = "buy"; signal_pattern = "momentum_up"
    assert mb._pattern_value(S()) not in mb.MT5_BRIDGE_ALLOWED_PATTERNS
    assert mb._jeton_derogation_restant() is True


def test_apres_le_quota_le_meme_pattern_est_refuse(base, monkeypatch):
    _quota(monkeypatch, 1)
    _pousse(base, 1)
    monkeypatch.setattr(mb, "MT5_BRIDGE_ALLOWED_PATTERNS",
                        frozenset({"range_bounce_up"}))
    assert mb._jeton_derogation_restant() is False


# ── Le jeton leve AUSSI la porte de cout, mais pas sur Kraken ─────────

def _dest(bridge_type="mt5"):
    from backend.services.cost_model import CostModel
    class D: pass
    d = D()
    d.bridge_type = bridge_type
    d.cost_model = CostModel(proportional_rate_per_leg=0.0005)
    d.expected_edge_r = 0.11
    return d


def _setup_stop_serre():
    class S: pass
    s = S()
    s.pair = "XAU/USD"; s.direction = "buy"; s.horizon = "5min"
    s.entry_price = 4000.0
    s.stop_loss = 4000.0 * (1 - 0.001)   # 0,1 % : bien sous le seuil
    s.take_profit_1 = 4000.0 * 1.002
    return s


def test_le_jeton_leve_la_porte_de_cout_sur_MT5(base, monkeypatch):
    _quota(monkeypatch, 1)
    assert mb._cost_rejection(_setup_stop_serre(), _dest("mt5")) is None


def test_apres_le_quota_la_porte_de_cout_refuse_de_nouveau(base, monkeypatch):
    _quota(monkeypatch, 1)
    _pousse(base, 1)
    assert mb._cost_rejection(_setup_stop_serre(), _dest("mt5")) == "fees_exceed_edge"


def test_le_jeton_n_ouvre_JAMAIS_kraken(base, monkeypatch):
    """Effet de bord à éviter : les frais Kraken sont 10x superieurs et
    s'ajoutent a un portage. Un jeton pose pour observer MT5 ne doit pas
    faire passer un trade crypto non rentable."""
    _quota(monkeypatch, 1)
    assert mb._cost_rejection(_setup_stop_serre(), _dest("kraken")) == "fees_exceed_edge"
