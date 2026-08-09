"""La grille de session est un objet FOREX ; le crypto n'y est pas soumis.

Contexte (2026-08-09). Les trois premiers trades réels de la route Kraken —
ETHFI, SEI, CRV — ont risqué 0,55 % à 0,58 % du portefeuille alors que la
route est armée à 1 %. Reconstruction du calcul, capital 98,70 USD :

    risk_money = capital × 1 % × conf_mult × pnl_mult × session_mult × macro_mult
               = 98,70 × 1 % × ~0,79 × 1,0 × 0,70 × 1,0
               ≈ 0,54 USD

Le 0,70 vient d'``activity_multiplier`` : les trois trades tombaient un
week-end, et le repli crypto du 2026-06-14 rend 0,7 (« équivalent asian »).
Ce 0,7 n'a jamais été une mesure — c'était un pis-aller pour éviter qu'un
multiplicateur de 0,0 ne tue ``risk_money`` et ne bloque l'auto-exécution.
L'hypothèse initialement notée, « granularité du contrat », est fausse :
l'arrondi ROUND_FLOOR du bridge ne coûte que 0,7 %, pas 45 %.

Or la grille (Sydney/Tokyo/London/NY, overlap à 1,2×) décrit les fenêtres de
volume du FOREX. Un perpétuel crypto n'a pas de séance : il cote 24/7. Lui
appliquer la grille taxe 30 % chaque trade de week-end — et la route Kraken
ne trade QUE du crypto, sur des setups journaliers qui tombent n'importe quand.

En l'absence de calibration, la valeur honnête est la neutralité : 1,0, dans
les deux sens. Le crypto perd donc aussi le bonus d'overlap à 1,2×.
"""
from __future__ import annotations

import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.services import session_service

SAMEDI_MIDI = datetime.datetime(2026, 8, 8, 12, 0, tzinfo=datetime.timezone.utc)
DIMANCHE_4H = datetime.datetime(2026, 8, 9, 4, 1, tzinfo=datetime.timezone.utc)
MARDI_ASIE = datetime.datetime(2026, 8, 11, 2, 0, tzinfo=datetime.timezone.utc)
MARDI_OVERLAP = datetime.datetime(2026, 8, 11, 13, 0, tzinfo=datetime.timezone.utc)
MARDI_OFF = datetime.datetime(2026, 8, 11, 6, 30, tzinfo=datetime.timezone.utc)


@pytest.mark.parametrize(
    "dt", [SAMEDI_MIDI, DIMANCHE_4H, MARDI_ASIE, MARDI_OVERLAP, MARDI_OFF]
)
def test_le_crypto_ignore_la_grille_de_session(dt):
    """1,0 à toute heure : ni pénalité de week-end, ni bonus d'overlap.

    ``BTC/USD`` est reconnu crypto par préfixe codé en dur, donc ce test ne
    dépend pas d'``ASSET_CLASS_OVERRIDES`` — contrairement à ETHFI/SEI/CRV.
    """
    assert session_service.activity_multiplier(dt, pair="BTC/USD") == 1.0


def test_le_forex_conserve_la_grille():
    mul = session_service.activity_multiplier
    assert mul(MARDI_OVERLAP, pair="EUR/USD") == 1.2
    assert mul(MARDI_ASIE, pair="EUR/USD") == 0.7
    assert mul(SAMEDI_MIDI, pair="EUR/USD") == 0.0


def test_les_autres_classes_conservent_la_grille():
    """Le métal et l'énergie ferment vraiment le week-end : 0,0 reste juste."""
    mul = session_service.activity_multiplier
    assert mul(SAMEDI_MIDI, pair="XAU/USD") == 0.0
    assert mul(SAMEDI_MIDI, pair="WTI/USD") == 0.0
    assert mul(MARDI_OVERLAP, pair="XAU/USD") == 1.2


def test_sans_paire_le_comportement_est_inchange():
    """Les appelants historiques ne passent pas de paire — ils gardent la grille."""
    mul = session_service.activity_multiplier
    assert mul(SAMEDI_MIDI) == 0.0
    assert mul(MARDI_OVERLAP) == 1.2
    assert mul(MARDI_ASIE) == 0.7


def test_une_paire_inconnue_reste_traitee_en_forex():
    """Pas de repli permissif : un symbole non déclaré crypto garde la grille.

    C'est le mode de défaillance à connaître — ajouter un instrument Kraken
    sans l'inscrire dans ``ASSET_CLASS_OVERRIDES`` le fait retomber en
    « forex », donc 0,0 le week-end, donc ``risk_money = 0``.
    """
    assert session_service.activity_multiplier(SAMEDI_MIDI, pair="ZZZ/USD") == 0.0


def test_le_trade_ethfi_rejoue_atteint_la_cible(tmp_path, monkeypatch):
    """Rejoue le sizing du trade ETHFI du 2026-08-08 23:58 UTC.

    Score 70/100 ⇒ conf_mult 0,786. Sans la taxe de séance, le risque visé
    passe de 0,54 USD (0,55 % du capital) à 0,78 USD (0,79 %), la seule
    modulation restante étant celle de la confiance — ce qui est l'intention.
    """
    from backend.services import macro_alignment, sizing, trade_log_service

    monkeypatch.setattr(trade_log_service, "_DB_PATH", tmp_path / "t.db")
    trade_log_service._init_schema()

    setup = SimpleNamespace(
        pair="BTC/USD", direction="buy", confidence_score=70,
        entry_price=0.3825, stop_loss=0.34446,
    )
    dest = SimpleNamespace(
        destination_id="admin_kraken", bridge_type="kraken",
        trading_capital=98.70, max_notional_leverage=None, capital_mirror=None,
    )

    with patch.object(session_service, "label", return_value="weekend"), \
         patch.object(macro_alignment, "alignment_for",
                      return_value={"multiplier": 1.0, "reasons": []}):
        res = sizing.compute_risk_money(setup, dest)

    assert res["session_mult"] == 1.0
    assert res["conf_mult"] == 0.79
    assert res["risk_money"] == pytest.approx(0.78, abs=0.01)
    # Le rapport au capital est bien celui de la confiance seule.
    assert res["risk_money"] / res["capital"] == pytest.approx(0.0079, abs=0.0002)
