"""La route `POST /api/signals/external` et l'attribution jusqu'au push.

Dernier maillon de la conception du 26/08. Jusqu'au 28/08 au soir,
`external_signals` existait et etait teste, mais **rien ne l'appelait** : aucun
bot ne pouvait poster. Et `source=` n'etait passe a `try_register_push` par
aucun des quatre appels de production — la colonne restait `NULL`, donc tout
trade s'enregistrait `interne`, y compris ceux d'un fournisseur.

> **Une plomberie sans robinet ne coule pas.** Les deux moities existaient,
> aucune ne touchait l'autre.

Ce que ces tests verrouillent :

1. le jeton voyage en **en-tete**, pas en query — une URL finit dans les
   journaux d'acces, d'ou personne ne la retire ensuite ;
2. le **code HTTP suit la CAUSE**, jamais le texte du motif : reformuler un
   message ne doit pas casser le contrat ;
3. un rejeu rend **200**, pas une erreur — l'idempotence qui fonctionne n'est
   pas un echec, et le marquer comme tel apprendrait a reessayer ;
4. le motif accompagne **toujours** la reponse, refus compris ;
5. `source_du_setup` rend `interne` et **jamais `None`** : la colonne sert a
   filtrer, et un `NULL` echappe a tout filtre — y compris a celui qui
   chercherait nos propres trades ;
6. les **quatre** appelants de `try_register_push` passent la source.
"""
from __future__ import annotations

import ast
import pathlib
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_RACINE = pathlib.Path(__file__).resolve().parents[2]

CHARGE = {
    "source": "bot_x",
    "external_id": "sig-1",
    "pair": "EUR/USD",
    "direction": "buy",
    "entry_price": 1.1000,
    "stop_loss": 1.0950,
    "take_profit": 1.1100,
    "horizon": "4h",
    "pattern": "breakout_up",
    "confidence": 72.0,
}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    from backend.services import external_signals, trade_log_service
    monkeypatch.setattr(trade_log_service, "_DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(external_signals, "_SCHEMA_ENSURED", False)
    monkeypatch.setattr(external_signals, "_fournisseurs",
                        lambda: {"bot_x": "jeton_x"})
    from backend.app import app
    return TestClient(app)


def _poster(client, charge=None, jeton="jeton_x"):
    return client.post("/api/signals/external",
                       json=charge if charge is not None else CHARGE,
                       headers={"X-Signal-Token": jeton})


# ── L'authentification ─────────────────────────────────────────────────────

def test_un_jeton_absent_rend_401_ET_son_motif(client):
    r = client.post("/api/signals/external", json=CHARGE)
    assert r.status_code == 401
    assert r.json()["accepte"] is False
    assert "jeton" in r.json()["motif"]


def test_le_jeton_d_un_autre_fournisseur_ne_vaut_pas(client):
    r = _poster(client, jeton="jeton_y")
    assert r.status_code == 401
    assert "bot_x" in r.json()["motif"]


def test_une_source_inconnue_rend_401(client):
    r = _poster(client, dict(CHARGE, source="bot_inconnu"))
    assert r.status_code == 401
    assert "inconnue" in r.json()["motif"]


def test_le_jeton_en_QUERY_ne_marche_pas(client):
    """⛔ Un secret dans l'URL se retrouve dans les journaux d'acces, les
    referents et l'historique du client — trois endroits d'ou personne ne le
    retire. La route ne lit QUE l'en-tete."""
    r = client.post("/api/signals/external?token=jeton_x", json=CHARGE)
    assert r.status_code == 401


# ── La forme ───────────────────────────────────────────────────────────────

def test_un_champ_manquant_rend_400_et_le_NOMME(client):
    charge = dict(CHARGE)
    del charge["stop_loss"]
    r = _poster(client, charge)
    assert r.status_code == 400
    assert "stop_loss" in r.json()["motif"]


def test_un_sens_inconnu_rend_400(client):
    r = _poster(client, dict(CHARGE, direction="peut-etre"))
    assert r.status_code == 400
    assert "buy" in r.json()["motif"]


def test_le_code_suit_la_CAUSE_pas_le_texte(client):
    """⛔ Si la route relisait la phrase francaise pour deviner le code,
    reformuler un message casserait le contrat HTTP en silence."""
    r = _poster(client, dict(CHARGE, direction="peut-etre"))
    assert r.json()["cause"] == "forme" and r.status_code == 400
    r = _poster(client, jeton="faux")
    assert r.json()["cause"] == "auth" and r.status_code == 401


# ── Le chemin nominal, et l'idempotence ───────────────────────────────────

def test_un_signal_valide_est_dispatche(client):
    envoyes = []

    async def _faux_send(setup):
        envoyes.append(setup)

    with patch("backend.services.mt5_bridge.send_setup", _faux_send):
        r = _poster(client)
    assert r.status_code == 200 and r.json()["accepte"] is True
    assert len(envoyes) == 1
    assert envoyes[0].source == "bot_x"
    assert envoyes[0].direction.value == "buy"


def test_le_MEME_external_id_ne_dispatche_qu_UNE_fois(client):
    envoyes = []

    async def _faux_send(setup):
        envoyes.append(setup)

    with patch("backend.services.mt5_bridge.send_setup", _faux_send):
        premier = _poster(client)
        second = _poster(client)

    assert premier.json()["accepte"] is True
    assert second.json()["accepte"] is False
    assert len(envoyes) == 1, "un rejeu a produit un second ordre"


def test_un_REJEU_rend_200_pas_une_erreur(client):
    """⛔ L'idempotence qui fonctionne n'est pas un echec. La marquer comme
    telle apprendrait au fournisseur a reessayer."""
    async def _faux_send(setup):
        return None

    with patch("backend.services.mt5_bridge.send_setup", _faux_send):
        _poster(client)
        second = _poster(client)
    assert second.status_code == 200
    assert second.json()["cause"] == "doublon"


def test_un_corps_VIDE_ne_fait_pas_tomber_la_route(client):
    r = client.post("/api/signals/external", json={},
                    headers={"X-Signal-Token": "jeton_x"})
    assert r.status_code in (400, 401)
    assert r.json()["motif"]


# ── L'attribution : `source` jusqu'a la poussee ───────────────────────────

def test_source_du_setup_rend_interne_JAMAIS_None():
    """⛔ La colonne sert a FILTRER (`source IN (...)` du banc). Un `NULL`
    echappe a tout filtre, y compris a celui qui chercherait les notres."""
    from backend.services.mt5_pushes_service import source_du_setup
    for setup in (SimpleNamespace(pair="EUR/USD"),
                  SimpleNamespace(source=None),
                  SimpleNamespace(source=""),
                  SimpleNamespace(source="   ")):
        assert source_du_setup(setup) == "interne"
    assert source_du_setup(SimpleNamespace(source="  bot_x ")) == "bot_x"


def test_la_source_arrive_bien_dans_mt5_pushes(monkeypatch, tmp_path):
    """De bout en bout : ce qui est ecrit dans la table, pas ce qu'on croit."""
    import sqlite3

    from backend.services import mt5_pushes_service as ps, trade_log_service
    monkeypatch.setattr(trade_log_service, "_DB_PATH", tmp_path / "t.db")

    assert ps.try_register_push("admin_legacy", "2026-08-28", "EUR/USD",
                                "buy", "1.10000", source="bot_x")
    assert ps.try_register_push("admin_legacy", "2026-08-28", "XAU/USD",
                                "sell", "4598.00000")

    with sqlite3.connect(trade_log_service._DB_PATH) as c:
        lignes = dict(c.execute(
            "SELECT pair, source FROM mt5_pushes").fetchall())
    assert lignes["EUR/USD"] == "bot_x"
    assert lignes["XAU/USD"] is None, (
        "un appelant qui n'annonce rien laisse NULL — c'est `source_du_setup` "
        "qui pose `interne`, pas la table")


def test_les_QUATRE_appelants_passent_la_source():
    """⛔ Test de niveau source, a dessein : c'est l'OUBLI d'un appelant qu'on
    veut attraper, et un appelant oublie ne se voit dans aucun test qui ne
    l'exerce pas. Trois d'entre eux vivent sur des chemins (miroir demo->reel,
    Binance) qu'aucun test d'integration ne traverse.

    Le defaut ferme ici a dure du 26 au 28/08 : la colonne existait, les
    quatre appelants l'ignoraient, et tout trade s'enregistrait `interne`.
    """
    fichiers = [
        _RACINE / "backend" / "services" / "mt5_bridge.py",
        _RACINE / "backend" / "services" / "bridge_push_ledger.py",
        _RACINE / "backend" / "services" / "binance_bridge_client.py",
    ]
    total, sans_source = 0, []
    for f in fichiers:
        arbre = ast.parse(f.read_text(encoding="utf-8"))
        for n in ast.walk(arbre):
            if not isinstance(n, ast.Call):
                continue
            nom = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
            if nom != "try_register_push":
                continue
            total += 1
            if not any(k.arg == "source" for k in n.keywords):
                sans_source.append(f"{f.name}:{n.lineno}")
    assert total >= 4, f"seulement {total} appel(s) trouve(s) — extraction cassee"
    assert not sans_source, f"appels sans source : {sans_source}"
