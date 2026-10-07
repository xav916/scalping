"""Un envoi Telegram qui ÉCHOUE ne doit pas consommer le silence du cooldown.

## ⛔ CE QUE CES TESTS ÉPINGLENT

Le 2026-10-07, `/api/admin/notify-infra-telegram` posait sa marque de dedup
**avant** d'appeler Telegram :

    _INFRA_ALERT_LAST_SENT[dedup_key] = now     # <- ici
    ...
    response = await client.post(url, ...)      # <- et si ça rate ?
    if response.status_code != 200: raise HTTPException(502)

⇒ Un 502, un jeton mort, un Telegram en panne : la marque était **quand même
posée**. L'alerte était donc **perdue pour toute la durée du cooldown**, sans
que personne l'apprenne, et l'appelant qui rejouait proprement se faisait
répondre « cooldown » alors que rien n'était jamais parti.

> 🔑 Un cooldown doit taire les **doublons**, jamais les **échecs**.

Ce défaut était inoffensif tant que la sonde des métaux n'envoyait pas de
`cooldown_seconds` — ce qui était l'autre moitié du bug. En la réparant, ce
piège devenait armé : d'où ces tests, écrits en même temps.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


VALID_TOKEN = "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
URL = f"/api/admin/notify-infra-telegram?token={VALID_TOKEN}"


def _client(monkeypatch, statuts):
    """Client dont le faux Telegram rend les `statuts` donnés, dans l'ordre.

    `statuts` est une liste de codes HTTP ; la dernière valeur est répétée.
    """
    from backend.app import app
    import config.settings as _settings
    import httpx as _httpx

    monkeypatch.setattr(_settings, "INFRA_TELEGRAM_BOT_TOKEN", "fake_token",
                        raising=False)
    monkeypatch.setattr(_settings, "INFRA_TELEGRAM_CHAT_ID", "12345",
                        raising=False)

    appels = {"n": 0}

    class _Reponse:
        def __init__(self, code):
            self.status_code = code
            self.text = "boom" if code != 200 else "ok"

    class _Faux:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            i = min(appels["n"], len(statuts) - 1)
            appels["n"] += 1
            return _Reponse(statuts[i])

    monkeypatch.setattr(_httpx, "AsyncClient", _Faux)
    return TestClient(app), appels


@pytest.fixture(autouse=True)
def _etat_propre():
    from backend.app import _INFRA_ALERT_LAST_SENT
    _INFRA_ALERT_LAST_SENT.clear()
    yield
    _INFRA_ALERT_LAST_SENT.clear()


def test_un_502_de_telegram_ne_pose_aucune_marque(monkeypatch):
    """🔑 L'INVARIANT : après un échec, le rejeu doit VRAIMENT rappeler Telegram."""
    client, appels = _client(monkeypatch, [502, 200])
    corps = {"title": "Ordre metal PARTI", "body": "ticket 1360596228",
             "dedup_key": "metal_parti:admin_live:4930",
             "cooldown_seconds": 21600}

    r1 = client.post(URL, json=corps)
    assert r1.status_code == 502          # Telegram a refusé

    from backend.app import _INFRA_ALERT_LAST_SENT
    assert "metal_parti:admin_live:4930" not in _INFRA_ALERT_LAST_SENT, (
        "un echec a consomme le silence : l'alerte serait PERDUE")

    r2 = client.post(URL, json=corps)
    assert r2.status_code == 200 and r2.json()["sent"] is True
    assert appels["n"] == 2, "le rejeu n'a pas rappele Telegram"


def test_une_panne_reseau_ne_pose_aucune_marque(monkeypatch):
    """Même exigence quand `httpx` lève au lieu de rendre un code."""
    from backend.app import app
    import config.settings as _settings
    import httpx as _httpx

    monkeypatch.setattr(_settings, "INFRA_TELEGRAM_BOT_TOKEN", "fake_token",
                        raising=False)
    monkeypatch.setattr(_settings, "INFRA_TELEGRAM_CHAT_ID", "12345",
                        raising=False)

    class _Faux:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            raise _httpx.ConnectTimeout("telegram injoignable")

    monkeypatch.setattr(_httpx, "AsyncClient", _Faux)
    client = TestClient(app)

    r = client.post(URL, json={"title": "T", "body": "b",
                               "dedup_key": "panne_reseau",
                               "cooldown_seconds": 3600})
    assert r.status_code == 502

    from backend.app import _INFRA_ALERT_LAST_SENT
    assert "panne_reseau" not in _INFRA_ALERT_LAST_SENT


def test_un_succes_pose_bien_la_marque_et_le_doublon_est_tu(monkeypatch):
    """⛔ Le cooldown doit continuer à faire son travail : taire les doublons."""
    client, appels = _client(monkeypatch, [200])
    corps = {"title": "T", "body": "b", "dedup_key": "succes_puis_doublon",
             "cooldown_seconds": 3600}

    r1 = client.post(URL, json=corps)
    assert r1.json()["sent"] is True

    r2 = client.post(URL, json=corps)
    assert r2.json()["sent"] is False
    assert r2.json()["skipped"] == "cooldown"
    assert appels["n"] == 1, "le doublon a quand meme appele Telegram"


def test_sans_cooldown_seconds_aucune_marque_n_est_posee(monkeypatch):
    """La garde reste inerte sans durée — c'était l'autre moitié du bug du 07/10.

    ⚠️ Ce comportement est CONSERVÉ volontairement : des appelants historiques
    envoient une `dedup_key` sans durée et comptent sur un envoi à chaque fois.
    C'est à l'appelant de fournir la durée, et la sonde des métaux le fait
    désormais.
    """
    client, appels = _client(monkeypatch, [200])
    corps = {"title": "T", "body": "b", "dedup_key": "sans_duree"}

    client.post(URL, json=corps)
    client.post(URL, json=corps)

    from backend.app import _INFRA_ALERT_LAST_SENT
    assert "sans_duree" not in _INFRA_ALERT_LAST_SENT
    assert appels["n"] == 2
