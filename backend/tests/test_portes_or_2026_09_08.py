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


# ── Les 15 % réservés à l'OR SEUL (2026-09-08) ───────────────────────
#
# Xavier : « un risque cumulé engagé à 20 % du capital dont 15 % réservés
# uniquement à l'or ». Le total de 20 % existait déjà ; ce qui change est la
# PORTÉE de la poche des 15 %, dont l'argent sort.

def _bloc_poches(argent_dans_la_poche_or: bool):
    """Exécute le bloc des poches du bridge MT5, seul.

    ⚠️ `mt5-bridge/bridge.py` importe MetaTrader5, absent des tests. Le dépôt
    en extrait donc les fonctions depuis la source — même méthode ici.

    ⛔ Le drapeau est INJECTÉ, pas lu dans l'environnement : le bloc consulte
    `globals()`, parce que douze fichiers de tests l'exécutent sans `os`. Un
    `os.getenv` à cet endroit cassait 66 tests sur du code juste.
    """
    src = io.open("mt5-bridge/bridge.py", encoding="utf-8").read()
    debut = src.index("# ⛔ L'etiquette SUIT le contenu.")
    fin = src.index("# MT5 : POSITION_TYPE_BUY")
    ns: dict = {"_ARGENT_DANS_LA_POCHE_OR": argent_dans_la_poche_or}
    exec(compile(src[debut:fin], "bloc_poches", "exec"), ns)
    return ns


def test_l_ARGENT_sort_de_la_poche_des_15_pct():
    ns = _bloc_poches(False)
    assert ns["_poche_du_symbole"]("XAUUSD") == "or"
    assert ns["_poche_du_symbole"]("XAGUSD") == "autres"
    assert ns["_poche_du_symbole"]("EURUSD") == "autres"


def test_l_etiquette_de_la_poche_SUIT_son_contenu():
    """⛔ Un nom qui ment est pire qu'un nom absent : `/health`, le détail des
    poches et les messages Telegram sont tous alimentés par cette chaîne."""
    assert _bloc_poches(False)["_POCHE_OR_ARGENT"] == "or"
    assert _bloc_poches(True)["_POCHE_OR_ARGENT"] == "or_argent"


def test_l_etat_d_avant_reste_ATTEIGNABLE_sans_redeploiement():
    """🔑 Une décision qui s'est déjà inversée une fois doit pouvoir se
    re-inverser — l'argent est entré dans cette poche le 28/08, il en sort le
    08/09."""
    ns = _bloc_poches(True)
    assert ns["_poche_du_symbole"]("XAGUSD") == "or_argent"


def test_le_total_reste_a_20_pct():
    """⚠️ 5 % + 15 % = 20 %. Les deux réglages vivent dans le bridge et rien
    ne les additionne : un test le fait."""
    src = io.open("mt5-bridge/bridge.py", encoding="utf-8").read()
    import re
    autres = float(re.search(r'MAX_RISQUE_ENGAGE_PCT[^\n]*?"([\d.]+)"', src).group(1))
    metaux = float(re.search(r'or\s*"([\d.]+)"\s*\)', src).group(1))
    assert autres + metaux == 20.0, (autres, metaux)
    assert metaux == 15.0


def test_le_bloc_de_risque_reconnait_les_DEUX_etiquettes():
    """⛔ Épingler « or_argent » ferait disparaître la ligne « Or » du message
    le jour de la bascule — un affichage muet, sans erreur."""
    for nom in ("or", "or_argent"):
        etat = {"lisible": True, "desarme": False, "indecidable": False,
                "engage_eur": 20.0, "plafond_eur": 97.5, "restant_eur": 22.5,
                "pct": 30.0, "poche": nom, "positions": 2,
                "metaux": {"libre_eur": 80.0, "pct": 18.0,
                           "plafond_eur": 97.5, "nom": nom},
                "converti": False, "taux_vivant": True}
        from backend.services.bloc_risque import lignes
        texte = "\n".join(lignes(etat))
        assert "🥇 Or" in texte, nom
        assert nom.replace("_", "/") in texte, nom


# ── La taille de contrat de l'ARGENT (2026-09-08) ────────────────────

def test_l_argent_ne_partage_PAS_la_taille_de_contrat_de_l_or():
    """⛔ Défaut trouvé le 08/09 : `TAILLE_CONTRAT_MT5` est indexée par CLASSE,
    et or comme argent y valent « metal ». Le risque de l'argent était donc
    sous-estimé d'un facteur 10.

    🔑 Dérivé des trades réels — `contrat = pnl / ((sortie−entrée) × sens ×
    volume)` — : 100,4 sur 21 trades or (table : 100 ✅) et **1 002,4 sur
    9 trades argent** (table : 100 ⛔).
    """
    from backend.services.risk_eur import taille_contrat
    assert taille_contrat("XAU/USD", "mt5") == 100
    assert taille_contrat("XAG/USD", "mt5") == 1000


def test_le_risque_d_un_lot_d_argent_est_VRAISEMBLABLE():
    """La borne qui aurait attrapé les 0,25 €."""
    from backend.services.risk_eur import calculer
    r = calculer(pair="XAG/USD", entry=48.0, sl=47.7, tp=48.54,
                 volume=0.01, bridge_type="mt5")
    assert 1.5 <= r["risque_eur"] <= 6.0, r


# ── Le fail-OUVERT de `limite()` (2026-09-08) ────────────────────────
#
# ⛔ Trouvé en vérifiant mon propre travail : j'avais passé un `Destination` du
# registre (qui porte `id`) là où le code attend un `BridgeConfig` (qui porte
# `destination_id`). `limite()` rendait alors **0 = illimité** pour les six
# comptes — le garde-fou de concentration se désarmait tout seul, en silence,
# sur un chemin d'argent réel.

@dataclass
class DestRegistreFictive:
    """Le `Destination` du registre : il porte `id`, pas `destination_id`."""
    id: str = "admin_live"
    max_correlated_positions: int = 1


def test_un_objet_du_REGISTRE_ne_desarme_plus_le_garde_fou():
    """⛔ LE défaut. Avant : 0, c'est-à-dire illimité, sans une ligne de log."""
    assert cg.limite(DestRegistreFictive()) == 1


def test_la_derogation_marche_AUSSI_avec_l_objet_du_registre():
    """⚠️ Sans résolution de l'identifiant, la clé de dérogation était ('', …)
    et ne correspondait à rien : la dérogation était muette, elle aussi."""
    assert cg.limite(DestRegistreFictive(), "XAU/USD") == 2


def test_une_destination_INCONNUE_ne_rend_JAMAIS_l_illimite():
    """🔑 Les deux destinations réellement illimitées (`user:N`,
    `admin_binance`) sont DÉCLARÉES à 0 et passent par le registre. Le chemin
    « inconnu » ne sert donc qu'aux bugs : le fermer ne casse rien de
    légitime."""
    assert cg.limite(DestFictive(destination_id="admin_martien")) == cg.LIMITE_INCONNUE
    assert cg.LIMITE_INCONNUE >= 1


def test_l_illimite_DECLARE_est_preserve():
    """⛔ Le contre-test : fermer le trou ne doit pas fermer ce qui est ouvert
    exprès. `user:N` sert les comptes clients."""
    assert cg.limite(DestFictive(destination_id="user:2")) == 0


def test_dest_None_garde_son_contrat():
    """⚠️ Documenté : ce module réduit la concentration, il ne protège pas
    d'une panne et ne doit pas bloquer sur une panne."""
    assert cg.limite(None) == 0
    assert cg.limite(None, "XAU/USD") == 0


def test_la_confusion_de_type_est_JOURNALISEE(caplog):
    """⛔ Un repli silencieux se lit comme un fonctionnement normal. C'est
    précisément ce qui a laissé ce défaut vivre sans être vu."""
    import logging
    with caplog.at_level(logging.WARNING, logger=cg.logger.name):
        cg.limite(DestRegistreFictive())
    assert any("destination_id" in r.message or "destination_id" in r.getMessage()
               for r in caplog.records), caplog.text
