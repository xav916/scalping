"""Plafond journalier PAR PAIRE : l'or à 10 %, chaque autre paire à 3 %.

## Pourquoi, et ce que ça change

Demandé par Xavier le 2026-10-07 : *« le plafond journalier des trades OR à
10 % du capital »*. Jusqu'ici le plafond était **unique et par COMPTE** (3 %
du solde d'ouverture) : il coupait à 17,87 € bien avant que l'or n'approche
ses 59,58 €, donc un réglage propre à l'or n'aurait **jamais** pu se
déclencher.

⚠️ **Deux étages sont nécessaires, et c'est le cœur de ces tests.** Monter le
plafond du compte à 10 % sans borner les paires une par une ne confine rien :
dix paires à 3 % chacune feraient un pire cas de **178 €**, pas 59,58 €.

    etage 1  le COMPTE     10 %  = 59,58 €   <- le filet dur, inchangé de nature
    etage 2  CHAQUE paire   3 %  = 17,87 €   <- sauf l'or, à 10 %

⇒ L'or seul peut consommer tout le budget du jour ; aucune autre paire ne peut
y contribuer plus de 17,87 €.

## ⛔ Ce que ces tests verrouillent

- l'ARGENT n'est pas l'or : Xavier a dit « OR », et `XAG` ne doit pas héberber
  le plafond large par simple appartenance aux métaux ;
- un symbole en GAIN ne doit pas se lire comme une perte (le signe) ;
- les tickets exclus du drawdown restent exclus ici aussi, sinon on aurait
  deux comptabilités différentes du même jour ;
- une donnée absente ne doit jamais lever dans le chemin d'un ordre réel.

`bridge.py` importe MetaTrader5, absent hors du VPS : on extrait les fonctions
du source et on les exécute, plutôt que d'importer le module. Un renommage ou
une suppression fait donc échouer ces tests — ce n'est pas une
réimplémentation figée.
"""
import types
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "mt5-bridge" / "bridge.py"


def _charger(plafonds=None, defaut=3.0, exclus=frozenset()):
    """Extrait le bloc des plafonds par paire, avec la config voulue."""
    src = _SRC.read_text(encoding="utf-8")
    debut = src.index("def _plafond_jour_pct(")
    fin = src.index("def _parse_trading_hours(")
    module = types.ModuleType("bridge_extrait")
    module.__dict__.update({
        # ⚠️ Le MEME defaut que le source : un courtier peut nommer l'or
        # `XAUUSD` ou `GOLD`, et n'en couvrir qu'un laisserait l'autre au
        # plafond serre SANS que rien ne le dise.
        "DAILY_LOSS_PCT_PAR_SYMBOLE": (
            {"XAU": 10.0, "GOLD": 10.0} if plafonds is None else plafonds),
        "DAILY_LOSS_PCT_PAIRE_DEFAUT": defaut,
        "DAILY_LOSS_EXCLUDED_TICKETS": frozenset(exclus),
    })
    exec(compile(src[debut:fin], str(_SRC), "exec"), module.__dict__)
    return module


class _Pos:
    def __init__(self, symbol, profit, ticket=1, swap=0.0):
        self.symbol = symbol
        self.profit = profit
        self.ticket = ticket
        self.swap = swap


class _Deal:
    def __init__(self, symbol, profit, commission=0.0, swap=0.0):
        self.symbol = symbol
        self.profit = profit
        self.commission = commission
        self.swap = swap


# ─── Quel plafond pour quel symbole ───────────────────────────────────────

def test_l_or_recoit_son_plafond_large():
    m = _charger()
    assert m._plafond_jour_pct("XAUUSD") == 10.0


def test_l_ARGENT_n_est_PAS_l_or():
    """⛔ Xavier a dit « OR ». `XAG` ne doit pas hériter du plafond large."""
    m = _charger()
    assert m._plafond_jour_pct("XAGUSD") == 3.0


def test_une_paire_non_nommee_recoit_le_defaut():
    m = _charger()
    for s in ("EURUSD", "BTCUSD", "XTIUSD", "US500"):
        assert m._plafond_jour_pct(s) == 3.0, s


def test_la_casse_et_les_suffixes_du_courtier_ne_comptent_pas():
    """Les symboles courtier portent parfois un suffixe (`XAUUSD.r`, `xauusd`)."""
    m = _charger()
    for s in ("xauusd", "XAUUSD.r", "XAUUSD-ECN", "GOLD"):
        assert m._plafond_jour_pct(s) == 10.0, s


def test_un_symbole_vide_ou_absent_retombe_sur_le_defaut():
    """⛔ Jamais le plafond LARGE par défaut : se tromper doit resserrer."""
    m = _charger()
    assert m._plafond_jour_pct(None) == 3.0
    assert m._plafond_jour_pct("") == 3.0


def test_GOLD_peut_etre_retire_de_la_liste():
    """La config fait loi : rien n'est codé en dur."""
    m = _charger(plafonds={})
    assert m._plafond_jour_pct("XAUUSD") == 3.0


# ─── La perte du jour, symbole par symbole ────────────────────────────────

def test_somme_le_realise_et_le_flottant_du_meme_symbole():
    m = _charger()
    pertes = m._perte_du_jour_par_symbole(
        positions=[_Pos("XAUUSD", -5.0)],
        deals=[_Deal("XAUUSD", -10.0)])
    assert pertes["XAUUSD"] == pytest.approx(15.0)


def test_une_PERTE_est_positive_un_GAIN_est_negatif():
    """🔑 Le signe : la porte compare `perte >= plafond`."""
    m = _charger()
    pertes = m._perte_du_jour_par_symbole(
        positions=[], deals=[_Deal("XAUUSD", -20.0), _Deal("EURUSD", 7.0)])
    assert pertes["XAUUSD"] == pytest.approx(20.0)
    assert pertes["EURUSD"] == pytest.approx(-7.0)


def test_les_symboles_ne_se_melangent_pas():
    """⛔ Un gain sur l'or ne doit pas payer les pertes de l'argent."""
    m = _charger()
    pertes = m._perte_du_jour_par_symbole(
        positions=[], deals=[_Deal("XAUUSD", 50.0), _Deal("XAGUSD", -8.0)])
    assert pertes["XAUUSD"] == pytest.approx(-50.0)
    assert pertes["XAGUSD"] == pytest.approx(8.0)


def test_commission_et_swap_comptent_dans_le_realise():
    """Le coût fait partie de la perte : c'est de l'argent qui est parti."""
    m = _charger()
    pertes = m._perte_du_jour_par_symbole(
        positions=[],
        deals=[_Deal("XAUUSD", -10.0, commission=-1.5, swap=-0.5)])
    assert pertes["XAUUSD"] == pytest.approx(12.0)


def test_le_swap_d_une_position_OUVERTE_compte_aussi():
    """Le plafond du COMPTE mesure l'equity, qui inclut le swap : l'analogue
    par symbole doit l'inclure aussi, sinon les deux comptent autrement."""
    m = _charger()
    pertes = m._perte_du_jour_par_symbole(
        positions=[_Pos("XAUUSD", -4.0, swap=-1.0)], deals=[])
    assert pertes["XAUUSD"] == pytest.approx(5.0)


def test_un_ticket_EXCLU_du_drawdown_l_est_ici_aussi():
    """⛔ Sinon le même jour aurait DEUX comptabilités, et la position tenue
    à part confisquerait de nouveau le garde-fou des autres trades."""
    m = _charger(exclus={999})
    pertes = m._perte_du_jour_par_symbole(
        positions=[_Pos("XAUUSD", -100.0, ticket=999),
                   _Pos("XAUUSD", -3.0, ticket=1)],
        deals=[])
    assert pertes["XAUUSD"] == pytest.approx(3.0)


def test_une_donnee_absente_ne_leve_PAS():
    """⚠️ Chemin d'un ordre REEL : une exception ici bloquerait tout."""
    m = _charger()
    bancal = types.SimpleNamespace()          # ni symbol, ni profit
    pertes = m._perte_du_jour_par_symbole(
        positions=[bancal, _Pos("XAUUSD", -2.0)], deals=[bancal, None])
    assert pertes["XAUUSD"] == pytest.approx(2.0)


def test_rien_du_tout_rend_un_dictionnaire_vide():
    m = _charger()
    assert m._perte_du_jour_par_symbole(positions=[], deals=[]) == {}
    assert m._perte_du_jour_par_symbole(positions=None, deals=None) == {}


def test_les_suffixes_sont_normalises_pour_le_regroupement():
    """`XAUUSD` et `XAUUSD.r` sont la MEME paire : les compter à part
    laisserait chacune sous son plafond."""
    m = _charger()
    pertes = m._perte_du_jour_par_symbole(
        positions=[], deals=[_Deal("XAUUSD", -10.0), _Deal("XAUUSD.r", -10.0)])
    assert sum(pertes.values()) == pytest.approx(20.0)
    assert len(pertes) == 1, pertes


# ─── Lire l'historique du jour : TROIS états, jamais deux ─────────────────

def _charger_deals(mt5_faux, jour=None):
    """Extrait `_deals_du_jour` avec un faux MT5 et un faux jour."""
    import datetime as _dt
    import logging
    src = _SRC.read_text(encoding="utf-8")
    debut = src.index("def _deals_du_jour(")
    fin = src.index("def _drawdown_publie(")
    module = types.ModuleType("bridge_extrait_deals")
    module.__dict__.update({
        "mt5": mt5_faux,
        "logger": logging.getLogger("test"),
        "_start_of_day_date": jour or _dt.date(2026, 10, 7),
        "datetime": _dt.datetime,
        "date": _dt.date,
    })
    exec(compile(src[debut:fin], str(_SRC), "exec"), module.__dict__)
    return module._deals_du_jour


def test_aucun_trade_du_jour_est_une_LECTURE_REUSSIE():
    """🔑 Une liste vide n'est PAS un échec : rien ne s'est passé, c'est tout."""
    faux = types.SimpleNamespace(history_deals_get=lambda a, b: ())
    deals, ok = _charger_deals(faux)()
    assert deals == [] and ok is True


def test_None_de_MT5_est_une_LECTURE_RATEE():
    """⛔ Le cas qui ouvrirait la porte en silence : MT5 rend `None` quand il
    n'a pas pu lire. Le confondre avec « aucune perte » laisserait passer des
    ordres sur un compte déjà au plafond."""
    faux = types.SimpleNamespace(history_deals_get=lambda a, b: None)
    deals, ok = _charger_deals(faux)()
    assert deals == [] and ok is False


def test_une_EXCEPTION_est_une_lecture_ratee_et_ne_remonte_PAS():
    """⚠️ Chemin d'un ordre réel : lever ici bloquerait tout le pont."""
    def _boum(a, b):
        raise RuntimeError("terminal perdu")
    faux = types.SimpleNamespace(history_deals_get=_boum)
    deals, ok = _charger_deals(faux)()
    assert deals == [] and ok is False


def test_la_fenetre_part_du_JOUR_DU_PLAFOND_pas_d_aujourd_hui():
    """⛔ Une SECONDE définition du jour ferait diverger les deux étages.

    La borne basse doit être minuit du `_start_of_day_date` retenu par le
    plafond, pas minuit de la date système.
    """
    import datetime as _dt
    vu = {}

    def _capture(a, b):
        vu["debut"] = a
        return ()

    faux = types.SimpleNamespace(history_deals_get=_capture)
    _charger_deals(faux, jour=_dt.date(2026, 10, 5))()
    assert vu["debut"] == _dt.datetime(2026, 10, 5, 0, 0)


# ─── LA PORTE : refuse-t-elle vraiment, et au BON plafond ? ───────────────
#
# 🔑 Tout ce qui précède teste des fonctions pures. Ce qui suit teste la
# DÉCISION — c'est elle qui coûte de l'argent si elle se trompe.

class _Info:
    def __init__(self, equity, balance=None, margin_free=1e9, margin=0.0):
        self.equity = equity
        self.balance = balance if balance is not None else equity
        self.margin_free = margin_free
        self.margin = margin


class _FauxMT5:
    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1

    def __init__(self, info, deals=(), positions=(), deals_none=False):
        self._info = info
        self._deals = deals
        self._positions = positions
        self._deals_none = deals_none

    def account_info(self):
        return self._info

    def positions_get(self, **kw):
        return list(self._positions)

    def history_deals_get(self, a, b):
        return None if self._deals_none else tuple(self._deals)

    def symbol_info(self, s):
        return None

    def symbol_info_tick(self, s):
        return None


def _porte(equity=750.50, solde_ouverture=750.50, deals=(), positions=(),
           deals_none=False):
    """La VRAIE `_check_safety_gates`, avec les portes voisines désarmées.

    On étend la tranche extraite jusqu'à `_pick_filling_mode` comme le fait
    `test_bridge_drawdown_arbitre`, et on injecte les fonctions pures RÉELLES
    du source — pas une copie, qui continuerait de passer après un changement.
    """
    import datetime as _dt
    import logging
    src = _SRC.read_text(encoding="utf-8")

    pur = _charger()                                  # les 3 fonctions pures
    mod = types.ModuleType("bridge_porte_paire")
    mod.__dict__.update({
        "mt5": _FauxMT5(_Info(equity), deals=deals, positions=positions,
                        deals_none=deals_none),
        "logger": logging.getLogger("test"),
        "MAX_DAILY_LOSS_PCT": 10.0,
        "DAILY_LOSS_PCT_PAR_SYMBOLE": {"XAU": 10.0, "GOLD": 10.0},
        "DAILY_LOSS_PCT_PAIRE_DEFAUT": 3.0,
        "DAILY_LOSS_EXCLUDED_TICKETS": frozenset(),
        "MAX_OPEN_POSITIONS": 10,
        "MAX_RISQUE_ENGAGE_PCT": 0.0,
        "MAX_RISQUE_ENGAGE_OR_ARGENT_PCT": 0.0,
        "TRADING_HOURS_UTC": "",
        "MARGE_LIBRE_MIN_PCT": 0.0,
        "DEDUP_WINDOW_SEC": 0,
        "_start_of_day_balance": solde_ouverture,
        "_start_of_day_date": _dt.date(2026, 10, 7),
        "_in_trading_hours": lambda: True,
        "_refresh_start_of_day": lambda: None,
        "_flottant_exclu": lambda p: (0.0, set()),
        "_controle_risque": lambda *a, **k: (True, ""),
        "_controle_marge": lambda *a, **k: (True, ""),
        "_ouverture_utc": lambda p: None,
        "_plafond_jour_pct": pur._plafond_jour_pct,
        "_symbole_normalise": pur._symbole_normalise,
        "_perte_du_jour_par_symbole": pur._perte_du_jour_par_symbole,
        "datetime": _dt.datetime,
        "timezone": _dt.timezone,
        "date": _dt.date,
    })
    debut = src.index("def _perte_journaliere(")
    fin = src.index("def _pick_filling_mode(")
    exec(compile(src[debut:fin], str(_SRC), "exec"), mod.__dict__)
    return mod


# 10 % de 750,50 = 75,05   |   3 % de 750,50 = 22,52

def test_l_or_passe_encore_a_50_EUR_de_perte():
    """🔑 LE point de la demande : à 50 € l'or continue, là où l'ancien
    plafond unique de 3 % (22,52 €) l'aurait arrêté."""
    p = _porte(equity=700.50, deals=[_Deal("XAUUSD", -50.0)])
    ok, raison = p._check_safety_gates("XAUUSD", "buy")
    assert ok is True, raison


def test_un_GAIN_ailleurs_ne_FINANCE_pas_le_depassement_de_l_or():
    """🔑 Le cas qui donne tout son sens à l'étage 2.

    L'or perd 80 € (> ses 75,05 €) mais le forex gagne 30 €, donc le COMPTE
    n'est qu'à −50 € : l'étage 1 laisserait passer. Sans plafond par paire,
    une bonne journée ailleurs financerait silencieusement le dépassement de
    l'or — et son budget ne voudrait plus rien dire.
    """
    p = _porte(equity=700.50, deals=[_Deal("XAUUSD", -80.0),
                                     _Deal("EURUSD", 30.0)])
    ok, raison = p._check_safety_gates("XAUUSD", "buy")
    assert ok is False
    assert "XAUUSD" in raison and "80.00" in raison and "75.05" in raison, raison


def test_quand_toute_la_perte_est_a_l_or_c_est_le_COMPTE_qui_coupe():
    """⚠️ Et c'est normal : les deux plafonds de l'or valent 10 %, donc
    l'étage 1 arrive le premier. Le refus est le même, le message diffère."""
    p = _porte(equity=670.50, deals=[_Deal("XAUUSD", -80.0)])
    ok, raison = p._check_safety_gates("XAUUSD", "buy")
    assert ok is False
    assert "Daily drawdown reached" in raison and "75.05" in raison, raison


def test_une_AUTRE_paire_est_refusee_des_3_pct():
    """⛔ Le desserrage reste confiné à l'or. L'argent garde son plafond serré,
    même si le compte, lui, autorise 10 %."""
    p = _porte(equity=720.50, deals=[_Deal("XAGUSD", -30.0)])
    ok, raison = p._check_safety_gates("XAGUSD", "sell")
    assert ok is False
    assert "XAGUSD" in raison and "22.52" in raison, raison


def test_les_pertes_de_l_ARGENT_ne_ferment_PAS_l_or():
    """🔑 Chaque paire a son compteur : c'est tout l'intérêt de l'étage 2."""
    p = _porte(equity=720.50, deals=[_Deal("XAGUSD", -30.0)])
    ok, raison = p._check_safety_gates("XAUUSD", "buy")
    assert ok is True, raison


def test_le_COMPTE_coupe_quand_meme_au_dela_de_ses_10_pct():
    """⛔ L'étage 1 reste le filet dur : plusieurs paires sous leur plafond
    ne doivent pas pouvoir dépasser le budget du compte ensemble."""
    p = _porte(equity=670.50, deals=[_Deal("XAGUSD", -20.0),
                                     _Deal("EURUSD", -20.0),
                                     _Deal("USDJPY", -20.0),
                                     _Deal("USDCAD", -20.0)])
    ok, raison = p._check_safety_gates("GBPUSD", "buy")
    assert ok is False
    assert "Daily drawdown reached" in raison and "75.05" in raison, raison


def test_un_GAIN_sur_la_paire_ne_declenche_rien():
    p = _porte(equity=800.50, deals=[_Deal("XAUUSD", 50.0)])
    assert p._check_safety_gates("XAUUSD", "buy")[0] is True


def test_historique_ILLISIBLE_retombe_sur_le_plafond_SERRE_du_compte():
    """⛔ LE cas qui ouvrirait la porte. Si l'on ne peut pas attribuer la perte
    par paire, on ne retombe PAS sur les 10 % du compte — ce serait plus LARGE
    qu'avant, à cause d'une panne de lecture. On applique le plafond serré."""
    p = _porte(equity=720.50, deals_none=True)      # 30 € de perte compte
    ok, raison = p._check_safety_gates("XAUUSD", "buy")
    assert ok is False
    assert "repli serre" in raison and "22.52" in raison, raison


def test_historique_illisible_sous_le_plafond_serre_laisse_passer():
    """⚠️ Le repli ne doit pas tout bloquer : sous 3 % du compte, ça passe."""
    p = _porte(equity=740.50, deals_none=True)      # 10 € de perte
    assert p._check_safety_gates("XAUUSD", "buy")[0] is True


def test_l_arbitrage_leve_AUSSI_le_plafond_de_la_paire():
    """Sinon « continue » redeviendrait un bouton décoratif : le compte
    passerait et la paire refuserait juste après."""
    p = _porte(equity=670.50, deals=[_Deal("XAUUSD", -80.0)])
    ok, raison = p._check_safety_gates(
        "XAUUSD", "buy",
        drawdown_arbitre={"accorde_a": -80.0, "couvre_jusqua": -120.0,
                          "repondu_le": "2026-10-07T13:58:41+00:00"})
    assert ok is True, raison


# ─── Les DEUX freins de compte doivent CONCORDER ──────────────────────────

def test_les_deux_plafonds_de_compte_CONCORDENT():
    """⛔ Deux freins au même nom qui divergent sont pires qu'un seul.

    Sur un compte réel il y a deux plafonds journaliers indépendants :

        radar  `DAILY_LOSS_LIMIT_PCT`  sur les pertes RÉALISÉES en base
        pont   `MAX_DAILY_LOSS_PCT`    sur l'equity (réalisé + flottant)

    Le 2026-10-07 ils comptaient **16,45 €** et **19,77 €** du même jour — deux
    mesures, c'est assumé. Mais leur POURCENTAGE doit être le même : laisser le
    radar à 3 % quand le pont est à 10 % aurait gelé la destination bien avant
    que l'or n'approche son budget, et le réglage du pont serait resté
    **décoratif**.

    🔑 Ce test n'existait pas, et c'est précisément pour ça que les deux ont pu
    vivre séparément : rien ne les additionnait, rien ne les comparait.
    """
    import re
    from config.settings import DAILY_LOSS_LIMIT_PCT

    src = _SRC.read_text(encoding="utf-8")
    m = re.search(
        r'MAX_DAILY_LOSS_PCT = float\(os\.getenv\("MAX_DAILY_LOSS_PCT",\s*"([\d.]+)"\)\)',
        src)
    assert m, "le defaut du pont n'est plus lisible — ce test ne garde plus rien"
    pont = float(m.group(1))

    assert pont == DAILY_LOSS_LIMIT_PCT, (
        f"les deux plafonds de compte divergent : pont {pont} %, "
        f"radar {DAILY_LOSS_LIMIT_PCT} %")
    assert pont == 10.0, (
        "le plafond de compte a change sans que ce test le dise "
        f"(il vaut {pont} %)")


def test_le_plafond_d_une_paire_ne_depasse_PAS_celui_du_compte():
    """⚠️ Un plafond de paire plus large que celui du compte serait
    inatteignable — le compte couperait toujours le premier."""
    import re
    src = _SRC.read_text(encoding="utf-8")
    pont = float(re.search(
        r'MAX_DAILY_LOSS_PCT = float\(os\.getenv\("MAX_DAILY_LOSS_PCT",\s*"([\d.]+)"\)\)',
        src).group(1))
    m = _charger()
    for symbole in ("XAUUSD", "XAGUSD", "EURUSD", "BTCUSD"):
        assert m._plafond_jour_pct(symbole) <= pont, symbole
