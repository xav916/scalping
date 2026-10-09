"""Le TP doit pouvoir être DÉPLACÉ, pas seulement préservé.

Règle dictée par Xavier le 2026-10-09 :

> « Je veux qu'il y ait toujours 2 euros d'écart quand on se rapproche du TP :
> quand 1 euro est atteint, update SL:1 et TP:3 ; si 1,5 est atteint, SL:1,5 et
> TP:3,5, etc. »

Avec la **marge de 0,25 €** qu'il a choisie après mesure du spread (0,151 €),
cela donne : `SL = niveau − 0,25` et `TP = niveau + 2,00`.

🔑 Le côté **SL** est donc *exactement* l'échelle déjà installée
(1,00→0,75 ; 1,50→1,25 ; 1,75→1,50 ; 2,00→1,75). **Seul le TP est nouveau.**

## ⛔ CE QUI BLOQUAIT

`/position/sltp` **préservait** le TP, explicitement :

```python
new_tp = p.tp or 0.0   # préserve le TP existant tel quel (0 = pas de TP)
```

Aucune entrée ne permettait de le changer. La route est pourtant déjà le bon
endroit : MT5 exige **les deux champs dans le même appel**
(`TRADE_ACTION_SLTP`), ce qui est précisément la raison pour laquelle elle
relisait le TP existant.

## ⛔ ET LE CLIQUET VAUT AUSSI POUR LE TP

Un objectif ne doit **jamais se rapprocher** du prix d'entrée : le ramener
réduirait le gain visé sur une position qui travaille. Pour un achat il ne peut
que **monter**, pour une vente que **descendre** — le miroir exact du cliquet du
stop.

⚠️ Et comme le stop, il est soumis aux **deux** conditions : le client doit le
demander (`deplacer`) **et** le drapeau doit l'autoriser. Sans quoi un appelant
historique déplacerait un objectif sans le savoir.
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "mt5-bridge" / "bridge.py"


@pytest.fixture()
def b():
    """`_lire_tp_demande` et le cliquet, extraits du source."""
    src = _SRC.read_text(encoding="utf-8")
    debut = src.index("def _lire_sl_demande(")
    fin = src.index('@app.route("/position/sltp"')
    mod = types.ModuleType("bridge_tp")
    exec(compile(src[debut:fin], str(_SRC), "exec"), mod.__dict__)
    return mod


# ─────────────────────────────────────────────────────────────────────────
# La lecture du TP demandé
# ─────────────────────────────────────────────────────────────────────────

def test_tp_absolu_est_lu(b):
    tp, err = b._lire_tp_demande({"ticket": 1, "tp_absolu": 4193.37})

    assert err is None
    assert tp == pytest.approx(4193.37)


def test_SANS_tp_absolu_on_rend_None_et_non_zero(b):
    """⛔ `None` veut dire « ne touche pas au TP ». Rendre `0` EFFACERAIT
    l'objectif de la position — un ordre sans TP ne sort plus jamais au
    profit."""
    tp, err = b._lire_tp_demande({"ticket": 1})

    assert err is None
    assert tp is None


def test_un_tp_ILLISIBLE_est_refuse(b):
    _, err = b._lire_tp_demande({"ticket": 1, "tp_absolu": "pas un prix"})

    assert err is not None and "nombre" in err


def test_un_tp_NEGATIF_ou_NUL_est_refuse(b):
    """⚠️ Un prix ne peut pas etre nul : ce serait l'effacement deguise en
    valeur."""
    for mauvais in (0, -1, -4193.37):
        _, err = b._lire_tp_demande({"ticket": 1, "tp_absolu": mauvais})
        assert err is not None and "> 0" in err, mauvais


# ─────────────────────────────────────────────────────────────────────────
# ⛔ LE CLIQUET DU TP — il ne se rapproche JAMAIS de l'entrée
# ─────────────────────────────────────────────────────────────────────────

def test_pour_un_ACHAT_le_tp_ne_peut_que_MONTER(b):
    assert b._tp_mieux(4193.37, actuel=4192.25, is_buy=True) is True
    # ⛔ Le ramener reduirait le gain vise sur une position qui travaille.
    assert b._tp_mieux(4191.00, actuel=4192.25, is_buy=True) is False
    assert b._tp_mieux(4192.25, actuel=4192.25, is_buy=True) is False


def test_pour_une_VENTE_le_tp_ne_peut_que_DESCENDRE(b):
    assert b._tp_mieux(4180.00, actuel=4182.00, is_buy=False) is True
    assert b._tp_mieux(4185.00, actuel=4182.00, is_buy=False) is False


def test_un_TP_ABSENT_accepte_le_premier_objectif(b):
    """Une position sans TP (0) doit pouvoir en recevoir un."""
    assert b._tp_mieux(4193.37, actuel=0.0, is_buy=True) is True
    assert b._tp_mieux(4180.00, actuel=None, is_buy=False) is True


# ─────────────────────────────────────────────────────────────────────────
# La route, vérifiée sur le SOURCE — le piège de ce matin
# ─────────────────────────────────────────────────────────────────────────

def _bloc_route() -> str:
    src = _SRC.read_text(encoding="utf-8")
    debut = src.index('@app.route("/position/sltp"')
    return src[debut:debut + 6000]


def test_la_route_UTILISE_la_lecture_du_tp():
    """⛔ LE PIEGE DE CE MATIN : j'avais verifie le CALCUL et non la ROUTE, et
    `sl_absolu` etait refuse en production pendant des heures. Ce test exige
    que la correction vive SUR le chemin reel."""
    assert "_lire_tp_demande(" in _bloc_route()


def test_la_route_applique_le_CLIQUET_du_tp():
    assert "_tp_mieux(" in _bloc_route()


def test_le_TP_EXISTANT_reste_preserve_par_defaut():
    """⚠️ Le comportement historique ne doit PAS changer pour les appelants qui
    n'envoient pas de TP : le garde-fou SL/TP protege des positions nues et ne
    doit jamais effacer un objectif."""
    bloc = _bloc_route()

    assert "p.tp or 0.0" in bloc, (
        "la preservation du TP existant a disparu : un appel sans tp_absolu "
        "effacerait l'objectif")
