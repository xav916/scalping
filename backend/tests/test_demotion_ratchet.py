"""Le cliquet de rétrogradation : coupé le 2026-08-06.

Constat de production : l'univers tradable est passé de 11 couples à 8 en un
jour, et 62 % du volume a disparu. Cause — la rétrogradation se déclenchait sur
« 3 pertes consécutives », alors que **73,4 % des fenêtres de 7 trades** en
contiennent déjà une (mesuré sur 1581 trades réels, taux de réussite 23,9 %).

Combiné au plancher de 30 trades RÉELS exigé pour promouvoir — qu'une paire non
exécutante ne peut jamais atteindre — cela formait un **cliquet** : l'univers ne
pouvait que rétrécir.

⚠️ Ces tests distinguent deux choses que le code confondait :
- une **inférence statistique** sur quelques observations (désactivée) ;
- une **limite de perte** sur de l'argent réellement perdu (toujours active).
"""
import pytest

from backend.services import promotion_engine as pe
from backend.services import pair_admission_controller as pac


@pytest.fixture
def live_auto(monkeypatch):
    """Couple en AUTO_EXEC sur la destination Live."""
    monkeypatch.setattr(pac, "get_current_state", lambda *a, **k: pac.STATE_AUTO_EXEC)
    monkeypatch.setattr(pe.pac, "get_current_state", lambda *a, **k: pac.STATE_AUTO_EXEC)


@pytest.fixture
def capital_3000(monkeypatch):
    """Fixe le capital de référence. Sans ça, le seuil de drawdown dépend de
    l'environnement (10 000 € en local, 3 000 € en production) et le test
    mesurerait la config plutôt que la règle."""
    import config.settings
    monkeypatch.setattr(config.settings, "TRADING_CAPITAL", 3000.0)


def _trades(monkeypatch, pnls):
    """`_query_trades_pnl` rend les trades du plus récent au plus ancien."""
    monkeypatch.setattr(pe, "_query_trades_pnl", lambda *a, **k: [{"pnl": p} for p in pnls])


# ── Le critère qui ne mesurait rien ───────────────────────────────────

def test_dix_pertes_consecutives_ne_retrogradent_plus(live_auto, monkeypatch):
    """Dix pertes d'affilée sur de petits montants : c'est du bruit ordinaire
    à 24 % de réussite, pas une dégradation. Aucune rétrogradation."""
    _trades(monkeypatch, [-1.0] * 10)
    assert pe.check_demotion("XAU/USD", "sell", "admin_live") is None


def test_trois_pertes_consecutives_ne_retrogradent_plus(live_auto, monkeypatch):
    """LE cas qui a coupé ETH/USD vente et WTI/USD achat en production."""
    _trades(monkeypatch, [-1.0, -1.0, -1.0, 5.0, 3.0])
    assert pe.check_demotion("ETH/USD", "sell", "admin_live") is None


def test_le_critere_reste_activable_sciemment(live_auto, monkeypatch):
    """Désactivé par défaut, pas supprimé : un seuil explicite le réarme."""
    monkeypatch.setattr(pe, "DEMOTION_LIVE_TRAD_MAX_CONSEC_SL", 3)
    _trades(monkeypatch, [-1.0, -1.0, -1.0])
    d = pe.check_demotion("ETH/USD", "sell", "admin_live")
    assert d is not None
    assert d["trigger"] == "3_consec_sl"


# ── La limite de perte, elle, reste active ────────────────────────────

def test_le_drawdown_retrograde_toujours(live_auto, capital_3000, monkeypatch):
    """Une perte réelle supérieure à 10 % du capital est une grandeur mesurée,
    pas une inférence. Elle doit continuer de couper."""
    # Capital 3000 € : un drawdown de 400 € = 13,3 % > seuil Live de 10 %.
    _trades(monkeypatch, [-400.0, 0.0])
    d = pe.check_demotion("XAU/USD", "sell", "admin_live")
    assert d is not None
    assert d["trigger"].startswith("dd_above_")
    assert d["to_state"] == pac.STATE_TELEGRAM


def test_drawdown_sous_le_seuil_ne_retrograde_pas(live_auto, capital_3000, monkeypatch):
    _trades(monkeypatch, [-50.0, -50.0, -50.0])
    assert pe.check_demotion("XAU/USD", "sell", "admin_live") is None


def test_seuil_demo_plus_permissif_que_live(live_auto, capital_3000, monkeypatch):
    """Demo tolère 15 % de drawdown, Live seulement 10 % : un drawdown de 12 %
    coupe le Live et laisse passer la Demo."""
    _trades(monkeypatch, [-380.0, 0.0])   # 12,7 % de 3000 €
    assert pe.check_demotion("XAU/USD", "sell", "admin_live") is not None
    assert pe.check_demotion("XAU/USD", "sell", "admin_legacy") is None


# ── Le cliquet lui-même ───────────────────────────────────────────────

def test_une_sequence_realiste_ne_declenche_aucune_coupure(live_auto, monkeypatch):
    """Reproduction du profil réel : 24 % de réussite, gain moyen 16 €, perte
    moyenne 7,50 €. C'est le régime NORMAL du système — il ne doit produire
    aucune rétrogradation, sinon la coupure est un minuteur et l'univers
    tradable ne peut que rétrécir."""
    sequence = ([-7.5] * 3 + [16.0] + [-7.5] * 4 + [16.0] + [-7.5] * 3) * 2
    _trades(monkeypatch, sequence)
    assert pe.check_demotion("ETH/USD", "sell", "admin_live") is None
    assert pe.check_demotion("ETH/USD", "sell", "admin_legacy") is None


# ── Garde-fous de portée ──────────────────────────────────────────────

def test_un_couple_non_auto_exec_n_est_pas_concerne(monkeypatch):
    monkeypatch.setattr(pe.pac, "get_current_state", lambda *a, **k: pac.STATE_TELEGRAM)
    _trades(monkeypatch, [-400.0])
    assert pe.check_demotion("XAU/USD", "sell", "admin_live") is None


def test_destination_inconnue_ne_retrograde_rien(live_auto, monkeypatch):
    _trades(monkeypatch, [-400.0])
    assert pe.check_demotion("XAU/USD", "sell", "user:2") is None


def test_aucun_trade_ne_declenche_rien(live_auto, monkeypatch):
    _trades(monkeypatch, [])
    assert pe.check_demotion("XAU/USD", "sell", "admin_live") is None
