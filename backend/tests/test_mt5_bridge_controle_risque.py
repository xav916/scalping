"""Le risque REELLEMENT engage doit correspondre au risque VOULU.

Mesure du 2026-08-11 : sur 610 trades du demo, **455 (75 %) risquaient un
milliere de ce qui etait prevu**.

```
paire          n  risque reel   risk_money    rapport
XAU/USD       64      14,45 EUR    19,66 EUR     0,925   <- correct
ETH/USD      277       0,08 EUR    16,98 EUR     0,006
DOT/USD       44       0,02 EUR    15,00 EUR     0,001   <- 750x trop petit
```

Ces 455 ordres ont rapporte −11 EUR au total : ils ont paye le spread sans
prendre de position. **Rien ne l'a detecte** — la position etait valide, juste
minuscule. Aucun controle ne comparait le realise au voulu apres calcul du lot.

Le defaut joue dans les DEUX sens : le plancher du lot minimum sur-dimensionne
l'or (2 a 5x), le plafond `MAX_LOT` sous-dimensionne les cryptos (/100 a /750).
Les deux etaient muets.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

_CHEMIN = Path(__file__).resolve().parents[2] / "mt5-bridge" / "bridge.py"
_spec = importlib.util.spec_from_file_location("bridge_controle_risque", _CHEMIN)
bridge = importlib.util.module_from_spec(_spec)
sys.modules["bridge_controle_risque"] = bridge
_spec.loader.exec_module(bridge)


# --- calcul du risque reellement engage -----------------------------------

def test_or_au_lot_minimum():
    """XAU : 1 lot = 100 onces, point = 0,01, tick_value ~0,87 EUR.
    Un stop de 13,81 $ sur 0,01 lot risque donc ~12 EUR — valeur mesuree
    sur le ticket reel du 2026-08-11."""
    r = bridge._risque_realise(entry=4378.71, sl=4364.90, lots=0.01,
                               point=0.01, tick_value=0.8665)
    assert 11.5 < r < 12.5


def test_crypto_ecrasee_par_le_plafond_de_lot():
    """ETH : le lot calcule pour risquer 17 EUR est tronque par MAX_LOT.
    Le risque reel tombe a une fraction d'euro."""
    r = bridge._risque_realise(entry=2000.0, sl=1980.0, lots=0.01,
                               point=0.01, tick_value=0.004)
    assert r == pytest.approx(0.08, abs=0.01)


@pytest.mark.parametrize("entry,sl,lots,point,tick", [
    (100.0, 100.0, 0.01, 0.01, 1.0),   # stop colle a l'entree
    (100.0, 99.0, 0.0, 0.01, 1.0),     # aucun lot
    (100.0, 99.0, 0.01, 0.0, 1.0),     # point inconnu
    (100.0, 99.0, 0.01, 0.01, 0.0),    # valeur du tick inconnue
])
def test_donnees_degradees_ne_rendent_pas_un_faux_chiffre(entry, sl, lots, point, tick):
    """Une donnee manquante doit rendre None, jamais un zero qui se ferait
    passer pour une mesure — le piege qui a produit ce bug."""
    assert bridge._risque_realise(entry, sl, lots, point, tick) is None


# --- le verdict ------------------------------------------------------------

def test_dimensionnement_correct_passe():
    ratio, cause = bridge._controle_risque(14.45, 19.66, mini=0.5, maxi=0.0)
    assert cause is None
    assert 0.7 < ratio < 0.8


def test_position_placebo_refusee():
    """Le cas des 455 trades : risquer 0,08 EUR quand on en voulait 17."""
    ratio, cause = bridge._controle_risque(0.08, 16.98, mini=0.5, maxi=0.0)
    assert cause == "risque_realise_trop_faible"
    assert ratio < 0.01


def test_sur_dimensionnement_signale_mais_TOLERE_par_defaut():
    """L'or au lot minimum risque 2 a 5x le voulu. Le refuser par defaut
    arreterait tout trading sur un petit compte — c'est un probleme de
    CAPITAL, pas une erreur d'execution. On le mesure, Xavier decide."""
    ratio, cause = bridge._controle_risque(60.0, 15.0, mini=0.5, maxi=0.0)
    assert cause is None
    assert ratio == pytest.approx(4.0)


def test_sur_dimensionnement_refuse_si_le_plafond_est_arme():
    ratio, cause = bridge._controle_risque(60.0, 15.0, mini=0.5, maxi=3.0)
    assert cause == "risque_realise_trop_eleve"


def test_sans_risque_voulu_aucun_controle():
    """Quand l'appelant impose `lots` directement, il n'y a pas de risque
    voulu a comparer. Ne rien inventer."""
    assert bridge._controle_risque(12.0, None, mini=0.5, maxi=0.0) == (None, None)
    assert bridge._controle_risque(12.0, 0.0, mini=0.5, maxi=0.0) == (None, None)


def test_risque_incalculable_ne_bloque_jamais():
    """Meme principe que l'ajustement a la marge : une panne de calcul ne doit
    pas arreter le trading. Le courtier reste l'arbitre."""
    assert bridge._controle_risque(None, 15.0, mini=0.5, maxi=0.0) == (None, None)


def test_le_plancher_peut_etre_desarme():
    ratio, cause = bridge._controle_risque(0.08, 16.98, mini=0.0, maxi=0.0)
    assert cause is None
    assert ratio is not None


# --- le garde-fou est-il REELLEMENT branche ? ------------------------------

def test_place_order_appelle_le_controle():
    """⚠️ Verification par ARBRE SYNTAXIQUE, pas par recherche de chaine.

    Un `assert "_controle_risque" in source` passerait sur une simple mention
    en commentaire, ou sur du code mort. Ce projet a deja livre un correctif
    branche sur un import mort. On exige donc un APPEL, situe dans la fonction
    qui place les ordres.
    """
    import ast

    arbre = ast.parse(_CHEMIN.read_text(encoding="utf-8"))
    place_order = next(
        (n for n in ast.walk(arbre)
         if isinstance(n, ast.FunctionDef) and n.name == "place_order"),
        None,
    )
    assert place_order is not None, "place_order introuvable"

    appels = {
        n.func.id for n in ast.walk(place_order)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "_controle_risque" in appels, "le controle n'est pas appele dans place_order"
    assert "_risque_realise" in appels, "le risque realise n'est jamais calcule"


def test_le_controle_precede_l_envoi_de_l_ordre():
    """Controler apres avoir envoye l'ordre ne servirait a rien : la position
    serait deja ouverte.

    ⚠️ `place_order` n'appelle pas `mt5.order_send` directement, ni meme a un
    niveau de delegation : il faut suivre le graphe d'appels TRANSITIVEMENT.
    Deux versions de ce test ont echoue sur une hypothese trop courte avant
    d'aller voir. Ne pas remplacer par un cas particulier code en dur : le jour
    ou la chaine d'appels change, le test doit suivre tout seul.
    """
    import ast

    arbre = ast.parse(_CHEMIN.read_text(encoding="utf-8"))
    fonctions = {n.name: n for n in ast.walk(arbre)
                 if isinstance(n, ast.FunctionDef)}

    def _appels(noeud):
        return [(n.func.id, n.lineno) for n in ast.walk(noeud)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]

    def _envoie_un_ordre(nom, vus=None):
        """Vrai si `nom` finit, directement ou non, par appeler order_send."""
        vus = vus or set()
        if nom in vus or nom not in fonctions:
            return False
        vus.add(nom)
        corps = fonctions[nom]
        if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "order_send" for n in ast.walk(corps)):
            return True
        return any(_envoie_un_ordre(f, vus) for f, _ in _appels(corps))

    place_order = fonctions["place_order"]
    envoyeurs = {nom for nom, _ in _appels(place_order) if _envoie_un_ordre(nom)}
    assert envoyeurs, "aucun chemin d'appel de place_order n'atteint order_send"

    ligne_controle = min(l for nom, l in _appels(place_order)
                         if nom == "_controle_risque")
    ligne_envoi = min(l for nom, l in _appels(place_order) if nom in envoyeurs)
    assert ligne_controle < ligne_envoi, (
        f"le controle (ligne {ligne_controle}) doit preceder l'envoi "
        f"(ligne {ligne_envoi}, via {sorted(envoyeurs)})"
    )


# --- robustesse d'entree ---------------------------------------------------

@pytest.mark.parametrize("valeur", ["15.0", "0.08", " 15 "])
def test_risk_money_en_chaine_ne_fait_pas_tomber_l_ordre(valeur):
    """⚠️ Le JSON peut livrer `risk_money` en chaine. Une comparaison directe
    `risk_money <= 0` leve alors TypeError — ce qui ferait echouer TOUS les
    ordres, pas seulement celui-la. Un garde-fou qui casse le trading est pire
    que pas de garde-fou.
    """
    rapport, cause = bridge._controle_risque(12.0, valeur, mini=0.5, maxi=0.0)
    assert rapport is not None


@pytest.mark.parametrize("valeur", ["", "abc", None, [], {}])
def test_risk_money_illisible_ne_controle_rien(valeur):
    """Illisible n'est pas << trop faible >> : on ne refuse pas sur une valeur
    qu'on n'a pas su lire."""
    assert bridge._controle_risque(12.0, valeur, mini=0.5, maxi=0.0) == (None, None)
