"""La whitelist de patterns doit pouvoir differer selon la paire ET l'horizon.

Mesure du 2026-08-11 : **l'or produit 76 setups 4h en 30 jours, dont ZERO
dispatchable.** Son jeu de patterns au 4h — `momentum_up`, `engulfing_bullish`,
`breakout_up` — ne contient aucun `range_bounce`, et le bridge n'accepte que
`range_bounce_up/down`.

L'instrument qui porte **87,6 % du resultat** est donc totalement absent du seul
horizon qui paie ses frais.

⚠️ D'ou vient la whitelist : d'un edge `range_bounce` de +0,129 R valide hors
echantillon **sur le flux 5 MINUTES** (2026-08-04). Le controle aleatoire du
lendemain a montre que ce +0,129 etait du **beta de marche**, pas de la
selection (Δ = +0,004 R sur 29 000 trades). La regle survit a sa justification
— et elle est appliquee a un horizon pour lequel elle n'a jamais ete testee.

⚠️ Ce qui n'est PAS corrige ici, volontairement : le **petrole 4h est mesure a
−0,128 R, negatif etabli**. Il reste ferme. Seul l'or est ouvert — decision de
Xavier, prise en connaissance du fait que les metaux 4h sont a −0,045 R,
intervalle [−0,100 ; +0,012], donc **non tranches**.

La cascade reprend l'idiome deja en place pour l'admission :
(paire, horizon) -> destination -> global.
"""
import ast
from pathlib import Path

import pytest

from backend.services import mt5_bridge


class _Setup:
    def __init__(self, pair, horizon, pattern):
        self.pair = pair
        self.horizon = horizon
        self.signal_pattern = pattern


@pytest.fixture
def surcharges(monkeypatch):
    def _poser(config):
        monkeypatch.setattr(mt5_bridge, "MT5_BRIDGE_PATTERN_OVERRIDES", config)
    return _poser


OR_4H = {"XAU/USD": {"4h": ["momentum_up", "engulfing_bullish",
                           "breakout_up", "range_bounce_up", "range_bounce_down"]}}


# --- la surcharge ----------------------------------------------------------

@pytest.mark.parametrize("pattern", ["momentum_up", "engulfing_bullish", "breakout_up"])
def test_l_or_en_4h_accepte_ses_propres_patterns(surcharges, pattern):
    surcharges(OR_4H)
    assert mt5_bridge._patterns_autorises(
        _Setup("XAU/USD", "4h", pattern), None) == set(OR_4H["XAU/USD"]["4h"])


def test_l_or_en_5min_reste_sur_la_regle_globale(surcharges):
    """La surcharge est par HORIZON : le 5 min de l'or garde la whitelist
    d'origine, qui a ete validee sur ce pas de temps."""
    surcharges(OR_4H)
    assert mt5_bridge._patterns_autorises(
        _Setup("XAU/USD", "5min", "momentum_up"),
        None) == mt5_bridge.MT5_BRIDGE_ALLOWED_PATTERNS


def test_le_petrole_en_4h_reste_ferme(surcharges):
    """⚠️ WTI 4h est mesure a −0,128 R, NEGATIF ETABLI. Ne pas l'ouvrir."""
    surcharges(OR_4H)
    assert mt5_bridge._patterns_autorises(
        _Setup("WTI/USD", "4h", "momentum_up"),
        None) == mt5_bridge.MT5_BRIDGE_ALLOWED_PATTERNS


def test_une_paire_non_surchargee_garde_la_regle_globale(surcharges):
    surcharges(OR_4H)
    assert mt5_bridge._patterns_autorises(
        _Setup("EUR/USD", "4h", "momentum_up"),
        None) == mt5_bridge.MT5_BRIDGE_ALLOWED_PATTERNS


# --- la cascade ------------------------------------------------------------

def test_la_surcharge_prime_sur_la_destination(surcharges):
    """Ordre : (paire, horizon) -> destination -> global. Le plus specifique
    gagne, comme pour la resolution d'admission."""
    surcharges(OR_4H)
    class _Dest:
        allowed_patterns = frozenset({"range_bounce_up"})
    assert mt5_bridge._patterns_autorises(
        _Setup("XAU/USD", "4h", "momentum_up"),
        _Dest()) == set(OR_4H["XAU/USD"]["4h"])


def test_sans_surcharge_la_destination_prime_sur_le_global(surcharges):
    surcharges({})
    class _Dest:
        allowed_patterns = frozenset({"pin_bar_down"})
    assert mt5_bridge._patterns_autorises(
        _Setup("XAU/USD", "4h", "momentum_up"), _Dest()) == frozenset({"pin_bar_down"})


# --- ne jamais bloquer plus qu'avant ---------------------------------------

@pytest.mark.parametrize("mauvais", [
    None, "", [], "XAU/USD", {"XAU/USD": "4h"}, {"XAU/USD": {"4h": "momentum_up"}},
    {"XAU/USD": {"4h": []}},
])
def test_configuration_illisible_retombe_sur_le_global(surcharges, mauvais):
    """⚠️ Une surcharge mal ecrite doit retomber sur la regle existante, jamais
    produire un ensemble vide — qui bloquerait TOUT sur cette paire."""
    surcharges(mauvais)
    assert mt5_bridge._patterns_autorises(
        _Setup("XAU/USD", "4h", "range_bounce_up"),
        None) == mt5_bridge.MT5_BRIDGE_ALLOWED_PATTERNS


def test_setup_sans_horizon_retombe_sur_le_global(surcharges):
    surcharges(OR_4H)
    s = _Setup("XAU/USD", None, "momentum_up")
    assert mt5_bridge._patterns_autorises(s, None) == mt5_bridge.MT5_BRIDGE_ALLOWED_PATTERNS


# --- branchement -----------------------------------------------------------

def test_la_resolution_est_utilisee_par_la_chaine():
    src = Path(mt5_bridge.__file__).read_text(encoding="utf-8")
    arbre = ast.parse(src)
    chaine = next(n for n in ast.walk(arbre)
                  if isinstance(n, ast.FunctionDef) and n.name == "_check_rejection")
    appels = {n.func.id for n in ast.walk(chaine)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_patterns_autorises" in appels
