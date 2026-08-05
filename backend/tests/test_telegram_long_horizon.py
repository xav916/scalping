"""Canal dédié au flux long-horizon (2026-08-05).

`send_setup` est fermé en production (TELEGRAM_SETUP_VERDICTS vide) et le
rallumer produirait ~2000 messages/jour. Le flux long-horizon est minuscule
— quelques setups par jour — et obtient son propre canal.
"""
from datetime import datetime, timezone

import pytest

from backend.models.schemas import (
    PatternDetection, PatternType, TradeDirection, TradeSetup,
)


def _setup(horizon="4h", score=75.0, verdict="TAKE"):
    pattern = PatternDetection(
        pair="XAU/USD", pattern=PatternType.MOMENTUM_UP, confidence=0.9,
        description="momentum haussier", detected_at=datetime.now(timezone.utc),
    )
    s = TradeSetup(
        pair="XAU/USD", direction=TradeDirection.BUY, pattern=pattern,
        entry_price=2000.0, stop_loss=1990.0, take_profit_1=2015.0,
        take_profit_2=2025.0, risk_pips=10.0, reward_pips_1=15.0,
        reward_pips_2=25.0, risk_reward_1=1.5, risk_reward_2=2.5,
        message="test", timestamp=datetime.now(timezone.utc), horizon=horizon,
    )
    s.confidence_score = score
    s.verdict_action = verdict
    s.shadow_system_id = "V2_CORE_LONG_XAUUSD_4H"
    return s


@pytest.mark.asyncio
async def test_un_setup_long_horizon_part(monkeypatch):
    envoyes = []
    from backend.services import telegram_service as tg

    async def _faux(text, parse_mode="HTML"):
        envoyes.append(text)
        return True

    monkeypatch.setattr(tg, "send_sales_text", _faux)
    monkeypatch.setattr(tg, "TELEGRAM_LONG_HORIZON_ENABLED", True, raising=False)
    monkeypatch.setattr(tg, "TELEGRAM_LONG_HORIZON_MIN_CONFIDENCE", 61.0, raising=False)

    assert await tg.send_long_horizon_setup(_setup()) is True
    assert len(envoyes) == 1
    assert "XAU/USD" in envoyes[0]
    assert "4h" in envoyes[0]


@pytest.mark.asyncio
async def test_un_setup_de_scalping_ne_part_pas_par_ce_canal(monkeypatch):
    # Ce canal existe pour le flux long-horizon. Y laisser passer le
    # scalping recreerait les ~2000 messages/jour qu'on evite.
    from backend.services import telegram_service as tg

    monkeypatch.setattr(tg, "TELEGRAM_LONG_HORIZON_ENABLED", True, raising=False)
    assert await tg.send_long_horizon_setup(_setup(horizon="5min")) is False


@pytest.mark.asyncio
async def test_sous_le_seuil_de_confiance_rien_ne_part(monkeypatch):
    from backend.services import telegram_service as tg

    monkeypatch.setattr(tg, "TELEGRAM_LONG_HORIZON_ENABLED", True, raising=False)
    monkeypatch.setattr(tg, "TELEGRAM_LONG_HORIZON_MIN_CONFIDENCE", 61.0, raising=False)
    assert await tg.send_long_horizon_setup(_setup(score=42.0)) is False


@pytest.mark.asyncio
async def test_le_drapeau_coupe_le_canal(monkeypatch):
    from backend.services import telegram_service as tg

    monkeypatch.setattr(tg, "TELEGRAM_LONG_HORIZON_ENABLED", False, raising=False)
    assert await tg.send_long_horizon_setup(_setup()) is False


@pytest.mark.asyncio
async def test_le_canal_global_reste_ferme(monkeypatch):
    # Garde-fou : ce canal ne doit PAS dependre de TELEGRAM_SETUP_VERDICTS,
    # et surtout ne pas le rallumer.
    import inspect

    from backend.services import telegram_service as tg

    src = inspect.getsource(tg.send_long_horizon_setup)
    assert "TELEGRAM_SETUP_VERDICTS" not in src


@pytest.mark.asyncio
async def test_un_reglage_global_hostile_ne_bloque_pas_le_canal(monkeypatch):
    # Complement comportemental au test precedent (qui ne fait qu'une
    # inspection de source, donc ne garantit rien a l'execution). Ici on
    # rend TELEGRAM_SETUP_VERDICTS hostile (liste vide, comme en prod) et on
    # verifie que le canal long-horizon emet quand meme : la preuve qu'il ne
    # depend pas du gate global au moment de s'executer, pas seulement dans
    # son texte source.
    #
    # Patch sur `tg.TELEGRAM_SETUP_VERDICTS` : c'est le nom global du module
    # telegram_service (importe une fois depuis config.settings a l'import),
    # celui que `_should_push_setup` consomme reellement (ligne ~337). Un
    # patch sur config.settings.TELEGRAM_SETUP_VERDICTS ne serait pas vu par
    # une lecture par nom deja liee dans ce module.
    envoyes = []
    from backend.services import telegram_service as tg

    async def _faux(text, parse_mode="HTML"):
        envoyes.append(text)
        return True

    monkeypatch.setattr(tg, "send_sales_text", _faux)
    monkeypatch.setattr(tg, "TELEGRAM_LONG_HORIZON_ENABLED", True, raising=False)
    monkeypatch.setattr(tg, "TELEGRAM_LONG_HORIZON_MIN_CONFIDENCE", 61.0, raising=False)
    monkeypatch.setattr(tg, "TELEGRAM_SETUP_VERDICTS", [], raising=False)

    assert await tg.send_long_horizon_setup(_setup()) is True
    assert len(envoyes) == 1


@pytest.mark.asyncio
async def test_un_echec_d_envoi_ne_leve_pas(monkeypatch):
    from backend.services import telegram_service as tg

    async def _casse(text, parse_mode="HTML"):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(tg, "send_sales_text", _casse)
    monkeypatch.setattr(tg, "TELEGRAM_LONG_HORIZON_ENABLED", True, raising=False)
    monkeypatch.setattr(tg, "TELEGRAM_LONG_HORIZON_MIN_CONFIDENCE", 61.0, raising=False)
    assert await tg.send_long_horizon_setup(_setup()) is False


@pytest.mark.asyncio
async def test_le_message_est_echappe_en_html(monkeypatch):
    # send_sales_text envoie en HTML : un `<` non echappe fait rejeter le
    # message entier par l'API Telegram, silencieusement du point de vue
    # de l'appelant.
    envoyes = []
    from backend.services import telegram_service as tg

    async def _faux(text, parse_mode="HTML"):
        envoyes.append(text)
        return True

    monkeypatch.setattr(tg, "send_sales_text", _faux)
    monkeypatch.setattr(tg, "TELEGRAM_LONG_HORIZON_ENABLED", True, raising=False)
    monkeypatch.setattr(tg, "TELEGRAM_LONG_HORIZON_MIN_CONFIDENCE", 61.0, raising=False)

    s = _setup()
    s.pair = "A<B>&C"
    await tg.send_long_horizon_setup(s)
    assert "<B>" not in envoyes[0]
    assert "&lt;" in envoyes[0] or "&amp;" in envoyes[0]


def test_le_flux_v2_notifie_seulement_les_lignes_nouvelles():
    # `_persist_setup` respecte UNIQUE (system_id, bar_timestamp) et rend
    # True seulement pour une ligne reellement nouvelle. Notifier sur cette
    # valeur suffit — aucun etat de dedup a inventer.
    import inspect

    from backend.services import shadow_v2_core_long

    src = inspect.getsource(shadow_v2_core_long.run_shadow_log)
    assert "send_long_horizon_setup" in src
    i_persist = src.index("if _persist_setup(")
    i_notif = src.index("send_long_horizon_setup")
    assert i_persist < i_notif, "la notification doit suivre la persistance reussie"
