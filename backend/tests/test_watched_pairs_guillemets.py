"""`WATCHED_PAIRS` doit survivre aux guillemets du `.env` (2026-08-23).

⛔ `docker run --env-file` NE retire PAS les guillemets, contrairement au
shell. Une ligne `WATCHED_PAIRS="EUR/USD,...,LINK/USD"` donne donc une
premiere paire nommee `"EUR/USD` et une derniere `LINK/USD"`.

Mesure du 23/08 : `LINK/USD"` tombait en classe `forex` par defaut — la
valeur de repli — et **disparaissait silencieusement de l'univers crypto**.
Aucune erreur, aucun log : juste un instrument qui cesse d'exister.

> **Un nom qui ne correspond a rien ne provoque pas d'erreur, il provoque un
> repli.** C'est ce qui rend ce genre de faute invisible.

Le nettoyage est fait A LA LECTURE, pas laisse a la discipline de celui qui
edite le fichier.
"""
from __future__ import annotations

import importlib

import pytest


def _recharger(monkeypatch, valeur):
    monkeypatch.setenv("WATCHED_PAIRS", valeur)
    import config.settings as s
    importlib.reload(s)
    return s.WATCHED_PAIRS


@pytest.fixture(autouse=True)
def _rendre_settings(monkeypatch):
    """Recharge `settings` propre apres chaque test : c'est un module global."""
    yield
    monkeypatch.undo()
    import config.settings as s
    importlib.reload(s)


def test_la_ligne_entouree_de_guillemets_ne_pollue_pas_les_bords(monkeypatch):
    """Le cas reel : la faute que j'ai introduite en prod le 23/08."""
    p = _recharger(monkeypatch, '"EUR/USD,BTC/USD,LINK/USD"')
    assert p == ["EUR/USD", "BTC/USD", "LINK/USD"]
    assert p[0] == "EUR/USD", "guillemet collé à la première paire"
    assert p[-1] == "LINK/USD", "guillemet collé à la dernière paire"


def test_la_classe_d_actif_suit(monkeypatch):
    """La consequence qui comptait : la derniere paire reste une crypto.

    ⚠️ On prend `DOT/USD`, reconnue par la liste en dur d'`asset_class_for`.
    `LINK/USD` — la victime reelle du 23/08 — n'est crypto que grace a
    `ASSET_CLASS_OVERRIDES` dans le `.env` de prod ; l'utiliser ici testerait
    la config de la machine, pas le code.
    """
    _recharger(monkeypatch, '"BTC/USD,DOT/USD"')
    from config.settings import WATCHED_PAIRS, asset_class_for
    assert [asset_class_for(p) for p in WATCHED_PAIRS] == ["crypto", "crypto"]


def test_pourquoi_la_faute_etait_INVISIBLE(monkeypatch):
    """⛔ Le repli d'`asset_class_for` est `forex`, jamais une erreur.

    Precision qui a son importance : le guillemet ne fait tomber que les
    paires classees par **correspondance EXACTE** (`ASSET_CLASS_OVERRIDES`).
    Celles reconnues par prefixe survivent — `DOT/USD"` commence toujours par
    `DOT`. C'est pour ca que la faute n'a coute que LINK, ALGO, UNI, BNB et
    PAXG, et pas BTC ni DOT : les cinq qui dependent d'un override.

    Et rien n'a proteste, parce que le repli est `forex`.
    """
    monkeypatch.setenv("ASSET_CLASS_OVERRIDES", "LINK/USD:crypto")
    import config.settings as s
    importlib.reload(s)

    assert s.asset_class_for("LINK/USD") == "crypto"
    assert s.asset_class_for('LINK/USD"') == "forex", (
        "le repli silencieux a disparu — ce test n'a plus d'objet")
    # Le prefixe, lui, resiste : la faute est selective, donc plus sournoise.
    assert s.asset_class_for('DOT/USD"') == "crypto"


def test_guillemets_simples_aussi(monkeypatch):
    assert _recharger(monkeypatch, "'EUR/USD,BTC/USD'") == ["EUR/USD", "BTC/USD"]


def test_espaces_et_entrees_vides(monkeypatch):
    """Une virgule en trop ne doit pas créer une paire vide."""
    assert _recharger(monkeypatch, " EUR/USD , BTC/USD ,, ") == \
        ["EUR/USD", "BTC/USD"]


def test_sans_guillemets_le_cas_normal_reste_intact(monkeypatch):
    assert _recharger(monkeypatch, "EUR/USD,BTC/USD") == ["EUR/USD", "BTC/USD"]


def test_une_seule_paire(monkeypatch):
    assert _recharger(monkeypatch, '"XAU/USD"') == ["XAU/USD"]
