"""Le veilleur de l'interrupteur d'exécution : il doit PARLER quand c'est fermé.

## ⛔ CE QU'IL EXISTE POUR EMPÊCHER

Le 2026-10-07 à 22h14 UTC, un déploiement a changé l'empreinte du code et
REM-002 a désarmé l'exécution — exactement ce qu'il doit faire. Personne ne l'a
lu :

    456 refus `execution_globale_fermee` sur l'or en une heure, seul motif
    SIX HEURES de marché sans un ordre
    et c'est Xavier qui l'a remarqué, en regardant ses bougies

Les signaux sortaient pendant tout ce temps. Rien n'était cassé.

> 🔑 Ce qui a manqué, ce n'est pas un garde-fou. C'est de le LIRE.

## ⛔ Les deux façons dont ce veilleur pourrait trahir

1. **Se taire quand c'est fermé** — il ne servirait à rien.
2. **Se taire quand il n'a pas pu lire** — « je n'ai pas regardé » n'est pas
   « tout va bien ». C'est précisément la panne qu'on ne verrait pas.

Et une troisième, plus discrète : **parler à chaque passage**. Une alerte
répétée sans fin n'est plus lue — la leçon des 8 doublons du 07/10. D'où le
`cooldown_seconds`, qui doit être transmis au relais (sans durée, sa garde est
INERTE).
"""
from __future__ import annotations

import importlib.util
import types
from pathlib import Path

import pytest

_SCRIPT = (Path(__file__).resolve().parents[2] / "scripts"
           / "veilleur_interrupteur_execution.py")


@pytest.fixture()
def v():
    spec = importlib.util.spec_from_file_location("veilleur_inter", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _armer(v, monkeypatch, etat):
    """Remplace la lecture d'état et capture ce qui serait envoyé."""
    envois = []
    monkeypatch.setattr(v, "_etat", lambda: etat)
    monkeypatch.setattr(v, "_prevenir",
                        lambda titre, corps, dedup: envois.append(
                            (titre, corps, dedup)) or True)
    return envois


ARME = {"decision": "ALLOW", "reason_code": "ARMED", "live_execution": "ON",
        "fingerprint_running": "56cec100aa97",
        "fingerprint_armed": "56cec100aa97", "configuration_drift": False,
        "blocages": []}
FERME = {"decision": "DENY", "reason_code": "COMMIT_MISMATCH",
         "live_execution": "OFF", "fingerprint_running": "9056d41abcde",
         "fingerprint_armed": "91be2f066aa4", "configuration_drift": True,
         "blocages": []}


def test_arme_il_se_TAIT(v, monkeypatch):
    """Mode événement : un veilleur qui parle à chaque passage n'est plus lu."""
    envois = _armer(v, monkeypatch, ARME)
    assert v.main() == 0
    assert envois == []


def test_DESARME_il_PARLE(v, monkeypatch):
    """🔑 LA raison d'être. Sans ça, six heures de marché repassent."""
    envois = _armer(v, monkeypatch, FERME)
    assert v.main() == 0
    assert len(envois) == 1
    titre, corps, _dedup = envois[0]
    assert "DÉSARMÉE" in titre
    # Le message doit porter de quoi AGIR, pas seulement de quoi s'inquiéter.
    assert "9056d41abcde" in corps, "l'empreinte à armer manque"
    assert "91be2f066aa4" in corps, "l'empreinte armée manque"
    assert "Aucun ordre ne partira" in corps


def test_etat_ILLISIBLE_il_PARLE_aussi(v, monkeypatch):
    """⛔ « Je n'ai pas pu regarder » n'est PAS « tout va bien »."""
    envois = _armer(v, monkeypatch, None)
    assert v.main() == 0
    assert len(envois) == 1
    _titre, corps, _d = envois[0]
    assert "Impossible de LIRE" in corps
    assert "absence de mesure" in corps


def test_la_DERIVE_de_configuration_se_DIT(v, monkeypatch):
    envois = _armer(v, monkeypatch, FERME)
    assert v.main() == 0
    assert "dérive de configuration" in envois[0][1]


def test_essai_n_envoie_RIEN_meme_desarme(v, monkeypatch):
    """Une observation ne doit déplacer ni alerter."""
    envois = _armer(v, monkeypatch, FERME)
    monkeypatch.setattr(v.sys, "argv", ["x", "--essai"])
    assert v.main() == 0
    assert envois == []


def test_bilan_parle_MEME_quand_tout_va_bien(v, monkeypatch):
    envois = _armer(v, monkeypatch, ARME)
    monkeypatch.setattr(v.sys, "argv", ["x", "--bilan"])
    assert v.main() == 0
    assert len(envois) == 1
    assert "armée" in envois[0][0]


def test_le_COOLDOWN_part_avec_la_cle_sinon_la_garde_est_INERTE(v, monkeypatch):
    """⛔ `app.py` teste `if dedup_key and cooldown_seconds > 0`.

    La sonde des métaux envoyait la clé SANS la durée : la garde du relais
    était inerte et chaque rejeu repartait vraiment — 8 copies du même message
    le 07/10. On ne refait pas ça.
    """
    vu = {}

    def _faux_notifier(canal, titre, corps, *, timeout=15.0, dedup_key=None,
                       cooldown_seconds=None):
        vu.update(dedup_key=dedup_key, cooldown_seconds=cooldown_seconds)
        return True

    faux_canaux = types.ModuleType("backend.services.canaux_telegram")
    faux_canaux.canal_pour = lambda _d: "infra"
    faux_canaux.notifier = _faux_notifier
    import sys as _sys
    monkeypatch.setitem(_sys.modules, "backend.services.canaux_telegram",
                        faux_canaux)

    assert v._prevenir("t", "c", dedup="interrupteur_desarme") is True
    assert vu["dedup_key"] == "interrupteur_desarme"
    assert vu["cooldown_seconds"] and vu["cooldown_seconds"] > 0, (
        "sans duree, le relais ne tait RIEN et l alerte se repetera")


def test_il_poste_sur_le_fil_INFRA_pas_sur_un_fil_de_compte(v, monkeypatch):
    """Un ordre qui ne part pas n'appartient à aucun compte : c'est un fait
    d'infrastructure."""
    vu = {}
    faux_canaux = types.ModuleType("backend.services.canaux_telegram")
    faux_canaux.canal_pour = lambda d: vu.setdefault("destination", d) or "infra"
    faux_canaux.notifier = lambda *a, **k: True
    import sys as _sys
    monkeypatch.setitem(_sys.modules, "backend.services.canaux_telegram",
                        faux_canaux)
    v._prevenir("t", "c", dedup="k")
    assert vu["destination"] is None, (
        "`canal_pour(None)` mene au fil infra ; une destination y mettrait le "
        "message dans le fil d un compte")
