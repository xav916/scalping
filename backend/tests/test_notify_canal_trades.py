"""Canal Telegram `trades` : routage et repli (2026-08-19).

Un fil dédié aux ordres, pour qu'ils ne se noient plus dans les digests
d'analyse, l'état des marchés et le récap quotidien portés par le bot sales.

Ce qui est verrouillé ici, c'est surtout le **repli**. Basculer les scripts
vers `channel=trades` avant que le bot dédié n'existe ferait échouer chaque
notification en 503 — donc perdre en silence l'annonce d'un ordre réel. Le
repli sur `sales` transforme cette panne en simple erreur d'aiguillage.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

VALID_TOKEN = "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"


@pytest.fixture
def urls_appelees(monkeypatch):
    """Rend la liste des URL Telegram appelées — le jeton y est visible.

    ⚠️ `vues.charges` porte en plus les corps envoyés : le jeton dit à QUEL bot
    le message est parti, le corps dit de quel COMPTE il parle. Les deux sont
    nécessaires pour juger un repli.
    """
    class _Vues(list):
        charges: list = []

    vues = _Vues()
    vues.charges = []

    class _Reponse:
        status_code = 200
        text = "ok"

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, *a, **kw):
            vues.append(url)
            vues.charges.append(kw.get("json") or kw.get("data") or {})
            return _Reponse()

    import httpx as _httpx
    monkeypatch.setattr(_httpx, "AsyncClient", _Client)
    return vues


@pytest.fixture
def client(monkeypatch, urls_appelees):
    import config.settings as _s
    from backend.app import app

    monkeypatch.setattr(_s, "INFRA_TELEGRAM_BOT_TOKEN", "jeton_infra", raising=False)
    monkeypatch.setattr(_s, "INFRA_TELEGRAM_CHAT_ID", "1", raising=False)
    monkeypatch.setattr(_s, "SALES_TELEGRAM_BOT_TOKEN", "jeton_sales", raising=False)
    monkeypatch.setattr(_s, "SALES_TELEGRAM_CHAT_ID", "1", raising=False)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset():
    from backend.app import _INFRA_ALERT_LAST_SENT
    _INFRA_ALERT_LAST_SENT.clear()
    yield
    _INFRA_ALERT_LAST_SENT.clear()


def _envoyer(client, canal):
    return client.post(
        f"/api/admin/notify-infra-telegram?token={VALID_TOKEN}&channel={canal}",
        json={"title": "T", "body": "b"},
    )


def test_trades_configure_va_sur_son_propre_bot(client, urls_appelees, monkeypatch):
    import config.settings as _s
    monkeypatch.setattr(_s, "TRADES_TELEGRAM_BOT_TOKEN", "jeton_trades", raising=False)
    monkeypatch.setattr(_s, "TRADES_TELEGRAM_CHAT_ID", "1", raising=False)

    r = _envoyer(client, "trades")
    assert r.status_code == 200 and r.json()["sent"] is True
    assert "jeton_trades" in urls_appelees[0]


def test_fil_non_configure_retombe_sur_INFRA_SANS_perdre_le_message(
    client, urls_appelees, monkeypatch
):
    """LE test qui compte : un 503 ici perdrait l'annonce d'un ordre réel.

    ⚠️ Le repli visait `sales` jusqu'au 06/09. Sous des canaux nommés par
    COMPTE, cela attribuerait un trade Kraken au compte IC Markets — on se
    replie donc sur `infra`, qui n'est le fil de trading de personne.
    """
    import config.settings as _s
    monkeypatch.setattr(_s, "TRADES_TELEGRAM_BOT_TOKEN", "", raising=False)
    monkeypatch.setattr(_s, "TRADES_TELEGRAM_CHAT_ID", "", raising=False)

    r = _envoyer(client, "trades")
    assert r.status_code == 200
    assert r.json()["sent"] is True
    assert "jeton_infra" in urls_appelees[0]


def test_le_repli_ESTAMPILLE_le_compte_vise(client, urls_appelees, monkeypatch):
    """⛔ Sans estampille, le repli transforme un message Kraken en message
    d'infra : on saurait qu'il est arrivé, plus de quel compte il parle."""
    import config.settings as _s, json
    monkeypatch.setattr(_s, "TRADES_TELEGRAM_BOT_TOKEN", "", raising=False)
    monkeypatch.setattr(_s, "TRADES_TELEGRAM_CHAT_ID", "", raising=False)

    _envoyer(client, "trades")
    envoye = json.dumps(urls_appelees.charges, ensure_ascii=False)
    assert "KRAKEN" in envoye, envoye


def test_jeton_sans_chat_id_retombe_aussi(client, urls_appelees, monkeypatch):
    """Une configuration a moitié faite ne doit pas passer pour complète."""
    import config.settings as _s
    monkeypatch.setattr(_s, "TRADES_TELEGRAM_BOT_TOKEN", "jeton_trades", raising=False)
    monkeypatch.setattr(_s, "TRADES_TELEGRAM_CHAT_ID", "", raising=False)

    r = _envoyer(client, "trades")
    assert r.status_code == 200
    assert "jeton_infra" in urls_appelees[0]


def test_un_fil_INFRA_non_configure_ne_boucle_pas(client, monkeypatch):
    """⛔ Se replier sur infra quand infra lui-même manque doit rendre un 503
    franc, pas tourner en rond ni prétendre avoir envoyé."""
    import config.settings as _s
    for v in ("TRADES_TELEGRAM_BOT_TOKEN", "TRADES_TELEGRAM_CHAT_ID",
              "INFRA_TELEGRAM_BOT_TOKEN", "INFRA_TELEGRAM_CHAT_ID"):
        monkeypatch.setattr(_s, v, "", raising=False)
    assert _envoyer(client, "trades").status_code == 503


def test_les_canaux_existants_ne_bougent_pas(client, urls_appelees):
    assert _envoyer(client, "sales").status_code == 200
    assert "jeton_sales" in urls_appelees[-1]
    assert _envoyer(client, "infra").status_code == 200
    assert "jeton_infra" in urls_appelees[-1]


def test_canal_inconnu_reste_refuse(client):
    """Un nom mal orthographié doit crier, pas partir sur l'infra en douce."""
    assert _envoyer(client, "trade").status_code == 400
