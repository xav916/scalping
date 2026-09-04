"""Sonde de déploiement de l'horizon 1 jour (2026-09-04).

Les 12 paires de la whitelist démo servent désormais 4h **et** 1 jour. Le
chemin est vérifié mécaniquement (60 bougies récupérées par paire), mais au
rythme du 1 jour — ~0,4 setup par paire et par jour — le premier signal réel
n'était pas attendu avant ~5 heures.

Cette sonde répond à la seule question qui reste : **est-ce que ça produit ?**

🔑 **Elle a une fin.** Une sonde qui répète indéfiniment devient du bruit, et
on a vu aujourd'hui ce que devient une alerte qu'on cesse de lire : la
sauvegarde S3 signalait son échec depuis cinq nuits, les messages arrivaient,
personne ne les voyait plus. Celle-ci annonce le premier setup 1 jour, puis se
tait — définitivement.

⛔ Elle n'annonce RIEN au premier passage si le fait est déjà acquis : elle
pose son état et se tait. Sans ça, un redémarrage rejouerait l'annonce.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture()
def base(tmp_path, monkeypatch):
    import backend.services.trade_log_service as t

    chemin = tmp_path / "trades.db"
    monkeypatch.setattr(t, "_DB_PATH", chemin, raising=False)
    t._init_schema()
    c = sqlite3.connect(chemin)
    c.execute("""CREATE TABLE IF NOT EXISTS shadow_setups (
        id INTEGER PRIMARY KEY AUTOINCREMENT, detected_at TEXT, pair TEXT,
        timeframe TEXT, pattern TEXT, system_id TEXT, bar_timestamp TEXT)""")
    c.commit()
    c.close()
    from backend.services import sonde_horizon_1d as sonde
    sonde._init_schema()
    return sonde, chemin


def _setup_1d(chemin, pair="XAU/USD", quand=None):
    c = sqlite3.connect(chemin)
    c.execute("INSERT INTO shadow_setups (detected_at, pair, timeframe, pattern, "
              "system_id, bar_timestamp) VALUES (?,?,?,?,?,?)",
              ((quand or datetime.now(timezone.utc)).isoformat(), pair, "1d",
               "momentum_up", "X", "b"))
    c.commit()
    c.close()


# ── Elle annonce, une fois ────────────────────────────────────────────────

def test_elle_annonce_le_PREMIER_setup_1_jour(base):
    sonde, chemin = base
    sonde.marquer_etat_initial()          # rien encore
    _setup_1d(chemin)

    msg = sonde.construire_message()
    assert msg is not None
    assert "XAU/USD" in msg and "1" in msg


def test_elle_se_TAIT_ensuite(base):
    """🔑 La propriété qui la distingue d'une source de bruit."""
    sonde, chemin = base
    sonde.marquer_etat_initial()
    _setup_1d(chemin)

    assert sonde.construire_message() is not None
    sonde.marquer_annonce()
    assert sonde.construire_message() is None, "une fois répondu, elle se tait"


def test_elle_ne_dit_rien_tant_qu_il_n_y_a_rien(base):
    sonde, _ = base
    sonde.marquer_etat_initial()
    assert sonde.construire_message() is None


def test_un_fait_DEJA_acquis_au_premier_passage_ne_declenche_rien(base):
    """⛔ Sinon un redémarrage rejouerait l'annonce d'un événement ancien."""
    sonde, chemin = base
    _setup_1d(chemin, quand=datetime.now(timezone.utc) - timedelta(days=3))
    sonde.marquer_etat_initial()          # pose l'état SUR l'existant

    assert sonde.construire_message() is None


# ── Elle ne déplace rien sans confirmation ────────────────────────────────

@pytest.mark.asyncio
async def test_un_envoi_ECHOUE_ne_marque_PAS_la_sonde_comme_repondue(base, monkeypatch):
    """⛔ La leçon des sondes existantes : le curseur n'avance que sur `sent:true`.

    Marquer avant confirmation ferait disparaître l'annonce à jamais — la
    sonde se tairait sur une réponse que personne n'a reçue.
    """
    sonde, chemin = base
    sonde.marquer_etat_initial()
    _setup_1d(chemin)

    async def _echec(texte, parse_mode=None):
        return False

    monkeypatch.setattr("backend.services.telegram_service.send_sales_text", _echec)
    await sonde.executer()

    assert sonde.construire_message() is not None, (
        "envoi échoué → la sonde doit encore avoir quelque chose à dire")


@pytest.mark.asyncio
async def test_un_envoi_REUSSI_la_fait_taire(base, monkeypatch):
    sonde, chemin = base
    sonde.marquer_etat_initial()
    _setup_1d(chemin)

    envoyes = []

    async def _ok(texte, parse_mode=None):
        envoyes.append(texte)
        return True

    monkeypatch.setattr("backend.services.telegram_service.send_sales_text", _ok)
    await sonde.executer()

    assert len(envoyes) == 1
    assert sonde.construire_message() is None


@pytest.mark.asyncio
async def test_elle_n_envoie_rien_quand_il_n_y_a_rien_a_dire(base, monkeypatch):
    sonde, _ = base
    sonde.marquer_etat_initial()
    envoyes = []

    async def _ok(texte, parse_mode=None):
        envoyes.append(texte)
        return True

    monkeypatch.setattr("backend.services.telegram_service.send_sales_text", _ok)
    await sonde.executer()
    assert envoyes == [], "pas de message vide, pas de « rien à signaler »"


def test_le_message_ne_casse_pas_le_HTML(base, monkeypatch):
    sonde, chemin = base
    sonde.marquer_etat_initial()
    _setup_1d(chemin)
    msg = sonde.construire_message()
    assert "<" not in msg and ">" not in msg
