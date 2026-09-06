"""Les mots `gele` / `continue` sur le fil sales tranchent l'arbitrage (2026-09-04).

⛔ Ces commandes sont les PREMIÈRES du webhook à écrire quelque chose. Les
précédentes (`recap`, `risque`) ne font que lire — la mémoire du 25/08 le note
explicitement : « Répondre n'écrit RIEN ». Celles-ci débloquent un compte qui
trade de l'argent réel. Elles ne sont acceptables que parce que la route
valide le secret Telegram ET filtre sur le `chat_id` de Xavier ; ce sont ces
deux verrous que `test_un_autre_chat_ne_peut_PAS_debloquer` garde.

⚠️ Le second risque est le branchement, pas la logique : `plafond_arbitrage`
peut être parfait et n'être jamais appelé. C'est le trou qu'avait le détecteur
de positions nues — un mécanisme qu'on croyait armé et qui ne l'était pas.
D'où des tests qui passent par la vraie route HTTP, pas par la fonction.
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

CHAT = "8745809091"


@pytest.fixture
def envois(monkeypatch):
    vus: list[str] = []

    async def _faux_send(texte, *a, **kw):
        vus.append(texte)
        return True

    import backend.services.telegram_service as ts
    monkeypatch.setattr(ts, "send_sales_text", _faux_send)
    return vus


@pytest.fixture
def arbitrage(tmp_path, monkeypatch):
    """Une demande d'arbitrage réellement ouverte, sur une base isolée."""
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

    from backend.services import plafond_arbitrage as a
    a._init_schema()
    a.ouvrir_demande("admin_live", -32.27, -21.54)
    return a


@pytest.fixture
def client(monkeypatch, envois):
    import config.settings as _s
    from backend.app import app

    monkeypatch.setattr(_s, "SALES_TELEGRAM_CHAT_ID", CHAT, raising=False)
    monkeypatch.setattr(_s, "TELEGRAM_SALES_WEBHOOK_SECRET", "", raising=False)
    return TestClient(app)


def _poster(client, texte, chat=CHAT):
    return client.post(
        "/api/telegram/sales-webhook",
        json={"message": {"chat": {"id": chat}, "text": texte}},
    )


# ── Le branchement ────────────────────────────────────────────────────────

def test_le_mot_continue_debloque_VRAIMENT(client, envois, arbitrage):
    r = _poster(client, "continue")

    assert r.status_code == 200, r.text
    assert r.json()["command"] == "arbitrage"
    assert r.json()["decision"] == "CONTINUER"
    assert r.json()["applique"] == 1
    assert arbitrage.demandes_en_attente() == [], "la demande doit être tranchée"
    assert len(envois) == 1, "Xavier doit recevoir un acquittement"


def test_le_mot_gele_maintient_le_blocage(client, envois, arbitrage):
    r = _poster(client, "gele")

    assert r.json()["decision"] == "GELER"
    assert arbitrage.demandes_en_attente() == []
    etat = arbitrage.etat_courant("admin_live", 1)
    assert etat["etat"] == "GELER"


@pytest.mark.parametrize("mot", ["gele", "gèle", "geler", "/gele", "GELE",
                                 "  Gele  ", "freeze"])
def test_les_variantes_de_gele_sont_acceptees(client, envois, arbitrage, mot):
    assert _poster(client, mot).json()["decision"] == "GELER", f"{mot!r} raté"


@pytest.mark.parametrize("mot", ["continue", "continuer", "/continue", "GO",
                                 "  Continue  "])
def test_les_variantes_de_continue_sont_acceptees(client, envois, arbitrage,
                                                  mot):
    assert _poster(client, mot).json()["decision"] == "CONTINUER", f"{mot!r} raté"


# ── Les verrous ───────────────────────────────────────────────────────────

def test_un_autre_chat_ne_peut_PAS_debloquer(client, envois, arbitrage):
    """🔑 Le seul rempart entre un message Telegram et un compte réel."""
    r = _poster(client, "continue", chat="999999")

    assert r.json().get("skipped") == "chat_id_mismatch"
    assert arbitrage.demandes_en_attente(), "la demande doit rester ouverte"
    assert envois == []


def test_un_continue_sans_demande_ne_repond_pas_OK_a_tort(client, envois,
                                                          tmp_path, monkeypatch):
    """⛔ Rien en attente : la commande doit le DIRE, pas pré-autoriser."""
    import backend.services.trade_log_service as t

    chemin = tmp_path / "vide.db"
    monkeypatch.setattr(t, "_DB_PATH", chemin, raising=False)
    t._init_schema()
    from backend.services import plafond_arbitrage as a
    a._init_schema()

    r = _poster(client, "continue")

    assert r.json()["applique"] == 0
    assert len(envois) == 1
    assert "Aucun arbitrage en attente" in envois[0], envois[0]


def test_un_mot_quelconque_ne_touche_a_rien(client, envois, arbitrage):
    r = _poster(client, "bonjour")

    assert r.json()["command"] is None
    assert arbitrage.demandes_en_attente(), "rien ne doit avoir été tranché"
    assert envois == []


def test_un_echec_interne_ne_pretend_PAS_avoir_debloque(client, envois,
                                                        arbitrage, monkeypatch):
    """⛔ Se taire ou acquitter à tort laisserait croire la décision passée
    alors que le compte reste bloqué — le pire des deux mondes."""
    def _casse(*a, **kw):
        raise RuntimeError("base verrouillée")

    monkeypatch.setattr("backend.services.plafond_arbitrage.repondre", _casse)
    r = _poster(client, "continue")

    assert r.json()["applique"] == 0
    assert len(envois) == 1
    assert "NON enregistree" in envois[0], envois[0]
    assert "reste bloque" in envois[0], envois[0]


# ── La décision porte sur UN compte (2026-09-06) ───────────────────────────
#
# ⛔ Le défaut vivait ICI, pas dans le service : la route appelait
# `repondre(decision)` sans destination. `plafond_arbitrage` savait filtrer par
# compte depuis le premier jour — personne ne le lui demandait. Un « continue »
# tapé pour l'or débloquait aussi Kraken, dont Xavier n'avait pas lu la ligne.
#
# ⚠️ C'est exactement le risque annoncé en tête de ce fichier : « le service
# peut être parfait et n'être jamais appelé ». Il l'était mal appelé.


@pytest.fixture
def deux_demandes(arbitrage):
    arbitrage.ouvrir_demande("admin_kraken", -48.0, -21.54)
    assert len(arbitrage.demandes_en_attente()) == 2
    return arbitrage


def test_un_CONTINUE_nu_ne_debloque_RIEN_quand_deux_comptes_attendent(
        client, envois, deux_demandes):
    """⛔ LE test du défaut. Avant : `applique == 2`."""
    r = _poster(client, "continue")

    assert r.status_code == 200, r.text
    assert r.json()["applique"] == 0
    assert r.json().get("refus") is True
    assert len(deux_demandes.demandes_en_attente()) == 2, \
        "les deux comptes restent BLOQUES"
    assert len(envois) == 1, "Xavier doit savoir POURQUOI rien n'a bouge"
    assert "admin_kraken" in envois[0] and "admin_live" in envois[0]


def test_un_CONTINUE_NOMME_ne_debloque_QUE_lui(client, envois, deux_demandes):
    r = _poster(client, "continue admin_kraken")

    assert r.json()["applique"] == 1
    restants = [d["destination_id"] for d in deux_demandes.demandes_en_attente()]
    assert restants == ["admin_live"], "l'autre compte reste bloque"


def test_le_nom_ABREGE_passe_aussi_par_la_route(client, envois, deux_demandes):
    """⚠️ Xavier tape « continue kraken ». Exiger le nom technique ferait
    repondre a cote, donc ne pas repondre du tout."""
    r = _poster(client, "continue kraken")

    assert r.json()["applique"] == 1
    assert [d["destination_id"] for d in deux_demandes.demandes_en_attente()] \
        == ["admin_live"]


def test_un_GELE_nu_bloque_les_DEUX(client, envois, deux_demandes):
    """⚠️ Le gel va dans le sens qui protège : pas de refus pour ambiguïté."""
    r = _poster(client, "gele")

    assert r.json()["applique"] == 2
    assert deux_demandes.demandes_en_attente() == []


def test_un_compte_qui_N_ATTEND_PAS_ne_debloque_rien(
        client, envois, deux_demandes):
    """⛔ Un nom qui ne matche pas ne doit PAS retomber sur « toutes »."""
    r = _poster(client, "continue admin_legacy")

    assert r.json()["applique"] == 0 and r.json().get("refus") is True
    assert len(deux_demandes.demandes_en_attente()) == 2


def test_un_seul_compte_en_attente_repond_toujours_au_mot_nu(
        client, envois, arbitrage):
    """Pas de regression : sans ambiguite, rien a nommer."""
    assert _poster(client, "continue").json()["applique"] == 1
