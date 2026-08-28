"""L'heure du courtier n'est pas l'heure UTC (2026-08-28).

`p.time` d'une position MT5 est exprimé en heure **serveur** — UTC+3 chez IC
Markets et Pepperstone — et MT5 ne le signale nulle part. Le comparer à
`datetime.now(timezone.utc)` rendait un âge faux de **−10 800 s**, donc négatif
pendant trois heures, donc toujours sous n'importe quelle fenêtre.

Mesuré sur 30 jours de `bridge_audit.db` avant correction :

| | refus « Duplicate » | vrais doublons (< 5 min) | **sur-blocages** |
|---|---|---|---|
| démo | 49 (14 % des tentatives) | 8 | **41** |
| réel | 76 (21 %) | 7 | **69** |

Âge réel médian des positions qui bloquaient : 24 min (démo), 55 min (réel).
La fenêtre annoncée valait 300 s ; la fenêtre réelle valait **3 h 05**.

⛔ Le même `p.time` alimentait deux autres lecteurs, et l'erreur y penchait
dans l'AUTRE sens : `_sltp_guard_eligible` datait les positions trois heures
trop tard, donc une position ouverte jusqu'à 3 h **avant** l'activation du
garde-fou passait pour postérieure et devenait éligible — fail-**open** sur un
garde-fou. Et `/positions` publiait des ouvertures 3 h dans le futur sous une
étiquette `utc`.

> **Deux horloges qui se ressemblent ne sont pas la même horloge.** L'écart
> valait un multiple exact de l'heure : parfaitement plausible, donc
> parfaitement invisible.

`bridge.py` importe MetaTrader5 ; on charge le module et on neutralise les
portes sans rapport, comme `test_bridge_risque_engage`.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "mt5-bridge" / "bridge.py"

DECALAGE = 10800.0          # UTC+3, mesuré en production le 2026-08-28


@pytest.fixture()
def bridge(monkeypatch):
    """Instance fraîche : le module porte de l'état mutable (cache du décalage)."""
    nom = f"_bridge_horloge_{id(monkeypatch)}"
    spec = importlib.util.spec_from_file_location(nom, _SRC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nom] = mod
    ancien = os.getcwd()
    os.chdir(_SRC.parent)          # bridge.log est ouvert en chemin relatif
    try:
        spec.loader.exec_module(mod)
    finally:
        os.chdir(ancien)
    yield mod
    sys.modules.pop(nom, None)


class _Pos:
    def __init__(self, ticket, symbol, time_serveur, type_=0):
        self.ticket = ticket
        self.symbol = symbol
        self.time = time_serveur
        self.type = type_
        self.price_open = 1.36
        self.sl = 1.35
        self.volume = 0.01


class _Compte:
    equity = 552.0
    margin_free = 443.0


def _maintenant() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _serveur(age_reel_sec: int) -> int:
    """`p.time` tel que le courtier le rend pour une position de cet âge."""
    return int(_maintenant() - age_reel_sec + DECALAGE)


def _armer(bridge, monkeypatch, positions=()):
    """Neutralise les portes sans rapport, garde l'anti-doublon."""
    monkeypatch.setattr(bridge, "_in_trading_hours", lambda: True)
    monkeypatch.setattr(bridge, "_refresh_start_of_day", lambda: None)
    monkeypatch.setattr(bridge, "_start_of_day_balance", None)
    monkeypatch.setattr(bridge, "MAX_OPEN_POSITIONS", 10)
    monkeypatch.setattr(bridge.mt5, "account_info", lambda: _Compte())
    monkeypatch.setattr(bridge.mt5, "positions_get", lambda: list(positions))
    monkeypatch.setattr(bridge, "_decalage_serveur_courant", lambda: DECALAGE)


# ── Dater une position ─────────────────────────────────────────────────────

def test_l_ouverture_est_ramenee_en_UTC(bridge, monkeypatch):
    monkeypatch.setattr(bridge, "_decalage_serveur_courant", lambda: DECALAGE)
    p = _Pos(1, "GBPUSD", _serveur(7200))
    assert bridge._ouverture_utc(p) == pytest.approx(_maintenant() - 7200, abs=2)


def test_decalage_non_mesurable_rend_None_PAS_l_heure_brute(bridge, monkeypatch):
    """⛔ Rendre `p.time` tel quel serait présenter de l'heure serveur comme de
    l'UTC — exactement le défaut qu'on répare."""
    monkeypatch.setattr(bridge, "_decalage_serveur_courant", lambda: None)
    assert bridge._ouverture_utc(_Pos(1, "GBPUSD", _serveur(7200))) is None


def test_un_zero_de_decalage_reste_une_MESURE(bridge, monkeypatch):
    """0 est une valeur qui a du sens (courtier en UTC). Le confondre avec
    « inconnu » est ce qui a laissé vivre les 3 h."""
    monkeypatch.setattr(bridge, "_decalage_serveur_courant", lambda: 0.0)
    p = _Pos(1, "GBPUSD", _maintenant() - 60)
    assert bridge._ouverture_utc(p) == pytest.approx(_maintenant() - 60, abs=2)


def test_une_position_sans_heure_est_indatable(bridge, monkeypatch):
    monkeypatch.setattr(bridge, "_decalage_serveur_courant", lambda: DECALAGE)
    assert bridge._ouverture_utc(_Pos(1, "GBPUSD", 0)) is None


def test_le_decalage_n_est_mesure_qu_une_fois(bridge, monkeypatch):
    """Il est lu sur le chemin d'un ordre : deux appels MT5 par décision
    seraient payés à chaque signal."""
    appels = []

    def _mesure():
        appels.append(1)
        return DECALAGE

    monkeypatch.setattr(bridge, "_decalage_serveur_sec", _mesure)
    monkeypatch.setattr(bridge, "_decalage_mesure", None)
    assert bridge._decalage_serveur_courant() == DECALAGE
    assert bridge._decalage_serveur_courant() == DECALAGE
    assert len(appels) == 1


# ── L'anti-doublon, branché ────────────────────────────────────────────────

def test_la_fenetre_par_defaut_vaut_UNE_HEURE(bridge):
    """Décidée le 28/08. Revenir à 300 s en corrigeant la pendule aurait été
    un desserrage de 37× que personne n'avait choisi."""
    assert bridge.DEDUP_WINDOW_SEC == 3600


def test_une_position_de_DEUX_HEURES_ne_bloque_plus(bridge, monkeypatch):
    """⛔ LE cas des 110 sur-blocages : âge réel 2 h, âge calculé −1 h."""
    ouverte = _Pos(11, "XTIUSD", _serveur(7200))
    _armer(bridge, monkeypatch, positions=[ouverte])
    ok, raison = bridge._check_safety_gates("XTIUSD", "buy")
    assert ok is True, raison


def test_une_position_de_DIX_MINUTES_bloque_toujours(bridge, monkeypatch):
    ouverte = _Pos(12, "XTIUSD", _serveur(600))
    _armer(bridge, monkeypatch, positions=[ouverte])
    ok, raison = bridge._check_safety_gates("XTIUSD", "buy")
    assert ok is False
    assert "Duplicate" in raison
    # L'âge annoncé est le VRAI, pas celui d'une horloge décalée.
    assert "age 6" in raison or "age 59" in raison, raison


def test_le_SENS_oppose_n_est_pas_un_doublon(bridge, monkeypatch):
    ouverte = _Pos(13, "XTIUSD", _serveur(600), type_=0)   # buy
    _armer(bridge, monkeypatch, positions=[ouverte])
    ok, raison = bridge._check_safety_gates("XTIUSD", "sell")
    assert ok is True, raison


def test_une_position_INDATABLE_bloque(bridge, monkeypatch):
    """⛔ Fail-closed : un âge inventé laisserait passer un vrai doublon."""
    ouverte = _Pos(14, "XTIUSD", _serveur(7200))
    _armer(bridge, monkeypatch, positions=[ouverte])
    monkeypatch.setattr(bridge, "_decalage_serveur_courant", lambda: None)
    ok, raison = bridge._check_safety_gates("XTIUSD", "buy")
    assert ok is False
    assert "indatable" in raison


# ── Les deux autres lecteurs du meme `p.time` ─────────────────────────────

def test_le_garde_fou_SLTP_refuse_une_position_indatable(bridge, monkeypatch):
    """⛔ Ici l'erreur penchait en fail-OPEN : trois heures d'avance faisaient
    passer une position antérieure à l'activation pour postérieure."""
    monkeypatch.setattr(bridge, "_SLTP_GUARD_ACTIVATED_AT_EPOCH", 1_700_000_000)
    eligible, raison = bridge._sltp_guard_eligible(ticket=1,
                                                   position_open_epoch=None)
    assert eligible is False
    assert "indatable" in raison


def test_le_garde_fou_SLTP_juge_sur_l_heure_CORRIGEE(bridge, monkeypatch):
    """Ouverte 1 h avant l'activation : en heure serveur elle paraît 2 h
    APRÈS, et deviendrait éligible."""
    activation = 1_700_000_000
    monkeypatch.setattr(bridge, "_SLTP_GUARD_ACTIVATED_AT_EPOCH", activation)
    monkeypatch.setattr(bridge, "_decalage_serveur_courant", lambda: DECALAGE)
    p = _Pos(1, "GBPUSD", int(activation - 3600 + DECALAGE))
    assert int(p.time) > activation                      # ce que voyait l'ancien code
    eligible, _ = bridge._sltp_guard_eligible(1, bridge._ouverture_utc(p))
    assert eligible is False


def test_health_publie_la_fenetre_de_dedup(bridge, monkeypatch):
    """Une fenêtre qui a valu 3 h 05 au lieu de 5 min pendant des mois doit
    au moins être LISIBLE à distance."""
    monkeypatch.setattr(bridge, "ensure_mt5_connected", lambda: True)
    with bridge.app.test_request_context():
        charge = bridge.health().get_json()
    assert charge["garde_fous"]["dedup_window_sec"] == 3600
