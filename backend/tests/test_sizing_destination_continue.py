"""La 6e porte : une destination qui ne cote QUE du 24/7 le déclare déjà.

Contexte (2026-08-09). Le crypto échappe désormais à la grille de séance
(cf. ``test_sizing_session_crypto``), mais la reconnaissance passait par
``asset_class_for``, donc par une liste de préfixes codée en dur **plus**
``ASSET_CLASS_OVERRIDES`` du ``.env``. Un instrument Kraken ajouté sans cette
déclaration retombait en « forex » ⇒ multiplicateur 0,0 le week-end ⇒
``risk_money = 0`` ⇒ ``qty <= 0`` ⇒ rejet, sous un motif faux. Et l'échec ne
se produisait **que** le week-end.

C'était une sixième chose à ne pas oublier en ajoutant un instrument, après
les cinq de ``project_kraken_quatre_portes_2026_08_08``.

Or ``destinations_registry`` déclare déjà ``asset_classes={"crypto"}`` sur
``admin_kraken``, ``admin_kraken_spot`` et ``admin_binance``. Cette
déclaration-là est la bonne autorité : elle est une propriété du **lieu de
cotation**, pas de la chaîne du symbole. Un perpétuel listé sur Kraken
Futures cote 24/7 quel que soit son nom.

La porte se ferme donc sans rien ajouter à déclarer : ``cote_en_continu`` est
**dérivé** d'``asset_classes``. Rien de neuf à remplir, donc rien de neuf à
oublier.
"""
from __future__ import annotations

import datetime
import logging
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.services import destinations_registry as registry
from backend.services import session_service

SAMEDI_MIDI = datetime.datetime(2026, 8, 8, 12, 0, tzinfo=datetime.timezone.utc)
MARDI_OVERLAP = datetime.datetime(2026, 8, 11, 13, 0, tzinfo=datetime.timezone.utc)

# Symbole volontairement inconnu de la liste de préfixes ET des overrides :
# il représente l'instrument crypto ajouté sans déclaration.
NON_DECLARE = "ZZZ/USD"


# ─── Le registre sait déjà ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "dest_id", ["admin_kraken", "admin_kraken_spot", "admin_binance"]
)
def test_les_destinations_crypto_cotent_en_continu(dest_id):
    assert registry.cote_en_continu(dest_id) is True


@pytest.mark.parametrize(
    "dest_id",
    ["admin_live", "admin_legacy", "admin_kraken_stocks", "user:2", "inconnue", None],
)
def test_les_autres_destinations_ne_cotent_pas_en_continu(dest_id):
    """Défaut sûr : ne rien supposer. Une destination multi-classe (MT5) ou
    inconnue garde la grille — c'est le repli conservateur."""
    assert registry.cote_en_continu(dest_id) is False


# ─── La porte fermée ───────────────────────────────────────────────────


def test_un_instrument_non_declare_est_quand_meme_dimensionne():
    """LE test de la porte : symbole inconnu + destination Kraken = 1,0.

    Avant, ce cas rendait 0,0 le week-end, donc un risque nul et un ordre
    jamais envoyé.
    """
    mult = session_service.activity_multiplier(
        SAMEDI_MIDI, pair=NON_DECLARE, marche_continu=True
    )
    assert mult == 1.0


def test_un_instrument_non_declare_reste_bloque_hors_destination_continue():
    """Sans destination continue, le repli strict demeure : on ne devine pas
    qu'un symbole inconnu est du crypto."""
    mult = session_service.activity_multiplier(SAMEDI_MIDI, pair=NON_DECLARE)
    assert mult == 0.0


def test_la_declaration_oubliee_est_signalee(caplog):
    """La porte est fermée, mais l'oubli reste dit — sinon on l'apprend le
    jour où un AUTRE consommateur d'``asset_class_for`` en dépend."""
    with caplog.at_level(logging.WARNING, logger="backend.services.session_service"):
        session_service.activity_multiplier(
            SAMEDI_MIDI, pair=NON_DECLARE, marche_continu=True
        )
    assert any(
        NON_DECLARE in r.message and "ASSET_CLASS_OVERRIDES" in r.message
        for r in caplog.records
    )


def test_un_instrument_bien_declare_ne_declenche_aucune_alerte(caplog):
    with caplog.at_level(logging.WARNING, logger="backend.services.session_service"):
        session_service.activity_multiplier(
            SAMEDI_MIDI, pair="BTC/USD", marche_continu=True
        )
    assert not caplog.records


def test_marche_continu_neutralise_aussi_le_bonus_overlap():
    """Neutralité dans les deux sens, comme pour le crypto reconnu."""
    mult = session_service.activity_multiplier(
        MARDI_OVERLAP, pair=NON_DECLARE, marche_continu=True
    )
    assert mult == 1.0


# ─── Le raccordement dans le sizing ────────────────────────────────────


def _dest(destination_id: str, capital: float = 98.70):
    return SimpleNamespace(
        destination_id=destination_id, bridge_type="kraken",
        trading_capital=capital, max_notional_leverage=None, capital_mirror=None,
    )


def test_compute_risk_money_lit_la_destination(tmp_path, monkeypatch):
    """Bout en bout : instrument non déclaré, destination Kraken, week-end.

    Le risque doit être celui de la confiance seule, pas zéro.
    """
    from backend.services import macro_alignment, sizing, trade_log_service

    monkeypatch.setattr(trade_log_service, "_DB_PATH", tmp_path / "t.db")
    trade_log_service._init_schema()

    setup = SimpleNamespace(
        pair=NON_DECLARE, direction="buy", confidence_score=70,
        entry_price=0.3825, stop_loss=0.34446,
    )
    with patch.object(session_service, "label", return_value="weekend"), \
         patch.object(macro_alignment, "alignment_for",
                      return_value={"multiplier": 1.0, "reasons": []}):
        res = sizing.compute_risk_money(setup, _dest("admin_kraken"))

    assert res["session_mult"] == 1.0
    assert res["risk_money"] == pytest.approx(0.78, abs=0.01)


def test_compute_risk_money_garde_la_grille_sur_mt5(tmp_path, monkeypatch):
    """Une destination MT5 multi-classe n'est pas continue : le forex reste
    à 0,0 le week-end, comme avant."""
    from backend.services import macro_alignment, sizing, trade_log_service

    monkeypatch.setattr(trade_log_service, "_DB_PATH", tmp_path / "t.db")
    trade_log_service._init_schema()

    setup = SimpleNamespace(
        pair="EUR/USD", direction="buy", confidence_score=90,
        entry_price=1.1000, stop_loss=1.0950,
    )
    dest = _dest("admin_live")
    dest.bridge_type = "mt5"
    with patch.object(session_service, "label", return_value="weekend"), \
         patch.object(macro_alignment, "alignment_for",
                      return_value={"multiplier": 1.0, "reasons": []}):
        res = sizing.compute_risk_money(setup, dest)

    assert res["session_mult"] == 0.0
    assert res["risk_money"] == 0.0


# ─── Le motif de refus ne devine plus ──────────────────────────────────


def test_le_motif_de_refus_nomme_la_vraie_cause():
    """« qty<=0, likely sl==entry » était une conjecture écrite en dur.

    Elle était fausse chaque fois que la cause venait du sizing — et un motif
    faux coûte plus cher qu'un motif absent : il envoie chercher ailleurs.
    """
    from backend.services.sizing import raison_du_refus

    setup = SimpleNamespace(entry_price=0.3825, stop_loss=0.34446)

    capital_absent = {"risk_money": 0.0, "capital": None, "session_mult": 0.0}
    assert "capital" in raison_du_refus(capital_absent, setup)

    seance_nulle = {"risk_money": 0.0, "capital": 98.7, "session_mult": 0.0}
    assert "séance" in raison_du_refus(seance_nulle, setup)

    stop_colle = SimpleNamespace(entry_price=0.3825, stop_loss=0.3825)
    distance_nulle = {"risk_money": 0.55, "capital": 98.7, "session_mult": 1.0}
    assert "stop" in raison_du_refus(distance_nulle, stop_colle)
