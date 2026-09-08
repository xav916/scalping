"""La rétrogradation se juge en R, plus en euros contre un capital fixe.

## ⛔ Ce qui ne marchait pas

`dd_pct` rapportait le creux en EUROS à `TRADING_CAPITAL` (650 €). Le seuil de
10 % valait donc **65 €** pour tous les instruments, alors que le risque par
trade va de 3,93 € (forex) à 18,61 € (or) :

    or    : 65 / 18,61 =  3,5 trades perdants d'affilée  → rétrogradé
    forex : 65 /  3,93 = 16,5 trades                     → jamais

L'or était puni **parce qu'il est dimensionné plus gros**. Le 08/09 il a été
rétrogradé sur `dd 13,96 %` avec n=7 et 4 stops consécutifs — une série
parfaitement ordinaire.

🔑 Le garde-fou mesurait la TAILLE, pas la détérioration.

## Le seuil est DÉRIVÉ

Distribution du pire creux 7 j en R, fenêtre fiable (depuis le 25/08, placebos
crypto écartés, 11 couples) : médiane 1,00 R · 75 % 2,08 R · **max 3,57 R**.
Ce maximum est l'or acheteur du réel — celui que la règle en euros a coupé.
5 R laisse passer tout l'observé et vaut cinq stops pleins d'affilée.
"""
from __future__ import annotations

import pytest

from backend.services import promotion_engine as pe


def _trade(pnl, entry=3400.0, sl=3390.0, exit_=None, direction="buy",
           closed="2026-09-08T10:00:00+00:00"):
    """Un trade avec ses NIVEAUX — sans eux, aucun R n'est calculable."""
    if exit_ is None:
        exit_ = sl if pnl < 0 else entry + (entry - sl) * 1.8
    return {"pnl": pnl, "closed_at": closed, "close_reason": "SL" if pnl < 0 else "TP1",
            "entry_price": entry, "stop_loss": sl, "exit_price": exit_,
            "direction": direction}


# ── Le calcul ────────────────────────────────────────────────────────

def test_le_drawdown_en_R_est_calcule():
    """Quatre stops pleins d'affilée = un creux de 4 R, quelle que soit la
    taille de position."""
    m = pe._compute_metrics([_trade(-10.0) for _ in range(4)])
    assert m["n_R"] == 4
    assert m["dd_R"] == pytest.approx(4.0, abs=0.05)


def test_le_R_ne_depend_PAS_de_la_taille_en_euros():
    """🔑 LA propriété. Deux séries identiques en R, dix fois différentes en
    euros, doivent rendre le MÊME drawdown en R."""
    petit = [_trade(-3.0, entry=1.1000, sl=1.0900) for _ in range(4)]
    gros = [_trade(-30.0, entry=3400.0, sl=3300.0) for _ in range(4)]
    assert pe._compute_metrics(petit)["dd_R"] == pytest.approx(
        pe._compute_metrics(gros)["dd_R"], abs=0.05)


def test_un_stop_PLACEBO_est_ecarte_du_R():
    """⛔ Un stop à moins de 0,1 % du prix rend des R de plusieurs centaines —
    155 des 181 stops du réel étaient des placebos à 4 centimes. Les compter
    ferait exploser n'importe quel seuil."""
    placebo = _trade(-1.0, entry=4200.0, sl=4199.96, exit_=4100.0)
    m = pe._compute_metrics([placebo])
    assert m["n_R"] == 0
    assert m["dd_R"] == 0.0


def test_un_trade_SANS_niveaux_ne_casse_rien():
    """⚠️ Les trades des comptes clients (`ea_closed_trades`) n'ont pas de
    niveaux : ils doivent être ignorés pour le R, pas faire lever."""
    m = pe._compute_metrics([{"pnl": -5.0, "closed_at": "2026-09-08T10:00:00+00:00",
                              "close_reason": "SL"}])
    assert m["n_R"] == 0
    assert m["n"] == 1                # il compte toujours pour les euros


# ── La décision ──────────────────────────────────────────────────────

def _armer(monkeypatch, trades, etat=None):
    from backend.services import pair_admission_controller as pac
    monkeypatch.setattr(pac, "get_current_state",
                        lambda *a, **k: etat or pac.STATE_AUTO_EXEC)
    monkeypatch.setattr(pe, "_query_trades_pnl", lambda *a, **k: trades)


def test_QUATRE_stops_sur_l_or_ne_retrogradent_PLUS(monkeypatch):
    """⛔ Le cas réel du 08/09 : n=7, 4 SL consécutifs, dd 13,96 % en euros.
    Une série ordinaire ne doit pas couper un instrument."""
    _armer(monkeypatch, [_trade(-18.61) for _ in range(4)])
    assert pe.check_demotion("XAU/USD", "buy", "admin_live") is None


def test_un_VRAI_mauvais_parcours_retrograde_toujours(monkeypatch):
    """⚠️ Le contre-test. Desserrer ne doit pas désarmer : six stops pleins
    d'affilée dépassent le seuil et coupent."""
    _armer(monkeypatch, [_trade(-18.61) for _ in range(6)])
    d = pe.check_demotion("XAU/USD", "buy", "admin_live")
    assert d is not None
    assert "R_7d" in d["trigger"]
    assert d["to_state"] == "TELEGRAM"


def test_le_seuil_est_le_MEME_pour_le_forex(monkeypatch):
    """🔑 Ce que l'ancienne règle rendait impossible : le forex et l'or sont
    désormais jugés à la même aune."""
    _armer(monkeypatch, [_trade(-3.93, entry=1.1000, sl=1.0900) for _ in range(6)])
    assert pe.check_demotion("EUR/USD", "buy", "admin_live") is not None
    _armer(monkeypatch, [_trade(-3.93, entry=1.1000, sl=1.0900) for _ in range(4)])
    assert pe.check_demotion("EUR/USD", "buy", "admin_live") is None


def test_SANS_niveaux_on_retombe_sur_les_euros_ET_on_le_DIT(monkeypatch):
    """⛔ Un repli silencieux se lit comme une décision normale. Le motif doit
    porter la mention, sinon on ne saura jamais lequel des deux a tranché."""
    # ⚠️ La perte est DÉRIVÉE du seuil et du capital, jamais écrite en dur :
    # `TRADING_CAPITAL` vaut 650 en production et 10 000 en local. Ma première
    # version tombait pile SUR le seuil et le test échouait sur du code juste —
    # la leçon de la journée, resservie.
    from config.settings import TRADING_CAPITAL
    capital = float(TRADING_CAPITAL or 3000.0)
    perte = capital * (pe.DEMOTION_LIVE_TRAD_MAX_DD_7D / 100.0) * 2 / 5
    sans = [{"pnl": -perte, "closed_at": "2026-09-08T10:00:00+00:00",
             "close_reason": "SL"} for _ in range(5)]
    _armer(monkeypatch, sans)
    d = pe.check_demotion("XAU/USD", "buy", "admin_live")
    assert d is not None
    assert "repli euros" in d["trigger"]
    assert "n_R=0" in d["trigger"]


def test_un_etat_non_AUTO_EXEC_n_est_jamais_juge(monkeypatch):
    from backend.services import pair_admission_controller as pac
    _armer(monkeypatch, [_trade(-18.61) for _ in range(9)], etat=pac.STATE_TELEGRAM)
    assert pe.check_demotion("XAU/USD", "buy", "admin_live") is None


def test_le_seuil_est_REGLABLE_sans_redeploiement():
    """⚠️ Une décision qui desserre doit pouvoir se resserrer vite."""
    import inspect
    src = inspect.getsource(pe)
    assert 'os.getenv("DEMOTION_MAX_DD_R"' in src
    assert 'os.getenv("DEMOTION_MIN_TRADES_R"' in src
