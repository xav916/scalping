"""La ligne d'audit d'une fermeture doit porter la cause donnée par MT5.

Défaut du 2026-08-17. `_log_closed_position` itère les deals de la position,
a `d.reason` sous la main — et ne l'écrit pas. La ligne d'audit part donc
SANS cause. Côté radar, le chemin `/audit` arrive le premier, ne trouve rien,
et **devine** par proximité de prix : trois clôtures décidées à la main par
Xavier ont été créditées au stop suiveur, précisément le mécanisme désarmé le
08-11 pour destruction de valeur.

Le correctif du 08-17 (`9c58322`) a colmaté côté radar, en allant demander la
cause au bridge avant d'écrire. Ces tests-ci verrouillent la source : quand le
bridge portera la cause dans son audit, l'aller-retour HTTP disparaîtra de
lui-même.

`bridge.py` importe MetaTrader5, absent hors du VPS Windows : on charge les
seules fonctions voulues plutôt que d'importer le module.
Cf. [[project_close_reason_devinee_2026_08_17]].
"""
import types
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "mt5-bridge" / "bridge.py"


class _FauxMT5:
    """Le strict nécessaire pour dérouler `_log_closed_position`."""
    DEAL_ENTRY_OUT = 1
    DEAL_ENTRY_OUT_BY = 2
    DEAL_REASON_CLIENT = 3
    DEAL_REASON_SL = 4
    DEAL_REASON_TP = 5
    DEAL_REASON_EXPERT = 6

    def __init__(self, deals):
        self._deals = deals

    def history_deals_get(self, position=None):
        return self._deals


class _Deal:
    def __init__(self, entry, reason, price=4420.0, profit=12.0):
        self.entry = entry
        self.reason = reason
        self.price = price
        self.profit = profit
        self.swap = 0.0
        self.commission = 0.0
        self.time = 1_755_000_000
        self.symbol = "XAUUSD"
        self.volume = 0.01


def _charger(deals):
    """Extrait `_log_closed_position` + `_deal_reason_label` du source.

    Le corps est lu dans le fichier à l'exécution : un renommage ou une
    suppression fait échouer le test, ce n'est pas une réimplémentation figée.
    """
    src = _SRC.read_text(encoding="utf-8")
    morceaux = (
        src[src.index("def _log_closed_position("):src.index("def _position_monitor_loop(")]
        + "\n\n"
        + src[src.index("def _deal_reason_label("):src.index("@app.route(\"/deals\"")]
    )
    module = types.ModuleType("bridge_extrait")
    ecrites = []
    module.__dict__.update({
        "mt5": _FauxMT5(deals),
        "logger": types.SimpleNamespace(
            info=lambda *a, **k: None, warning=lambda *a, **k: None
        ),
        "_db_log_order": lambda **champs: ecrites.append(champs),
    })
    exec(compile(morceaux, str(_SRC), "exec"), module.__dict__)
    return module._log_closed_position, ecrites


def test_une_fermeture_a_la_main_est_auditee_MANUAL():
    """Le cas qui a coûté : trois sorties manuelles gagnantes du 08-17.

    Sans cause dans l'audit, le radar les devinait `TRAILING_SL` — et le
    `COALESCE` sur `close_reason` interdisait ensuite au réconciliateur d'y
    poser le `MANUAL` que le courtier donnait pourtant.
    """
    log, ecrites = _charger([
        _Deal(entry=0, reason=_FauxMT5.DEAL_REASON_EXPERT),          # entrée
        _Deal(entry=_FauxMT5.DEAL_ENTRY_OUT, reason=_FauxMT5.DEAL_REASON_CLIENT),
    ])

    log(84570193)

    assert len(ecrites) == 1
    assert ecrites[0]["close_reason"] == "MANUAL"


def test_un_stop_touche_est_auditee_SL():
    log, ecrites = _charger([
        _Deal(entry=_FauxMT5.DEAL_ENTRY_OUT, reason=_FauxMT5.DEAL_REASON_SL),
    ])

    log(1)

    assert ecrites[0]["close_reason"] == "SL"


def test_une_cause_illisible_n_est_pas_inventee():
    """Un deal sans `reason` exploitable ne doit pas produire d'étiquette.

    Écrire une cause fausse est pire que n'en écrire aucune : le radar a une
    heuristique de repli, mais rien ne rattrape une cause affirmée à tort.
    Cf. [[feedback_detection_par_absence]].
    """
    log, ecrites = _charger([
        _Deal(entry=_FauxMT5.DEAL_ENTRY_OUT, reason=None),
    ])

    log(2)

    assert ecrites[0].get("close_reason") in (None, "")
