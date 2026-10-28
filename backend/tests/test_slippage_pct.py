"""Le glissement en % du prix — l'unité qui ne dépend d'aucune convention.

Contexte (2026-10-28) : `slippage_pips` passe par `_pip_size`, qui n'a **aucun
cas crypto ni énergie** et retombe sur le facteur forex `0.0001`. `BTC/USD`
sortait donc à **1 113 350 pips** de médiane, et la sonde de couverture rendait
`OK` dessus — elle vérifiait la présence, jamais le sens.

Mesuré alors sur 544 trades réels : le coût d'exécution vaut **0,1298 %** du
prix sur `BTC/USD`, **0,0251 %** sur `XAU/USD`, **0,006 à 0,016 %** en forex.
C'est cette quantité, et pas des pips, dont les bancs ont besoin : leur coût en
`R` vaut `slippage_pct / risk_pct`.

⛔ Ces tests FONT TOURNER `_upsert_open_trade` sur des lignes d'audit, jusqu'à
l'écriture en base. Ils ne lisent pas le source : un test qui cherche une
chaîne dans un fichier passe encore quand la ligne est commentée.
"""
import sqlite3

import pytest

from backend.services import mt5_sync


@pytest.fixture
def db(tmp_path, monkeypatch):
    """`personal_trades` SANS `slippage_pct` : la migration doit l'ajouter.

    🔑 C'est volontaire — la table de test reproduit l'état d'avant, donc le
    test exerce aussi le `ALTER TABLE` idempotent.
    """
    f = tmp_path / "trades.db"
    conn = sqlite3.connect(f)
    conn.execute("""
        CREATE TABLE personal_trades (
            id INTEGER PRIMARY KEY,
            user TEXT, pair TEXT, direction TEXT,
            entry_price REAL, stop_loss REAL, take_profit REAL,
            size_lot REAL, signal_pattern TEXT, signal_confidence REAL,
            checklist_passed INTEGER, notes TEXT, status TEXT,
            created_at TEXT, mt5_ticket INTEGER UNIQUE, is_auto INTEGER,
            post_entry_sl INTEGER, post_entry_tp INTEGER, post_entry_size INTEGER,
            context_macro TEXT, signal_id INTEGER,
            fill_price REAL, slippage_pips REAL
        )
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr(mt5_sync, "_db_path", lambda: str(f))
    monkeypatch.setattr(
        mt5_sync.macro_context_service, "get_macro_snapshot", lambda: None
    )
    return str(f)


def _sync(db_path, **overrides):
    """Joue une ligne d'audit et rend `(slippage_pips, slippage_pct)`."""
    ticket = overrides.pop("ticket", 1)
    row = {
        "ticket": ticket,
        "pair": "EUR/USD",
        "direction": "buy",
        "lots": 0.01,
        "sl": 1.0950,
        "tp": 1.1050,
        "entry": overrides.get("fill_price"),
    }
    row.update(overrides)
    mt5_sync._upsert_open_trade(row, "trader@test.com")
    with sqlite3.connect(db_path) as c:
        return c.execute(
            "SELECT slippage_pips, slippage_pct FROM personal_trades"
            " WHERE mt5_ticket=?", (ticket,),
        ).fetchone()


# ─── la migration ───────────────────────────────────────────────────────────


def test_la_colonne_est_AJOUTEE_a_une_table_qui_ne_l_a_pas(db):
    """⛔ Sans migration idempotente, l'INSERT lèverait sur la prod existante."""
    avant = {r[1] for r in sqlite3.connect(db).execute(
        "PRAGMA table_info(personal_trades)")}
    assert "slippage_pct" not in avant

    _sync(db, entry_requested=1.1000, fill_price=1.0998, fill_source="result")

    apres = {r[1] for r in sqlite3.connect(db).execute(
        "PRAGMA table_info(personal_trades)")}
    assert "slippage_pct" in apres


def test_la_migration_est_REJOUABLE(db):
    """Deux passages de suite ne doivent pas lever."""
    _sync(db, ticket=1, entry_requested=1.1000, fill_price=1.0998,
          fill_source="result")
    _sync(db, ticket=2, entry_requested=1.1000, fill_price=1.0999,
          fill_source="result")

    n = sqlite3.connect(db).execute(
        "SELECT COUNT(*) FROM personal_trades").fetchone()[0]
    assert n == 2


# ─── la valeur, calculée à la main ──────────────────────────────────────────


def test_le_pourcentage_se_calcule_a_la_main_sur_du_forex(db):
    """Acheté 1,0998 pour 1,1000 demandé : 2 pips ET +0,018182 %."""
    pips, pct = _sync(db, direction="buy", entry_requested=1.1000,
                      fill_price=1.0998, fill_source="result")

    assert pips == pytest.approx(2.0)
    assert pct == pytest.approx(100.0 * (1.1000 - 1.0998) / 1.1000, abs=1e-6)
    assert pct == pytest.approx(0.018182, abs=1e-6)


def test_le_SIGNE_suit_celui_des_pips(db):
    """Défavorable = négatif, des deux côtés, comme `slippage_pips`."""
    pips_a, pct_a = _sync(db, ticket=1, direction="buy",
                          entry_requested=1.1000, fill_price=1.1003,
                          fill_source="result")
    pips_v, pct_v = _sync(db, ticket=2, direction="sell",
                          entry_requested=1.1000, fill_price=1.0997,
                          fill_source="result")

    assert pips_a < 0 and pct_a < 0
    assert pips_v < 0 and pct_v < 0


def test_une_VENTE_favorable_est_POSITIVE(db):
    pips, pct = _sync(db, direction="sell", entry_requested=1.1000,
                      fill_price=1.1002, fill_source="result")

    assert pips > 0 and pct > 0


# ─── 🔑 LE CŒUR : la crypto, que les pips rendaient absurde ─────────────────


def test_la_CRYPTO_rend_un_pourcentage_SENSE_la_ou_les_pips_sont_ABSURDES(db):
    """🔑 LE DÉFAUT QUI A MOTIVÉ CETTE COLONNE.

    `BTC/USD` acheté 111 USD au-dessus du prix demandé sur ~85 000 :
    - en pips, `_pip_size` retombe sur 0,0001 et rend **−1 110 000** ;
    - en pourcentage, **−0,1306 %** — exactement l'ordre de grandeur mesuré
      en production (0,1298 % de médiane sur 24 trades réels).
    """
    pips, pct = _sync(db, pair="BTC/USD", direction="buy",
                      entry_requested=85000.0, fill_price=85111.0,
                      fill_source="result")

    assert pips == pytest.approx(-1110000.0)          # absurde, et conservé
    assert pct == pytest.approx(-0.130588, abs=1e-5)  # sensé
    assert abs(pct) < 1.0                             # ⛔ la garde de sens


def test_le_pourcentage_est_COMPARABLE_entre_classes_la_ou_les_pips_non(db):
    """🔑 Même coût relatif sur deux instruments d'échelles opposées : le
    pourcentage le dit, les pips le cachent."""
    _, pct_fx = _sync(db, ticket=1, pair="EUR/USD", direction="buy",
                      entry_requested=1.1000, fill_price=1.09989,
                      fill_source="result")
    _, pct_btc = _sync(db, ticket=2, pair="BTC/USD", direction="buy",
                       entry_requested=85000.0, fill_price=84991.5,
                       fill_source="result")
    pips_fx, _ = _sync(db, ticket=3, pair="EUR/USD", direction="buy",
                       entry_requested=1.1000, fill_price=1.09989,
                       fill_source="result")
    pips_btc, _ = _sync(db, ticket=4, pair="BTC/USD", direction="buy",
                        entry_requested=85000.0, fill_price=84991.5,
                        fill_source="result")

    # ~0,01 % de coût des deux cotes
    assert pct_fx == pytest.approx(pct_btc, abs=1e-4)
    # alors que les pips diffèrent de cinq ordres de grandeur
    assert abs(pips_btc) > 1000 * abs(pips_fx)


def test_l_ENERGIE_aussi(db):
    """`WTI/USD` : médiane mesurée 0,2322 % en production."""
    _, pct = _sync(db, pair="WTI/USD", direction="buy",
                   entry_requested=70.0, fill_price=70.07,
                   fill_source="result")

    assert pct == pytest.approx(-0.1, abs=1e-6)


# ─── et les mêmes refus de mesurer que les pips ─────────────────────────────


def test_le_repli_sur_le_prix_demande_ne_produit_AUCUNE_mesure(db):
    """⛔ `fill_source == "requested"` : le glissement vaudrait zéro PAR
    CONSTRUCTION. Un faux zéro tirerait la moyenne vers l'absence de coût."""
    pips, pct = _sync(db, entry_requested=1.1000, fill_price=1.1000,
                      fill_source="requested")

    assert pips is None and pct is None


def test_sans_prix_DEMANDE_aucune_mesure(db):
    pips, pct = _sync(db, fill_price=1.0998, fill_source="result")

    assert pips is None and pct is None


def test_sans_FILL_aucune_mesure(db):
    pips, pct = _sync(db, entry_requested=1.1000, fill_price=None,
                      fill_source="result")

    assert pips is None and pct is None
