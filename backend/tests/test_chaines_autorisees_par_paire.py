"""Armer une chaine SUR UNE PAIRE, pas sur tout le compte.

⛔ **Le constat du 2026-10-01.** Xavier demande d'armer `sur_niveau_majeur`
apres une conversation entierement consacree a l'or. Or
`autorisee(nom, destination, horizon)` **n'a aucune dimension de paire** :
l'armer a 5 min sur `admin_live` l'armerait sur les **25 paires** de la portee
de ce compte — 11 cryptos, l'argent, le WTI, les forex majors.

Et ce registre **contourne la liste blanche des motifs** : il ouvrirait donc un
chemin vers l'argent reel a 25 instruments dont la plupart n'ont jamais ete
mesures pour cette chaine.

> **« Sur niveau majeur » dans une conversation sur l'or veut dire sur l'or.**

Meme discipline que `MT5_BRIDGE_HORIZON_OVERRIDES` le meme jour.

## La forme

    {"admin_live": {"5min": {"XAU/USD": ["chaine:sweep_sur_niveau_majeur_haussier"]}}}

⚠️ La forme en LISTE reste acceptee — `{"5min": ["chaine:x"]}` — parce qu'elle
est documentee et testee. Mais elle vaut **toutes les paires**, et elle doit le
DIRE dans les journaux : une portee implicite large est exactement ce qui vient
d'etre evite ici.
"""
from __future__ import annotations

import pytest

from backend.services import chaines_autorisees as ca

VRAIE = "chaine:sweep_sur_niveau_majeur_haussier"


@pytest.fixture(autouse=True)
def _vide_le_cache():
    ca._cache = None
    yield
    ca._cache = None


def _registre(monkeypatch, valeur: str):
    monkeypatch.setenv("CHAINES_AUTORISEES", valeur)
    ca._cache = None


# --- La forme PAR PAIRE --------------------------------------------------

def test_la_paire_declaree_passe(monkeypatch):
    _registre(monkeypatch,
              '{"admin_live": {"5min": {"XAU/USD": ["%s"]}}}' % VRAIE)
    assert ca.autorisee(VRAIE, "admin_live", "5min", "XAU/USD") is True


def test_une_AUTRE_paire_est_refusee(monkeypatch):
    """⛔ Le cœur : l'argent et les cryptos ne doivent PAS en heriter."""
    _registre(monkeypatch,
              '{"admin_live": {"5min": {"XAU/USD": ["%s"]}}}' % VRAIE)
    for paire in ("XAG/USD", "BTC/USD", "EUR/USD", "WTI/USD"):
        assert ca.autorisee(VRAIE, "admin_live", "5min", paire) is False, paire


def test_sans_paire_transmise_la_forme_par_paire_REFUSE(monkeypatch):
    """Si le registre est scope par paire, on ne peut pas verifier sans paire.

    ⛔ Fail-closed : l'inconnu FERME, puisqu'il s'agit d'ouvrir une porte.
    """
    _registre(monkeypatch,
              '{"admin_live": {"5min": {"XAU/USD": ["%s"]}}}' % VRAIE)
    assert ca.autorisee(VRAIE, "admin_live", "5min", None) is False


def test_un_autre_horizon_reste_refuse(monkeypatch):
    _registre(monkeypatch,
              '{"admin_live": {"5min": {"XAU/USD": ["%s"]}}}' % VRAIE)
    assert ca.autorisee(VRAIE, "admin_live", "30min", "XAU/USD") is False


def test_une_autre_destination_reste_refusee(monkeypatch):
    _registre(monkeypatch,
              '{"admin_live": {"5min": {"XAU/USD": ["%s"]}}}' % VRAIE)
    assert ca.autorisee(VRAIE, "admin_legacy", "5min", "XAU/USD") is False


# --- La forme en LISTE : compatible, et large ----------------------------

def test_la_forme_en_liste_vaut_toutes_les_paires(monkeypatch):
    """Elle reste acceptee — documentee et testee ailleurs."""
    _registre(monkeypatch, '{"admin_live": {"5min": ["%s"]}}' % VRAIE)
    assert ca.autorisee(VRAIE, "admin_live", "5min", "XAU/USD") is True
    assert ca.autorisee(VRAIE, "admin_live", "5min", "BTC/USD") is True
    assert ca.autorisee(VRAIE, "admin_live", "5min", None) is True


def test_la_forme_en_liste_se_DIT_dans_les_journaux(monkeypatch, caplog):
    """⚠️ Une portee large ne doit pas etre silencieuse."""
    import logging
    _registre(monkeypatch, '{"admin_live": {"5min": ["%s"]}}' % VRAIE)
    with caplog.at_level(logging.WARNING):
        ca.tout()
    assert any("TOUTES" in r.message.upper() or "toutes les paires" in r.message
               for r in caplog.records), [r.message for r in caplog.records]


# --- Les refus deja en place ne bougent pas ------------------------------

def test_un_nom_non_declare_est_refuse_meme_scope_par_paire(monkeypatch):
    _registre(monkeypatch,
              '{"admin_live": {"5min": {"XAU/USD": ["chaine:inventee"]}}}')
    assert ca.autorisee("chaine:inventee", "admin_live", "5min",
                        "XAU/USD") is False


def test_un_json_casse_ferme(monkeypatch):
    _registre(monkeypatch, '{"admin_live": {"5min": {"XAU/USD": [')
    assert ca.autorisee(VRAIE, "admin_live", "5min", "XAU/USD") is False
    assert ca.tout() == {}
