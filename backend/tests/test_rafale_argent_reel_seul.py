"""La pause « rafale » ne se déclenche que sur de l'argent RÉEL (2026-09-04).

Second chemin démo → réel, trouvé en auditant la certification demandée. Le
premier était l'admission (`fcdf6c0`) ; celui-ci est le disjoncteur de rafale.

`_fetch_recent_sl` lisait `personal_trades WHERE close_reason='SL'` **sans
filtre de destination**, et son verdict pose :

    kill_switch.set_pair_rafale_pause(pair)     -> la paire, sur les 2 comptes
    kill_switch.set_global_rafale_pause(...)    -> TOUT, sur les 2 comptes

⇒ **3 stops sur la DÉMO en une heure mettaient la paire en pause sur le
compte RÉEL.** Cinq stops toutes paires confondues gelaient tout.

Mesuré sur 90 jours : la démo seule a atteint le seuil des 3 SL/h **8 fois**,
et celui des 5 SL/h **6 fois**. Le mécanisme n'est pas théorique — et il
devient plus probable à mesure qu'on ouvre des instruments sur la démo, ce qui
est précisément le but du banc d'essai.

🔑 Un banc d'essai qui peut geler le compte qu'il est censé préparer n'est pas
un banc d'essai.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture()
def base(tmp_path, monkeypatch):
    import backend.services.stop_loss_alerts as sla
    import backend.services.trade_log_service as t

    chemin = tmp_path / "trades.db"
    monkeypatch.setattr(t, "_DB_PATH", chemin, raising=False)
    monkeypatch.setattr(sla, "_db_path", lambda: str(chemin), raising=False)
    t._init_schema()
    return sla, chemin


def _sl(chemin, destination, pair="XAU/USD", n=1, minutes=5):
    """Des stops loss fermés il y a `minutes`."""
    c = sqlite3.connect(chemin)
    cols = [r[1] for r in c.execute("PRAGMA table_info(personal_trades)")]
    quand = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    for _ in range(n):
        vals = {"user": "admin", "pair": pair, "direction": "buy",
                "entry_price": 4400.0, "stop_loss": 4380.0, "take_profit": 4440.0,
                "size_lot": 0.01,
                "status": "CLOSED", "pnl": -7.5, "is_auto": 1,
                "close_reason": "SL", "signal_pattern": "breakout_up",
                "destination_id": destination,
                "created_at": quand, "closed_at": quand}
        u = {k: v for k, v in vals.items() if k in cols}
        c.execute(f"INSERT INTO personal_trades ({','.join(u)}) "
                  f"VALUES ({','.join('?' * len(u))})", tuple(u.values()))
    c.commit()
    c.close()


def _fenetre():
    maintenant = datetime.now(timezone.utc)
    return (maintenant - timedelta(hours=1)).isoformat(), maintenant.isoformat()


# ── Le cœur ───────────────────────────────────────────────────────────────

def test_les_stops_de_DEMO_ne_declenchent_plus_de_rafale(base):
    """⛔ LE test de la certification.

    S'il tombe, trois stops en démo peuvent de nouveau geler une paire du
    compte réel.
    """
    sla, chemin = base
    _sl(chemin, "admin_legacy", n=6)

    depuis, jusqu = _fenetre()
    assert sla._fetch_recent_sl(depuis, jusqu) == []


def test_les_stops_REELS_declenchent_toujours(base):
    """Le correctif ne doit pas désarmer le disjoncteur qu'il assainit."""
    sla, chemin = base
    _sl(chemin, "admin_live", n=4)

    depuis, jusqu = _fenetre()
    assert len(sla._fetch_recent_sl(depuis, jusqu)) == 4


def test_un_melange_ne_compte_que_le_reel(base):
    """Deux stops réels et quatre en démo : le seuil de trois n'est PAS atteint."""
    sla, chemin = base
    _sl(chemin, "admin_live", n=2)
    _sl(chemin, "admin_legacy", n=4)

    depuis, jusqu = _fenetre()
    assert len(sla._fetch_recent_sl(depuis, jusqu)) == 2


def test_une_destination_NULLE_compte_comme_reelle(base):
    """Lignes antérieures à la migration du 20/08 — un résidu, on les garde.

    Même règle que pour l'admission et le plafond journalier : quand on ne
    sait pas, on protège.
    """
    sla, chemin = base
    _sl(chemin, None, n=3)

    depuis, jusqu = _fenetre()
    assert len(sla._fetch_recent_sl(depuis, jusqu)) == 3


def test_kraken_compte_aussi_c_est_de_l_argent_reel(base):
    sla, chemin = base
    _sl(chemin, "admin_kraken", n=3)

    depuis, jusqu = _fenetre()
    assert len(sla._fetch_recent_sl(depuis, jusqu)) == 3
