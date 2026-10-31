"""La doublure `MetaTrader5` doit ressembler au VRAI module.

## Pourquoi ce fichier existe

`backend/tests/doublures/metatrader5_absent.py` permet aux cinq fichiers de
tests des garde-fous de risque MT5 de tourner sur Linux (audit IT-1). Mais une
doublure qui ne ressemble pas au vrai est pire que pas de doublure : elle rend
les tests **verts et faux**.

🔑 Et le piège précis est connu : `bridge.py` **compare** ces constantes à ce
que les tests fournissent (`p.type == mt5.POSITION_TYPE_BUY`,
`r.retcode == mt5.TRADE_RETCODE_DONE`). Une valeur fausse ferait passer un test
de garde-fou alors que le garde-fou ne mordrait pas en production.

⛔ **Un témoin doit avoir une source indépendante de l'instrument.** Comparer
la doublure à elle-même donnerait un accord parfait et vide. La source
indépendante, ici, c'est le module **réellement installé** — présent sur tout
poste Windows de développement.

Donc : sur Linux ces comparaisons s'ignorent, en le disant. Sur Windows elles
mordent, et c'est là que la dérive sera vue.
"""
from __future__ import annotations

import importlib
import sys
from unittest import mock
import types
import importlib.util

import pytest

from backend.tests.doublures import metatrader5_absent as doublure

#: Les constantes que `mt5-bridge/bridge.py` lit. Si le pont en utilise une
#: nouvelle, `test_la_doublure_couvre_TOUT_ce_que_le_pont_utilise` le dira.
_CONSTANTES = [
    "DEAL_ENTRY_IN", "DEAL_ENTRY_OUT", "DEAL_ENTRY_OUT_BY",
    "ORDER_FILLING_FOK", "ORDER_FILLING_IOC", "ORDER_FILLING_RETURN",
    "ORDER_TIME_GTC", "ORDER_TYPE_BUY", "ORDER_TYPE_SELL",
    "POSITION_TYPE_BUY", "POSITION_TYPE_SELL", "TIMEFRAME_H1",
    "TRADE_ACTION_DEAL", "TRADE_ACTION_SLTP", "TRADE_RETCODE_DONE",
]

def _le_vrai_module_est_la() -> bool:
    """⛔ `find_spec("MetaTrader5") is not None` ne suffit PAS.

    Une fois la doublure posee dans `sys.modules`, `find_spec` rend SON
    `__spec__` : la reponse est « oui » alors que le vrai module est absent.
    Les comparaisons se faisaient alors doublure contre doublure, et
    passaient toutes — 16 tests verts et vides, livres en CI le 2026-10-31.

    La question juste est donc : y a-t-il un module `MetaTrader5` qui NE
    porte PAS le sceau de la doublure ?
    """
    installe = sys.modules.get("MetaTrader5")
    if installe is not None:
        return not getattr(installe, "EST_UNE_DOUBLURE", False)
    return importlib.util.find_spec("MetaTrader5") is not None


_vrai_dispo = _le_vrai_module_est_la()

_sans_le_vrai = pytest.mark.skipif(
    not _vrai_dispo,
    reason="MOTIF DOCUMENTE : le vrai MetaTrader5 n'existe que sous Windows. "
           "Cette comparaison est la source INDEPENDANTE de verite de la "
           "doublure ; elle mord sur tout poste Windows et en CI Windows. Les "
           "cinq fichiers de garde-fous, eux, TOURNENT sur Linux grace a la "
           "doublure — c'est tout l'objet du correctif IT-1.")


# --- la comparaison au vrai module (Windows) ----------------------------

@_sans_le_vrai
@pytest.mark.parametrize("nom", _CONSTANTES)
def test_chaque_constante_a_la_VRAIE_valeur(nom):
    """⛔ LE test qui compte. `TIMEFRAME_H1 = 16385` ne se devine pas."""
    import MetaTrader5 as vrai
    attendu = getattr(vrai, nom)
    obtenu = getattr(doublure, nom)
    assert obtenu == attendu, (
        "doublure.%s = %r mais le vrai module dit %r. bridge.py COMPARE cette "
        "constante : la corriger dans la doublure, pas ici." % (nom, obtenu, attendu))


@_sans_le_vrai
def test_la_doublure_expose_les_memes_FONCTIONS_que_le_vrai():
    """Une fonction que le pont appelle et que la doublure n'a pas rendrait un
    `AttributeError` sur Linux, pas une erreur lisible."""
    import MetaTrader5 as vrai
    manquantes = [n for n in dir(doublure)
                  if not n.startswith("_") and n not in ("TerminalAbsent",)
                  and callable(getattr(doublure, n))
                  and not hasattr(vrai, n)]
    assert manquantes == [], (
        "la doublure expose des fonctions qui n'existent pas dans le vrai "
        "module : %s" % manquantes)


# --- l'instrument lui-meme, verifiable PARTOUT --------------------------

def test_la_doublure_couvre_TOUT_ce_que_le_pont_utilise():
    """🔑 Verifiable sur Linux comme sur Windows, parce qu'il lit le pont par
    AST et non le module MT5.

    Si quelqu'un ajoute un `mt5.quelque_chose` dans `bridge.py`, la collecte
    repartirait en erreur sur Linux. Ce test le dit AVANT.
    """
    import ast
    import pathlib

    racine = pathlib.Path(__file__).resolve().parents[2]
    src = (racine / "mt5-bridge" / "bridge.py").read_text(
        encoding="utf-8", errors="ignore")
    utilises = {
        n.attr for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.Attribute)
        and isinstance(n.value, ast.Name) and n.value.id == "mt5"
    }
    assert utilises, "aucun usage de mt5.* trouve — l'AST a-t-il change de forme ?"
    absents = sorted(a for a in utilises if not hasattr(doublure, a))
    assert absents == [], (
        "mt5-bridge/bridge.py utilise %d attribut(s) que la doublure n'a pas : "
        "%s\nLes ajouter a backend/tests/doublures/metatrader5_absent.py, en "
        "LISANT leur vraie valeur sur un poste Windows — jamais en l'inventant."
        % (len(absents), absents))


def test_une_fonction_non_doublee_LEVE_au_lieu_de_rendre_None():
    """⛔ Le temoin qui protege du pire scenario : un `None` silencieux ferait
    conclure « aucune position » a un garde-fou, et il ne mordrait pas."""
    with pytest.raises(doublure.TerminalAbsent) as e:
        doublure.positions_get()
    assert "positions_get" in str(e.value)
    msg = str(e.value)
    # le message doit dire QUOI FAIRE, pas seulement que ca a echoue
    assert "remplacer `bridge.mt5`" in msg, (
        "le message doit nommer le geste de reparation : %r" % msg[:160])
    assert "valeur par defaut" in msg, (
        "le message doit dire pourquoi on ne met PAS de valeur par defaut")


@pytest.mark.parametrize("nom", ["order_send", "account_info", "symbol_info",
                                 "positions_total", "order_calc_margin"])
def test_aucune_fonction_ne_rend_une_valeur_par_defaut(nom):
    with pytest.raises(doublure.TerminalAbsent):
        getattr(doublure, nom)()


def test_les_constantes_de_sens_OPPOSE_sont_bien_distinctes():
    """Un copier-coller qui donnerait la meme valeur a BUY et SELL rendrait
    tous les tests de direction verts et vides."""
    assert doublure.POSITION_TYPE_BUY != doublure.POSITION_TYPE_SELL
    assert doublure.ORDER_TYPE_BUY != doublure.ORDER_TYPE_SELL
    assert doublure.DEAL_ENTRY_IN != doublure.DEAL_ENTRY_OUT
    assert doublure.TRADE_ACTION_DEAL != doublure.TRADE_ACTION_SLTP


def test_la_doublure_ne_REMPLACE_pas_le_vrai_module_quand_il_existe():
    """⚠️ Sur Windows, les cinq fichiers doivent continuer de tourner contre le
    VRAI MetaTrader5. La doublure ne s'installe que s'il est absent."""
    import sys
    if not _vrai_dispo:
        pytest.skip("MOTIF DOCUMENTE : sans le vrai module, il n'y a rien a "
                    "ne pas remplacer — le cas teste ici ne peut pas exister.")
    installe = sys.modules.get("MetaTrader5")
    assert installe is not None, "conftest n'a pas laisse MetaTrader5 importable"
    assert getattr(installe, "__version__", "") != doublure.__version__, (
        "la doublure a ete installee a la place du vrai module alors qu'il est "
        "disponible : corriger la condition dans conftest.py")


# --- le garde du SCEAU, qui empeche le defaut de revenir ---------------

def test_un_module_SCELLE_n_est_jamais_pris_pour_le_vrai():
    """⛔ Le defaut livre en CI le 2026-10-31, et son garde.

    `find_spec("MetaTrader5") is not None` rendait VRAI une fois la doublure
    posee dans `sys.modules` — car `find_spec` consulte `sys.modules` avant
    tout. Les 16 comparaisons « Windows seulement » comparaient donc la
    doublure A ELLE-MEME : 16 tests verts et vides.

    🔑 Le piege etait ANNONCE dans la docstring de ce fichier — « comparer la
    doublure a elle-meme donnerait un accord parfait et vide » — et il s'est
    referme quand meme. L'annoncer ne suffit pas : il faut le verifier.

    ⚠️ Et il etait invisible en local parce que mon simulateur de Linux
    forcait `find_spec` a rendre None MEME apres l'installation de la
    doublure. Un temoin plus clement que la realite ne temoigne de rien.
    """
    faux = types.ModuleType("MetaTrader5")
    faux.EST_UNE_DOUBLURE = True
    faux.__spec__ = importlib.util.spec_from_loader("MetaTrader5", loader=None)
    with mock.patch.dict(sys.modules, {"MetaTrader5": faux}):
        assert _le_vrai_module_est_la() is False, (
            "un module portant EST_UNE_DOUBLURE a ete pris pour le vrai : les "
            "comparaisons vont se faire doublure contre doublure")


def test_un_module_NON_scelle_est_bien_pris_pour_le_vrai():
    """Le pendant : la detection ne doit pas devenir aveugle au vrai module,
    sinon les comparaisons ne mordraient plus JAMAIS, nulle part."""
    vrai_ish = types.ModuleType("MetaTrader5")
    vrai_ish.TIMEFRAME_H1 = 16385      # pas de sceau
    with mock.patch.dict(sys.modules, {"MetaTrader5": vrai_ish}):
        assert _le_vrai_module_est_la() is True


def test_la_doublure_livree_PORTE_bien_son_sceau():
    """Si le sceau disparaissait du fichier de doublure, la detection
    redeviendrait fausse en silence."""
    assert getattr(doublure, "EST_UNE_DOUBLURE", False) is True, (
        "backend/tests/doublures/metatrader5_absent.py a perdu son sceau "
        "EST_UNE_DOUBLURE : les comparaisons vont repasser a vide")
