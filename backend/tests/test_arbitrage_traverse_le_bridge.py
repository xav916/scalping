"""L'arbitrage doit traverser jusqu'au bridge (2026-09-04, 16:44).

Le compte réel a été débloqué à 16:35 : Xavier avait répondu « continue », le
backend laissait passer. À 16:44, l'ordre `XAG/USD sell` est quand même mort —
non pas dans le backend, mais **au bridge** :

    bridge_perte_journaliere
    "Daily drawdown reached: loss=31.45 >= limit=22.52 (3.0% of 750.50)"

⛔ **Deux plafonds journaliers vivent sur deux machines et ne se parlent pas.**
Le backend juge sur le PnL *réalisé* des clôtures ; le bridge sur l'*equity*
comparée au solde d'ouverture. Lever l'un laissait l'autre annuler la décision
de Xavier en silence — un arbitrage décoratif sur la couche qui exécute
réellement. C'est la même maladie que « une porte posée d'un seul côté n'est
pas une porte ».

Ces tests tiennent les deux bords :

  - le drapeau part **quand** une autorisation couvre encore la perte ;
  - il ne part **jamais** autrement — pas d'arbitrage, `GELER`, autorisation
    périmée, compte démo. Son absence est ce que le bridge lit comme « applique
    ton garde-fou », donc le défaut sûr.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from types import SimpleNamespace

import pytest


@pytest.fixture()
def base(tmp_path, monkeypatch):
    import backend.services.trade_log_service as t

    chemin = tmp_path / "trades.db"
    monkeypatch.setattr(t, "_DB_PATH", chemin, raising=False)
    t._init_schema()
    c = sqlite3.connect(chemin)
    c.execute("""CREATE TABLE IF NOT EXISTS mt5_pushes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, destination_id TEXT,
        bridge_response TEXT)""")
    c.commit()
    c.close()
    monkeypatch.setattr(t, "TRADING_CAPITAL", 650.0, raising=False)
    monkeypatch.setattr(t, "DAILY_LOSS_LIMIT_PCT", 3.0, raising=False)

    from backend.services import plafond_arbitrage as a
    a._init_schema()
    return t, a, chemin


def _perte(chemin, pnl, ticket, destination="admin_live"):
    c = sqlite3.connect(chemin)
    cols = [r[1] for r in c.execute("PRAGMA table_info(personal_trades)")]
    vals = {"user": "admin", "pair": "XAU/USD", "direction": "buy",
            "entry_price": 4450.0, "stop_loss": 4420.0, "take_profit": 4504.0,
            "size_lot": 0.01, "status": "CLOSED", "pnl": pnl,
            "mt5_ticket": ticket, "destination_id": destination,
            "created_at": date.today().isoformat() + "T10:00:00"}
    utiles = {k: v for k, v in vals.items() if k in cols}
    c.execute(f"INSERT INTO personal_trades ({','.join(utiles)}) "
              f"VALUES ({','.join('?' * len(utiles))})", tuple(utiles.values()))
    c.commit()
    c.close()


def _setup():
    return SimpleNamespace(
        pair="XAG/USD", direction="sell", entry_price=30.0,
        stop_loss=30.6, take_profit_1=29.0, take_profit_2=None,
        confidence_score=52.2)


def _dest(destination_id="admin_live", reel=True):
    return SimpleNamespace(destination_id=destination_id, reel=reel,
                           symbol_map=None)


def _payload(dest):
    from backend.services import mt5_bridge
    return mt5_bridge._build_order_payload(
        _setup(), {"risk_money": 7.0, "risk_pct": 1.0}, dest=dest)


# ── Le drapeau part quand il doit ─────────────────────────────────────────

def test_le_drapeau_accompagne_l_ordre_quand_Xavier_a_dit_continue(base):
    """🔑 Sans ça, sa réponse s'arrête à mi-chemin — le cas du 04/09 à 16:44."""
    t, a, chemin = base
    _perte(chemin, -32.27, 1001)
    t.silent_mode_active_for_destination("admin_live")
    a.repondre(a.CONTINUER)

    payload = _payload(_dest())

    assert "drawdown_arbitre" in payload, (
        "le bridge doit apprendre que Xavier a autorisé")
    assert payload["drawdown_arbitre"]["accorde_a"] == -32.27
    assert payload["drawdown_arbitre"]["couvre_jusqua"] == -51.77


# ── Il ne part jamais autrement ───────────────────────────────────────────

def test_aucun_drapeau_sans_depassement(base):
    t, a, chemin = base
    _perte(chemin, -5.00, 1001)
    assert "drawdown_arbitre" not in _payload(_dest())


def test_aucun_drapeau_tant_que_Xavier_n_a_pas_repondu(base):
    """L'intervalle d'arbitrage ne doit rien lever nulle part."""
    t, a, chemin = base
    _perte(chemin, -32.27, 1001)
    t.silent_mode_active_for_destination("admin_live")

    assert "drawdown_arbitre" not in _payload(_dest())


def test_aucun_drapeau_apres_un_GELER(base):
    t, a, chemin = base
    _perte(chemin, -32.27, 1001)
    t.silent_mode_active_for_destination("admin_live")
    a.repondre(a.GELER)

    assert "drawdown_arbitre" not in _payload(_dest())


def test_un_GELER_annule_un_CONTINUER_plus_ancien(base):
    """⛔ Xavier a tranché dans l'autre sens depuis : la vieille autorisation
    ne doit pas survivre au gel qui l'a remplacée."""
    t, a, chemin = base
    _perte(chemin, -32.27, 1001)
    t.silent_mode_active_for_destination("admin_live")
    a.repondre(a.CONTINUER)
    assert "drawdown_arbitre" in _payload(_dest())

    a.ouvrir_demande("admin_live", -35.00, -19.50)
    a.repondre(a.GELER)
    assert "drawdown_arbitre" not in _payload(_dest())


def test_aucun_drapeau_quand_l_autorisation_ne_couvre_PLUS(base):
    """Au-delà de la tranche autorisée, le bridge doit reprendre la main."""
    t, a, chemin = base
    _perte(chemin, -32.27, 1001)
    t.silent_mode_active_for_destination("admin_live")
    a.repondre(a.CONTINUER)

    _perte(chemin, -25.00, 1002)          # −57,27 € > couverture −51,77 €
    assert "drawdown_arbitre" not in _payload(_dest())


def test_aucun_drapeau_sur_un_compte_DEMO(base):
    """La démo n'a jamais eu ce plafond — lui joindre un drapeau serait un
    mensonge, et brouillerait la lecture des logs du bridge."""
    t, a, chemin = base
    _perte(chemin, -500.00, 1001, destination="admin_legacy")
    assert "drawdown_arbitre" not in _payload(_dest("admin_legacy", reel=False))


def test_une_lecture_impossible_ne_joint_AUCUN_drapeau(base, monkeypatch):
    """⛔ Une panne ne peut pas valoir autorisation : sans drapeau, le bridge
    applique son garde-fou."""
    t, a, chemin = base
    _perte(chemin, -32.27, 1001)
    t.silent_mode_active_for_destination("admin_live")
    a.repondre(a.CONTINUER)

    def _casse(*args, **kw):
        raise RuntimeError("base verrouillée")

    monkeypatch.setattr(t, "_cumul_et_limite", _casse)
    assert "drawdown_arbitre" not in _payload(_dest())


# ── Le chiffre lu est bien LE MÊME des deux côtés ─────────────────────────

def test_la_decision_et_l_ordre_lisent_le_meme_cumul(base):
    """Deux calculs du même cumul qui divergeraient rouvriraient la faille
    que tout ce dispositif prétend fermer."""
    t, a, chemin = base
    _perte(chemin, -32.27, 1001)

    cumul, limite = t._cumul_et_limite("admin_live")
    assert cumul == -32.27
    assert round(limite, 2) == -19.50
    assert t.silent_mode_active_for_destination("admin_live") is True
