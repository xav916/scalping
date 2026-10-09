"""La marge d'un ordre qui COUVRE : la demander au courtier, pas la supposer.

## ⛔ LE DÉFAUT, mesuré sur le compte réel le 2026-10-09 à 15h55

Compte en mode **hedging** (`margin_mode = 2`), **deux positions SELL** d'or
ouvertes. Simulation chez le courtier (`mt5.order_check`, qui ne place rien) :

```
             retcode              marge totale    supplément RÉEL
BUY  0,01    0   « Done »         373,61          +0,20 €
SELL 0,01    10019 « No money »   560,70        +187,29 €
                                  (marge actuelle du compte : 373,41)
```

🔑 **Un BUY ne coûte que 0,20 € de marge parce qu'il COUVRE les deux SELL.**
Le niveau de marge reste à 137,7 %, soit *inchangé*.

⛔ Or la porte utilisait `mt5.order_calc_margin()`, qui chiffre une position
**isolée** : 186,70 €, soit **930 fois** le coût réel. Elle refusait donc un
ordre que le courtier accepte, et pour lequel il ne demande presque rien.

> Ce n'est pas le SEUIL de la porte qui était trop strict. C'est son ENTRÉE
> qui était fausse.

Et la conséquence pratique était vicieuse : `141,07 − 186,70 = −45,63`, donc
**aucune valeur positive du plancher ne laissait passer**. « Baisser le
plancher » et « désarmer la porte » devenaient le même geste — ce qui aurait
transformé une correction en suppression de garde-fou.
→ [[feedback_ne_pas_desserrer_les_portes]]

## 🔑 Et l'autre moitié : le courtier refuse le SELL lui-même

`retcode 10019 « No money »`. Aucun réglage de notre côté n'y change rien.
Corriger l'entrée rend donc la porte **juste**, pas **permissive** : elle
laisse passer ce qui est bon marché et continue de refuser ce qui est cher —
et quand elle se tromperait, le courtier reste derrière.

## Ce que ces tests épinglent

1. le supplément est l'**écart** entre la marge totale après ordre et la marge
   actuelle, tel que le courtier les déclare ;
2. les deux chiffres réels du 09/10 sont reproduits au centime ;
3. ⛔ `order_check` indisponible ⇒ **repli** sur l'estimation isolée, et la
   source est **dite** : un refus calculé sur une supposition ne doit pas se
   présenter comme un refus mesuré ;
4. un `order_check` qui ne porte pas de marge n'est pas une marge de zéro.
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "mt5-bridge" / "bridge.py"


class _FauxResultat:
    """Ce que rend `mt5.order_check()` — seuls les champs lus ici."""

    def __init__(self, margin=None, retcode=0, comment="Done"):
        if margin is not None:
            self.margin = margin
        self.retcode = retcode
        self.comment = comment


def _faux_mt5(*, order_check=None, calc_margin=None, leve_calc=False):
    """Un `mt5` minimal. ⛔ On ne fournit QUE ce que le source utilise."""
    m = types.SimpleNamespace()
    m.TRADE_ACTION_DEAL = 1
    m.ORDER_TYPE_BUY = 0
    m.ORDER_TYPE_SELL = 1
    m.ORDER_TIME_GTC = 0

    def _oc(req):
        return order_check

    def _calc(action, symbole, lots, prix):
        if leve_calc:
            raise RuntimeError("order_calc_margin indisponible")
        return calc_margin

    m.order_check = _oc
    m.order_calc_margin = _calc
    m.last_error = lambda: (1, "Success")
    return m


@pytest.fixture()
def b():
    """Extrait la fonction du source et l'execute seule.

    ⛔ Les noms viennent du SOURCE : le harnais ne FOURNIT aucun nom que
    `bridge.py` n'importe pas. Le 2026-10-08, injecter `timedelta` absent du
    source a fait passer neuf tests sur du code qui rendait 500 en production.
    """
    src = _SRC.read_text(encoding="utf-8")
    debut = src.index("def _marge_du_nouvel_ordre(")
    # ⚠️ Borne mise a jour le 2026-10-09 : `_marge_du_nouvel_ordre` a ete
    # DEPLACEE avant son premier usage (`_marge_requise`), pour que le
    # fichier se lise de haut en bas. Son voisin n'est plus
    # `_controle_marge_libre`.
    fin = src.index("def _marge_requise(")
    mod = types.ModuleType("bridge_marge")
    mod.__dict__.update({
        "DEVIATION_POINTS": 20,
        "MAGIC_NUMBER": 424242,
        "_pick_filling_mode": lambda s: 1,
        "logger": types.SimpleNamespace(
            info=lambda *a, **k: None, warning=lambda *a, **k: None),
    })
    exec(compile(src[debut:fin], str(_SRC), "exec"), mod.__dict__)
    return mod


# ─── Les chiffres REELS du 2026-10-09 ────────────────────────────────────

def test_un_BUY_qui_couvre_ne_coute_que_vingt_centimes(b):
    """🔑 Le cas qui a declenche tout ceci : 373,61 − 373,41 = 0,20 €."""
    mt5 = _faux_mt5(order_check=_FauxResultat(margin=373.61), calc_margin=186.70)

    marge, source = b._marge_du_nouvel_ordre(
        mt5, "XAUUSD", "buy", 0.01, 4178.0, marge_actuelle=373.41)

    assert marge == pytest.approx(0.20, abs=0.01)
    assert source == "courtier"


def test_un_SELL_de_plus_coute_bien_cent_quatre_vingt_sept_euros(b):
    """L'autre moitie : la correction ne rend pas la porte permissive. Le meme
    calcul chiffre honnetement un ordre qui, lui, coute cher."""
    mt5 = _faux_mt5(order_check=_FauxResultat(margin=560.70, retcode=10019,
                                              comment="No money"),
                    calc_margin=186.70)

    marge, source = b._marge_du_nouvel_ordre(
        mt5, "XAUUSD", "sell", 0.01, 4183.0, marge_actuelle=373.41)

    assert marge == pytest.approx(187.29, abs=0.01)
    assert source == "courtier"


def test_l_ancien_calcul_IGNORAIT_le_hedging(b):
    """⛔ Epingle l'ecart entre les deux methodes, pour que le defaut ne puisse
    pas revenir en silence : 186,70 suppose contre 0,20 mesure, soit un facteur
    933."""
    mt5 = _faux_mt5(order_check=_FauxResultat(margin=373.61), calc_margin=186.70)

    mesure, _ = b._marge_du_nouvel_ordre(
        mt5, "XAUUSD", "buy", 0.01, 4178.0, marge_actuelle=373.41)

    assert mesure < 1.0
    assert 186.70 / max(mesure, 0.01) > 100


# ─── Les replis, et ils se DISENT ────────────────────────────────────────

def test_order_check_MUET_rend_un_repli_ETIQUETE(b):
    """⛔ Un refus calcule sur une supposition ne doit pas se presenter comme un
    refus mesure. La source change, la valeur aussi."""
    mt5 = _faux_mt5(order_check=None, calc_margin=186.70)

    marge, source = b._marge_du_nouvel_ordre(
        mt5, "XAUUSD", "buy", 0.01, 4178.0, marge_actuelle=373.41)

    assert marge == pytest.approx(186.70)
    assert source == "estimation"


def test_un_order_check_SANS_marge_n_est_pas_une_marge_NULLE(b):
    """⚠️ `getattr(res, 'margin', None)` peut etre absent. Le lire comme 0
    ferait passer n'importe quel ordre pour gratuit — exactement le defaut
    qu'on repare, en pire."""
    mt5 = _faux_mt5(order_check=_FauxResultat(margin=None), calc_margin=186.70)

    marge, source = b._marge_du_nouvel_ordre(
        mt5, "XAUUSD", "buy", 0.01, 4178.0, marge_actuelle=373.41)

    assert marge == pytest.approx(186.70)
    assert source == "estimation"


def test_les_DEUX_sources_muettes_rendent_None_et_non_zero(b):
    """🔑 `None` veut dire « incalculable », et la porte le traite comme un
    garde-fou SECONDAIRE : elle laisse passer en le signalant. Rendre `0`
    ferait croire a une mesure."""
    mt5 = _faux_mt5(order_check=None, calc_margin=None, leve_calc=True)

    marge, source = b._marge_du_nouvel_ordre(
        mt5, "XAUUSD", "buy", 0.01, 4178.0, marge_actuelle=373.41)

    assert marge is None
    assert source == "inconnue"


def test_une_marge_actuelle_inconnue_interdit_la_soustraction(b):
    """⚠️ Sans la marge actuelle, l'ecart n'a pas de sens : on retombe sur
    l'estimation isolee plutot que de soustraire zero."""
    mt5 = _faux_mt5(order_check=_FauxResultat(margin=373.61), calc_margin=186.70)

    marge, source = b._marge_du_nouvel_ordre(
        mt5, "XAUUSD", "buy", 0.01, 4178.0, marge_actuelle=None)

    assert marge == pytest.approx(186.70)
    assert source == "estimation"


def test_un_ecart_NEGATIF_est_ramene_a_zero_pas_credite(b):
    """⛔ Un ordre qui REDUIRAIT la marge totale (couverture parfaite) ne doit
    pas CREDITER de la marge libre : on plafonne a zero. Crediter ferait passer
    une porte sur un gain imaginaire."""
    mt5 = _faux_mt5(order_check=_FauxResultat(margin=300.00), calc_margin=186.70)

    marge, source = b._marge_du_nouvel_ordre(
        mt5, "XAUUSD", "buy", 0.01, 4178.0, marge_actuelle=373.41)

    assert marge == pytest.approx(0.0)
    assert source == "courtier"
