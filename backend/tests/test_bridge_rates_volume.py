"""`/rates` transportait le prix mais jetait le volume.

⛔ MESURE DU 2026-09-12. Le laboratoire construit ses bougies avec
`volume=0.0` en dur, et pour cause : Twelve Data rend zéro sur toutes les
paires. Vérifié en production le même jour :

    XAU/USD   30 bougies | volume > 0 sur 0 | somme = 0
    XAG/USD   30 bougies | volume > 0 sur 0 | somme = 0
    EUR/USD   30 bougies | volume > 0 sur 0 | somme = 0

Conséquence : « stratégie Volume Profile » et « confirmation par les volumes »
étaient déclarées non implémentables — deux piliers d'une méthode entière.

🔑 **La donnée existait déjà.** `mt5.copy_rates_range` rend un tableau
structuré dont les champs sont `time, open, high, low, close, tick_volume,
spread, real_volume`. Notre `/rates` en recopiait cinq et laissait les deux
volumes derrière. Le pont voyait le volume et ne le transportait pas.

## ⚠️ Ce que `tv` est, et ce qu'il n'est pas

`tick_volume` compte les **changements de prix**, pas les contrats échangés.
C'est ce que la quasi-totalité des indicateurs « volume » du retail utilisent
en forex et en CFD, parce que c'est tout ce qui existe là-bas. Le vrai volume
échangé n'est disponible que sur les **futures** (COMEX GC/SI), via `rv`.

⇒ Les deux champs sont rendus SÉPARÉMENT et jamais fusionnés. Les confondre
ferait passer un compte de ticks pour un volume négocié — exactement le genre
de glissement de sens que ce dépôt paie ensuite pendant des semaines.

## Invariants

- un champ absent du tableau rend `None`, jamais `0` : « pas de donnée » ne
  doit pas être indiscernable de « aucune activité » ;
- les champs existants (`t o h l c s`) ne bougent pas — un client déjà en
  place ne doit rien avoir à changer.
"""
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "mt5-bridge" / "bridge.py"


class _Dtype:
    def __init__(self, names):
        self.names = tuple(names)


class _Bougie(dict):
    """Imite une ligne du tableau structuré rendu par `copy_rates_range`."""

    def __init__(self, champs: dict):
        super().__init__(champs)
        self.dtype = _Dtype(champs.keys())


@pytest.fixture(scope="module")
def bougie_json():
    """Extrait `_bougie_json` de bridge.py et l'exécute sans MetaTrader5."""
    src = _SRC.read_text(encoding="utf-8")
    debut = src.index("def _bougie_json(")
    fin = src.index("\n@app.route", debut)
    module = {}
    exec("from datetime import datetime, timezone\n" + src[debut:fin], module)
    return module["_bougie_json"]


_COMPLET = {"time": 1_757_000_000.0, "open": 4348.36, "high": 4348.55,
            "low": 4348.29, "close": 4348.39, "tick_volume": 137,
            "spread": 24, "real_volume": 0}


def test_le_tick_volume_est_TRANSPORTE(bougie_json):
    """⛔ LE manque : la donnée existait au courtier et n'arrivait jamais."""
    b = bougie_json(_Bougie(_COMPLET), 0)
    assert b["tv"] == 137


def test_le_volume_REEL_est_un_champ_distinct(bougie_json):
    """🔑 Un compte de ticks n'est pas un volume negocie. Les fusionner ferait
    passer l'un pour l'autre — le vrai volume n'existe que sur les futures."""
    b = bougie_json(_Bougie(_COMPLET), 0)
    assert b["rv"] == 0
    assert b["tv"] != b["rv"] or _COMPLET["tick_volume"] == _COMPLET["real_volume"]
    assert "tv" in b and "rv" in b


def test_un_champ_ABSENT_rend_None_et_pas_zero(bougie_json):
    """⛔ « pas de donnee » doit rester discernable de « aucune activite ».
    Rendre 0 ferait lire un marche mort la ou on n'a simplement rien mesure."""
    sans = {k: v for k, v in _COMPLET.items() if k not in ("tick_volume",
                                                           "real_volume")}
    b = bougie_json(_Bougie(sans), 0)
    assert b["tv"] is None
    assert b["rv"] is None


def test_les_champs_EXISTANTS_ne_bougent_pas(bougie_json):
    """Un client deja en place ne doit rien avoir a changer."""
    b = bougie_json(_Bougie(_COMPLET), 0)
    assert b["o"] == pytest.approx(4348.36)
    assert b["h"] == pytest.approx(4348.55)
    assert b["l"] == pytest.approx(4348.29)
    assert b["c"] == pytest.approx(4348.39)
    assert b["s"] == 24
    assert b["t"].endswith("+00:00")


def test_le_decalage_serveur_est_toujours_applique(bougie_json):
    """⛔ `p.time` est en heure SERVEUR. Trois portes ont deja ete faussees par
    cet ecart — il ne doit pas disparaitre avec le refactor."""
    a = bougie_json(_Bougie(_COMPLET), 0)
    b = bougie_json(_Bougie(_COMPLET), 3600)
    assert a["t"] != b["t"], "le decalage serveur n'est plus applique"


def test_le_spread_ABSENT_rend_None(bougie_json):
    """Comportement d'origine, preserve."""
    sans = {k: v for k, v in _COMPLET.items() if k != "spread"}
    assert bougie_json(_Bougie(sans), 0)["s"] is None
