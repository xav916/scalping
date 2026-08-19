"""Ouvertures et clôtures du compte réel → fil « Scalping Radar Trades ».

Xavier veut le message complet — risque et objectif en euros, niveaux,
« pourquoi ce trade », ticket — sur le fil dédié au compte 13137475, et non
plus mêlé au reste sur le bot radar.

⚠️ Le piège verrouillé ici est le même que pour les annonces Horizon : le fil
trades vise **un seul destinataire**. `_destinataires()` boucle sur
`TELEGRAM_CHATS` pour servir les clients ; l'emprunter enverrait les trades du
compte réel chez Cédric et les futurs Premium le jour où ils y seraient
inscrits. `TELEGRAM_CHATS` étant vide aujourd'hui, rien ne le révélerait avant
qu'il ne soit trop tard.
"""
from __future__ import annotations

import pytest

import backend.services.telegram_service as ts


@pytest.fixture(autouse=True)
def _bots(monkeypatch):
    import config.settings as s
    monkeypatch.setattr(s, "TRADES_TELEGRAM_BOT_TOKEN", "jeton_trades", raising=False)
    monkeypatch.setattr(s, "TRADES_TELEGRAM_CHAT_ID", "5875076284", raising=False)
    monkeypatch.setattr(ts, "TELEGRAM_BOT_TOKEN", "jeton_radar", raising=False)


def test_compte_reel_va_sur_le_fil_trades(monkeypatch):
    monkeypatch.setattr(ts, "_destinataires", lambda: [("xavier", "1"), ("cedric", "42")])
    jeton, dests = ts._canal_trade("admin_live")
    assert jeton == "jeton_trades"
    assert dests == [("__any__", "5875076284")]


def test_le_fil_trades_ne_diffuse_PAS_aux_clients(monkeypatch):
    """Un seul destinataire, même avec des clients inscrits."""
    monkeypatch.setattr(ts, "_destinataires", lambda: [("xavier", "1"), ("cedric", "42")])
    _, dests = ts._canal_trade("admin_live")
    assert len(dests) == 1
    assert all(chat != "42" for _, chat in dests)


@pytest.mark.parametrize("dest", ["admin_kraken", "admin_legacy", "user:2", None])
def test_les_autres_destinations_gardent_le_bot_radar(monkeypatch, dest):
    monkeypatch.setattr(ts, "_destinataires", lambda: [("xavier", "1")])
    jeton, dests = ts._canal_trade(dest)
    assert jeton == "jeton_radar"
    assert dests == [("xavier", "1")]


def test_fil_trades_non_configure_retombe_sur_le_bot_radar(monkeypatch):
    """Sans repli, les trades du compte réel disparaîtraient."""
    import config.settings as s
    monkeypatch.setattr(s, "TRADES_TELEGRAM_BOT_TOKEN", "", raising=False)
    monkeypatch.setattr(s, "TRADES_TELEGRAM_CHAT_ID", "", raising=False)
    monkeypatch.setattr(ts, "_destinataires", lambda: [("xavier", "1")])

    jeton, dests = ts._canal_trade("admin_live")
    assert jeton == "jeton_radar"
    assert dests == [("xavier", "1")]


def test_configuration_a_moitie_faite_retombe_aussi(monkeypatch):
    import config.settings as s
    monkeypatch.setattr(s, "TRADES_TELEGRAM_CHAT_ID", "", raising=False)
    monkeypatch.setattr(ts, "_destinataires", lambda: [("xavier", "1")])
    jeton, _ = ts._canal_trade("admin_live")
    assert jeton == "jeton_radar"


# ── Bout en bout : l'ouverture part bien sur le bon bot ────────────────────

@pytest.mark.asyncio
async def test_ouverture_du_reel_part_sur_le_fil_trades(monkeypatch):
    envois: list = []

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
            envois.append((url, kw.get("json") or {}))
            return _Rep()

    monkeypatch.setattr(ts.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(ts, "is_configured", lambda: True)
    monkeypatch.setattr(ts, "destination_is_real_money", lambda d: True)
    monkeypatch.setattr(ts, "_format_trade_opened",
                        lambda *a, **kw: "🟢 ACHAT Livre / Dollar")
    monkeypatch.setattr(ts, "_destinataires", lambda: [("cedric", "42")])

    await ts.send_trade_opened(
        setup=object(), ticket=1355176392, fill_price=1.36067, volume=0.01,
        mode="live", destination_id="admin_live")

    assert len(envois) == 1
    url, payload = envois[0]
    assert "jeton_trades" in url
    assert payload["chat_id"] == "5875076284"
    assert payload["parse_mode"] == "Markdown"
