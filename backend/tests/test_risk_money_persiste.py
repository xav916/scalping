"""`risk_money` doit survivre au trade (2026-09-30).

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


def test_une_base_ANCIENNE_recoit_la_colonne_sans_perdre_ses_lignes(
        tmp_path, monkeypatch):
    """⛔ La migration doit être idempotente ET non destructive : `mt5_pushes`
    porte l'historique des ordres réellement passés."""
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


def test_un_appelant_SANS_risk_money_n_EFFACE_pas_la_valeur_ecrite(
        tmp_path, monkeypatch):
    """⛔ Le `COALESCE` existe pour ça.

    Quatre appelants de `update_push_result` n'ont pas le sizing en portée.
    Sans `COALESCE`, le premier d'entre eux à repasser sur la ligne y
    écraserait le risque voulu par un NULL — et le contrôle de réciprocité
    n'aurait plus rien à comparer, sans qu'aucune erreur ne le dise.
    """
    from backend.services import mt5_pushes_service as svc
    db = tmp_path / "t.db"
    monkeypatch.setattr(svc, "_db_path", lambda: str(db))
    svc._ensure_schema()
    cle = ("admin_live", "2026-09-30", "XAU/USD", "buy", "4607.60986")
    svc.try_register_push(*cle)

    svc.update_push_result(*cle, ok=True, response={"ticket": 42},
                           risk_money=1.55)
    svc.update_push_result(*cle, ok=True, response={"ticket": 42})

    with sqlite3.connect(db) as c:
        val = c.execute("SELECT risk_money FROM mt5_pushes").fetchone()[0]
    assert val == 1.55, "un appelant sans sizing a effacé le risque voulu"


def test_une_valeur_ABSENTE_reste_NULL_et_ne_devient_pas_zero():
    """⛔ Zéro dirait « on a voulu risquer zéro ». NULL dit « on ne sait pas ».
    Les confondre rendrait tout contrôle de réciprocité ininterprétable."""
    from backend.services.mt5_bridge import _risk_money_pour_persistance
    assert _risk_money_pour_persistance({}) is None
    assert _risk_money_pour_persistance({"risk_money": None}) is None
    assert _risk_money_pour_persistance({"risk_money": 0.0}) == 0.0
    assert _risk_money_pour_persistance({"risk_money": "1.55"}) == 1.55
    assert _risk_money_pour_persistance({"risk_money": "illisible"}) is None


def test_TOUS_les_appelants_qui_ONT_le_sizing_le_persistent():
    """⛔ Le garde-fou contre l'appelant oublié.

    Quatre appels à `update_push_result` vivent dans `mt5_bridge`, tous dans
    des fonctions où `sz` est en portée. En oublier un laisserait la colonne à
    NULL sur ce chemin-là seulement — un trou silencieux, du genre qui ne se
    voit qu'en cherchant pourquoi les chiffres ne se recoupent pas.
    """
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "services" / "mt5_bridge.py"
    arbre = ast.parse(src.read_text(encoding="utf-8"))

    appels = [n for n in ast.walk(arbre)
              if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute)
              and n.func.attr == "update_push_result"]
    assert appels, "aucun appel trouvé — le test ne mesure plus rien"

    sans = [a.lineno for a in appels
            if not any(k.arg == "risk_money" for k in a.keywords)]
    assert not sans, f"appels sans risk_money aux lignes {sans}"
