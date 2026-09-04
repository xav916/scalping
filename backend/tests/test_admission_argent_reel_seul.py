"""L'admission ne juge le RÉEL que sur de l'argent RÉEL (2026-09-04).

Découvert en cherchant à certifier que la démo n'impacte pas le réel — elle
l'impactait. `_fetch_real_trades_for_pair` lisait `personal_trades` et
`ea_closed_trades` **sans aucun filtre de destination**, et le verdict qui en
sort commande une ligne GLOBALE :

    if score["sample"] >= PROMOTE_MIN_SAMPLE and score["pnl_pct"] < -3.0:
        set_state(pair, STATE_PAUSED, ...)      # ← les DEUX comptes

⇒ une série perdante sur la démo pouvait mettre en pause une paire du compte
réel. Ce n'est pas une hypothèse : `XAU/USD buy` était à 7 clôtures de
franchir le seuil de décidabilité, sur un échantillon majoritairement démo, et
la démo en produit ~16 par mois.

⚠️ Ce qui protégeait jusque-là — un score indéterminé sous 30 trades réels —
protégeait **par accident**, pas par conception. C'est ce que ce module
remplace par une garantie.

Même famille que le correctif `911b6b0` du 29/08 sur `pair_pnl_regulator` :
juger chaque compte sur SES clôtures. Le régulateur avait été corrigé, la
machine d'admission ne l'avait jamais été.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest


@pytest.fixture()
def base(tmp_path, monkeypatch):
    """Schéma réel, données maîtrisées."""
    import backend.services.pair_admission_controller as pac
    import backend.services.trade_log_service as t

    chemin = tmp_path / "trades.db"
    monkeypatch.setattr(t, "_DB_PATH", chemin, raising=False)
    monkeypatch.setattr(pac, "_db_path", lambda: str(chemin), raising=False)
    # ⛔ `_SCHEMA_ENSURED` est un booleen GLOBAL, pas une memoire par chemin :
    # sans cette remise a zero, le schema n'est cree que sur la premiere base
    # du run et les tests suivants tombent sur « no such table ». Passe isole,
    # rouge en suite — la signature de ce piege.
    monkeypatch.setattr(pac, "_SCHEMA_ENSURED", False, raising=False)
    t._init_schema()
    pac._ensure_schema()
    from backend.services import ea_closed_trades_service as eact
    monkeypatch.setattr(eact, "_db_path", lambda: str(chemin), raising=False)
    # Même drapeau global, même piège, autre module.
    monkeypatch.setattr(eact, "_SCHEMA_ENSURED", False, raising=False)
    eact._ensure_schema()
    return pac, chemin


def _trade(chemin, pnl, destination, pair="XAU/USD", direction="buy",
           n=1, jours=1):
    c = sqlite3.connect(chemin)
    cols = [r[1] for r in c.execute("PRAGMA table_info(personal_trades)")]
    quand = (datetime.now(timezone.utc) - timedelta(days=jours)).isoformat()
    for _ in range(n):
        vals = {"user": "admin", "pair": pair, "direction": direction,
                "entry_price": 4400.0, "stop_loss": 4380.0, "take_profit": 4440.0,
                "size_lot": 0.01, "status": "CLOSED", "pnl": pnl, "is_auto": 1,
                "destination_id": destination, "closed_at": quand,
                "created_at": quand}
        u = {k: v for k, v in vals.items() if k in cols}
        c.execute(f"INSERT INTO personal_trades ({','.join(u)}) "
                  f"VALUES ({','.join('?' * len(u))})", tuple(u.values()))
    c.commit()
    c.close()


# ── Le cœur : la démo n'entre plus dans le verdict global ─────────────────

def test_les_trades_DEMO_n_entrent_pas_dans_le_score_global(base):
    """⛔ LE test de la certification demandée le 04/09.

    Si celui-ci tombe, la démo peut de nouveau mettre en pause une paire du
    compte réel, et la dissociation des deux comptes n'est plus vraie.
    """
    pac, chemin = base
    _trade(chemin, pnl=-50.0, destination="admin_legacy", n=40)

    pnls = pac._fetch_real_trades_for_pair("XAU/USD", 30, direction="buy")
    assert pnls == [], "aucun trade de démo ne doit peser sur le verdict du réel"


def test_les_trades_REELS_entrent_bien(base):
    pac, chemin = base
    _trade(chemin, pnl=-5.0, destination="admin_live", n=10)

    pnls = pac._fetch_real_trades_for_pair("XAU/USD", 30, direction="buy")
    assert len(pnls) == 10


def test_une_destination_NULLE_compte_comme_reelle(base):
    """Les lignes antérieures à la migration du 20/08 n'ont pas de destination.

    Mesuré le 04/09 : 11 lignes sur 669 dans les 90 derniers jours — un
    résidu. Les écarter ferait perdre de l'historique sans rien protéger ;
    les compter suit le précédent déjà posé sur le plafond journalier.
    """
    pac, chemin = base
    _trade(chemin, pnl=-5.0, destination=None, n=8)

    assert len(pac._fetch_real_trades_for_pair("XAU/USD", 30, direction="buy")) == 8


def test_un_melange_ne_retient_que_le_reel(base):
    pac, chemin = base
    _trade(chemin, pnl=-50.0, destination="admin_legacy", n=25)
    _trade(chemin, pnl=+3.0, destination="admin_live", n=5)

    pnls = pac._fetch_real_trades_for_pair("XAU/USD", 30, direction="buy")
    assert len(pnls) == 5
    assert all(p > 0 for p in pnls), "les pertes démo ont disparu du verdict"


# ── Bout en bout : une saignée démo ne rétrograde plus le réel ────────────

def test_une_serie_perdante_en_DEMO_ne_met_plus_le_reel_en_PAUSE(base):
    """Le scénario complet, celui qui empêchait la certification.

    40 trades démo à −50 € donnent un `pnl_pct` très en dessous des −3 % qui
    déclenchent la pause. Avant le correctif, `evaluate_pair` posait une ligne
    GLOBALE `PAUSED` — donc sur le compte réel aussi.
    """
    pac, chemin = base
    pac.set_state("XAU/USD", pac.STATE_AUTO_EXEC, "mise en place du test",
                  direction="buy")
    _trade(chemin, pnl=-50.0, destination="admin_legacy", n=40)

    d = pac.evaluate_pair("XAU/USD", direction="buy")

    assert d["action"] != "transition" or d.get("to_state") != pac.STATE_PAUSED, (
        "une saignée en démo ne doit pas toucher l'état du compte réel")
    assert pac.get_current_state("XAU/USD", "buy") == pac.STATE_AUTO_EXEC


def test_une_serie_perdante_REELLE_met_toujours_en_PAUSE(base):
    """Le correctif ne doit pas désarmer la porte qu'il assainit.

    C'est le pendant obligatoire du test précédent : si celui-ci tombe, on a
    supprimé la protection au lieu de la corriger.
    """
    pac, chemin = base
    pac.set_state("XAU/USD", pac.STATE_AUTO_EXEC, "mise en place du test",
                  direction="buy")
    _trade(chemin, pnl=-50.0, destination="admin_live", n=40)

    pac.evaluate_pair("XAU/USD", direction="buy")

    assert pac.get_current_state("XAU/USD", "buy") == pac.STATE_PAUSED


# ── Portée explicite ──────────────────────────────────────────────────────

def test_une_destination_nommee_restreint_a_elle_seule(base):
    pac, chemin = base
    _trade(chemin, pnl=+1.0, destination="admin_live", n=6)
    _trade(chemin, pnl=+2.0, destination="admin_kraken", n=6)

    pnls = pac._fetch_real_trades_for_pair("XAU/USD", 30, direction="buy",
                                           destination="admin_kraken")
    assert len(pnls) == 6
    assert all(p == 2.0 for p in pnls)
