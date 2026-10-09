"""La marge du DIMENSIONNEMENT aussi vient du courtier, pas d'une estimation.

## ⛔ MON CORRECTIF DU MATIN ETAIT INCOMPLET

Le 2026-10-09 j'ai corrige `_controle_marge_libre` pour qu'il demande au
courtier la marge d'un ordre qui **couvre** (0,20 € au lieu de 186,70 €
supposes). Mais `order_calc_margin` etait appele a **DEUX** endroits, et je
n'en avais vu qu'un.

Le second est `_marge_requise`, dans le chemin de **dimensionnement du lot**.
Mesure en production a 15h15, deux positions SELL ouvertes :

```
15:15:13  buy  status=500
  {"message":"Marge insuffisante : marge_insuffisante_meme_au_lot_minimum"}
```

Un **BUY** couvre les deux SELL et ne coute reellement que **0,10 €**. Estime
a 186,70 € contre un budget de ~124 € (90 % de 137 € libres), il etait refuse
« meme au lot minimum ».

## 🔑 LA CONSEQUENCE, ET ELLE EST PIRE QU'UNE CADENCE REDUITE

L'automatique ne pouvait plus que **VENDRE** : tout signal d'achat mourait la.
Une experience en cours sur de l'argent reel qui ne prend qu'**un seul sens**
ne mesure plus ce qu'elle croit mesurer — c'est un biais, pas un ralentissement.

Et le refus sortait en **HTTP 500**, donc range dans le fourre-tout
`bridge_error` au lieu d'un motif nomme : neuf refus parfaitement invisibles.
Meme maladie que `bridge_refus_indetermine` ce matin.

## Ce que ces tests épinglent

1. la marge exigee vient du courtier et tient compte du hedging ;
2. le repli sur l'estimation isolee reste possible, mais la **source est
   rendue** ;
3. ⚠️ **fail-open preserve** : `None` quand c'est incalculable, pour que
   `_ajuster_volume_a_la_marge` laisse passer et que le courtier arbitre —
   bloquer sur une panne de calcul arreterait le trading ;
4. le motif cesse de se cacher dans `bridge_error`.
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "mt5-bridge" / "bridge.py"


class _Res:
    def __init__(self, margin=None):
        if margin is not None:
            self.margin = margin


def _faux_mt5(*, order_check=None, calc=None, leve=False):
    m = types.SimpleNamespace()
    m.TRADE_ACTION_DEAL = 1
    m.ORDER_TYPE_BUY = 0
    m.ORDER_TYPE_SELL = 1
    m.ORDER_TIME_GTC = 0
    m.order_check = lambda req: order_check
    def _calc(a, s, v, p):
        if leve:
            raise RuntimeError("indisponible")
        return calc
    m.order_calc_margin = _calc
    m.last_error = lambda: (1, "Success")
    return m


@pytest.fixture()
def b():
    """`_marge_requise` extraite du source, avec son voisin dont elle depend."""
    src = _SRC.read_text(encoding="utf-8")
    debut = src.index("def _marge_du_nouvel_ordre(")
    fin = src.index("def _send_market_order(")
    mod = types.ModuleType("bridge_marge_dim")
    mod.__dict__.update({
        "DEVIATION_POINTS": 20,
        "MAGIC_NUMBER": 424242,
        "_pick_filling_mode": lambda s: 1,
        "logger": types.SimpleNamespace(info=lambda *a, **k: None,
                                        warning=lambda *a, **k: None),
    })
    exec(compile(src[debut:fin], str(_SRC), "exec"), mod.__dict__)
    return mod


# ─────────────────────────────────────────────────────────────────────────

def test_un_BUY_qui_couvre_est_chiffre_a_son_cout_REEL(b):
    """🔑 Le cas de production : 373,61 − 373,41 = 0,20 €, pas 186,70."""
    mt5 = _faux_mt5(order_check=_Res(margin=373.61), calc=186.70)

    marge = b._marge_requise(mt5.ORDER_TYPE_BUY, "XAUUSD", 0.01, 4182.0,
                             mt5=mt5, marge_actuelle=373.41)

    assert marge == pytest.approx(0.20, abs=0.01)


def test_un_SELL_de_plus_reste_chiffre_a_son_prix(b):
    """La correction ne rend pas le dimensionnement permissif."""
    mt5 = _faux_mt5(order_check=_Res(margin=560.70), calc=186.70)

    marge = b._marge_requise(mt5.ORDER_TYPE_SELL, "XAUUSD", 0.01, 4183.0,
                             mt5=mt5, marge_actuelle=373.41)

    assert marge == pytest.approx(187.29, abs=0.01)


def test_order_check_muet_retombe_sur_l_estimation(b):
    mt5 = _faux_mt5(order_check=None, calc=186.70)

    marge = b._marge_requise(mt5.ORDER_TYPE_BUY, "XAUUSD", 0.01, 4182.0,
                             mt5=mt5, marge_actuelle=373.41)

    assert marge == pytest.approx(186.70)


def test_INCALCULABLE_rend_None_pour_preserver_le_fail_open(b):
    """⚠️ `_ajuster_volume_a_la_marge` laisse passer sur `None` : le courtier
    reste l'arbitre final. Rendre 0 ferait passer tout ordre pour gratuit ;
    rendre un grand nombre bloquerait le trading sur une panne de calcul."""
    mt5 = _faux_mt5(order_check=None, calc=None, leve=True)

    assert b._marge_requise(mt5.ORDER_TYPE_BUY, "XAUUSD", 0.01, 4182.0,
                            mt5=mt5, marge_actuelle=373.41) is None


def test_sans_marge_actuelle_on_ne_soustrait_pas(b):
    mt5 = _faux_mt5(order_check=_Res(margin=373.61), calc=186.70)

    marge = b._marge_requise(mt5.ORDER_TYPE_BUY, "XAUUSD", 0.01, 4182.0,
                             mt5=mt5, marge_actuelle=None)

    assert marge == pytest.approx(186.70)


def test_le_VOLUME_demande_est_bien_transmis_au_courtier(b):
    """⛔ `marge_pour` est appelee avec PLUSIEURS volumes (le voulu, puis le
    minimum). Si le volume n'arrivait pas a `order_check`, les deux appels
    rendraient la meme valeur et la reduction au lot minimum ne servirait
    plus a rien."""
    vus: list[float] = []

    mt5 = _faux_mt5(order_check=_Res(margin=400.0), calc=186.70)
    vrai = mt5.order_check
    mt5.order_check = lambda req: (vus.append(req["volume"]), vrai(req))[1]

    b._marge_requise(mt5.ORDER_TYPE_BUY, "XAUUSD", 0.05, 4182.0,
                     mt5=mt5, marge_actuelle=373.41)
    b._marge_requise(mt5.ORDER_TYPE_BUY, "XAUUSD", 0.01, 4182.0,
                     mt5=mt5, marge_actuelle=373.41)

    assert vus == [0.05, 0.01]


# ─────────────────────────────────────────────────────────────────────────
# Le motif cesse de se cacher dans `bridge_error`
# ─────────────────────────────────────────────────────────────────────────

MSG_REEL = "Marge insuffisante : marge_insuffisante_meme_au_lot_minimum"


def test_le_refus_de_dimensionnement_porte_son_nom():
    """⛔ Il sortait en HTTP 500, donc range dans `bridge_error` : neuf refus
    parfaitement invisibles. Meme maladie que `bridge_refus_indetermine`."""
    from backend.services.mt5_bridge import _categoriser_refus

    assert _categoriser_refus(500, MSG_REEL) == "bridge_marge_insuffisante"


def test_il_ne_VOLE_PAS_l_etiquette_des_autres():
    from backend.services.mt5_bridge import _categoriser_refus

    cas = {
        "Max open positions reached": "bridge_max_positions",
        "Daily drawdown reached: loss=157": "bridge_perte_journaliere",
        "Marge libre apres ordre -30.27 < 159.03": "bridge_marge_insuffisante",
        "Risque engage trop eleve": "bridge_plafond_risque",
    }
    for corps, attendu in cas.items():
        assert _categoriser_refus(429, corps) == attendu, corps


def test_une_erreur_500_INCONNUE_reste_une_erreur():
    """🔑 On ne range pas tous les 500 sous la marge : un motif qu'on ne sait
    pas lire se declare, il ne se devine pas."""
    from backend.services.mt5_bridge import _categoriser_refus

    assert _categoriser_refus(500, "boom quelque chose") == "bridge_error"
