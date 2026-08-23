"""Remonter le stop a l'EQUILIBRE pour laisser passer un trade (2026-08-23).

Demande par Xavier : plutot que refuser un setup faute de place sous les 6 %,
remonter a l'entree le stop de positions deja gagnantes. Leur risque tombe a
zero sans rien fermer, sans payer de spread, sans tronquer leur potentiel.

⚠️ **Ce mecanisme est de la GESTION DE SORTIE** — la famille qui a mesure
−0,329 R par trade sur l'or. J'ai recommande contre ; Xavier a tranche. Ce
qui est verrouille ici, ce sont les trois facons dont il pourrait nuire :

1. **toucher une position pas assez en profit** — un stop a l'equilibre colle
   au marche se fait sortir par le bruit. C'est EXACTEMENT le suiveur. La
   marge minimale (`EQUILIBRE_MARGE_R`) est le seul rempart ;
2. **reculer un stop**, donc AUGMENTER le risque d'une position ;
3. **deplacer des stops pour rien** — si l'ensemble des candidats ne suffit
   pas a couvrir le manque, l'ordre sera refuse quand meme et on aura abime
   des positions sans contrepartie.

`bridge.py` importe MetaTrader5, absent hors du VPS : on extrait les fonctions
du source et on les execute seules.
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "mt5-bridge" / "bridge.py"


@pytest.fixture(scope="module")
def m():
    src = _SRC.read_text(encoding="utf-8")
    debut = src.index("def _risque_realise(")
    fin = src.index("def _remonter_a_l_equilibre(")
    mod = types.ModuleType("bridge_equilibre")
    exec(compile(src[debut:fin], str(_SRC), "exec"), mod.__dict__)
    return mod


class _Pos:
    def __init__(self, ticket, symbol, price_open, sl, volume, price_current,
                 type_=0):
        self.ticket, self.symbol = ticket, symbol
        self.price_open, self.sl, self.volume = price_open, sl, volume
        self.price_current, self.type = price_current, type_


class _Info:
    point, trade_tick_value = 0.00001, 1.0


def _specs(_):
    return _Info()


# --------------------------------------------------------------------------
# La mesure du coussin de profit
# --------------------------------------------------------------------------

def test_marge_en_R_dun_achat(m):
    """Entree 1,10000, stop 1,09500 (50 pts de risque), prix 1,10500."""
    p = _Pos(1, "EURUSD", 1.10000, 1.09500, 0.10, 1.10500)
    assert m._marge_de_profit_r(p, _Info()) == pytest.approx(1.0)


def test_marge_en_R_dune_VENTE(m):
    """Le sens s'inverse : le profit est SOUS l'entree."""
    p = _Pos(1, "EURUSD", 1.10000, 1.10500, 0.10, 1.09500, type_=1)
    assert m._marge_de_profit_r(p, _Info()) == pytest.approx(1.0)


def test_position_en_PERTE_a_une_marge_negative(m):
    p = _Pos(1, "EURUSD", 1.10000, 1.09500, 0.10, 1.09800)
    assert m._marge_de_profit_r(p, _Info()) < 0


def test_marge_indisponible_rend_None_pas_zero(m):
    """⚠️ 0.0 se confondrait avec « pile a l'entree » et rendrait la
    position eligible a tort."""
    assert m._marge_de_profit_r(
        _Pos(1, "EURUSD", 1.10, 0.0, 0.10, 1.11), _Info()) is None
    assert m._marge_de_profit_r(
        _Pos(1, "EURUSD", 1.10, 1.09, 0.10, 0.0), _Info()) is None


# --------------------------------------------------------------------------
# ⛔ Le rempart : ne PAS toucher une position trop juste
# --------------------------------------------------------------------------

def test_une_position_a_peine_gagnante_est_ECARTEE(m):
    """⛔ Le cas qui transformerait ce mecanisme en suiveur.

    +0,3 R de profit : un stop a l'equilibre serait a 30 % de la distance de
    bruit. On n'y touche pas.
    """
    p = _Pos(1, "EURUSD", 1.10000, 1.09500, 0.10, 1.10150)   # +0,3 R
    assert m._candidats_equilibre([p], _specs, 1.0) == []


def test_une_position_EN_PERTE_est_ecartee(m):
    p = _Pos(1, "EURUSD", 1.10000, 1.09500, 0.10, 1.09800)
    assert m._candidats_equilibre([p], _specs, 1.0) == []


def test_le_seuil_est_inclusif(m):
    """Exactement 1,0 R acquis suffit."""
    p = _Pos(1, "EURUSD", 1.10000, 1.09500, 0.10, 1.10500)
    assert len(m._candidats_equilibre([p], _specs, 1.0)) == 1


def test_une_position_SANS_STOP_n_est_jamais_candidate(m):
    """Son risque n'est pas bornable ; poser un stop ici serait un autre
    mecanisme, pas celui-ci."""
    p = _Pos(1, "EURUSD", 1.10000, 0.0, 0.10, 1.20000)
    assert m._candidats_equilibre([p], _specs, 1.0) == []


def test_une_position_DEJA_a_l_equilibre_n_est_pas_candidate(m):
    """Elle ne libererait rien : son risque vaut deja zero."""
    p = _Pos(1, "EURUSD", 1.10000, 1.10000, 0.10, 1.11000)
    assert m._candidats_equilibre([p], _specs, 1.0) == []


# --------------------------------------------------------------------------
# Le choix : le MOINS de positions touchees possible
# --------------------------------------------------------------------------

def test_les_plus_generreuses_d_abord(m):
    """Une seule position suffit : on n'en touche pas trois."""
    petite = _Pos(1, "EURUSD", 1.10000, 1.09900, 0.10, 1.10300)   # 10 EUR
    grosse = _Pos(2, "EURUSD", 1.10000, 1.09000, 0.10, 1.12000)   # 100 EUR
    cands = m._candidats_equilibre([petite, grosse], _specs, 1.0)
    assert [c["ticket"] for c in cands] == [2, 1]
    assert [c["ticket"] for c in m._choisir_pour_liberer(cands, 50.0)] == [2]


def test_plusieurs_positions_quand_une_ne_suffit_pas(m):
    a = _Pos(1, "EURUSD", 1.10000, 1.09500, 0.10, 1.11000)   # 50 EUR
    b = _Pos(2, "EURUSD", 1.10000, 1.09500, 0.10, 1.11000)   # 50 EUR
    cands = m._candidats_equilibre([a, b], _specs, 1.0)
    assert len(m._choisir_pour_liberer(cands, 80.0)) == 2


def test_RIEN_n_est_touche_si_ca_ne_suffit_pas(m):
    """⛔ Le garde-fou le plus important de la selection.

    Deplacer des stops pour un ordre qui sera refuse quand meme, c'est abimer
    des positions sans aucune contrepartie.
    """
    a = _Pos(1, "EURUSD", 1.10000, 1.09500, 0.10, 1.11000)   # 50 EUR
    cands = m._candidats_equilibre([a], _specs, 1.0)
    assert cands, "la position devrait etre candidate"
    assert m._choisir_pour_liberer(cands, 500.0) == []


def test_aucun_manque_aucun_mouvement(m):
    a = _Pos(1, "EURUSD", 1.10000, 1.09500, 0.10, 1.11000)
    cands = m._candidats_equilibre([a], _specs, 1.0)
    assert m._choisir_pour_liberer(cands, 0.0) == []
    assert m._choisir_pour_liberer(cands, -10.0) == []


def test_le_risque_libere_est_le_risque_REEL_de_la_position(m):
    """C'est lui qu'on soustrait au total : une erreur ici ferait passer un
    ordre qui ne devrait pas passer."""
    p = _Pos(1, "EURUSD", 1.10000, 1.09500, 0.10, 1.11000)
    c = m._candidats_equilibre([p], _specs, 1.0)[0]
    assert c["risque_libere"] == pytest.approx(
        m._risque_position(p, _Info()))
    assert c["risque_libere"] == pytest.approx(50.0)


def test_le_sens_VENTE_est_traite_dans_la_selection(m):
    """Une vente gagnante doit etre candidate au meme titre qu'un achat."""
    v = _Pos(1, "EURUSD", 1.10000, 1.10500, 0.10, 1.09000, type_=1)
    cands = m._candidats_equilibre([v], _specs, 1.0)
    assert len(cands) == 1 and cands[0]["risque_libere"] == pytest.approx(50.0)


# --------------------------------------------------------------------------
# ⛔ A L'EQUILIBRE, JAMAIS AU-DELA (question tranchee le 2026-08-23)
#
# « Vaut-il mieux poser le stop a l'equilibre ou a un niveau positif ? »
# Reponse : a l'equilibre. Un stop qui verrouille un GAIN ne libere pas un
# euro de plus — `_distance_perdante` clampe a zero, donc les deux rendent un
# risque nul (cf. test_stop_AU_DELA_de_l_equilibre_ne_compte_pas_un_risque_
# fantome dans test_bridge_risque_engage.py). Il ne fait que rapprocher le
# stop du marche, donc augmenter la chance d'une sortie par le bruit : c'est
# la definition d'un suiveur, la famille mesuree a -0,329 R sur l'or.
#
# ⚠️ Le spread n'est PAS un argument pour decaler : mesure le 23/08 sur 4
# positions reelles, `price_current` d'un ACHAT vaut exactement le BID, et
# `price_open` est l'ask du fill. Un stop a `price_open` rend donc un
# resultat de zero EXACT — le spread est deja dans le compte. Commission
# nulle et swap negligeable sur ces comptes (mesure sur 191 trades).
#
# Ces tests verrouillent la decision pour qu'une session future ne la
# « ameliore » pas en prise de profit deguisee.
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def poseur():
    """`_remonter_a_l_equilibre` avec le courtier remplace par des doublures.

    Elle n'etait couverte par aucun test alors que c'est **elle** qui deplace
    des stops en argent reel : les trois autres fonctions sont pures.
    """
    src = _SRC.read_text(encoding="utf-8")
    debut = src.index("def _risque_realise(")
    fin = src.index("def _controle_marge_libre(")
    mod = types.ModuleType("bridge_poseur")
    exec(compile(src[debut:fin], str(_SRC), "exec"), mod.__dict__)

    mod.logger = types.SimpleNamespace(
        info=lambda *a, **k: None, warning=lambda *a, **k: None)
    mod.poses = []

    def _apply(symbol, ticket, new_sl, new_tp):
        mod.poses.append({"ticket": ticket, "sl": new_sl})
        return {"ok": True}

    mod._apply_stops = _apply
    # Par defaut le courtier accepte le niveau demande tel quel.
    mod._clamp_stops = lambda symbol, is_buy, new_sl, new_tp: (new_sl, new_tp)
    return mod


def _pose(poseur, position, clamp=None):
    poseur.poses.clear()
    if clamp is not None:
        poseur._clamp_stops = clamp
    else:
        poseur._clamp_stops = lambda s, b, sl, tp: (sl, tp)
    retenus = poseur._candidats_equilibre([position], _specs, 1.0)
    faits = poseur._remonter_a_l_equilibre(retenus, [position])
    return faits, list(poseur.poses)


def test_le_stop_pose_est_EXACTEMENT_l_entree_pas_au_dela(poseur):
    """Un achat tres gagnant : le stop va a l'entree, pas plus haut."""
    a = _Pos(1, "EURUSD", 1.10000, 1.09500, 0.10, 1.15000)
    faits, poses = _pose(poseur, a)
    assert len(poses) == 1
    assert poses[0]["sl"] == pytest.approx(1.10000)
    assert faits[0]["reste_a_risque"] == pytest.approx(0.0)


def test_le_stop_pose_est_EXACTEMENT_l_entree_sur_une_VENTE(poseur):
    v = _Pos(1, "EURUSD", 1.10000, 1.10500, 0.10, 1.05000, type_=1)
    faits, poses = _pose(poseur, v)
    assert len(poses) == 1
    assert poses[0]["sl"] == pytest.approx(1.10000)


def test_un_stop_qui_VERROUILLERAIT_UN_GAIN_est_REFUSE(poseur):
    """⛔ Le garde-fou du 23/08.

    Si le clamp rendait un niveau au-dela de l'entree, on aurait une prise de
    profit deguisee : zero euro de budget en plus, et un stop colle au
    marche. On refuse et on laisse la position INTACTE.
    """
    a = _Pos(1, "EURUSD", 1.10000, 1.09500, 0.10, 1.15000)
    faits, poses = _pose(poseur, a, clamp=lambda s, b, sl, tp: (1.12000, tp))
    assert poses == [], "un gain verrouille a ete pose"
    assert faits == []


def test_un_stop_qui_verrouillerait_un_gain_est_refuse_en_VENTE(poseur):
    v = _Pos(1, "EURUSD", 1.10000, 1.10500, 0.10, 1.05000, type_=1)
    faits, poses = _pose(poseur, v, clamp=lambda s, b, sl, tp: (1.08000, tp))
    assert poses == [] and faits == []


def test_un_clamp_qui_laisse_du_risque_est_ACCEPTE_mais_trace(poseur):
    """Le courtier peut refuser un stop trop proche : on prend ce qu'on
    obtient, mais `reste_a_risque` doit le DIRE au lieu de pretendre zero."""
    a = _Pos(1, "EURUSD", 1.10000, 1.09500, 0.10, 1.15000)
    faits, poses = _pose(poseur, a, clamp=lambda s, b, sl, tp: (1.09800, tp))
    assert poses[0]["sl"] == pytest.approx(1.09800)
    assert faits[0]["reste_a_risque"] == pytest.approx(0.00200)


def test_un_stop_qui_RECULE_est_toujours_refuse(poseur):
    """Le garde-fou existant ne doit pas avoir ete casse par le nouveau."""
    a = _Pos(1, "EURUSD", 1.10000, 1.09500, 0.10, 1.15000)
    faits, poses = _pose(poseur, a, clamp=lambda s, b, sl, tp: (1.09000, tp))
    assert poses == [] and faits == []
