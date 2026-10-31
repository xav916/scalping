"""`_pip_size` d'affichage : une valeur, ou `None` — jamais un nombre inventé.

## Le défaut (2026-10-31)

Il n'existe aucune convention de pip pour la crypto ni l'énergie, et le repli
`0.0001` affichait `BTC/USD` à **~1 113 350 pips**. C'est le même défaut qui
avait aveuglé la sonde de glissement **onze semaines** en annonçant un
glissement moyen de **−19 082,80 pips** : un contrôle vert sur la mauvaise
question rassure à tort.

🔑 La décision est de **ne pas inventer d'unité**. Un nombre fabriqué est pire
qu'une absence : il s'affiche, il se croit, et il ne se vérifie pas.

⛔ Et cette fonction reste SÉPARÉE de `mt5_sync._pip_size`, qui alimente la
colonne historique `slippage_pips`. Leurs contrats sont opposés : la changer
elle ne touche aucune donnée stockée, changer l'autre rendrait les lignes
d'avant incomparables aux suivantes sous le même nom.
"""
from __future__ import annotations

import pytest

from backend.services import cockpit_service as C
from backend.services import mt5_sync as M


# --- ce qui a une convention ----------------------------------------------

@pytest.mark.parametrize("pair,attendu", [
    ("XAU/USD", 0.01), ("XAG/USD", 0.01), ("XPT/USD", 0.01), ("XPD/USD", 0.01),
    ("USD/JPY", 0.01), ("EUR/JPY", 0.01), ("GBP/JPY", 0.01),
    ("EUR/USD", 0.0001), ("GBP/USD", 0.0001), ("AUD/USD", 0.0001),
    ("USD/CAD", 0.0001), ("USD/CHF", 0.0001), ("EUR/GBP", 0.0001),
])
def test_les_classes_a_convention_gardent_leur_pip(pair, attendu):
    assert C._pip_size(pair) == attendu


# --- ce qui n'en a pas : None, pas un nombre ------------------------------

@pytest.mark.parametrize("pair", [
    "BTC/USD", "ETH/USD", "SOL/USD", "ADA/USD", "DOGE/USD", "PAXG/USD",
    "WTI/USD", "BRENT/USD",
    "SPX", "NDX", "DAX",
    "", "n'importe quoi", "XYZ/ABC",
])
def test_sans_convention_la_fonction_rend_None(pair):
    """⛔ LE test qui compte. Un repli à 0,0001 affichait BTC à 1,1 million
    de pips — un nombre qui s'affiche et qu'on croit."""
    assert C._pip_size(pair) is None


def test_BTC_ne_rend_plus_un_nombre_absurde():
    """Témoin chiffré : à 0,0001, un delta de 111 $ sur BTC donnait
    1 113 350 pips. On vérifie que ce calcul n'est plus possible."""
    pip = C._pip_size("BTC/USD")
    assert pip is None, "un pip sur BTC n'a pas de sens"
    # et l'appelant sait quoi faire d'un None
    assert (round(111.335 / pip, 1) if pip else None) is None


# --- la plomberie en aval doit tenir --------------------------------------

def test_un_trade_crypto_s_enrichit_SANS_pnl_pips(monkeypatch):
    """Bout en bout : `_enrich_open_trade` ne doit ni lever ni fabriquer."""
    monkeypatch.setattr(C, "_current_price", lambda p: 70000.0)
    trade = {"pair": "BTC/USD", "direction": "buy", "entry_price": 69000.0,
             "size_lot": 0.01, "stop_loss": 68000.0, "take_profit": 72000.0,
             "created_at": "2026-10-30T12:00:00+00:00"}
    out = C._enrich_open_trade(dict(trade))
    assert out["pnl_pips"] is None, "pas de pips inventes sur la crypto"
    assert out["pnl_unrealized"] is not None, "le P&L en devise reste calcule"


def test_un_trade_OR_garde_ses_pips(monkeypatch):
    """Le contre-exemple : l'or a une convention, donc il garde l'affichage."""
    monkeypatch.setattr(C, "_current_price", lambda p: 4130.0)
    trade = {"pair": "XAU/USD", "direction": "buy", "entry_price": 4129.0,
             "size_lot": 0.01, "stop_loss": 4100.0, "take_profit": 4160.0,
             "created_at": "2026-10-30T12:00:00+00:00"}
    out = C._enrich_open_trade(dict(trade))
    assert out["pnl_pips"] == pytest.approx(100.0)


# --- LA DUPLICATION RESTE, et c'est voulu ---------------------------------

def test_les_deux_fonctions_DIVERGENT_desormais_et_c_est_VOULU():
    """⛔ Le garde-fou contre une « harmonisation » bien intentionnée.

    `mt5_sync._pip_size` alimente `slippage_pips`, colonne HISTORIQUE : lui
    faire rendre `None` sur la crypto changerait la valeur de la colonne et
    rendrait les lignes d'avant incomparables aux suivantes SOUS LE MEME NOM.
    C'est la faute qui a produit un verdict faux le 28/10.

    Si ce test échoue, quelqu'un a fusionné les deux. Relire les docstrings
    AVANT de « corriger ».
    """
    assert C._pip_size("BTC/USD") is None, "l'affichage n'invente plus"
    assert M._pip_size("BTC/USD") == 0.0001, (
        "la colonne historique doit garder SON ancienne convention, meme "
        "fausse : la changer casse la comparabilite sous le meme nom")


def test_les_deux_fonctions_restent_D_ACCORD_la_ou_la_convention_existe():
    """La divergence est bornee : elle ne porte QUE sur les classes sans
    convention. Partout ailleurs les deux doivent dire la meme chose."""
    for pair in ("XAU/USD", "XAG/USD", "USD/JPY", "EUR/JPY",
                 "EUR/USD", "GBP/USD", "USD/CAD"):
        assert C._pip_size(pair) == M._pip_size(pair), pair
