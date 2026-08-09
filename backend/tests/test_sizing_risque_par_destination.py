"""Le pourcentage de risque se déclare par destination.

Demande de Xavier le 2026-08-09 : « je veux qu'on puisse ouvrir de plus grosses
positions sur Kraken », sans rien changer sur MT5.

``RISK_PER_TRADE_PCT`` est **global**. Le monter aurait touché ``admin_live``,
où le compte réel n'a que 143,93 € de marge libre — la position or en
immobilisant 177,68 — et où le lot minimum sur-dimensionne déjà l'or. Le bon
levier est donc une déclaration **par destination**, au même endroit que
``max_notional_leverage`` et ``max_correlated_positions``.

⚠️ **Le piège évité, et il est subtil.** ``pair_admission_controller`` calcule
``TRADING_CAPITAL × RISK_PER_TRADE_PCT`` — mais comme **unité de
normalisation**, pas comme décision de sizing : c'est ce qui rend
``pnl_pct = somme(R) × RISK_PER_TRADE_PCT`` indépendant du capital. Y propager
une surcharge par destination déplacerait **rétroactivement** les seuils
d'admission de toutes les paires Kraken déjà mesurées.

> **Une constante utilisée comme UNITÉ ne doit pas suivre un changement de
> POLITIQUE**, même quand les deux portent le même nom.

La surcharge est donc strictement cantonnée à ``compute_risk_money``.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.services import destinations_registry as registry
from backend.services import session_service


def _setup(pair="BTC/USD", score=70):
    return SimpleNamespace(
        pair=pair, direction="buy", confidence_score=score,
        entry_price=100.0, stop_loss=92.41,   # stop journalier mesure 7,59 %
    )


def _dest(destination_id, capital, bridge_type="kraken"):
    return SimpleNamespace(
        destination_id=destination_id, bridge_type=bridge_type,
        trading_capital=capital, max_notional_leverage=None, capital_mirror=None,
    )


@pytest.fixture
def sizing_isole(tmp_path, monkeypatch):
    from backend.services import macro_alignment, sizing, trade_log_service

    monkeypatch.setattr(trade_log_service, "_DB_PATH", tmp_path / "t.db")
    trade_log_service._init_schema()
    ctx = patch.multiple(
        macro_alignment,
        alignment_for=lambda *a, **k: {"multiplier": 1.0, "reasons": []},
    )
    ctx.start()
    # Confiance neutre : on isole l'effet du pourcentage.
    monkeypatch.setattr(sizing, "confidence_multiplier", lambda s: 1.0)
    monkeypatch.setattr(session_service, "activity_multiplier", lambda **k: 1.0)
    yield sizing
    ctx.stop()


# ─── La déclaration ────────────────────────────────────────────────────


def test_seule_kraken_declare_un_pourcentage_propre():
    assert registry.get("admin_kraken").risk_per_trade_pct is not None
    for autre in ("admin_live", "admin_legacy", "admin_binance",
                  "admin_kraken_spot", "admin_kraken_stocks"):
        assert registry.get(autre).risk_per_trade_pct is None, autre


def test_une_destination_inconnue_ne_declare_rien():
    assert registry.risque_par_trade_pct("inconnue") is None
    assert registry.risque_par_trade_pct(None) is None
    assert registry.risque_par_trade_pct("user:2") is None


# ─── L'effet sur le sizing ─────────────────────────────────────────────


def test_kraken_size_sur_son_propre_pourcentage(sizing_isole):
    res = sizing_isole.compute_risk_money(_setup(), _dest("admin_kraken", 100.0))

    attendu = registry.get("admin_kraken").risk_per_trade_pct
    assert res["risk_pct"] == attendu
    assert res["risk_money"] == pytest.approx(100.0 * attendu / 100.0, abs=0.01)


def test_les_autres_destinations_gardent_le_global(sizing_isole):
    from config.settings import RISK_PER_TRADE_PCT

    dest = _dest("admin_live", 321.61, bridge_type="mt5")
    res = sizing_isole.compute_risk_money(_setup("EUR/USD"), dest)

    assert res["risk_pct"] == RISK_PER_TRADE_PCT
    assert res["risk_money"] == pytest.approx(3.22, abs=0.01)


def test_sans_destination_le_global_s_applique(sizing_isole):
    from config.settings import RISK_PER_TRADE_PCT

    res = sizing_isole.compute_risk_money(_setup())
    assert res["risk_pct"] == RISK_PER_TRADE_PCT


def test_le_dict_expose_le_pourcentage_EFFECTIF(sizing_isole):
    """Sans ça, les logs et le payload annonceraient 1 % pour un ordre à 2 %."""
    res = sizing_isole.compute_risk_money(_setup(), _dest("admin_kraken", 100.0))
    assert res["risk_pct"] == registry.get("admin_kraken").risk_per_trade_pct
    assert res["risk_money"] / res["capital"] * 100 == pytest.approx(
        res["risk_pct"], abs=0.05)


def test_capital_indisponible_annonce_quand_meme_le_bon_pourcentage(sizing_isole):
    """Le refus de sizing doit rester lisible : le % annoncé est celui visé."""
    dest = _dest("admin_kraken", None)
    dest.trading_capital = None
    res = sizing_isole.compute_risk_money(_setup(), dest)

    assert res["risk_money"] == 0.0
    assert res["risk_pct"] == registry.get("admin_kraken").risk_per_trade_pct


def test_le_plafond_de_notionnel_mord_toujours(sizing_isole, monkeypatch):
    """Monter le pourcentage ne contourne pas le garde-fou de notionnel."""
    setup = SimpleNamespace(
        pair="BTC/USD", direction="buy", confidence_score=70,
        entry_price=100.0, stop_loss=99.5,   # stop tres serre => notionnel enorme
    )
    res = sizing_isole.compute_risk_money(setup, _dest("admin_kraken", 100.0))

    assert res["notionnel_plafonne"] is True
    # `notionnel` expose ce qu'il AURAIT valu ; c'est le risque qui est réduit.
    # Le contrat est donc : risque × entrée / distance == plafond.
    assert res["risk_money"] * 100.0 / 0.5 == pytest.approx(
        res["plafond_notionnel"], abs=0.5)


# ─── Le piège : l'unité de normalisation ne doit PAS suivre ────────────


def test_l_unite_d_admission_reste_sur_le_global():
    """``pair_admission_controller`` normalise, il ne dimensionne pas.

    Si cette valeur suivait la surcharge Kraken, tous les `pnl_pct` déjà
    mesurés changeraient de sens et les seuils de promotion bougeraient
    rétroactivement.
    """
    from config.settings import RISK_PER_TRADE_PCT, TRADING_CAPITAL
    from backend.services import pair_admission_controller as pac

    assert pac._r_unit_eur() == pytest.approx(
        TRADING_CAPITAL * RISK_PER_TRADE_PCT / 100.0)
