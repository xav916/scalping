"""Le pont doit publier l'ETAT de son plafond, pas seulement son REGLAGE.

⛔ **Le 2026-10-07.** `/health` publiait `max_daily_loss_pct: 3.0` — le
réglage — mais rien sur l'endroit où le compte en était. Le radar ne pouvait
donc pas savoir si une autorisation « continue » couvrait encore la perte que
le COURTIER compte, et il n'avait le choix qu'entre deviner et se taire.

Les deux mesures diffèrent par nature :

| | mesure | ce jour-là |
|---|---|---|
| radar | somme des clôtures en base (`pnl`) | −16,45 € |
| **pont** | solde d'ouverture − equity (flottant et frais inclus) | **19,77 €** |

> Un garde-fou dont on lit le réglage mais jamais l'état est un garde-fou dont
> on ne sait pas s'il va mordre.

🔑 **Une seule arithmétique.** `_perte_journaliere()` sert la PORTE et
`/health` : deux calculs du même drawdown qui divergeraient seraient
exactement la faille que ce dispositif prétend fermer.

⚠️ `/health` ne doit JAMAIS tomber — le moniteur d'infra et le radar le
consomment. Un compte illisible fait disparaître les champs, pas la réponse.
"""
from __future__ import annotations

import types
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "mt5-bridge" / "bridge.py"

_REGLAGES = {
    "PAPER_MODE": False, "MT5_SERVER": "ICMarketsEU-MT5-5",
    "MT5_LOGIN": 13137475, "MAX_LOT": 0.02,
    "MAX_LOT_PER_CLASS": {"forex": 0.02}, "MAX_DAILY_LOSS_PCT": 3.0,
    # Plafond PAR PAIRE (2026-10-07) : l'or a son budget, le reste au defaut.
    "DAILY_LOSS_PCT_PAR_SYMBOLE": {"XAU": 10.0, "GOLD": 10.0},
    "DAILY_LOSS_PCT_PAIRE_DEFAUT": 3.0,
    "MAX_OPEN_POSITIONS": 10, "DEDUP_WINDOW_SEC": 3600,
    "MAX_RISQUE_ENGAGE_PCT": 5.0, "MAX_RISQUE_ENGAGE_OR_ARGENT_PCT": 15.0,
    "MARGE_LIBRE_MIN_PCT": 30.0, "SLTP_GUARD_ENABLED": True,
    "SLTP_GUARD_ACTIVATED_AT": "2026-08-28T21:00:00+00:00",
    "SLTP_GUARD_FROZEN_TICKETS": frozenset(), "DEVIATION_POINTS": 20,
    "TRAIL_DISTANCE_POINTS": 0, "PARTIAL_CLOSE_PCT": 50.0,
    "EQUILIBRE_AUTO_ENABLED": True, "EQUILIBRE_MARGE_R": 0.4,
    "EQUILIBRE_MARGE_SIGMA": 1.0, "TRADING_HOURS_UTC": "",
    "DAILY_LOSS_EXCLUDED_TICKETS": frozenset(),
    "SOURCE_SHA": "abc123def456",
    "DEMARRE_A": "2026-09-19T03:43:56+00:00",
}


class _Info:
    def __init__(self, equity):
        self.equity = equity
        self.balance = 595.81
        self.margin_free = 538.0


def _module(equity=576.04, solde_ouverture=595.81, positions=(), **surcharges):
    """`_perte_journaliere()` et `health()`, extraites du source réel."""
    src = _SRC.read_text(encoding="utf-8")
    mod = types.ModuleType("bridge_sante")
    mod.__dict__.update(_REGLAGES)
    mod.__dict__.update({
        "jsonify": lambda d: d,
        "ensure_mt5_connected": lambda: True,
        "logger": types.SimpleNamespace(info=lambda *a, **k: None,
                                        warning=lambda *a, **k: None),
        "mt5": types.SimpleNamespace(
            __version__="5.0.5735",
            account_info=lambda: _Info(equity) if equity is not None else None,
            positions_get=lambda **kw: list(positions)),
        "_start_of_day_balance": solde_ouverture,
        "_refresh_start_of_day": lambda: None,
        "_flottant_exclu": lambda p: (0.0, set()),
    })
    mod.__dict__.update(surcharges)
    for depart, arrivee in (("def _perte_journaliere(", "def _check_safety_gates("),
                            ("def health():", '@app.route("/account"')):
        bout = src[src.index(depart):src.index(arrivee)]
        exec(compile(bout, str(_SRC), "exec"), mod.__dict__)
    return mod


def test_la_perte_du_jour_et_son_plafond_sont_PUBLIES():
    """595,81 − 576,04 = 19,77 € perdus contre 3 % = 17,87 € : les chiffres
    exacts du refus qui a coupé la journée du 07/10."""
    g = _module().health()["garde_fous"]
    assert g["daily_loss"] == 19.77
    assert g["daily_loss_limit"] == 17.87


def test_une_journee_GAGNANTE_publie_une_perte_NEGATIVE():
    """Le signe doit rester lisible : +12 € gagnés = perte de −12."""
    g = _module(equity=607.81).health()["garde_fous"]
    assert g["daily_loss"] == -12.0


def test_le_flottant_EXCLU_est_retire_comme_dans_la_porte():
    g = _module(_flottant_exclu=lambda p: (-5.0, {1360532067})).health()["garde_fous"]
    # equity retenue = 576,04 − (−5,00) = 581,04  →  perte 14,77
    assert g["daily_loss"] == 14.77


def test_sans_solde_d_ouverture_on_ne_publie_AUCUN_chiffre():
    """⛔ Se taire plutôt qu'inventer : le radar lit l'absence comme
    « applique ton garde-fou »."""
    g = _module(solde_ouverture=None).health()["garde_fous"]
    assert "daily_loss" not in g
    assert g["max_daily_loss_pct"] == 3.0


def test_un_compte_illisible_ne_fait_PAS_tomber_health():
    """⚠️ Le moniteur d'infra et le radar consomment cette réponse."""
    sante = _module(equity=None).health()
    assert sante["ok"] is True
    assert "daily_loss" not in sante["garde_fous"]


def test_les_champs_historiques_ne_bougent_pas():
    sante = _module().health()
    assert sante["source_sha"] == "abc123def456"
    assert sante["login"] == 13137475
    assert sante["garde_fous"]["marge_libre_min_pct"] == 30.0
