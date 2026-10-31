"""Trois étages pour le fil IC Markets — et le défaut par défaut est AGIR.

> Xavier, 2026-10-11 : « je veux rationaliser les messages qui me sont envoyés
> par Telegram sur le fil IC Markets », puis, devant l'inventaire, il a choisi
> la règle des **trois étages**.

## ⛔ LA PROPRIÉTÉ QUI COMPTE PLUS QUE TOUTES LES AUTRES

Une clé **inconnue reste sur son fil**. Ranger l'inconnu en infra rendrait
muet, en silence, tout émetteur ajouté plus tard — exactement le défaut du
`channel` par défaut à `infra`, qui a fait atterrir quatre notificateurs de
trading sur le mauvais bot entre le 04/08 et le 19/08.

⇒ **Se tromper doit rendre bavard, jamais muet.**
"""
from __future__ import annotations

import datetime as dt

import pytest

from backend.services import digest_telegram as D
from backend.services import etages_notification as E
from backend.tests.jeton_de_test import JETON_PUBLIC_DE_TEST


@pytest.fixture(autouse=True)
def _propre(monkeypatch):
    monkeypatch.delenv("ETAGES_NOTIFICATION", raising=False)
    yield


# ─── ① Inerte par défaut ─────────────────────────────────────────────────

def test_inerte_par_defaut():
    assert E.arme() is False


def test_desarme_RIEN_ne_bouge(monkeypatch):
    """Même une clé classée DIGEST part comme avant."""
    canal, differer, et = E.router("ic_markets", "tiers_objectif:1:1.8")
    assert (canal, differer) == ("ic_markets", False)
    assert et == E.DIGEST, "l'étage doit être calculé même désarmé"


@pytest.mark.parametrize("v,attendu", [
    ("1", True), ("true", True), ("ON", True), ("oui", True),
    ("0", False), ("", False), ("non", False), ("off", False),
])
def test_le_drapeau_se_lit(monkeypatch, v, attendu):
    monkeypatch.setenv("ETAGES_NOTIFICATION", v)
    assert E.arme() is attendu


# ─── ② LE DÉFAUT PAR DÉFAUT : une clé inconnue RESTE sur son fil ─────────

@pytest.mark.parametrize("cle", [
    None, "", "   ", "une_sonde_ajoutee_demain", "quelque_chose_de_neuf",
    "TIERS_OBJECTIF", "xx",
])
def test_une_cle_INCONNUE_reste_sur_son_fil(monkeypatch, cle):
    """⛔ LA propriété. Réinjection : mettre `return (INFRA, False)` dans le
    cas inconnu et ce test tombe sept fois."""
    monkeypatch.setenv("ETAGES_NOTIFICATION", "1")
    et, connu = E.etage(cle)
    assert et == E.AGIR, f"{cle!r} serait rangé en {et} — message perdu de vue"
    assert connu is False
    canal, differer, _ = E.router("ic_markets", cle)
    assert (canal, differer) == ("ic_markets", False)


def test_une_cle_inconnue_est_JOURNALISEE(monkeypatch, caplog):
    """Un émetteur ajouté plus tard doit se voir dans le journal, pas se
    découvrir six mois après en cherchant un message jamais reçu."""
    monkeypatch.setenv("ETAGES_NOTIFICATION", "1")
    with caplog.at_level("INFO"):
        E.router("ic_markets", "sonde_de_demain:42")
    assert any("inconnue" in r.message for r in caplog.records)


# ─── ③ Les trois étages, sur les VRAIES clés du dépôt ────────────────────

@pytest.mark.parametrize("cle", [
    "nue", "nue-illisible", "push_echec_12345", "saturation",
    "metal_parti:admin_live:0.35", "metal_silence", "fermeture_metaux",
    "interrupteur_desarme",
])
def test_AGIR_reste_immediat_sur_son_fil(monkeypatch, cle):
    monkeypatch.setenv("ETAGES_NOTIFICATION", "1")
    canal, differer, et = E.router("ic_markets", cle)
    assert et == E.AGIR
    assert (canal, differer) == ("ic_markets", False)


@pytest.mark.parametrize("cle", [
    "tiers_objectif:12345:1.8000", "capture-niveaux-illisible",
    "capture-niveaux-manquantes", "echelles_or_journee",
    "equilibre-activations", "interrupteur_bilan", "divergence-univers",
])
def test_DIGEST_est_differe_mais_reste_son_fil(monkeypatch, cle):
    monkeypatch.setenv("ETAGES_NOTIFICATION", "1")
    canal, differer, et = E.router("ic_markets", cle)
    assert et == E.DIGEST
    assert differer is True, "il partirait tout de suite"
    assert canal == "ic_markets", "le bilan reste sur SON fil"


@pytest.mark.parametrize("cle", [
    "ibkr-digest", "ibkr-illisible", "ibkr-mvt-AAPL", "energie-weekend",
    "exec-client", "exec-client-illisible",
])
def test_INFRA_quitte_son_fil(monkeypatch, cle):
    """🔑 Gratuit : l'or est SEUL sur le compte réel depuis le 08/10, donc
    IBKR, l'énergie et les clients payants ne peuvent plus rien dire d'utile
    sur son fil."""
    monkeypatch.setenv("ETAGES_NOTIFICATION", "1")
    canal, differer, et = E.router("ic_markets", cle)
    assert et == E.INFRA
    assert canal == E.INFRA
    assert differer is False


def test_le_prefixe_le_PLUS_LONG_gagne():
    """⛔ `exec-client-illisible` doit gagner contre `exec-client`, sinon la
    clé la plus précise n'est jamais atteinte. Ici les deux donnent INFRA,
    donc on teste la MÉCANIQUE sur une paire où ça change."""
    assert E._PREFIXES_TRIES == tuple(sorted(E.ETAGES, key=len, reverse=True))
    longueurs = [len(p) for p in E._PREFIXES_TRIES]
    assert longueurs == sorted(longueurs, reverse=True)
    # et une vérification de bout en bout sur un cas réel
    assert E.etage("capture-niveaux-verification")[0] == E.DIGEST


# ─── ④ Les autres fils ne sont PAS touchés ───────────────────────────────

@pytest.mark.parametrize("canal", ["infra", "kraken", "demo", "ibkr"])
def test_rationaliser_un_fil_n_en_remue_pas_un_autre(monkeypatch, canal):
    """⛔ Une clé DIGEST sur le fil Kraken doit partir comme avant : la demande
    de Xavier porte sur SON fil."""
    monkeypatch.setenv("ETAGES_NOTIFICATION", "1")
    sortie, differer, _ = E.router(canal, "tiers_objectif:1:1.8")
    assert (sortie, differer) == (canal, False)


# ─── ⑤ Le magasin du bilan : différer ne doit JAMAIS perdre ──────────────

def test_ranger_puis_relire(tmp_path):
    db = str(tmp_path / "t.db")
    i = D.ranger("ic_markets", "tiers_objectif:1:1.8", "Palier", "1,80 R", db)
    assert i > 0
    lignes = D.en_attente("ic_markets", db)
    assert len(lignes) == 1
    assert lignes[0]["dedup_key"] == "tiers_objectif:1:1.8"
    assert lignes[0]["envoye_le"] is None


def test_un_magasin_indisponible_rend_ZERO_et_ne_leve_pas():
    """⛔ La route d'envoi ne doit pas tomber parce que le bilan est
    indisponible — mais elle doit SAVOIR que rien n'a été rangé, pour envoyer
    tout de suite plutôt que de perdre le message."""
    assert D.ranger("ic_markets", "k", "t", "c",
                    "/chemin/qui/n/existe/pas/x.db") == 0


def test_le_bilan_COMPTE_les_repetitions_au_lieu_de_les_repeter(tmp_path):
    """🔑 « palier franchi x10 » est une information ; dix lignes « palier
    franchi » sont du bruit."""
    db = str(tmp_path / "t.db")
    for k in range(10):
        D.ranger("ic_markets", f"tiers_objectif:{k}:1.8", "Palier",
                 f"ticket {k}", db)
    D.ranger("ic_markets", "echelles_or_journee", "Echelles", "rien", db)
    texte = D.formater(D.en_attente("ic_markets", db))
    assert "x10" in texte
    assert texte.count("Palier") <= 1, "les dix lignes sont répétées"
    assert "11 message" in texte


def test_le_bilan_ne_porte_AUCUN_markdown(tmp_path):
    """⛔ Les clés sont en snake_case et Telegram lit un underscore comme une
    italique OUVERTE : le message part en 400 et n'est jamais livré. Défaut
    déjà payé le 2026-10-10 sur `/trade`."""
    db = str(tmp_path / "t.db")
    D.ranger("ic_markets", "tiers_objectif:1:1.8", "Palier", "x", db)
    texte = D.formater(D.en_attente("ic_markets", db))
    for c in ("*", "_", "`", "[", "]"):
        assert c not in texte, f"le caractère Markdown {c!r} est présent"


def test_marquer_envoyes_retire_du_prochain_bilan(tmp_path):
    db = str(tmp_path / "t.db")
    i = D.ranger("ic_markets", "tiers_objectif:1:1.8", "Palier", "x", db)
    assert D.marquer_envoyes([i], db) == 1
    assert D.en_attente("ic_markets", db) == []


def test_un_bilan_vide_ne_fabrique_aucun_message(tmp_path):
    """⛔ Envoyer « Bilan du jour — 0 message » chaque soir serait exactement
    le bruit qu'on retire."""
    assert D.formater([]) == ""
    assert D.formater(D.en_attente("ic_markets",
                                   str(tmp_path / "vide.db"))) == ""


def test_le_bilan_d_un_fil_n_emporte_pas_celui_d_un_autre(tmp_path):
    db = str(tmp_path / "t.db")
    D.ranger("ic_markets", "tiers_objectif:1:1.8", "A", "", db)
    D.ranger("kraken", "tiers_objectif:2:1.8", "B", "", db)
    assert len(D.en_attente("ic_markets", db)) == 1
    assert len(D.en_attente("kraken", db)) == 1


def test_marquer_AVANT_l_envoi_perdrait_le_bilan(tmp_path):
    """La garde est documentaire, mais la propriété se teste : un marquage qui
    échoue laisse les lignes EN ATTENTE, donc le bilan repart demain."""
    db = str(tmp_path / "t.db")
    i = D.ranger("ic_markets", "tiers_objectif:1:1.8", "Palier", "x", db)
    assert D.marquer_envoyes([i], "/chemin/inexistant/x.db") == 0
    assert len(D.en_attente("ic_markets", db)) == 1, "la ligne a été perdue"


# ─── ⑥ LA ROUTE elle-même : le test que les unités ne couvrent pas ───────

VALID_TOKEN = JETON_PUBLIC_DE_TEST
URL = f"/api/admin/notify-infra-telegram?token={VALID_TOKEN}&channel=ic_markets"


@pytest.fixture
def client(monkeypatch, tmp_path):
    """Un client qui n'atteint jamais Telegram, et une base jetable."""
    from fastapi.testclient import TestClient
    from backend.app import app

    envois = []

    class _R:
        status_code = 200
        text = "{}"
        def json(self): return {"ok": True}

    class _FauxAsync:
        """La route envoie avec `httpx.AsyncClient`, pas `httpx.post` — ma
        premiere doublure interceptait la mauvaise fonction et trois tests
        tombaient sur un VRAI appel reseau."""
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, **kw):
            envois.append((url, kw))
            return _R()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _FauxAsync)

    # ⛔ SANS CA LE TEST NE PROUVE RIEN : un fil non gree fait se replier la
    # route sur `ic_markets -> infra` AVANT mon accroche, et elle rend 503. On
    # gree donc le fil, avec des valeurs manifestement fausses.
    from config import settings as _cfg
    monkeypatch.setattr(_cfg, "SALES_TELEGRAM_BOT_TOKEN", "999:FAUX", raising=False)
    monkeypatch.setattr(_cfg, "SALES_TELEGRAM_CHAT_ID", "1", raising=False)
    monkeypatch.setattr(_cfg, "INFRA_TELEGRAM_BOT_TOKEN", "888:FAUX", raising=False)
    monkeypatch.setattr(_cfg, "INFRA_TELEGRAM_CHAT_ID", "2", raising=False)
    monkeypatch.setattr(D, "_db",
                        lambda chemin=None: _db_jetable(str(tmp_path / "d.db")))
    return TestClient(app), envois


def _db_jetable(chemin):
    import sqlite3
    c = sqlite3.connect(chemin, timeout=15)
    c.row_factory = sqlite3.Row
    c.executescript(D._SCHEMA)
    return c


def test_la_ROUTE_differe_une_cle_digest_quand_c_est_arme(monkeypatch, client):
    """⛔ Mes 52 tests d'unité ne prouvaient RIEN sur la route : ils testaient
    `router()` et le magasin séparément. C'est l'accroche dans `app.py` qui
    décide, et elle n'était couverte par aucun d'eux."""
    cli, _ = client
    monkeypatch.setenv("ETAGES_NOTIFICATION", "1")
    r = cli.post(URL, json={"title": "Palier", "body": "1,80 R",
                            "dedup_key": "tiers_objectif:12345:1.8"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("sent") is False
    assert d.get("differe") == "bilan_du_jour", d
    assert d.get("etage") == "digest"


def test_la_ROUTE_envoie_une_cle_AGIR_immediatement(monkeypatch, client):
    cli, envois = client
    monkeypatch.setenv("ETAGES_NOTIFICATION", "1")
    r = cli.post(URL, json={"title": "Position nue", "body": "sans stop",
                            "dedup_key": "nue"})
    assert r.status_code == 200, r.text
    assert r.json().get("differe") is None


def test_la_ROUTE_ne_differe_RIEN_quand_c_est_desarme(monkeypatch, client):
    """⛔ La propriété qui rend la livraison sûre : désarmé, la route se
    comporte EXACTEMENT comme avant."""
    cli, _ = client
    monkeypatch.delenv("ETAGES_NOTIFICATION", raising=False)
    r = cli.post(URL, json={"title": "Palier", "body": "1,80 R",
                            "dedup_key": "tiers_objectif:12345:1.8"})
    assert r.status_code == 200, r.text
    assert r.json().get("differe") is None, "un message a été différé sans armement"


def test_la_ROUTE_envoie_plutot_que_de_PERDRE_si_le_magasin_refuse(
        monkeypatch, client):
    """⛔ Rationaliser un fil en jetant des messages serait le pire des deux."""
    cli, _ = client
    monkeypatch.setenv("ETAGES_NOTIFICATION", "1")
    monkeypatch.setattr(D, "ranger", lambda *a, **k: 0)
    r = cli.post(URL, json={"title": "Palier", "body": "x",
                            "dedup_key": "tiers_objectif:1:1.8"})
    assert r.status_code == 200, r.text
    assert r.json().get("differe") is None, "le message a été perdu"
