"""Le détecteur de positions sans stop doit DÉCLENCHER, pas seulement se taire.

Écrit après un bug réel du 2026-08-19 : la première version référençait
`dest.destination_id`, attribut inexistant — le champ s'appelle `dest.id`.
Le passage à vide ne touchait jamais cette ligne, donc la vérification en
conditions réelles affichait « 0 position sans stop » sur les trois
destinations, l'air parfaitement sain. Le détecteur aurait levé une exception
au premier vrai cas, c'est-à-dire précisément quand on comptait sur lui.

> **Un détecteur ne se teste pas sur son silence.** Il faut le mettre en face
> de ce qu'il doit trouver.

Cf. [[feedback_detection_par_absence]].
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

_SCRIPT = (pathlib.Path(__file__).resolve().parents[2]
           / "scripts" / "notify_positions_non_protegees.py")


@pytest.fixture()
def detecteur():
    spec = importlib.util.spec_from_file_location("nues_detect", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def dest():
    from backend.services.destinations_registry import DESTINATIONS
    return DESTINATIONS["admin_live"]


def _reponse(detecteur, charge, ok=True):
    detecteur._appel = lambda d, c: (charge, ok)


# ── MT5 : le stop vit dans la position ─────────────────────────────────────

def test_mt5_position_sans_stop_est_detectee(detecteur, dest):
    """LE test qui manquait : le chemin de détection doit s'exécuter."""
    _reponse(detecteur, {"positions": [
        {"ticket": 2, "symbol": "XAUUSD", "type": "sell", "volume": 0.01,
         "sl": 0.0, "tp": 4400.0},
    ]})
    nues, ok = detecteur._sans_stop_mt5(dest)
    assert ok is True
    assert len(nues) == 1
    assert nues[0]["symbole"] == "XAUUSD"
    assert nues[0]["cle"] == "admin_live:2"
    assert nues[0]["objectif_pose"] is True   # TP posé, mais pas de stop


def test_mt5_position_protegee_ne_declenche_pas(detecteur, dest):
    _reponse(detecteur, {"positions": [
        {"ticket": 1, "symbol": "EURUSD", "type": "buy", "volume": 0.01,
         "sl": 1.15, "tp": 1.17},
    ]})
    assert detecteur._sans_stop_mt5(dest) == ([], True)


@pytest.mark.parametrize("sl", [None, 0, 0.0, "", "0"])
def test_mt5_toutes_les_formes_de_stop_absent(detecteur, dest, sl):
    _reponse(detecteur, {"positions": [
        {"ticket": 3, "symbol": "EURUSD", "type": "buy", "volume": 0.01, "sl": sl},
    ]})
    nues, ok = detecteur._sans_stop_mt5(dest)
    assert ok is True and len(nues) == 1


def test_mt5_lecture_impossible_n_est_pas_zero_position(detecteur, dest):
    """Muet ≠ vide : un bridge injoignable ne doit pas se lire « tout va bien »."""
    _reponse(detecteur, None, ok=False)
    assert detecteur._sans_stop_mt5(dest) == ([], False)


def test_mt5_reponse_mal_formee_est_un_echec_de_lecture(detecteur, dest):
    _reponse(detecteur, {"positions": "pas une liste"})
    assert detecteur._sans_stop_mt5(dest) == ([], False)


# ── Kraken : le croisement est fait par le bridge ──────────────────────────

def test_kraken_position_sans_stop_est_detectee(detecteur):
    from backend.services.destinations_registry import DESTINATIONS
    k = DESTINATIONS["admin_kraken"]
    _reponse(detecteur, {"ok": True, "positions_non_protegees": [
        {"symbol": "PF_SOLUSD", "side": "long", "size": 0.38,
         "price": 76.43, "objectif_pose": False},
    ]})
    nues, ok = detecteur._sans_stop_kraken(k)
    assert ok is True
    assert nues[0]["cle"] == "admin_kraken:PF_SOLUSD"
    assert nues[0]["objectif_pose"] is False


def test_kraken_ok_false_est_un_echec_de_lecture(detecteur):
    """`ok:false` = le bridge n'a pas pu croiser : ne rien conclure."""
    from backend.services.destinations_registry import DESTINATIONS
    k = DESTINATIONS["admin_kraken"]
    _reponse(detecteur, {"ok": False, "error": "positions unreachable"})
    assert detecteur._sans_stop_kraken(k) == ([], False)
