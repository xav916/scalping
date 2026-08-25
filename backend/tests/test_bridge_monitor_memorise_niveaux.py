"""Le monitor doit se souvenir des niveaux UN TOUR de plus que la position.

⛔ Pourquoi ce test existe. `test_bridge_close_reason_audit` verrouille ce que
`_log_closed_position` ECRIT quand on lui passe des niveaux — mais rien ne
verrouillait le fait qu'on les lui PASSE. Or c'est là que tout se joue : à
l'instant où le monitor constate la disparition d'un ticket, la position
n'existe plus et MT5 ne rendra jamais ses SL/TP. La seule fenêtre est le tour
PRÉCÉDENT.

Un test qui ne couvre que l'écriture laisserait passer une boucle qui appelle
`_log_closed_position(t)` sans second argument : les colonnes resteraient vides
et tout aurait l'air de fonctionner. Le silence ressemblerait au succès.

Le corps de la boucle est lu dans le source à l'exécution, comme les autres
tests du bridge : un renommage fait échouer, ce n'est pas une réimplémentation.

Cf. [[project_analyse_clotures_main_2026_08_24]]
"""
import threading
import types
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "mt5-bridge" / "bridge.py"


class _Position:
    def __init__(self, ticket, sl, tp, symbol="XAUUSD"):
        self.ticket = ticket
        self.sl = sl
        self.tp = tp
        self.symbol = symbol


class _FauxMT5:
    """Rend une liste de positions différente à chaque tour du monitor."""

    def __init__(self, tours):
        self._tours = list(tours)
        self.appels = 0

    def positions_get(self):
        i = min(self.appels, len(self._tours) - 1)
        self.appels += 1
        return self._tours[i]


def _boucler(tours, n_tours):
    """Déroule `_position_monitor_loop` sur `n_tours` puis l'arrête.

    Rend la liste des appels à `_log_closed_position` : [(ticket, niveaux), ...]
    """
    src = _SRC.read_text(encoding="utf-8")
    corps = src[src.index("def _position_monitor_loop("):
                src.index("def _decalage_serveur_sec(")]

    module = types.ModuleType("bridge_boucle")
    fermetures = []
    stop = threading.Event()
    compteur = {"n": 0}

    def _wait(timeout=None):
        """Tient lieu d'attente ET de compteur de tours : la boucle sort quand
        le quota est atteint, sans jamais dormir."""
        compteur["n"] += 1
        if compteur["n"] >= n_tours:
            stop.set()
            return True
        return False

    stop.wait = _wait

    module.__dict__.update({
        "mt5": _FauxMT5(tours),
        "logger": types.SimpleNamespace(
            info=lambda *a, **k: None, warning=lambda *a, **k: None,
            debug=lambda *a, **k: None),
        "_monitor_stop": stop,
        "_last_known_tickets": set(),
        "_derniers_niveaux": {},
        "_breakeven_applied": set(),
        "_position_meta": {},
        "_cleanup_closed_meta": lambda ouverts: None,
        "_maybe_partial_close_and_trail": lambda p: None,
        "_maybe_move_to_breakeven": lambda p: None,
        "ensure_mt5_connected": lambda: True,
        "_log_closed_position": lambda t, niveaux=None: fermetures.append((t, niveaux)),
        "MONITOR_INTERVAL_SEC": 0,
        "BREAKEVEN_TRIGGER_PCT": 75,
        "PARTIAL_CLOSE_PCT": 50,
        "TRAIL_DISTANCE_POINTS": 0,
    })
    exec(compile(corps, str(_SRC), "exec"), module.__dict__)
    module._position_monitor_loop()
    return fermetures, module


def test_les_niveaux_du_tour_precedent_accompagnent_la_cloture():
    """Le cas nominal : la position est vue vivante, puis disparaît."""
    fermetures, _ = _boucler(
        tours=[[_Position(42, sl=4104.23, tp=4085.13)], []],
        n_tours=3,
    )

    assert [t for t, _ in fermetures] == [42]
    _, niveaux = fermetures[0]
    assert niveaux is not None, (
        "sans second argument, les colonnes resteraient vides en silence")
    assert niveaux["sl_at_close"] == 4104.23
    assert niveaux["tp_at_close"] == 4085.13
    assert niveaux["niveaux_source"] == "monitor"


def test_c_est_le_DERNIER_niveau_vu_qui_compte_pas_le_premier():
    """Le cœur du sujet : un stop déplacé en cours de route.

    C'est exactement ce que la base ne savait pas voir — elle gardait le niveau
    d'origine. Si la mémoire rendait le premier vu, la colonne reproduirait le
    défaut qu'elle est censée corriger.
    """
    fermetures, _ = _boucler(
        tours=[
            [_Position(7, sl=4104.23, tp=4085.13)],   # à l'ouverture
            [_Position(7, sl=4785.05, tp=4095.00)],   # stop remonté à la main
            [],                                        # fermée
        ],
        n_tours=4,
    )

    assert [t for t, _ in fermetures] == [7]
    niveaux = fermetures[0][1]
    assert niveaux["sl_at_close"] == 4785.05, "le niveau d'ORIGINE a survécu"
    assert niveaux["tp_at_close"] == 4095.00


def test_la_memoire_ne_grossit_pas_indefiniment():
    """Un ticket fermé doit sortir de la mémoire, sinon le bridge fuit sur des
    mois de fonctionnement continu."""
    _, module = _boucler(
        tours=[[_Position(1, 1.0, 2.0), _Position(2, 3.0, 4.0)],
               [_Position(2, 3.0, 4.0)],
               []],
        n_tours=4,
    )

    assert module._derniers_niveaux == {}, "les tickets fermés doivent être purgés"


def test_une_position_sans_stop_ne_fabrique_pas_un_niveau_a_zero():
    """MT5 rend `sl = 0.0` pour « aucun stop ». Le monitor le transporte tel
    quel — c'est `_log_closed_position` qui refuse de l'écrire — mais il ne doit
    surtout pas le transformer en autre chose au passage."""
    fermetures, _ = _boucler(
        tours=[[_Position(99, sl=0.0, tp=0.0)], []],
        n_tours=3,
    )

    niveaux = fermetures[0][1]
    assert niveaux["sl_at_close"] == 0.0
    assert niveaux["tp_at_close"] == 0.0
