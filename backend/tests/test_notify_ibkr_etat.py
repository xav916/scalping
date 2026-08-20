"""Surveillance IBKR par Telegram (2026-08-20).

L'application IBKR refuse de se connecter tant que le Gateway occupe la
session, et le second utilisateur qui reglerait ca n'est pas propose sur ce
compte. On lit donc par le bridge.

Ce qui est verrouille ici, ce sont les deux facons dont cette surveillance
pourrait nuire :

1. **annoncer une cloture qui n'a pas eu lieu** parce que le bridge etait
   injoignable — une lecture ratee rend « aucune position », et sans garde-fou
   on annoncerait la fermeture de tout le portefeuille ;
2. **avancer l'instantane apres un envoi echoue**, ce qui perdrait le
   mouvement pour toujours.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

_SCRIPT = (pathlib.Path(__file__).resolve().parents[2]
           / "scripts" / "notify_ibkr_etat.py")


@pytest.fixture()
def script(tmp_path, monkeypatch):
    monkeypatch.setenv("IBKR_SNAPSHOT_PATH", str(tmp_path / "ibkr.json"))
    monkeypatch.setenv("IBKR_BRIDGE_URL", "http://x:8792")
    monkeypatch.setenv("IBKR_BRIDGE_API_KEY", "k")
    spec = importlib.util.spec_from_file_location("ibkr_etat", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_SANTE = {"ok": True, "connected": True}
_COMPTE = {"account": "U27532710", "currency": "EUR",
           "NetLiquidation": 100.0, "AvailableFunds": 100.0}


def _brancher(script, monkeypatch, positions, envois, ok_lecture=True):
    def _lire(chemin):
        if not ok_lecture:
            return None, False
        if chemin == "/health":
            return _SANTE, True
        if chemin == "/account":
            return _COMPTE, True
        return {"positions": positions, "count": len(positions)}, True

    monkeypatch.setattr(script, "_lire", _lire)
    monkeypatch.setattr(
        script, "_notifier",
        lambda titre, corps, dedup: (envois.append((titre, corps)) or True))


def _pos(symbole, taille):
    return {"symbol": symbole, "position": taille, "avg_cost": 43.1}


# ── Detection des mouvements ───────────────────────────────────────────────

def test_ouverture_annoncee(script, monkeypatch):
    envois: list = []
    _brancher(script, monkeypatch, [_pos("XLU", 2)], envois)
    assert script.main() == 0
    assert len(envois) == 1
    assert "OUVERTE" in envois[0][1] and "XLU" in envois[0][1]


def test_cloture_annoncee(script, monkeypatch):
    envois: list = []
    # 1er passage : la position existe et est memorisee
    _brancher(script, monkeypatch, [_pos("XLU", 2)], envois)
    script.main()
    envois.clear()
    # 2e passage : elle a disparu
    _brancher(script, monkeypatch, [], envois)
    assert script.main() == 0
    assert "FERMÉE" in envois[0][1] and "XLU" in envois[0][1]


def test_sans_mouvement_rien_n_est_envoye(script, monkeypatch):
    envois: list = []
    _brancher(script, monkeypatch, [_pos("XLU", 2)], envois)
    script.main()
    envois.clear()
    script.main()
    assert envois == []


# ── Le garde-fou : muet n'est pas vide ─────────────────────────────────────

def test_bridge_injoignable_n_annonce_PAS_de_cloture(script, monkeypatch):
    """LE test qui compte : sinon une coupure reseau annonce la fermeture de
    tout le portefeuille."""
    envois: list = []
    _brancher(script, monkeypatch, [_pos("XLU", 2)], envois)
    script.main()
    envois.clear()

    _brancher(script, monkeypatch, [], envois, ok_lecture=False)
    assert script.main() == 1          # echec signale
    assert envois == []                 # et surtout : aucune cloture annoncee


def test_reponse_mal_formee_est_un_echec_de_lecture(script, monkeypatch):
    envois: list = []

    def _lire(chemin):
        if chemin == "/health":
            return _SANTE, True
        if chemin == "/account":
            return _COMPTE, True
        return {"positions": "pas une liste"}, True

    monkeypatch.setattr(script, "_lire", _lire)
    monkeypatch.setattr(script, "_notifier",
                        lambda *a, **k: envois.append(a) or True)
    assert script.main() == 1
    assert envois == []


def test_digest_signale_l_illisible_au_lieu_de_se_taire(script, monkeypatch):
    envois: list = []
    monkeypatch.setenv("DIGEST", "1")
    _brancher(script, monkeypatch, [], envois, ok_lecture=False)
    script.main()
    assert len(envois) == 1
    assert "on ne sait pas" in envois[0][1]


# ── L'instantane ───────────────────────────────────────────────────────────

def test_instantane_n_avance_PAS_si_l_envoi_echoue(script, monkeypatch):
    """Un mouvement non annonce doit rejouer, pas etre perdu."""
    envois: list = []
    _brancher(script, monkeypatch, [_pos("XLU", 2)], envois)
    monkeypatch.setattr(script, "_notifier", lambda *a, **k: False)
    script.main()

    # Second passage : le meme mouvement doit etre re-annonce.
    _brancher(script, monkeypatch, [_pos("XLU", 2)], envois)
    assert script.main() == 0
    assert len(envois) == 1


def test_digest_envoie_l_etat_sans_mouvement(script, monkeypatch):
    envois: list = []
    monkeypatch.setenv("DIGEST", "1")
    _brancher(script, monkeypatch, [], envois)
    script.main()
    assert len(envois) == 1
    assert "U27532710" in envois[0][1]
    assert "Aucune position ouverte" in envois[0][1]
