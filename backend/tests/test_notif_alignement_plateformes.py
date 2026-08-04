"""Un seul formateur de trade pour toutes les plateformes (2026-08-04).

Il existait deux systèmes de notification en parallèle, et personne ne
l'avait vu :

``send_trade_opened`` (Python)   canal Scalping Radar, format complet — SL,
                                 TP, montants en euros, justification — mais
                                 branché sur MT5 et Binance **seulement**

``notify-new-pushes.sh``         canal sales, format dégradé : ni SL, ni TP,
                                 prix brut ``63924.00000000001``, broker
                                 répété deux fois — branché sur **toutes**
                                 les destinations

D'où le symptôme observé sur les premiers trades Kraken réels : seul le
second partait, dans le mauvais format et sur le mauvais canal.

Ces tests verrouillent l'alignement : toute destination qui exécute
réellement doit passer par le formateur unique.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace as NS

import httpx
import pytest

from backend.models.schemas import PatternType
from backend.services import destinations_registry as reg
from backend.services import telegram_service as ts


def _setup(pair="BTC/USD", entry=63924.0):
    return NS(pair=pair, direction=NS(value="sell"),
              pattern=NS(pattern=PatternType.RANGE_BOUNCE_DOWN,
                         confidence=0.7, description="Rejet"),
              confidence_score=65.0, entry_price=entry,
              stop_loss=entry * 1.004, take_profit_1=entry * 0.993,
              take_profit_2=entry * 0.99, risk_pips=1.0, reward_pips_1=1.8,
              reward_pips_2=2.5, risk_reward_1=1.8, risk_reward_2=2.5,
              asset_class="crypto")


# --- l'unité de volume dépend du broker -----------------------------------

def test_une_quantite_crypto_n_est_pas_un_lot():
    """« 0,0023 lot » pour 0,0023 BTC est faux, et faux d'un facteur variable."""
    txt = ts._format_trade_opened(_setup(), ticket="a26c6df2", fill_price=63924.0,
                                  volume=0.0023, mode="live",
                                  destination_id="admin_kraken")
    assert "0,0023 BTC" in txt
    assert "lot" not in txt


def test_ethereum_porte_son_propre_symbole():
    txt = ts._format_trade_opened(_setup("ETH/USD", 1869.15), ticket="x",
                                  fill_price=1869.15, volume=0.098,
                                  mode="live", destination_id="admin_kraken")
    assert "0,098 ETH" in txt


def test_mt5_garde_le_lot():
    """Les CFD se dimensionnent bien en lots : ne rien casser de ce côté."""
    s = _setup("XAU/USD", 3312.40)
    s.asset_class = "metal"
    txt = ts._format_trade_opened(s, ticket=8842190, fill_price=3312.40,
                                  volume=0.02, mode="LIVE",
                                  destination_id="admin_live")
    assert "0,02 lot" in txt


def test_une_destination_inconnue_retombe_sur_le_lot():
    """Défaut prudent : ne pas inventer une unité qu'on ne connaît pas."""
    assert ts._unite_de_volume(_setup(), "admin_inexistant") == "lot"


# --- la référence d'ordre doit rester exploitable -------------------------

def test_la_reference_kraken_est_affichee_telle_quelle():
    """Elle était hachée en entier, donc inutilisable pour retrouver l'ordre."""
    ref = "a26c6df2-2846-4e18-8840-b26ceab21741"
    txt = ts._format_trade_opened(_setup(), ticket=ref, fill_price=63924.0,
                                  volume=0.0023, mode="live",
                                  destination_id="admin_kraken")
    assert ref in txt


def test_le_ticket_mt5_numerique_reste_intact():
    s = _setup("XAU/USD", 3312.40)
    s.asset_class = "metal"
    txt = ts._format_trade_opened(s, ticket=8842190, fill_price=3312.40,
                                  volume=0.02, mode="LIVE",
                                  destination_id="admin_live")
    assert "#8842190" in txt


# --- le message Kraken doit être aussi complet que le message MT5 ---------

@pytest.mark.parametrize("fragment", ["Risque", "Objectif", "SL ", "TP ",
                                      "Pourquoi ce trade"])
def test_le_message_kraken_porte_le_plan_complet(fragment):
    """C'est précisément ce que le format shell ne disait pas."""
    txt = ts._format_trade_opened(_setup(), ticket="x", fill_price=63924.0,
                                  volume=0.0023, mode="live",
                                  destination_id="admin_kraken")
    assert fragment in txt, f"{fragment!r} absent du message Kraken"


def test_kraken_est_annonce_comme_argent_reel():
    """Il s'affichait « Démo » avant que les libellés viennent du registre."""
    txt = ts._format_trade_opened(_setup(), ticket="x", fill_price=63924.0,
                                  volume=0.0023, mode="live",
                                  destination_id="admin_kraken")
    assert "réel" in txt


# --- LE test : aucune plateforme réelle ne doit rester sans hook ----------

def test_toute_destination_reelle_notifie_via_le_formateur_unique():
    """Kraken exécutait sans jamais appeler ``send_trade_opened``.

    Ce test échouera de la même façon si IBKR est branché sans son hook.
    """
    from backend.services import (binance_bridge_client, kraken_bridge_client,
                                  kraken_spot_bridge_client, mt5_bridge)
    clients = {
        "mt5": mt5_bridge, "kraken": kraken_bridge_client,
        "kraken_spot": kraken_spot_bridge_client, "binance": binance_bridge_client,
    }
    types_reels = {d.bridge_type for d in reg.DESTINATIONS.values() if d.reel}
    sans_hook = sorted(
        t for t in types_reels
        if t in clients
        and "send_trade_opened" not in inspect.getsource(clients[t])
    )
    assert sans_hook == [], (
        f"types de bridge en argent reel sans notification : {sans_hook}"
    )


def test_le_hook_kraken_part_bien_a_l_execution(tmp_path, monkeypatch):
    """Vérifié par exécution, pas par lecture du code."""
    from backend.services import kraken_bridge_client as kbc
    from backend.services import mt5_pushes_service

    monkeypatch.setattr(mt5_pushes_service, "_db_path",
                        lambda: str(tmp_path / "t.db"))
    monkeypatch.setattr("backend.services.rejection_service.record_rejection",
                        lambda **kw: None)
    mt5_pushes_service._ensure_schema()

    recu: list[dict] = []

    async def _capture(setup, **kw):
        recu.append(kw)

    monkeypatch.setattr(ts, "send_trade_opened", _capture)

    async def _post(self, url, json=None, headers=None):
        return httpx.Response(200, json={
            "ok": True, "market_order_id": "a26c6df2-2846", "avg_price": 63924.0,
            "volume": 0.0023, "mode": "live",
        }, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", _post)

    import asyncio
    asyncio.run(kbc.push_to_kraken(
        _setup(), {"risk_money": 0.66},
        NS(destination_id="admin_kraken", user_id=None,
           bridge_url="http://b.test", bridge_api_key="k", bridge_type="kraken"),
    ))

    assert len(recu) == 1, "aucune notification pour un fill Kraken reussi"
    assert recu[0]["ticket"] == "a26c6df2-2846"
    assert recu[0]["volume"] == 0.0023
    assert recu[0]["destination_id"] == "admin_kraken"


# --- le script shell ne doit plus doubler le message ---------------------

def test_le_script_shell_n_envoie_plus_de_trade_ouvert():
    """Deux messages par trade, dans deux formats, sur deux canaux."""
    import pathlib
    script = (pathlib.Path(__file__).resolve().parents[2]
              / "scripts" / "notify-new-pushes.sh").read_text(encoding="utf-8")
    corps = script.split("set -uo pipefail", 1)[1]  # hors du commentaire d'entete
    assert "🟢" not in corps, "le script emet encore un message de trade ouvert"
    assert "channel=infra" in corps, "les echecs de push relevent de l'infra"
    assert "ok = 0" in corps, "le script doit ne traiter que les pushes non confirmes"


def test_le_script_shell_lit_le_registre_des_destinations():
    """Il recopiait sa propre table de libellés — la source de la dérive."""
    import pathlib
    script = (pathlib.Path(__file__).resolve().parents[2]
              / "scripts" / "notify-new-pushes.sh").read_text(encoding="utf-8")
    assert "destinations_registry" in script
