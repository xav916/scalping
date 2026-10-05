"""Les horizons agreges doivent etre NORMALISES, comme ce que la porte compare.

## ⛔ LE DEFAUT, trouve le 2026-10-05 en cherchant pourquoi le WTI ne tradait pas

`_horizons_agreges()` derive les horizons de `ECHELLES_AGREGEES` via
`horizon_pour(facteur)`, qui rend `f"{5 * facteur}min"` :

    facteur 3  -> "15min"      normalize -> "15min"   ✅ identique
    facteur 6  -> "30min"      normalize -> "30min"   ✅ identique
    facteur 12 -> "60min"      normalize -> "1h"      ⛔ DIFFERENT

La porte d'horizon, elle, NORMALISE le setup avant de tester l'appartenance.
Elle cherchait donc `1h` dans un ensemble qui contenait `60min` — et refusait
les DEUX orthographes :

    horizon=60min -> horizon_not_allowed
    horizon=1h    -> horizon_not_allowed

🔑 **L'echelle 60 minutes n'a donc jamais fonctionne, sur aucune route.** Le 15
et le 30 min marchaient par coincidence : leur nom brut EST leur nom normalise.

⚠️ Troisieme fois dans la meme journee que le couple `1h` / `60min` fait des
degats — apres les motifs de l'or a 60 min, et la derogation d'horizon. Le
remede general : **ne jamais comparer deux noms d'horizon sans les normaliser
tous les deux**.
"""
from __future__ import annotations

import pytest

from backend.services import bridge_destinations as bd
from backend.services import echelle_agregee as ea
from backend.services.bridge_destinations import _horizons_agreges
from backend.services.echelle_agregee import horizon_pour
from backend.services.horizon import normalize


@pytest.fixture
def avec_60min(monkeypatch):
    """⚠️ Force le facteur 12. Sans lui, ces tests passent POUR RIEN :
    `ECHELLES_AGREGEES` vaut « 3,6 » par defaut et la production « 3,6,12 ».
    La 1re version de ce fichier etait verte sans rien eprouver."""
    monkeypatch.setattr(ea, "FACTEURS", (3, 6, 12))


def test_tous_les_horizons_agreges_sont_NORMALISES(avec_60min):
    """⛔ LE TEST QUI COMPTE : chaque horizon rendu doit etre son propre
    normalise, sinon la porte ne le reconnaitra jamais."""
    for h in _horizons_agreges():
        assert h == normalize(h), (
            f"« {h} » n'est pas normalise ({normalize(h)}) — la porte "
            f"cherchera « {normalize(h)} » et ne le trouvera pas")


def test_le_facteur_12_donne_bien_1h_et_non_60min(avec_60min):
    """Le cas precis qui cassait."""
    assert horizon_pour(12) == "60min", "le producteur garde son nom brut"
    assert normalize("60min") == "1h"
    assert "1h" in _horizons_agreges()
    assert "60min" not in _horizons_agreges(), (
        "l'orthographe brute ne doit plus sortir : la porte compare du "
        "normalise")


def test_les_facteurs_3_et_6_restent_inchanges(avec_60min):
    """⚠️ Ils marchaient par coincidence — leur nom brut EST leur normalise.
    La correction ne doit rien leur enlever."""
    for f, attendu in ((3, "15min"), (6, "30min")):
        assert normalize(horizon_pour(f)) == attendu
        assert attendu in _horizons_agreges()


def test_un_ensemble_VIDE_reste_vide(monkeypatch):
    """Aucune echelle agregee declaree ⇒ aucun horizon ouvert, pas un repli."""
    monkeypatch.setattr(ea, "FACTEURS", ())
    assert bd._horizons_agreges() == frozenset()
