"""Ouvertures et clôtures : chaque compte part sur SON fil (2026-09-06).

⛔ Ce fichier verrouillait la troisième table de canaux du dépôt :

    admin_live   -> TRADES_TELEGRAM_BOT_TOKEN
    toute autre  -> TELEGRAM_BOT_TOKEN

Or `TRADES_*` est le bot nommé « KRAKEN Trades » et `TELEGRAM_*` le bot
« DEMO Trades ». Les ouvertures du compte réel IC Markets partaient donc dans
le fil Kraken, et celles de Kraken dans le fil démo. Les tests validaient
l'inversion, parce qu'ils reprenaient la table plutôt que de la questionner.

⚠️ Le piège qui reste verrouillé, lui, est intact : un fil de compte vise **un
seul destinataire**. `_destinataires()` boucle sur `TELEGRAM_CHATS` pour servir
les clients ; l'emprunter enverrait nos trades chez Cédric et les futurs
Premium le jour où ils y seraient inscrits. `TELEGRAM_CHATS` étant vide
aujourd'hui, rien ne le révélerait avant qu'il ne soit trop tard. Cette garde
ne valait que pour le compte réel ; elle vaut désormais pour tous.
"""
from __future__ import annotations

import pytest

import backend.services.telegram_service as ts


@pytest.fixture(autouse=True)
def _bots(monkeypatch):
    import config.settings as s
    for var, val in (("SALES_TELEGRAM_BOT_TOKEN", "jeton_ic_markets"),
                     ("TRADES_TELEGRAM_BOT_TOKEN", "jeton_kraken"),
                     ("TELEGRAM_BOT_TOKEN", "jeton_demo"),
                     ("INFRA_TELEGRAM_BOT_TOKEN", "jeton_infra")):
        monkeypatch.setattr(s, var, val, raising=False)
    for var in ("SALES_TELEGRAM_CHAT_ID", "TRADES_TELEGRAM_CHAT_ID",
                "TELEGRAM_CHAT_ID", "INFRA_TELEGRAM_CHAT_ID"):
        monkeypatch.setattr(s, var, "5875076284", raising=False)
    monkeypatch.setattr(ts, "TELEGRAM_BOT_TOKEN", "jeton_demo", raising=False)


# ── Chaque compte, son bot ────────────────────────────────────────────────

@pytest.mark.parametrize("destination_id,jeton_attendu", [
    ("admin_live", "jeton_ic_markets"),
    ("admin_kraken", "jeton_kraken"),
    ("admin_kraken_spot", "jeton_kraken"),
    ("admin_legacy", "jeton_demo"),
])
def test_chaque_compte_part_sur_SON_bot(destination_id, jeton_attendu):
    """⛔ LE test de l'inversion : `admin_live` rendait « jeton_kraken »."""
    jeton, dests = ts._canal_trade(destination_id)
    assert jeton == jeton_attendu
    assert dests == [("__any__", "5875076284")]


def test_aucun_fil_de_compte_ne_diffuse_aux_CLIENTS(monkeypatch):
    """⚠️ La garde valait pour le seul compte réel. Elle vaut pour tous."""
    monkeypatch.setattr(ts, "_destinataires",
                        lambda: [("xavier", "1"), ("cedric", "42")])
    for did in ("admin_live", "admin_kraken", "admin_legacy"):
        _, dests = ts._canal_trade(did)
        assert len(dests) == 1, did
        assert all(chat != "42" for _, chat in dests), did


def test_une_destination_INCONNUE_ne_prend_aucun_fil_de_trading(monkeypatch):
    """⛔ Lui donner un fil de compte lui attribuerait des trades qu'elle n'a
    pas faits. Elle part sur infra."""
    monkeypatch.setattr(ts, "_destinataires", lambda: [("cedric", "42")])
    jeton, dests = ts._canal_trade("user:2")
    assert jeton == "jeton_infra"
    assert dests == [("__any__", "5875076284")]


# ── Les replis ────────────────────────────────────────────────────────────

def test_un_fil_non_gree_retombe_sur_INFRA_pas_sur_les_clients(monkeypatch):
    """⛔ Sans repli, les trades du compte disparaîtraient. Mais retomber sur
    `_destinataires()` les enverrait aux clients — pire que les perdre."""
    import config.settings as s
    monkeypatch.setattr(s, "SALES_TELEGRAM_BOT_TOKEN", "", raising=False)
    monkeypatch.setattr(ts, "_destinataires", lambda: [("cedric", "42")])

    jeton, dests = ts._canal_trade("admin_live")
    assert jeton == "jeton_infra"
    assert dests == [("__any__", "5875076284")]


def test_configuration_a_moitie_faite_retombe_aussi(monkeypatch):
    """Un jeton sans chat_id n'est pas une configuration."""
    import config.settings as s
    monkeypatch.setattr(s, "SALES_TELEGRAM_CHAT_ID", "", raising=False)
    monkeypatch.setattr(ts, "_destinataires", lambda: [("cedric", "42")])
    jeton, _ = ts._canal_trade("admin_live")
    assert jeton == "jeton_infra"


def test_si_meme_INFRA_manque_on_n_envoie_a_PERSONNE(monkeypatch):
    """⛔ Le dernier repli ne doit pas être les clients."""
    import config.settings as s
    for var in ("SALES_TELEGRAM_BOT_TOKEN", "INFRA_TELEGRAM_BOT_TOKEN"):
        monkeypatch.setattr(s, var, "", raising=False)
    monkeypatch.setattr(ts, "_destinataires", lambda: [("cedric", "42")])
    _, dests = ts._canal_trade("admin_live")
    assert dests == []


# ── Bout en bout ──────────────────────────────────────────────────────────

@pytest.fixture()
def envois(monkeypatch):
    vus: list = []

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
            vus.append((url, kw.get("json") or {}))
            return _Rep()

    monkeypatch.setattr(ts.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(ts, "is_configured", lambda: True)
    monkeypatch.setattr(ts, "_format_trade_opened",
                        lambda *a, **kw: "🟢 ACHAT Livre / Dollar")
    monkeypatch.setattr(ts, "_destinataires", lambda: [("cedric", "42")])
    return vus


@pytest.mark.asyncio
async def test_l_ouverture_du_reel_part_sur_le_fil_IC_MARKETS(envois):
    await ts.send_trade_opened(
        setup=object(), ticket=1355176392, fill_price=1.36067, volume=0.01,
        mode="live", destination_id="admin_live")

    assert len(envois) == 1
    url, payload = envois[0]
    assert "jeton_ic_markets" in url
    assert payload["chat_id"] == "5875076284"
    assert payload["parse_mode"] == "Markdown"


@pytest.mark.asyncio
async def test_l_ouverture_KRAKEN_part_sur_le_fil_KRAKEN(envois):
    await ts.send_trade_opened(
        setup=object(), ticket=42, fill_price=4450.0, volume=0.01,
        mode="live", destination_id="admin_kraken")
    assert "jeton_kraken" in envois[0][0]
