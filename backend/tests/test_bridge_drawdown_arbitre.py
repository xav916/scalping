"""Le bridge lève sa porte de drawdown UNIQUEMENT sur arbitrage (2026-09-04).

Le 04/09 à 16:35 Xavier répond « continue » à l'arbitrage du plafond
journalier. À 16:44 l'ordre `XAG/USD sell` meurt quand même — au bridge :

    "Daily drawdown reached: loss=31.45 >= limit=22.52 (3.0% of 750.50)"

Le bridge tient son propre plafond, calculé sur l'equity et le solde
d'ouverture, et il ignorait tout de la décision de Xavier. Sa réponse
s'arrêtait donc à la couche qui n'exécute pas.

⛔ Ce que ces tests gardent : la porte se lève **si et seulement si** le
drapeau est présent, et **elle seule**. Les autres garde-fous du bridge —
heures de marché, max positions, risque engagé, marge libre — ne bougent pas.
Un drapeau qui les lèverait tous transformerait une décision ponctuelle de
Xavier en désarmement général.

⚠️ `bridge.py` importe MetaTrader5, absent hors du VPS : on extrait la
fonction et on lui fournit ses globaux, comme `test_bridge_risque_engage.py`.
"""
from __future__ import annotations

import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "mt5-bridge" / "bridge.py"


class _Info:
    def __init__(self, equity=719.0, margin_free=680.0, balance=750.5):
        self.equity = equity
        self.margin_free = margin_free
        self.balance = balance


class _FauxMT5:
    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1

    def __init__(self, info, positions=()):
        self._info = info
        self._positions = list(positions)

    def account_info(self):
        return self._info

    def positions_get(self, **kw):
        return self._positions


@pytest.fixture()
def porte():
    """`_check_safety_gates` seule, avec des globaux maîtrisés.

    Le solde d'ouverture est 750,50 € et l'equity 719,05 € : une perte de
    31,45 € contre un plafond de 22,52 € — les chiffres exacts du refus de
    16:44.
    """
    src = _SRC.read_text(encoding="utf-8")
    debut = src.index("def _check_safety_gates(")
    fin = src.index("def _pick_filling_mode(")

    mod = types.ModuleType("bridge_portes")
    mod.__dict__.update({
        "mt5": _FauxMT5(_Info(equity=719.05)),
        "logger": types.SimpleNamespace(
            info=lambda *a, **k: None, warning=lambda *a, **k: None),
        "MAX_DAILY_LOSS_PCT": 3.0,
        "MAX_OPEN_POSITIONS": 10,
        "MAX_RISQUE_ENGAGE_PCT": 0.0,          # portes voisines désarmées :
        "MAX_RISQUE_ENGAGE_OR_ARGENT_PCT": 0.0,  # le sujet est le drawdown
        "TRADING_HOURS_UTC": "",
        "_start_of_day_balance": 750.50,
        "_in_trading_hours": lambda: True,
        "_refresh_start_of_day": lambda: None,
        "_flottant_exclu": lambda positions: (0.0, set()),
        "_controle_risque": lambda *a, **k: (True, ""),
        "_controle_marge": lambda *a, **k: (True, ""),
        # Portes voisines traversées après le drawdown : dedup et marge.
        "datetime": datetime,
        "timezone": timezone,
        "_ouverture_utc": lambda p: None,
        "MARGE_LIBRE_MIN_PCT": 0.0,
        "DEDUP_WINDOW_SEC": 0,
    })
    exec(compile(src[debut:fin], str(_SRC), "exec"), mod.__dict__)
    return mod


_ARBITRE = {"accorde_a": -32.27, "couvre_jusqua": -51.77,
            "repondu_le": "2026-09-04T14:35:12+00:00"}


# ── La porte, sans et avec arbitrage ──────────────────────────────────────

def test_sans_arbitrage_la_porte_refuse_comme_avant(porte):
    """Le comportement du 04/09 à 16:44 — inchangé par défaut."""
    ok, raison = porte._check_safety_gates("XAGUSD", "sell")

    assert ok is False
    assert "Daily drawdown reached" in raison
    assert "31.45" in raison, raison


def test_avec_arbitrage_la_porte_laisse_passer(porte):
    """🔑 La décision de Xavier atteint enfin la couche qui exécute."""
    ok, raison = porte._check_safety_gates(
        "XAGUSD", "sell", drawdown_arbitre=_ARBITRE)

    assert ok is True, raison


def test_un_drapeau_VIDE_ne_leve_rien(porte):
    """⛔ `{}` et `None` ne sont pas des autorisations."""
    for faux in (None, {}):
        ok, raison = porte._check_safety_gates(
            "XAGUSD", "sell", drawdown_arbitre=faux)
        assert ok is False, f"{faux!r} ne doit rien lever"
        assert "Daily drawdown reached" in raison


def test_sous_le_plafond_l_arbitrage_ne_change_RIEN(porte):
    """Un compte qui n'a rien franchi passe, avec ou sans drapeau : le
    dispositif ne doit pas devenir un chemin d'exécution parallèle."""
    porte.mt5 = _FauxMT5(_Info(equity=745.0))       # perte 5,50 € < 22,52 €

    assert porte._check_safety_gates("XAGUSD", "sell")[0] is True
    assert porte._check_safety_gates(
        "XAGUSD", "sell", drawdown_arbitre=_ARBITRE)[0] is True


# ── Elle ne lève QUE cette porte ──────────────────────────────────────────

def test_l_arbitrage_ne_leve_PAS_le_max_positions(porte):
    """⛔ Sinon une réponse ponctuelle deviendrait un désarmement général."""
    porte.MAX_OPEN_POSITIONS = 1
    porte.mt5 = _FauxMT5(_Info(equity=719.05), positions=[object(), object()])

    ok, raison = porte._check_safety_gates(
        "XAGUSD", "sell", drawdown_arbitre=_ARBITRE)

    assert ok is False
    assert "Max open positions" in raison, raison


def test_l_arbitrage_ne_leve_PAS_les_heures_de_marche(porte):
    porte._in_trading_hours = lambda: False

    ok, raison = porte._check_safety_gates(
        "XAGUSD", "sell", drawdown_arbitre=_ARBITRE)

    assert ok is False
    assert "TRADING_HOURS" in raison, raison


def test_l_arbitrage_ne_leve_PAS_un_compte_illisible(porte):
    """Ne pas pouvoir lire le compte n'est pas une autorisation."""
    porte.mt5 = _FauxMT5(None)

    ok, raison = porte._check_safety_gates(
        "XAGUSD", "sell", drawdown_arbitre=_ARBITRE)

    assert ok is False
    assert "account_info" in raison, raison
