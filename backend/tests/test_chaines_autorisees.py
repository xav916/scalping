"""Le registre des chaines — fail-closed, et separe de la liste blanche.

⛔ **Pourquoi un registre a part.** La liste blanche du pont est fail-closed
sur `PatternType`, et une chaine n'en est pas un — c'est voulu : « le
laboratoire mesure ; il n'ouvre aucune porte ». Promouvoir une chaine en
`PatternType` la ferait passer par la porte des motifs simples, sans decision
propre. Elle a donc **sa** porte, avec la meme discipline.

## Les trois refus

1. **Registre vide = rien n'est autorise.** C'est l'etat par defaut, et c'est
   l'etat actuel.
2. **Une chaine autorisee sur une destination ne l'est pas sur les autres** —
   la demo n'ouvre pas le reel. Meme lecon que la portee des fermetures.
3. **Un nom inconnu n'autorise rien**, et une exception de lecture non plus :
   un JSON casse dans l'`.env` doit fermer, pas ouvrir.
"""
from __future__ import annotations

import pytest

from backend.services import chaines_autorisees as ca


@pytest.fixture(autouse=True)
def _registre_neuf(monkeypatch):
    monkeypatch.setattr(ca, "_cache", None)
    yield
    ca._cache = None


def _poser(monkeypatch, brut: str):
    monkeypatch.setenv("CHAINES_AUTORISEES", brut)
    ca._cache = None


def test_par_DEFAUT_rien_n_est_autorise(monkeypatch):
    monkeypatch.delenv("CHAINES_AUTORISEES", raising=False)
    ca._cache = None
    assert ca.autorisee("chaine:x", "admin_live", "5min") is False
    assert ca.tout() == {}


def test_une_chaine_autorisee_passe_la_porte(monkeypatch):
    _poser(monkeypatch, '{"admin_legacy": {"5min": ["chaine:prise_en_accumulation_haussier"]}}')
    assert ca.autorisee("chaine:prise_en_accumulation_haussier",
                        "admin_legacy", "5min") is True
    assert ca.armees() == ["admin_legacy/5min/chaine:prise_en_accumulation_haussier"]


# ⚠️ Un nom REEL : le registre refuse — a juste titre — une chaine que le
# laboratoire ne declare pas. Ma premiere version testait la portee avec
# « chaine:x » et echouait pour une raison etrangere a ce qu'elle mesurait.
VRAIE = "chaine:prise_en_accumulation_haussier"


def test_la_DEMO_n_ouvre_pas_le_REEL(monkeypatch):
    """⛔ Meme lecon que la portee des fermetures : une decision vaut la ou
    elle a ete prise, pas ailleurs."""
    _poser(monkeypatch, '{"admin_legacy": {"5min": ["%s"]}}' % VRAIE)
    assert ca.autorisee(VRAIE, "admin_legacy", "5min") is True
    assert ca.autorisee(VRAIE, "admin_live", "5min") is False


def test_un_HORIZON_non_declare_n_autorise_rien(monkeypatch):
    _poser(monkeypatch, '{"admin_live": {"4h": ["%s"]}}' % VRAIE)
    assert ca.autorisee(VRAIE, "admin_live", "4h") is True
    assert ca.autorisee(VRAIE, "admin_live", "5min") is False


def test_un_JSON_CASSE_ferme_au_lieu_d_ouvrir(monkeypatch):
    """⛔ Fail-closed. Un `.env` mal edite ne doit pas ouvrir des portes."""
    _poser(monkeypatch, "{ceci n'est pas du json")
    assert ca.autorisee("chaine:x", "admin_live", "5min") is False
    assert ca.tout() == {}


def test_un_nom_qui_n_est_PAS_une_chaine_est_refuse(monkeypatch):
    """⛔ Le registre des chaines ne doit pas pouvoir ouvrir un motif simple :
    ce serait un second chemin vers la liste blanche, sans son controle."""
    _poser(monkeypatch, '{"admin_live": {"5min": ["momentum_up"]}}')
    assert ca.autorisee("momentum_up", "admin_live", "5min") is False


def test_une_chaine_INCONNUE_du_laboratoire_est_refusee(monkeypatch):
    """Une chaine qui n'est pas declaree ne peut pas etre armee — sinon on
    armerait un nom que rien ne mesure."""
    _poser(monkeypatch, '{"admin_live": {"5min": ["chaine:inventee"]}}')
    assert ca.autorisee("chaine:inventee", "admin_live", "5min") is False


def test_AUJOURD_HUI_le_registre_est_VIDE_en_production(monkeypatch):
    """⚠️ Etat de fait, documente : rien n'est arme. Le jour ou ce test rougit,
    c'est qu'une chaine a ete armee — et ce doit etre une decision, pas un
    effet de bord."""
    monkeypatch.delenv("CHAINES_AUTORISEES", raising=False)
    ca._cache = None
    assert ca.tout() == {}
