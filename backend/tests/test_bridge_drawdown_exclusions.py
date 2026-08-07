"""Exclusion nominative de tickets du drawdown journalier (2026-08-07).

Décidé par Xavier : la position or tenue à part (sans stop, conservée jusqu'à
son objectif) ne doit pas confisquer le garde-fou des AUTRES trades. Le
drawdown mesure la perte LATENTE — un flottant de -179 EUR sur un compte de
531 EUR bloquait le compte entier, et relever le plafond ne déplaçait que le
seuil (il aurait fallu dépasser 34 %).

⚠️ Ce que ces tests verrouillent, c'est la façon dont l'exclusion peut faire
des dégâts :
  - devenir globale au lieu de rester nominative ;
  - masquer les pertes des autres trades quand la position exclue est en GAIN ;
  - survivre à la fermeture de la position.

`bridge.py` importe MetaTrader5, absent hors du VPS Windows : on charge le
module source isolément plutôt que de l'importer.
"""
import types
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "mt5-bridge" / "bridge.py"


def _charger_flottant_exclu(tickets: set[int]):
    """Extrait `_flottant_exclu` du source, avec la constante voulue.

    On exécute la seule fonction, pas le module : `bridge.py` importe
    MetaTrader5 au chargement. Le corps est copié depuis le source à
    l'exécution, donc un renommage ou une suppression fait échouer le test —
    ce n'est pas une réimplémentation figée.
    """
    src = _SRC.read_text(encoding="utf-8")
    debut = src.index("def _flottant_exclu(")
    fin = src.index("def _parse_trading_hours(")
    module = types.ModuleType("bridge_extrait")
    module.__dict__["DAILY_LOSS_EXCLUDED_TICKETS"] = frozenset(tickets)
    exec(compile(src[debut:fin], str(_SRC), "exec"), module.__dict__)
    return module._flottant_exclu


class _P:
    def __init__(self, ticket, profit):
        self.ticket = ticket
        self.profit = profit


# ── Sans réglage, rien n'est exclu ────────────────────────────────────

def test_aucune_exclusion_par_defaut():
    f = _charger_flottant_exclu(set())
    exclu, vus = f([_P(1353960866, -179.23), _P(1, -5.0)])
    assert exclu == 0.0 and vus == []


def test_un_ticket_non_liste_n_est_pas_exclu():
    """Nominatif : lister un ticket n'ouvre pas la porte aux autres."""
    f = _charger_flottant_exclu({1353960866})
    exclu, vus = f([_P(999, -50.0)])
    assert exclu == 0.0 and vus == []


# ── Le cas réel ───────────────────────────────────────────────────────

def test_la_position_or_est_neutralisee():
    f = _charger_flottant_exclu({1353960866})
    positions = [_P(1353960866, -179.23), _P(777, -4.10)]
    exclu, vus = f(positions)
    assert vus == [1353960866]
    assert exclu == pytest.approx(-179.23)

    # Ce que fait l'appelant, avec les valeurs réelles du 2026-08-07.
    equity, solde_ouverture, plafond_pct = 351.98, 531.21, 10.0
    equity_retenue = equity - exclu
    perte = solde_ouverture - equity_retenue
    limite = solde_ouverture * plafond_pct / 100.0
    assert equity_retenue == pytest.approx(531.21)
    assert perte == pytest.approx(0.0, abs=0.01), "le flottant exclu ne pèse plus"
    assert perte < limite, "le compte doit pouvoir trader"


def test_les_pertes_des_AUTRES_trades_comptent_toujours():
    """Le garde-fou doit continuer à protéger contre ce qu'il surveille."""
    f = _charger_flottant_exclu({1353960866})
    exclu, _ = f([_P(1353960866, -179.23), _P(777, -60.0)])
    equity = 531.21 - 179.23 - 60.0
    perte = 531.21 - (equity - exclu)
    assert perte == pytest.approx(60.0), "seul le flottant des autres subsiste"
    assert perte >= 531.21 * 10.0 / 100.0, "et il doit pouvoir déclencher le blocage"


def test_une_position_exclue_en_GAIN_ne_masque_pas_les_pertes():
    """Le piège symétrique : sans soustraction signée, un gain exclu
    couvrirait les pertes des autres et rendrait le garde-fou inopérant."""
    f = _charger_flottant_exclu({1353960866})
    exclu, _ = f([_P(1353960866, +200.0), _P(777, -60.0)])
    assert exclu == pytest.approx(200.0)
    equity = 531.21 + 200.0 - 60.0
    perte = 531.21 - (equity - exclu)
    assert perte == pytest.approx(60.0), "le gain exclu ne doit rien compenser"


def test_l_exclusion_s_eteint_a_la_fermeture():
    """Aucun état à nettoyer : un ticket fermé n'est plus dans les positions."""
    f = _charger_flottant_exclu({1353960866})
    exclu, vus = f([_P(777, -4.10)])  # l'or n'est plus ouvert
    assert exclu == 0.0 and vus == []


def test_liste_vide_ou_bruitee_n_exclut_rien():
    f = _charger_flottant_exclu(set())
    assert f([_P(1353960866, -179.23)]) == (0.0, [])
