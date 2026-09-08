"""Les deux portes posées le 08/09 pour l'or du compte réel.

Xavier voulait plus de trades or. La mesure a montré que le verrou n'était pas
un edge négatif mais une **file d'attente à une place**
(`max_correlated_positions=1`), et qu'en l'ouvrant sans rien d'autre le pire
cas passait de 9,2 % à 18 % du capital — pour une limite de perte journalière
de 3 %.

⛔ Les deux portes ont donc été posées ENSEMBLE, et un test l'exige : une
dérogation de concurrence sans plafond par trade serait une régression de
sécurité, pas une amélioration.
"""
from __future__ import annotations

import ast
import io
from dataclasses import dataclass

import pytest

from backend.services import correlation_guard as cg
from backend.services import porte_risque_par_trade as prt


@dataclass
class SetupFictif:
    pair: str
    direction: str
    entry_price: float
    stop_loss: float


@dataclass
class DestFictive:
    destination_id: str = "admin_live"
    bridge_type: str = "mt5"


# ── Le plafond de risque par trade ───────────────────────────────────

def _capital(monkeypatch, valeur):
    import backend.services.sizing as sz
    monkeypatch.setattr(sz, "destination_capital", lambda d: (valeur, "test"))


def test_un_stop_LARGE_sur_l_or_est_refuse(monkeypatch):
    """⛔ Le cas mesuré : 0,01 lot d'or avec un stop à ~76 $ engageait
    65,64 € sur un compte de 710 € — 9,2 %, quand la journée est bornée à 3 %."""
    _capital(monkeypatch, 650.0)
    s = SetupFictif("XAU/USD", "buy", 3400.0, 3300.0)      # 100 $ de stop
    assert prt.refus(s, DestFictive()) == prt.MOTIF


def test_un_stop_SERRE_passe(monkeypatch):
    _capital(monkeypatch, 650.0)
    s = SetupFictif("XAU/USD", "buy", 3400.0, 3390.0)      # 10 $ de stop
    assert prt.refus(s, DestFictive()) is None


def test_le_calcul_porte_sur_le_LOT_MINIMUM():
    """🔑 Les 21 trades or sont partis à 0,01 lot — le plancher du courtier.
    Le dimensionnement calcule moins, mais le bridge remonte : le risque réel
    n'est pas choisi, il est subi. Juger la taille demandée raterait le sujet."""
    assert prt.LOT_MINIMUM["mt5"] == 0.01
    s = SetupFictif("XAU/USD", "buy", 3400.0, 3300.0)
    r = prt.risque_au_lot_minimum(s, DestFictive())
    # 100 $ × 0,01 lot × 100 oz = 100 $, soit ~86 € — l'ordre de grandeur du
    # cas réel (65,64 € pour un stop de ~76 $).
    assert r is not None and 70.0 < r < 100.0


def test_KRAKEN_est_HORS_de_cette_porte():
    """⚠️ Sur Kraken le volume est une quantité à granularité fine : le
    dimensionnement y descend vraiment, le plancher ne mord pas. Poser la porte
    là refuserait des trades correctement dimensionnés."""
    s = SetupFictif("XAU/USD", "buy", 3400.0, 3300.0)
    assert prt.risque_au_lot_minimum(s, DestFictive(bridge_type="kraken")) is None
    assert prt.refus(s, DestFictive(bridge_type="kraken")) is None


def test_un_capital_ILLISIBLE_ne_bloque_PAS(monkeypatch):
    """⛔ Fail-ouvert délibéré. Cette porte s'ajoute par-dessus des portes
    existantes ; la rendre bloquante sur l'inconnu couperait tout le flux le
    jour où le capital devient illisible, pour un défaut qui n'est pas le
    sien. Le risque NON BORNÉ, lui, est déjà refusé en amont."""
    _capital(monkeypatch, None)
    s = SetupFictif("XAU/USD", "buy", 3400.0, 3300.0)
    assert prt.refus(s, DestFictive()) is None


def test_un_prix_ABSENT_ne_bloque_pas(monkeypatch):
    _capital(monkeypatch, 650.0)
    assert prt.refus(SetupFictif("XAU/USD", "buy", 0.0, 0.0), DestFictive()) is None


def test_la_porte_est_CABLEE_dans_la_chaine_d_admission():
    """⛔ Une porte écrite mais jamais appelée est un commentaire.

    ⚠️ Première version fausse : elle comparait `str.index()` sur le fichier
    entier, qui trouvait la DÉFINITION de `_cost_rejection` (ligne ~460) et non
    son appel. Elle échouait sur du code juste. On lit donc la fonction
    d'admission elle-même, par AST.
    """
    src = io.open("backend/services/mt5_bridge.py", encoding="utf-8").read()
    arbre = ast.parse(src)

    def appelle(fn, nom):
        return [n.lineno for n in ast.walk(fn)
                if isinstance(n, ast.Call) and getattr(n.func, "id", None) == nom]

    chaines = [fn for fn in ast.walk(arbre)
               if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
               and appelle(fn, "_cost_rejection")]
    assert chaines, "aucune fonction n'appelle la porte de coût"

    for fn in chaines:
        importe = [n.lineno for n in ast.walk(fn)
                   if isinstance(n, ast.ImportFrom)
                   and (n.module or "").endswith("porte_risque_par_trade")]
        assert importe, f"{fn.name}() n'appelle pas la porte de risque par trade"
        # Avant la porte de coût, qui appelle en plus le sizing complet.
        assert min(importe) < min(appelle(fn, "_cost_rejection")), (
            "le plafond par trade doit précéder la porte de coût")


def test_le_motif_de_refus_est_TRADUIT():
    """⚠️ Un code non traduit s'affiche brut dans les récaps et les messages."""
    from backend.services.rejection_service import REASON_LABELS_FR
    assert prt.MOTIF in REASON_LABELS_FR


# ── La dérogation de concurrence sur l'or ────────────────────────────

def test_l_or_du_REEL_a_DEUX_places():
    assert cg.limite(DestFictive(), "XAU/USD") == 2


def test_les_AUTRES_paires_du_reel_gardent_UNE_place():
    """⛔ Pas un relèvement global : doubler la concurrence sur le forex et la
    crypto n'est justifié par aucune mesure."""
    assert cg.limite(DestFictive(), "EUR/USD") == 1
    assert cg.limite(DestFictive()) == 1


def test_l_or_des_AUTRES_comptes_garde_UNE_place():
    assert cg.limite(DestFictive(destination_id="admin_kraken"), "XAU/USD") == 1
    assert cg.limite(DestFictive(destination_id="admin_legacy"), "XAU/USD") == 1


def test_les_appelants_TRANSMETTENT_la_paire():
    """⛔ Une porte posée d'un seul côté n'est pas une porte : sans la paire,
    la dérogation ne serait jamais consultée et le test ci-dessus passerait
    quand même — il appelle `limite()` directement."""
    src = io.open("backend/services/correlation_guard.py", encoding="utf-8").read()
    arbre = ast.parse(src)
    for fn in ast.walk(arbre):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "limite":
                assert len(n.args) >= 2, (
                    f"{fn.name}() appelle limite() sans la paire — "
                    "la dérogation serait ignorée")


# ── L'invariant qui lie les deux ─────────────────────────────────────

def test_AUCUNE_derogation_de_concurrence_sans_plafond_par_trade():
    """⛔ LA règle du 08/09. Deux positions or simultanées portaient le pire
    cas de 9,2 % à 18 % du capital. La dérogation n'est acceptable QUE parce
    que le plafond par trade la borne.

    🔑 Propriété, pas liste : une dérogation ajoutée demain pour une autre
    paire fera échouer ce test si quelqu'un a désarmé le plafond.
    """
    if not cg.LIMITE_PAR_PAIRE:
        pytest.skip("aucune dérogation déclarée")
    assert prt.PLAFOND_PCT > 0, (
        "des dérogations de concurrence existent alors que le plafond de "
        "risque par trade est désarmé — le pire cas double sans contrepartie")
    for (compte, paire), n in cg.LIMITE_PAR_PAIRE.items():
        assert n <= 2, f"{compte}:{paire} à {n} places — non mesuré"
