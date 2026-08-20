"""Le plafond journalier ne doit compter que l'ARGENT RÉEL (2026-08-20).

`personal_trades` ne porte pas de `destination_id` : démo et réel
s'additionnaient sous le même utilisateur. Une perte sur le démo — de l'argent
qui n'existe pas — coupait donc le trading réel.

Mesuré sur 30 jours avant correction :

```
ARGENT RÉEL                     DÉMO
05/08  −271,88 €  ← la seule    12/08  −101,98 €  ← déclenchait à tort
11/08   −13,64 €                18/08   −71,25 €
```

Le seuil se déclenchait sur du démo et noyait la seule journée réellement
mauvaise dans le même total.

Ce qui est verrouillé ici : le filtrage, le fait qu'une destination inconnue
compte comme réelle, et surtout qu'un ticket apparié à **plusieurs** pushes ne
gonfle pas la somme — ce qui déclencherait le garde-fou à tort.
"""
from __future__ import annotations

import sqlite3
from datetime import date

import pytest


@pytest.fixture()
def base(tmp_path, monkeypatch):
    """Base réelle, schéma réel — pas une reconstitution."""
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
    return t, chemin


def _ajouter(chemin, user, pnl, ticket, destination=None, doublons=1):
    """Un trade fermé, et le(s) push correspondant(s)."""
    c = sqlite3.connect(chemin)
    cols = [r[1] for r in c.execute("PRAGMA table_info(personal_trades)")]
    vals = {"user": user, "pair": "XAU/USD", "direction": "buy",
            "entry_price": 4450.0, "stop_loss": 4420.0, "take_profit": 4504.0,
            "size_lot": 0.01, "status": "CLOSED", "pnl": pnl,
            "mt5_ticket": ticket,
            "created_at": date.today().isoformat() + "T10:00:00"}
    utiles = {k: v for k, v in vals.items() if k in cols}
    c.execute(
        f"INSERT INTO personal_trades ({','.join(utiles)}) "
        f"VALUES ({','.join('?' * len(utiles))})", tuple(utiles.values()))
    if destination:
        for _ in range(doublons):
            c.execute(
                "INSERT INTO mt5_pushes (destination_id, bridge_response) "
                "VALUES (?, ?)",
                (destination, '{"ticket": %s, "ok": true}' % ticket))
    c.commit()
    c.close()


def _seuil(monkeypatch, t, capital=650.0, pct=3.0):
    """Seuil à −19,50 € : 3 % de 650 € de capital réel."""
    monkeypatch.setattr(t, "TRADING_CAPITAL", capital, raising=False)
    monkeypatch.setattr(t, "DAILY_LOSS_LIMIT_PCT", pct, raising=False)


# ── Le cas qui motivait tout ───────────────────────────────────────────────

def test_une_perte_DEMO_ne_coupe_PLUS_le_reel(base, monkeypatch):
    """−101,98 € de démo : au-dessus du seuil, mais fictif."""
    t, chemin = base
    _seuil(monkeypatch, t)
    _ajouter(chemin, "xavier", -101.98, 85012345, "admin_legacy")
    assert t.silent_mode_active_any_user() is False


def test_une_perte_REELLE_coupe(base, monkeypatch):
    """−271,88 € sur admin_live : la seule journée qui le méritait."""
    t, chemin = base
    _seuil(monkeypatch, t)
    _ajouter(chemin, "xavier", -271.88, 1353960866, "admin_live")
    assert t.silent_mode_active_any_user() is True


def test_kraken_compte_comme_du_reel(base, monkeypatch):
    t, chemin = base
    _seuil(monkeypatch, t)
    _ajouter(chemin, "auto", -25.0, 777001, "admin_kraken")
    assert t.silent_mode_active_any_user() is True


def test_le_demo_ne_masque_pas_une_perte_reelle(base, monkeypatch):
    """Un gros GAIN démo ne doit pas compenser une perte réelle."""
    t, chemin = base
    _seuil(monkeypatch, t)
    _ajouter(chemin, "xavier", +166.83, 85012345, "admin_legacy")
    _ajouter(chemin, "xavier", -271.88, 1353960866, "admin_live")
    assert t.silent_mode_active_any_user() is True


# ── Les cas limites qui feraient mal ───────────────────────────────────────

def test_destination_inconnue_compte_comme_reelle(base, monkeypatch):
    """Quand on ne sait pas, on protège."""
    t, chemin = base
    _seuil(monkeypatch, t)
    _ajouter(chemin, "xavier", -50.0, 999999, destination=None)
    assert t.silent_mode_active_any_user() is True


def test_ticket_absent_compte_comme_reel(base, monkeypatch):
    t, chemin = base
    _seuil(monkeypatch, t)
    _ajouter(chemin, "xavier", -50.0, None, destination=None)
    assert t.silent_mode_active_any_user() is True


def test_plusieurs_pushes_pour_un_ticket_ne_GONFLENT_PAS_la_somme(
        base, monkeypatch):
    """LE piège d'une jointure : −15 € apparié 3 fois ferait −45 € et
    déclencherait à tort un seuil à −19,50 €."""
    t, chemin = base
    _seuil(monkeypatch, t)
    _ajouter(chemin, "xavier", -15.0, 1355154354, "admin_live", doublons=3)
    assert t.silent_mode_active_any_user() is False


def test_sous_le_seuil_ca_passe(base, monkeypatch):
    t, chemin = base
    _seuil(monkeypatch, t)
    _ajouter(chemin, "xavier", -13.64, 1353960866, "admin_live")
    assert t.silent_mode_active_any_user() is False


def test_aucun_trade_ne_declenche_pas(base, monkeypatch):
    t, _ = base
    _seuil(monkeypatch, t)
    assert t.silent_mode_active_any_user() is False


def test_registre_illisible_compte_TOUT_plutot_que_rien(base, monkeypatch):
    """Se taire désarmerait le garde-fou en silence : on retombe sur le
    comportement large, pas sur l'absence de contrôle."""
    t, chemin = base
    _seuil(monkeypatch, t)
    monkeypatch.setattr(t, "_destinations_reelles", lambda: frozenset())
    _ajouter(chemin, "xavier", -101.98, 85012345, "admin_legacy")
    assert t.silent_mode_active_any_user() is True
