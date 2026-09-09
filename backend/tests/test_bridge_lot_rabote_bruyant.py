"""Un lot raboté doit le DIRE — sinon le risque dérive en silence.

⛔ **La panne silencieuse qui attend** (identifiée le 2026-09-09). Sur l'or,
`MAX_LOT_PER_CLASS = {'metal': 0.01}`. Aujourd'hui c'est sans effet : à 716 €
de capital, le dimensionnement demande **0,0048** lot et le **plancher du
courtier** le remonte à 0,01.

Mais le risque médian d'un lot plein sur l'or vaut ~2 056 €. À la cible de 1 %,
le calcul demandera donc naturellement :

```
0,01 lot  a partir de ~1 028 EUR de capital
0,02 lot                 ~3 085 EUR       <-- ICI
```

⇒ Vers **3 085 €**, `lots = min(_max_lot_for_symbol(symbol), lots)` ramènera
0,02 à 0,01 **sans aucun journal**. Le risque par trade se mettra alors à
**baisser** relativement au capital, et rien ne le dira.

*Un garde qui rabote sans le dire est indiscernable d'un garde qui n'a rien
fait* — même famille que les 5,2 % de positions nues dont l'alerte partait sur
`infra`.

## Les deux rabotages sont de natures OPPOSÉES

| | effet | ce que ça veut dire |
|---|---|---|
| **plancher** du courtier (`volume_min`) | lot **monté** | le risque est **SUBI**, plus grand que voulu — c'est l'état actuel de l'or, 2,87 % au lieu de 1 % |
| **plafond** de classe (`MAX_LOT_PER_CLASS`) | lot **baissé** | le risque est **bridé**, plus petit que voulu |

Les confondre dans un même message ferait lire une sous-exposition comme une
sur-exposition. Ils sont donc journalisés **séparément**.

⚠️ On ne **change pas** le plafond : relever `metal` à 0,02 est un desserrage,
qui appartient à Xavier. On rend le rabotage **visible**, c'est tout.
"""
import logging
import types
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "mt5-bridge" / "bridge.py"


class _Info:
    def __init__(self, point=0.01, tick_value=1.0, vmin=0.01, vmax=100.0, step=0.01):
        self.point = point
        self.trade_tick_value = tick_value
        self.volume_min = vmin
        self.volume_max = vmax
        self.volume_step = step


@pytest.fixture
def module():
    """Extrait `_compute_lots_from_symbol` et l'exécute seule, sans MetaTrader5."""
    src = _SRC.read_text(encoding="utf-8")
    debut = src.index("def _compute_lots_from_symbol(")
    fin = src.index('@app.route("/order"', debut)
    mod = types.ModuleType("bridge_lots")
    journal: list[tuple[int, str]] = []

    class _Log:
        def warning(self, msg, *a):
            journal.append((logging.WARNING, msg % a if a else msg))

        def info(self, msg, *a):
            journal.append((logging.INFO, msg % a if a else msg))

    mod.__dict__["logger"] = _Log()
    mod.__dict__["journal"] = journal
    exec(compile(src[debut:fin], str(_SRC), "exec"), mod.__dict__)
    return mod


def _brancher(module, info, plafond):
    module.__dict__["mt5"] = types.SimpleNamespace(symbol_info=lambda s: info)
    module.__dict__["_max_lot_for_symbol"] = lambda s: plafond


# ─── Le plafond de classe, celui qui attend à 3 085 € ────────────────

def test_le_PLAFOND_de_classe_est_annonce(module):
    """⛔ Le cœur : sans ce message, le bridage est invisible."""
    _brancher(module, _Info(), plafond=0.01)
    # 0,02 lot demandé : risque 31 USD sur un stop de 15,52
    lots = module._compute_lots_from_symbol("XAUUSD", 4398.97, 4383.45, 31.04)

    assert lots == 0.01
    dits = [m for niveau, m in module.journal if niveau == logging.WARNING]
    assert any("plafond" in m.lower() and "XAUUSD" in m for m in dits), (
        f"le rabotage par le plafond n'est pas annonce : {module.journal}")


def test_le_message_du_plafond_donne_les_DEUX_lots(module):
    """Un avertissement sans le chiffre demandé ne permet pas de juger de
    l'ampleur du bridage."""
    _brancher(module, _Info(), plafond=0.01)
    module._compute_lots_from_symbol("XAUUSD", 4398.97, 4383.45, 31.04)
    tout = " ".join(m for _, m in module.journal)
    assert "0.02" in tout and "0.01" in tout, tout


def test_sans_rabotage_AUCUN_bruit(module):
    """⚠️ Un avertissement qui s'affiche toujours ne veut plus rien dire.
    C'est 95 % du flux : il doit rester silencieux."""
    _brancher(module, _Info(), plafond=1.0)
    lots = module._compute_lots_from_symbol("XAUUSD", 4398.97, 4383.45, 31.04)

    assert lots == 0.02
    assert not [m for niveau, m in module.journal if niveau == logging.WARNING]


# ─── Le plancher, de nature OPPOSÉE ──────────────────────────────────

def test_le_PLANCHER_du_courtier_est_annonce_SEPAREMENT(module):
    """⛔ Ne pas confondre : le plancher MONTE le lot, donc le risque est SUBI.
    Le mélanger au plafond ferait lire une sous-exposition comme une
    sur-exposition. C'est l'état actuel de l'or : 2,87 % subis pour 1 % visés.
    """
    _brancher(module, _Info(), plafond=1.0)
    # 0,005 lot demandé : sous le plancher de 0,01
    lots = module._compute_lots_from_symbol("XAUUSD", 4398.97, 4383.45, 7.7)

    assert lots == 0.01
    dits = [m for niveau, m in module.journal if niveau == logging.WARNING]
    assert any("plancher" in m.lower() for m in dits), module.journal
    assert not any("plafond" in m.lower() for m in dits), (
        "le plancher est annonce comme un plafond — sens INVERSE")


def test_les_deux_rabotages_ne_se_confondent_jamais(module):
    """Aucune situation ne doit produire les deux messages : un lot ne peut pas
    être simultanément monté par le plancher et baissé par le plafond."""
    for risque, plafond in ((7.7, 0.01), (31.04, 0.01), (7.7, 1.0), (31.04, 1.0)):
        module.journal.clear()
        _brancher(module, _Info(), plafond=plafond)
        module._compute_lots_from_symbol("XAUUSD", 4398.97, 4383.45, risque)
        dits = " ".join(m.lower() for _, m in module.journal)
        assert not ("plancher" in dits and "plafond" in dits), (
            f"les deux a la fois pour risque={risque} plafond={plafond}")


# ─── Ce qui ne doit pas changer ──────────────────────────────────────

def test_le_LOT_rendu_est_inchange(module):
    """⚠️ Ce correctif rend le rabotage visible, il ne le modifie PAS.
    Relever `metal` a 0,02 serait un desserrage, et il appartient a Xavier."""
    _brancher(module, _Info(), plafond=0.01)
    assert module._compute_lots_from_symbol("XAUUSD", 4398.97, 4383.45, 31.04) == 0.01
    _brancher(module, _Info(), plafond=1.0)
    assert module._compute_lots_from_symbol("XAUUSD", 4398.97, 4383.45, 31.04) == 0.02


def test_un_symbole_INCONNU_ne_leve_pas(module):
    """Le sizing est sur le chemin de chaque ordre : lever ici perdrait le
    trade entier."""
    module.__dict__["mt5"] = types.SimpleNamespace(symbol_info=lambda s: None)
    module.__dict__["_max_lot_for_symbol"] = lambda s: 0.01
    assert module._compute_lots_from_symbol("INCONNU", 1.0, 0.9, 10.0) == 0.01
