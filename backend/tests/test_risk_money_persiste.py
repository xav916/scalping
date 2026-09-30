"""`risk_money` doit survivre au trade (2026-08-25).

Sans lui, vérifier qu'une position risque bien ce qu'on voulait exige de
reconstruire le chiffre par arithmétique inverse — ce qui a été nécessaire le
25/08 et n'est pas tenable en routine. C'est aussi ce qui manquait pour
détecter les positions placebo du démo, où 455 trades sur 610 risquaient un
millième du voulu sans qu'aucun contrôle ne le voie.
"""
from __future__ import annotations

import sqlite3


def test_la_colonne_existe(tmp_path, monkeypatch):
    from backend.services import mt5_pushes_service as svc
    db = tmp_path / "t.db"
    monkeypatch.setattr(svc, "_db_path", lambda: str(db))
    svc._ensure_schema()
    cols = {r[1] for r in sqlite3.connect(db).execute(
        "PRAGMA table_info(mt5_pushes)")}
    assert "risk_money" in cols


def test_une_base_ANCIENNE_recoit_la_colonne_sans_perdre_ses_lignes(tmp_path,
                                                                    monkeypatch):
    """⛔ La migration doit être idempotente ET non destructive : `mt5_pushes`
    porte l'historique des ordres réels."""
    from backend.services import mt5_pushes_service as svc
    db = tmp_path / "t.db"
    with sqlite3.connect(db) as c:
        c.execute("""CREATE TABLE mt5_pushes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, destination_id TEXT NOT NULL,
            date TEXT NOT NULL, pair TEXT NOT NULL, direction TEXT NOT NULL,
            entry_price_5dp TEXT NOT NULL, pushed_at TEXT NOT NULL,
            ok INTEGER NOT NULL, bridge_response TEXT,
            UNIQUE(destination_id, date, pair, direction, entry_price_5dp))""")
        c.execute("""INSERT INTO mt5_pushes (destination_id, date, pair,
            direction, entry_price_5dp, pushed_at, ok)
            VALUES ('admin_kraken','2026-08-23','PAXG/USD','buy','4607.60986',
                    '2026-08-23T18:45:31+00:00', 1)""")
    monkeypatch.setattr(svc, "_db_path", lambda: str(db))
    svc._ensure_schema()
    svc._ensure_schema()          # deux fois : idempotence
    with sqlite3.connect(db) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(mt5_pushes)")}
        n = c.execute("SELECT COUNT(*) FROM mt5_pushes").fetchone()[0]
        val = c.execute("SELECT risk_money FROM mt5_pushes").fetchone()[0]
    assert "risk_money" in cols
    assert n == 1, "la migration a perdu des lignes"
    assert val is None, "une ligne ancienne doit rester NULL, pas devenir 0"


def test_une_valeur_ABSENTE_reste_NULL_et_ne_devient_pas_zero():
    """⛔ Zéro dirait « on a voulu risquer zéro ». NULL dit « on ne sait pas ».
    Les confondre rendrait tout contrôle de réciprocité ininterprétable."""
    from backend.services.mt5_bridge import _risk_money_pour_persistance
    assert _risk_money_pour_persistance({}) is None
    assert _risk_money_pour_persistance({"risk_money": None}) is None
    assert _risk_money_pour_persistance({"risk_money": 0.0}) == 0.0
    assert _risk_money_pour_persistance({"risk_money": "1.55"}) == 1.55
    assert _risk_money_pour_persistance({"risk_money": "illisible"}) is None
