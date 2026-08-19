"""Les annonces Horizon passent sur « Scalping Radar Info » (2026-08-19).

Les setups 4h/1d sont des **observations** — « aucune position n'est ouverte »,
le dit le message lui-même. Les laisser sur le bot sales les mélangeait aux
digests, à l'état des marchés et au récap quotidien. Elles partent désormais
sur `@xav_scalping_radar_bot`.

⚠️ Le piège verrouillé ici : ce bot sert AUSSI les clients, via `send_text`
qui boucle sur `TELEGRAM_CHATS`. Emprunter ce chemin ferait partir les
observations chez Cédric et les futurs Premium le jour où ils y seront
inscrits — et comme `TELEGRAM_CHATS` est vide aujourd'hui, aucun test ni
aucune observation ne le révélerait avant qu'il ne soit trop tard. L'envoi
vise donc `TELEGRAM_CHAT_ID` seul.
"""
from __future__ import annotations

import pytest

import backend.services.telegram_service as ts


@pytest.fixture
def envois(monkeypatch):
    """Capture (url, payload) de chaque envoi."""
    vues: list[tuple[str, dict]] = []

    class _Rep:
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
            vues.append((url, kw.get("json") or {}))
            return _Rep()

    monkeypatch.setattr(ts.httpx, "AsyncClient", _Client)
    return vues


@pytest.fixture(autouse=True)
def _canaux(monkeypatch):
    import config.settings as s
    monkeypatch.setattr(s, "SALES_TELEGRAM_BOT_TOKEN", "jeton_sales", raising=False)
    monkeypatch.setattr(s, "SALES_TELEGRAM_CHAT_ID", "999", raising=False)


def _radar(monkeypatch, jeton="jeton_radar", chat="5875076284"):
    import config.settings as s
    monkeypatch.setattr(s, "TELEGRAM_BOT_TOKEN", jeton, raising=False)
    monkeypatch.setattr(s, "TELEGRAM_CHAT_ID", chat, raising=False)


@pytest.mark.asyncio
async def test_va_sur_le_bot_radar(envois, monkeypatch):
    _radar(monkeypatch)
    assert await ts.send_info_text("coucou") is True
    url, payload = envois[0]
    assert "jeton_radar" in url
    assert payload["chat_id"] == "5875076284"


@pytest.mark.asyncio
async def test_ne_diffuse_PAS_aux_clients(envois, monkeypatch):
    """Un seul envoi, au chat admin — même si des clients sont inscrits."""
    import config.settings as s
    _radar(monkeypatch)
    monkeypatch.setattr(
        s, "TELEGRAM_CHATS", {"xavier": "5875076284", "cedric": "42"}, raising=False)
    monkeypatch.setattr(
        ts, "TELEGRAM_CHATS", {"xavier": "5875076284", "cedric": "42"}, raising=False)

    assert await ts.send_info_text("coucou") is True
    assert len(envois) == 1
    assert envois[0][1]["chat_id"] == "5875076284"
    assert all(p["chat_id"] != "42" for _, p in envois)


@pytest.mark.asyncio
async def test_bot_radar_absent_retombe_sur_sales(envois, monkeypatch):
    """Sans repli, l'annonce disparaîtrait au lieu de changer de fil."""
    _radar(monkeypatch, jeton="", chat="")
    assert await ts.send_info_text("coucou") is True
    assert "jeton_sales" in envois[0][0]


# ── Le setup long-horizon emprunte bien ce canal ───────────────────────────

class _Setup:
    horizon = "4h"
    pair = "XAU/USD"
    entry_price = 4450.0
    stop_loss = 4420.0
    take_profit_1 = 4504.0
    confidence_score = 70.0
    verdict_action = "TAKE"
    shadow_system_id = "V2_CORE_LONG_XAU"

    class direction:
        value = "buy"


@pytest.mark.asyncio
async def test_annonce_horizon_part_sur_le_bot_radar(envois, monkeypatch):
    _radar(monkeypatch)
    monkeypatch.setattr(ts, "TELEGRAM_LONG_HORIZON_ENABLED", True, raising=False)
    monkeypatch.setattr(ts, "TELEGRAM_LONG_HORIZON_MIN_CONFIDENCE", 61.0, raising=False)

    assert await ts.send_long_horizon_setup(_Setup()) is True
    url, payload = envois[0]
    assert "jeton_radar" in url
    assert "Horizon 4h" in payload["text"]
    assert "aucune position" in payload["text"]


@pytest.mark.asyncio
async def test_setup_5min_n_envoie_rien(envois, monkeypatch):
    """Ce canal ne doit pas se mettre à porter du 5 min : ~2000 msg/jour."""
    _radar(monkeypatch)
    monkeypatch.setattr(ts, "TELEGRAM_LONG_HORIZON_ENABLED", True, raising=False)

    class _Court(_Setup):
        horizon = "5min"

    assert await ts.send_long_horizon_setup(_Court()) is False
    assert envois == []


@pytest.mark.asyncio
async def test_sous_le_seuil_de_confiance_rien_ne_part(envois, monkeypatch):
    _radar(monkeypatch)
    monkeypatch.setattr(ts, "TELEGRAM_LONG_HORIZON_ENABLED", True, raising=False)
    monkeypatch.setattr(ts, "TELEGRAM_LONG_HORIZON_MIN_CONFIDENCE", 61.0, raising=False)

    class _Faible(_Setup):
        confidence_score = 50.0

    assert await ts.send_long_horizon_setup(_Faible()) is False
    assert envois == []
