"""Plafond par le RISQUE engagé, et non par le nombre de positions (2026-08-20).

Un compteur traite toutes les positions comme équivalentes alors qu'elles ne
le sont pas : 0,01 lot de forex immobilise ~37 € et risque ~5,5 €, 0,01 lot
d'or immobilise ~191 €. « 3 positions » peut donc valoir 110 € ou 570 €
d'engagement, et le chiffre ne suit pas le capital.

Mesuré avant ce changement : **105 ordres refusés en 30 jours** sur le compte
réel par le seul `MAX_OPEN_POSITIONS=3`, sans que personne ne sache si ces
refus protégeaient quoi que ce soit.

Ce qui est verrouillé ici :
  - le plafond s'ajuste seul selon l'instrument (le forex passe là où l'or est
    refusé, à risque égal) ;
  - une position **sans stop** bloque tout — son risque n'est pas bornable, et
    le confondre avec zéro laisserait passer précisément ce qu'on interdit ;
  - la marge libre reste un garde-fou **secondaire**, qui ne bloque jamais sur
    une donnée manquante.

`bridge.py` importe MetaTrader5, absent hors du VPS : on extrait les fonctions
du source et on les exécute seules.
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "mt5-bridge" / "bridge.py"


@pytest.fixture(scope="module")
def m():
    """Charge les fonctions de risque, sans le module entier."""
    src = _SRC.read_text(encoding="utf-8")
    debut = src.index("def _risque_realise(")
    fin = src.index("def _controle_risque(")
    mod = types.ModuleType("bridge_risque")
    exec(compile(src[debut:fin], str(_SRC), "exec"), mod.__dict__)
    return mod


class _Pos:
    def __init__(self, ticket, symbol, price_open, sl, volume):
        self.ticket = ticket
        self.symbol = symbol
        self.price_open = price_open
        self.sl = sl
        self.volume = volume


class _Info:
    """Specs réalistes d'une paire forex 5 décimales.

    `trade_tick_value` est la valeur d'un point pour **1 lot** (100 000
    unités) : ~1,0 en devise du compte. C'est le lot passé à
    `_risque_realise` qui ramène ensuite à la taille réelle.
    """
    def __init__(self, point=0.00001, tick_value=1.0):
        self.point = point
        self.trade_tick_value = tick_value


def _specs(_symbole):
    return _Info()


# ── La somme des risques ───────────────────────────────────────────────────

def test_somme_des_risques_ouverts(m):
    """GBPUSD 0,01 lot, stop à 89 pips → 8,90 € ; deux positions → 17,80 €."""
    positions = [
        _Pos(1, "GBPUSD", 1.36073, 1.35183, 0.01),
        _Pos(2, "GBPUSD", 1.36012, 1.35122, 0.01),
    ]
    total, nus = m._risque_engage(positions, _specs)
    assert nus == []
    assert total == pytest.approx(17.80, abs=0.05)


def test_aucune_position_vaut_zero(m):
    assert m._risque_engage([], _specs) == (0.0, [])


# ── Le cas qui compte : une position SANS stop ─────────────────────────────

def test_position_sans_stop_est_non_bornable_PAS_nulle(m):
    """La confondre avec un risque nul laisserait passer l'illimité."""
    total, nus = m._risque_engage([_Pos(7, "XAUUSD", 4450.0, 0.0, 0.01)], _specs)
    assert nus == [7]
    assert total == 0.0        # elle n'ajoute rien...


def test_position_sans_stop_BLOQUE_toute_ouverture(m):
    """...mais elle interdit d'ouvrir, ce qui est le comportement voulu."""
    ok, raison = m._controle_risque_engage(
        risque_ouvert=0.0, non_bornables=[7], risque_nouveau=5.0,
        equity=552.0, plafond_pct=6.0)
    assert ok is False
    assert "sans stop" in raison and "7" in raison


# ── Le plafond ─────────────────────────────────────────────────────────────

def test_sous_le_plafond_ca_passe(m):
    ok, raison = m._controle_risque_engage(17.8, [], 5.5, 552.0, 6.0)
    assert ok is True and raison == ""


def test_au_dessus_du_plafond_c_est_refuse(m):
    """6 % de 552 € = 33,12 €. 30 déjà en jeu + 5,5 demandés = 35,5."""
    ok, raison = m._controle_risque_engage(30.0, [], 5.5, 552.0, 6.0)
    assert ok is False
    assert "33.12" in raison and "30.00" in raison


def test_le_plafond_s_ajuste_a_l_instrument(m):
    """À risque égal disponible, le forex passe là où l'or est refusé.

    C'est TOUT l'intérêt du changement : le même « emplacement » vaut 5,5 €
    en forex et 27 € en or.
    """
    assert m._controle_risque_engage(10.0, [], 5.5, 552.0, 6.0)[0] is True
    assert m._controle_risque_engage(10.0, [], 27.0, 552.0, 6.0)[0] is False


def test_le_plafond_grandit_avec_le_capital(m):
    """Le meme ordre passe a 5 000 € ce qu'il ne passe pas a 552 €."""
    assert m._controle_risque_engage(30.0, [], 5.5, 552.0, 6.0)[0] is False
    assert m._controle_risque_engage(30.0, [], 5.5, 5000.0, 6.0)[0] is True


def test_plafond_a_zero_desarme_la_porte(m):
    """Retour au comportement d'avant : seul le compteur agit."""
    ok, _ = m._controle_risque_engage(999.0, [7], None, 0.0, 0.0)
    assert ok is True


@pytest.mark.parametrize("equity", [0.0, None, -5.0])
def test_equity_inconnue_refuse_plutot_que_deviner(m, equity):
    ok, raison = m._controle_risque_engage(0.0, [], 5.0, equity, 6.0)
    assert ok is False and "quity" in raison


def test_risque_du_nouvel_ordre_non_mesurable_refuse(m):
    ok, raison = m._controle_risque_engage(0.0, [], None, 552.0, 6.0)
    assert ok is False and "non mesurable" in raison


# ── La marge libre : garde-fou SECONDAIRE ──────────────────────────────────

def test_marge_suffisante_passe(m):
    ok, _ = m._controle_marge_libre(443.0, 37.0, 554.0, 30.0)
    assert ok is True


def test_marge_insuffisante_refuse(m):
    """30 % de 554 = 166,2. 200 libres − 100 demandés = 100 < 166,2."""
    ok, raison = m._controle_marge_libre(200.0, 100.0, 554.0, 30.0)
    assert ok is False and "166.20" in raison


def test_marge_incalculable_LAISSE_PASSER(m):
    """Secondaire : ne jamais bloquer sur une donnée manquante — la porte
    principale reste le plafond de risque."""
    assert m._controle_marge_libre(443.0, None, 554.0, 30.0)[0] is True
    assert m._controle_marge_libre(None, 37.0, 554.0, 30.0)[0] is True


def test_plancher_a_zero_desarme(m):
    assert m._controle_marge_libre(0.0, 1000.0, 554.0, 0.0)[0] is True


# ── Le BRANCHEMENT : les portes sont-elles vraiment appelées ? ─────────────
#
# Les tests ci-dessus valident des fonctions pures. Ils ne diraient rien si
# `_check_safety_gates` oubliait de les appeler. C'est exactement l'erreur
# commise la veille sur le detecteur de positions nues : une logique correcte,
# jamais atteinte. On charge donc le bridge entier.

import importlib.util  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402


@pytest.fixture()
def bridge(monkeypatch):
    """Instance fraîche du bridge — il porte de l'état mutable au niveau module."""
    nom = f"_bridge_risque_engage_{id(monkeypatch)}"
    spec = importlib.util.spec_from_file_location(nom, _SRC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nom] = mod
    ancien = os.getcwd()
    os.chdir(_SRC.parent)          # bridge.log est ouvert en chemin relatif
    try:
        spec.loader.exec_module(mod)
    finally:
        os.chdir(ancien)
    yield mod
    sys.modules.pop(nom, None)


class _Compte:
    def __init__(self, equity=552.0, margin_free=443.0):
        self.equity = equity
        self.margin_free = margin_free


def _armer(bridge, monkeypatch, positions=(), marge_nouvelle=37.0):
    """Neutralise les portes SANS rapport, garde celles qu'on teste."""
    monkeypatch.setattr(bridge, "_in_trading_hours", lambda: True)
    monkeypatch.setattr(bridge, "_refresh_start_of_day", lambda: None)
    monkeypatch.setattr(bridge, "_start_of_day_balance", None)
    monkeypatch.setattr(bridge.mt5, "account_info", lambda: _Compte())
    monkeypatch.setattr(bridge.mt5, "positions_get", lambda: list(positions))
    monkeypatch.setattr(bridge.mt5, "symbol_info", lambda s: _Info())
    monkeypatch.setattr(bridge.mt5, "order_calc_margin",
                        lambda *a, **k: marge_nouvelle)


def test_sans_details_d_ordre_la_porte_est_SAUTEE(bridge, monkeypatch):
    """Retro-compatibilite : les appelants qui ne decrivent pas l'ordre
    gardent le comportement d'avant."""
    _armer(bridge, monkeypatch)
    assert bridge._check_safety_gates("GBPUSD", "buy") == (True, "OK")


def test_avec_details_un_ordre_raisonnable_passe(bridge, monkeypatch):
    _armer(bridge, monkeypatch)
    ok, raison = bridge._check_safety_gates(
        "GBPUSD", "buy", lots=0.01, entry=1.36073, sl=1.35183)
    assert ok is True, raison


def test_avec_details_un_ordre_TROP_RISQUE_est_refuse(bridge, monkeypatch):
    """LE test de branchement : un stop enorme depasse les 6 % et doit
    etre bloque PAR `_check_safety_gates`, pas ailleurs."""
    monkeypatch.setattr(bridge, "MAX_RISQUE_ENGAGE_PCT", 6.0)
    _armer(bridge, monkeypatch)
    ok, raison = bridge._check_safety_gates(
        "GBPUSD", "buy", lots=0.01, entry=1.36073, sl=1.30000)
    assert ok is False
    assert "Risque engage" in raison


def test_une_position_sans_stop_bloque_via_la_porte(bridge, monkeypatch):
    monkeypatch.setattr(bridge, "MAX_RISQUE_ENGAGE_PCT", 6.0)
    nue = _Pos(77, "XAUUSD", 4450.0, 0.0, 0.01)
    nue.type, nue.time = 0, 0        # pour ne pas declencher l'anti-doublon
    _armer(bridge, monkeypatch, positions=[nue])
    ok, raison = bridge._check_safety_gates(
        "GBPUSD", "buy", lots=0.01, entry=1.36073, sl=1.35183)
    assert ok is False and "sans stop" in raison


def test_la_marge_bloque_quand_le_risque_passe(bridge, monkeypatch):
    """Les deux portes protegent de dangers differents : un stop tres serre
    passe le risque et peut quand meme saturer la marge."""
    monkeypatch.setattr(bridge, "MARGE_LIBRE_MIN_PCT", 30.0)
    _armer(bridge, monkeypatch, marge_nouvelle=400.0)
    ok, raison = bridge._check_safety_gates(
        "GBPUSD", "buy", lots=0.01, entry=1.36073, sl=1.36000)
    assert ok is False and "Marge libre" in raison


# ─── Stop a l'equilibre : le risque vaut VRAIMENT zero (2026-08-23) ────────
#
# Question posee : « peut-on remonter le stop a l'equilibre pour liberer de la
# place sous les 6 % ? » Mesure avant correctif — la reponse etait NON, et
# pour une raison inverse de l'intuition :
#
#   stop a l'equilibre  -> abs(entry - sl) == 0
#                       -> `_risque_realise` rend None (branche « donnee
#                          manquante »)
#                       -> position comptee comme NUE
#                       -> **toute ouverture refusee**, sur un message qui
#                          affirme faussement « Position sans stop »
#
# Le geste cense liberer de la place bloquait donc tout le compte.
#
# > **Zero mesure et zero faute de mesure ne sont pas le meme zero.**
#
# Un stop AU-DELA de l'equilibre comptait, lui, un risque fantome egal a la
# distance du gain verrouille — alors que la position ne peut plus perdre.


def test_stop_A_L_EQUILIBRE_ne_risque_plus_RIEN(m):
    """Le cas qui bloquait tout le compte."""
    p = _Pos(1, "EURUSD", 1.10000, 1.10000, 0.10)
    p.type = 0
    assert m._risque_position(p, _Info()) == 0.0


def test_stop_a_l_equilibre_n_est_PAS_une_position_nue(m):
    """⛔ La consequence qui comptait : elle ne doit bloquer personne."""
    p = _Pos(1, "EURUSD", 1.10000, 1.10000, 0.10)
    p.type = 0
    total, non_bornables = m._risque_engage([p], lambda s: _Info())
    assert non_bornables == [], "une position protegee passait pour nue"
    ok, raison = m._controle_risque_engage(total, non_bornables, 5.0, 556.0, 6.0)
    assert ok is True, raison


def test_stop_AU_DELA_de_l_equilibre_ne_compte_pas_un_risque_fantome(m):
    """Gain verrouille : la position ne peut plus perdre, donc zero."""
    achat = _Pos(1, "EURUSD", 1.10000, 1.10500, 0.10)
    achat.type = 0
    assert m._risque_position(achat, _Info()) == 0.0

    vente = _Pos(2, "EURUSD", 1.10000, 1.09500, 0.10)
    vente.type = 1
    assert m._risque_position(vente, _Info()) == 0.0


def test_le_SENS_de_la_position_est_respecte(m):
    """⚠️ Le meme stop est protecteur a l'achat et dangereux a la vente.

    `abs()` les confondait : c'est la faute de fond, dont le cas a l'equilibre
    n'etait que la manifestation la plus visible.
    """
    achat = _Pos(1, "EURUSD", 1.10000, 1.09500, 0.10)   # stop SOUS : risque
    achat.type = 0
    vente = _Pos(2, "EURUSD", 1.10000, 1.09500, 0.10)   # meme stop : protege
    vente.type = 1
    assert m._risque_position(achat, _Info()) == pytest.approx(50.0)
    assert m._risque_position(vente, _Info()) == 0.0


def test_une_position_SANS_stop_reste_non_bornable(m):
    """⛔ Le garde-fou a ne surtout pas emporter avec le correctif.

    Zero par ABSENCE de stop reste un risque infini. Seul le zero obtenu par
    un stop effectivement place devient un vrai zero.
    """
    nue = _Pos(1, "EURUSD", 1.10000, 0.0, 0.10)
    nue.type = 0
    assert m._risque_position(nue, _Info()) is None
    _, non_bornables = m._risque_engage([nue], lambda s: _Info())
    assert non_bornables == [1]


def test_sens_INCONNU_on_surestime_plutot_que_de_rendre_zero(m):
    """Sur donnee manquante, on compte le pire — jamais le plus favorable."""
    sans_sens = _Pos(1, "EURUSD", 1.10000, 1.10500, 0.10)
    assert not hasattr(sans_sens, "type"), "_Pos ne doit pas porter de sens"
    assert m._risque_position(sans_sens, _Info()) == pytest.approx(50.0)


# ─── Deux POCHES : 6 % hors or, 14 % pour l'or seul (2026-08-28) ───────────
#
# Demande de Xavier : porter le risque cumule de 6 % a 20 %, mais **pas en un
# seul reservoir**. Les 6 % restent a ce qui n'est pas de l'or ; les 14 %
# ajoutes sont a l'or SEUL, pour lui laisser du mouvement.
#
# ⛔ Ce qui est verrouille ici est la NON-FONGIBILITE, dans les deux sens. Un
# plafond unique a 20 % aurait aussi autorise 20 % de forex — personne ne l'a
# demande et personne ne l'a mesure.

def test_l_or_et_le_forex_ne_comptent_PAS_dans_la_meme_poche(m):
    positions = [
        _Pos(1, "GBPUSD", 1.36073, 1.35183, 0.01),   # 8,90 €
        _Pos(2, "XAUUSD", 1.36073, 1.35183, 0.01),   # 8,90 €, memes specs
    ]
    totaux, nus = m._risque_engage_par_poche(positions, _specs)
    assert nus == []
    assert totaux["autres"] == pytest.approx(8.90, abs=0.05)
    assert totaux["or_argent"] == pytest.approx(8.90, abs=0.05)


def test_l_ARGENT_partage_la_poche_des_14_pct(m):
    """⚠️ Renverse le 28/08, quelques heures apres la pose, SUR MESURE : un
    0,01 lot d'argent risque **11,80 EUR** (mediane de 262 ordres reels) contre
    7,71 EUR pour l'or et 2,50 a 3,00 EUR pour du forex. Un seul trade argent
    consommait donc le TIERS de la poche des 6 % — quatre trades forex."""
    assert m._poche_du_symbole("XAGUSD") == "or_argent"
    assert m._poche_du_symbole("SILVER") == "or_argent"
    assert m._poche_du_symbole("XAUUSD") == "or_argent"
    assert m._poche_du_symbole("GOLD") == "or_argent"
    assert m._poche_du_symbole("") == "autres"
    assert m._poche_du_symbole(None) == "autres"


def test_le_PLATINE_ne_s_invite_PAS_dans_la_poche_des_metaux(m):
    """⛔ La liste est nommee un par un, jamais par classe. Filtrer sur
    `metal` embarquerait XPT et XPD sans qu'aucune ligne ne change — deux
    instruments que personne n'a demande a financer sur ce budget."""
    assert m._poche_du_symbole("XPTUSD") == "autres"
    assert m._poche_du_symbole("XPDUSD") == "autres"


def test_les_deux_poches_existent_TOUJOURS_meme_vides(m):
    """⛔ 0.0, jamais une cle absente : un `.get()` rendrait `None` et un
    total absent finit toujours par se lire comme un total nul."""
    totaux, _ = m._risque_engage_par_poche([], _specs)
    assert totaux == {"autres": 0.0, "or_argent": 0.0}


def test_la_poche_de_l_or_desarmee_reverse_tout_dans_la_commune(m):
    """`MAX_RISQUE_ENGAGE_OR_ARGENT_PCT=0` rend l'etat EXACT d'avant le 28/08."""
    positions = [_Pos(1, "XAUUSD", 1.36073, 1.35183, 0.01)]
    totaux, _ = m._risque_engage_par_poche(positions, _specs,
                                           poches_separees=False)
    assert totaux["or_argent"] == 0.0
    assert totaux["autres"] == pytest.approx(8.90, abs=0.05)


def test_une_position_NUE_n_appartient_a_aucune_poche(m):
    """Son risque est infini : il ne se range dans aucun budget, et il bloque
    les deux — pas seulement celui de son instrument."""
    positions = [_Pos(9, "XAUUSD", 4450.0, 0.0, 0.01)]
    totaux, nus = m._risque_engage_par_poche(positions, _specs)
    assert nus == [9]
    assert totaux == {"autres": 0.0, "or_argent": 0.0}


def test_risque_engage_rend_toujours_le_TOTAL_toutes_poches(m):
    """Retro-compatibilite : les autres appelants n'ont pas change de sens."""
    positions = [
        _Pos(1, "GBPUSD", 1.36073, 1.35183, 0.01),
        _Pos(2, "XAUUSD", 1.36073, 1.35183, 0.01),
    ]
    total, nus = m._risque_engage(positions, _specs)
    assert nus == []
    assert total == pytest.approx(17.80, abs=0.05)


def test_le_refus_DIT_quelle_poche_a_mordu(m):
    """Un refus a 6 % et un refus a 14 % s'ecriraient pareil sans ca."""
    ok, raison = m._controle_risque_engage(70.0, [], 10.0, 552.0, 14.0,
                                           poche="or_argent")
    assert ok is False and "[or_argent]" in raison


# ── Branchement : les fonctions pures ne disent rien si la porte les ignore ─

def _specs_or(symbole):
    """Specs realistes de l'or : point 0,01 et 1 € le point pour 1 lot."""
    return _Info(point=0.01, tick_value=1.0) if "XAU" in (symbole or "") \
        else _Info()


def test_l_OR_obtient_bien_ses_14_pct(bridge, monkeypatch):
    """Sur 552 € : 6 % = 33,12 € et 14 % = 77,28 €. Un ordre or a 50 € de
    risque etait REFUSE avant le 28/08 ; il passe maintenant."""
    monkeypatch.setattr(bridge, "MAX_RISQUE_ENGAGE_PCT", 6.0)
    monkeypatch.setattr(bridge, "MAX_RISQUE_ENGAGE_OR_ARGENT_PCT", 14.0)
    _armer(bridge, monkeypatch)
    monkeypatch.setattr(bridge.mt5, "symbol_info", _specs_or)
    ok, raison = bridge._check_safety_gates(
        "XAUUSD", "buy", lots=0.01, entry=4450.0, sl=4400.0)
    assert ok is True, raison


def test_le_MEME_ordre_or_est_refuse_poche_desarmee(bridge, monkeypatch):
    """Preuve que c'est bien la poche qui l'a laisse passer, et rien d'autre."""
    monkeypatch.setattr(bridge, "MAX_RISQUE_ENGAGE_PCT", 6.0)
    monkeypatch.setattr(bridge, "MAX_RISQUE_ENGAGE_OR_ARGENT_PCT", 0.0)
    _armer(bridge, monkeypatch)
    monkeypatch.setattr(bridge.mt5, "symbol_info", _specs_or)
    ok, raison = bridge._check_safety_gates(
        "XAUUSD", "buy", lots=0.01, entry=4450.0, sl=4400.0)
    assert ok is False and "Risque engage" in raison


def test_l_or_ne_deborde_PAS_au_dela_de_ses_14_pct(bridge, monkeypatch):
    """50 € deja engages en or + 50 € demandes = 100 € > 77,28 €."""
    monkeypatch.setattr(bridge, "MAX_RISQUE_ENGAGE_OR_ARGENT_PCT", 14.0)
    monkeypatch.setattr(bridge, "MAX_OPEN_POSITIONS", 10)
    ouverte = _Pos(11, "XAUUSD", 4450.0, 4400.0, 0.01)
    ouverte.type, ouverte.time = 0, 0
    _armer(bridge, monkeypatch, positions=[ouverte])
    monkeypatch.setattr(bridge.mt5, "symbol_info", _specs_or)
    ok, raison = bridge._check_safety_gates(
        "XAUUSD", "sell", lots=0.01, entry=4450.0, sl=4500.0)
    assert ok is False
    assert "[or_argent]" in raison


def test_le_FOREX_ne_touche_PAS_au_budget_de_l_or(bridge, monkeypatch):
    """⛔ LE test de la non-fongibilite. 26,70 € de forex ouverts + 8,90 €
    demandes = 35,60 € > 33,12 €. Le refus doit TENIR, alors que les 14 % de
    l'or sont vides et que le total (35,60 €) reste loin des 20 % (110,40 €)."""
    monkeypatch.setattr(bridge, "MAX_RISQUE_ENGAGE_PCT", 6.0)
    monkeypatch.setattr(bridge, "MAX_RISQUE_ENGAGE_OR_ARGENT_PCT", 14.0)
    monkeypatch.setattr(bridge, "MAX_OPEN_POSITIONS", 10)
    monkeypatch.setattr(bridge, "EQUILIBRE_AUTO_ENABLED", False)
    ouvertes = []
    for i, paire in enumerate(("GBPUSD", "EURUSD", "AUDUSD")):
        p = _Pos(20 + i, paire, 1.36073, 1.35183, 0.01)
        p.type, p.time = 0, 0
        ouvertes.append(p)
    _armer(bridge, monkeypatch, positions=ouvertes)
    ok, raison = bridge._check_safety_gates(
        "USDCAD", "buy", lots=0.01, entry=1.36073, sl=1.35183)
    assert ok is False
    assert "[autres]" in raison


def test_l_or_ouvert_n_empeche_pas_un_forex(bridge, monkeypatch):
    """L'autre sens : 50 € engages en or saturent 6 % a eux seuls. Le forex
    doit passer quand meme — sa poche, elle, est vide."""
    monkeypatch.setattr(bridge, "MAX_RISQUE_ENGAGE_PCT", 6.0)
    monkeypatch.setattr(bridge, "MAX_RISQUE_ENGAGE_OR_ARGENT_PCT", 14.0)
    monkeypatch.setattr(bridge, "MAX_OPEN_POSITIONS", 10)
    ouverte = _Pos(31, "XAUUSD", 4450.0, 4400.0, 0.01)
    ouverte.type, ouverte.time = 0, 0
    _armer(bridge, monkeypatch, positions=[ouverte])
    monkeypatch.setattr(bridge.mt5, "symbol_info", _specs_or)
    ok, raison = bridge._check_safety_gates(
        "GBPUSD", "buy", lots=0.01, entry=1.36073, sl=1.35183)
    assert ok is True, raison
