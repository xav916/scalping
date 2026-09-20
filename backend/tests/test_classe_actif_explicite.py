"""Distinguer « classee » de « retombee sur forex » — et ne rien changer d'autre.

## ⛔ Le defaut que ces tests verrouillent

`asset_class_for` rend `"forex"` pour tout symbole inconnu, en silence. Or 22
des ~31 paires crypto de l'univers ne sont reconnues que par
`ASSET_CLASS_OVERRIDES`, une ligne d'`.env` tenue a la main : la liste de
prefixes du code n'en couvre que neuf. Un override oublie, ou une cle mal
orthographiee, et la paire devient une DEVISE pour le dispatch, le modele de
cout et la garde de correlation.

⚠️ Le test le plus important est `test_asset_class_for_ne_CHANGE_PAS` : tout ce
travail doit etre lisible SANS modifier une seule valeur de retour. Un garde-fou
qui change le comportement qu'il surveille n'est pas un garde-fou.
"""
from __future__ import annotations

import pytest

from config import settings as st


def test_asset_class_for_ne_CHANGE_PAS():
    """⛔ LE controle negatif : aucune valeur de retour ne bouge."""
    attendu = {
        "XAU/USD": "metal", "XAG/USD": "metal",
        "EUR/USD": "forex", "GBP/JPY": "forex", "USD/CHF": "forex",
        "BTC/USD": "crypto", "ETH/USD": "crypto", "DOT/USD": "crypto",
        "WTI/USD": "energy", "SPX": "equity_index", "AAPL": "equity",
        # inconnu => forex, comme avant. C'est le defaut, pas une correction.
        "FOO/USD": "forex",
    }
    for paire, classe in attendu.items():
        assert st.asset_class_for(paire) == classe, paire


def test_une_paire_INCONNUE_n_a_PAS_de_classe_explicite():
    assert st.classe_explicite("FOO/USD") is None
    assert st.asset_class_for("FOO/USD") == "forex"   # le defaut reste


def test_les_DEUX_jambes_doivent_etre_des_devises():
    """⚠️ `ZEC/USD` a une jambe en devise. Ca ne fait pas une paire de devises."""
    assert st.classe_explicite("EUR/USD") == "forex"
    assert st.classe_explicite("ZEC/USD") is None


def test_un_OVERRIDE_rend_la_classe_explicite(monkeypatch):
    monkeypatch.setitem(st._asset_overrides, "ZEC/USD", "crypto")
    assert st.classe_explicite("ZEC/USD") == "crypto"
    assert st.asset_class_for("ZEC/USD") == "crypto"


def test_paires_sans_classe_ne_signale_QUE_les_inconnues(monkeypatch):
    monkeypatch.setitem(st._asset_overrides, "UNI/USD", "crypto")
    univers = ["XAU/USD", "EUR/USD", "DOT/USD", "UNI/USD", "FOO/USD", "BAR/USD"]
    assert st.paires_sans_classe(univers) == ["FOO/USD", "BAR/USD"]


def test_une_liste_VIDE_ou_bruitee_ne_leve_pas():
    assert st.paires_sans_classe([]) == []
    assert st.paires_sans_classe(["", None]) == []


@pytest.mark.parametrize("forme", ["EUR/USD", "eur/usd", "EUR-USD"])
def test_la_forme_du_separateur_ne_change_pas_le_verdict(forme):
    assert st.classe_explicite(forme) == "forex"
