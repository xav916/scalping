"""Un critere que `or-verdict` ne sait pas evaluer doit etre refuse ICI.

## Le defaut que ce fichier empeche de revenir

Le 2026-10-31, une pre-inscription a passe `or-preinscription` avec :

    admission: t > +2 et moyenne_nette_eur > 0 et bat_plafond_permutation

Le banc a ete ecrit, puis execute sur la production. Et c'est seulement a la
publication que `or-verdict` a refuse :

> clause ILLISIBLE, donc non evaluable -- le critere ne peut pas etre
> applique en partie

Deux fautes de forme : ` et ` en minuscules la ou l'analyseur attend ` ET `,
et une clause `bat_plafond_permutation` sans operateur ni nombre.

⛔ **Le pire n'est pas le refus, c'est son MOMENT.** Il arrive apres que les
chiffres ont ete vus. Reecrire le critere a ce stade, c'est le reecrire en
connaissant le resultat -- exactement ce que ces deux skills existent pour
empecher. Le critere est donc perdu, et la mesure avec lui.

🔑 La porte d'entree doit refuser ce que la porte de sortie refusera.

## Pourquoi on IMPORTE l'analyseur de `or-verdict`

Deux analyseurs finiraient par divergir, et la divergence rouvrirait le trou
en silence. C'est la meme lecon que « cabler l'acteur ET tous ses
observateurs dans le meme commit ».
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

_RACINE = pathlib.Path(__file__).resolve().parents[1]


def _charger():
    spec = importlib.util.spec_from_file_location(
        "preinscrire_sous_test", _RACINE / "preinscrire.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pre = _charger()


# --- LE test ------------------------------------------------------------

def test_le_critere_fautif_du_31_10_est_REFUSE():
    """⛔ Le cas reel, verrouille nommement."""
    probleme = pre.lisible_par_or_verdict(
        "t > +2 et moyenne_nette_eur > 0 et bat_plafond_permutation")
    assert probleme is not None, (
        "le critere qui a coute une mesure le 2026-10-31 passerait encore")
    assert "ILLISIBLE" in probleme or "evaluable" in probleme


@pytest.mark.parametrize("expression", [
    "bat_plafond_permutation",                       # drapeau nu
    "t superieur a 2",                               # prose
    "t > +2 et moyenne > 0",                         # « et » minuscule
    "",                                              # vide
])
def test_les_formes_illisibles_sont_refusees(expression):
    assert pre.lisible_par_or_verdict(expression) is not None, (
        "forme acceptee a tort : %r" % expression)


@pytest.mark.parametrize("expression", [
    "t > +2",                                            # clause unique
    "t > +2 ET moyenne_nette_eur > 0",                   # deux clauses
    "abs(ecart_par_trade) < 0.50",                       # abs simple
    "abs(risk_median_placebo - risk_median_reel) < 1.0",  # abs a deux champs
    "t > +2 ET moyenne_nette_eur > 0 ET plafond_battu > 0",
])
def test_les_formes_lisibles_passent(expression):
    """⛔ Le pendant obligatoire : une sonde qui refuse tout ne garde rien, et
    rendrait la skill inutilisable."""
    assert pre.lisible_par_or_verdict(expression) is None, (
        "forme refusee a tort : %r" % expression)


# --- temoins de l'instrument -------------------------------------------

def test_la_sonde_ne_confond_pas_champ_absent_et_syntaxe_illisible():
    """🔑 Le point delicat. L'evaluateur rend `None` AUSSI quand un champ
    manque. Or au moment de la pre-inscription le resultat n'existe pas : tous
    les champs manquent, par construction.

    La sonde doit donc injecter les identifiants cites. Sans cela elle
    refuserait TOUT critere, y compris les bons.
    """
    # un champ au nom improbable, qui n'existera dans aucun resultat
    assert pre.lisible_par_or_verdict("un_champ_qui_n_existe_nulle_part > 3") is None


def test_la_sonde_utilise_bien_l_evaluateur_de_or_verdict():
    """Si le chargement echouait, la sonde rendrait `None` partout et ne
    garderait plus rien -- une panne silencieuse."""
    evaluer = pre._evaluateur_de_or_verdict()
    assert evaluer is not None, (
        "l'evaluateur de or-verdict n'est plus chargeable : la sonde est "
        "devenue aveugle et laisse passer n'importe quel critere")
    verdict, _ = evaluer("t > +2", {"t": 3.0})
    assert verdict is True, "l'evaluateur charge ne se comporte pas comme attendu"


def test_une_skill_or_verdict_absente_ne_BLOQUE_pas():
    """⚠️ Choix assume : si `or-verdict` n'est pas installee, on ne refuse pas
    la pre-inscription pour autant. Bloquer sur l'absence d'une skill tierce
    empecherait d'ecrire une pre-inscription sur une machine qui n'a que
    celle-ci -- et la lisibilite serait alors verifiee a la publication, comme
    avant. On degrade, on ne ferme pas.
    """
    import unittest.mock as mock
    with mock.patch.object(pre, "_evaluateur_de_or_verdict", lambda: None):
        assert pre.lisible_par_or_verdict("n importe quoi d illisible") is None
