"""Le prix d'entrée écrit dans l'audit ne doit JAMAIS valoir zéro (2026-08-24).

⛔ Le fait mesuré sur le compte RÉEL :

    filled + mode=live, 60 jours     57 lignes
      dont entry > 0                  0        <- AUCUNE
    blocked                          171/171 ont entry
    rejected                         108/108 ont entry

Le démo, lui, a `entry > 0` sur **39/39**. Le champ fonctionne partout sauf
là où il compte : les ordres RÉELLEMENT EXÉCUTÉS chez IC Markets.

## La cause

``entry=result["price"]`` écrivait le champ MT5 **brut**. Or IC Markets rend
``result.price = 0.0`` sur un ordre pourtant rempli — c'est un défaut connu et
déjà corrigé **ailleurs** : ``_resolve_fill_price()`` existe depuis le
2026-06-12 avec trois sources de repli, et son résultat était juste à côté
dans le même dict, inutilisé pour ``entry``.

> **Un correctif ne se propage pas seul aux autres consommateurs de la même
> donnée.** Le repli avait été posé pour la pose du SL/TP ; personne n'avait
> rebranché l'audit dessus. Même leçon que les stops Kraken posés au prix du
> signal.

## Ce que ça cassait en aval

``mt5_sync._upsert_open_trade`` fait ``entry_price = row.get("entry") or 0``.
Donc ``personal_trades.entry_price = 0`` sur les **217** trades du compte
réel, ce qui rend indécidable toute analyse en R du réel
([[project_entry_price_absent_reel_2026_08_24]]).

⚠️ ``0.0`` ne se lit pas « entrée à zéro » — ça n'aurait aucun sens. C'est
« jamais écrit ». Mais rien ne l'en distingue, donc une moyenne l'avale en
silence. Quatrième occurrence du même piège après ``pnl=0.0``,
``close_reason=MANUAL`` et ``mfe_pct=0``.
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "mt5-bridge" / "bridge.py"


@pytest.fixture(scope="module")
def m():
    src = _SRC.read_text(encoding="utf-8")
    debut = src.index("def _prix_pour_audit(")
    fin = src.index("def _resolve_fill_price(")
    mod = types.ModuleType("bridge_audit_prix")
    exec(compile(src[debut:fin], str(_SRC), "exec"), mod.__dict__)
    return mod


def test_le_cas_nominal_utilise_le_prix_MT5(m):
    """Quand le courtier rend un prix, c'est lui qui fait foi."""
    assert m._prix_pour_audit({"price": 1.36012, "fill_price": 1.36012}) == 1.36012


def test_le_cas_IC_MARKETS_result_price_a_ZERO(m):
    """⛔ Le bug : 57 ordres réels enregistrés avec entry=0.

    `result.price` vaut 0 alors que l'ordre est rempli. Le prix résolu est
    dans le même dict — on le prend.
    """
    assert m._prix_pour_audit({"price": 0.0, "fill_price": 1.36012}) == 1.36012


def test_un_prix_resolu_ABSENT_ne_fabrique_rien(m):
    """Ancien bridge sans `fill_price` : on retombe sur le brut, pas sur une
    valeur inventée. Rétrocompatible."""
    assert m._prix_pour_audit({"price": 1.36012}) == 1.36012


def test_les_DEUX_a_zero_rendent_None_jamais_zero(m):
    """⛔ Le cœur du correctif.

    Si aucune source ne donne de prix, il faut le DIRE. Écrire `0.0` fabrique
    un zéro qui se fera passer pour une mesure — exactement ce qu'on répare.
    `None` en base se lit « absent », et une moyenne l'écarte au lieu de
    l'avaler.
    """
    assert m._prix_pour_audit({"price": 0.0, "fill_price": 0.0}) is None
    assert m._prix_pour_audit({"price": 0.0, "fill_price": None}) is None
    assert m._prix_pour_audit({}) is None


def test_un_prix_NEGATIF_est_refuse(m):
    """Un prix négatif n'existe pas : c'est une donnée abîmée, pas un prix."""
    assert m._prix_pour_audit({"price": -1.0, "fill_price": -2.0}) is None


def test_un_champ_illisible_ne_fait_pas_tomber_l_ordre(m):
    """⚠️ Cette fonction est appelée APRÈS un ordre réussi. Lever une
    exception ici perdrait la trace d'un trade réel : on rend None."""
    assert m._prix_pour_audit({"price": "abc", "fill_price": None}) is None
    assert m._prix_pour_audit({"price": None, "fill_price": "xyz"}) is None


def test_le_site_d_ecriture_utilise_bien_la_fonction():
    """⚠️ Test d'inspection de source — faible par nature, mais il attrape la
    régression qui compte : quelqu'un qui réécrirait `entry=result["price"]`.

    ⚠️ On inspecte les **lignes d'argument**, pas le texte brut du fichier :
    la première version de ce test matchait sa propre docstring, qui cite le
    code fautif. Un test d'inspection doit viser du code, pas de la prose.
    """
    lignes = [l.strip() for l in _SRC.read_text(encoding="utf-8").splitlines()]
    fautives = [l for l in lignes if l.startswith('entry=result["price"]')]
    assert not fautives, (
        f"le prix BRUT est réécrit dans l'audit ({fautives}) — "
        "il vaut 0 chez IC Markets")
    assert any(l.startswith("entry=_prix_pour_audit(result)") for l in lignes)
