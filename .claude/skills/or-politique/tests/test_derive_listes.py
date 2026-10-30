"""Le mappage destination <-> liste blanche est le SEUL fait reconstruit.

Il n'existe que sous forme de `if dest_id_wl == "admin_live"` dans la porte.
Si la production ajoute, retire ou renomme une liste blanche, le verdict de
`or-politique` devient faux EN SILENCE. Ce test echoue a la place.

Il ne tourne que dans le conteneur (il importe la production) et se saute
proprement ailleurs.
"""
import pytest

prod = pytest.importorskip("backend.services.mt5_bridge",
                           reason="hors conteneur de production")

ATTENDUES = {"LIVE_WHITELIST_PAIRS", "LEGACY_WHITELIST_PAIRS"}


def test_les_constantes_de_liste_blanche_sont_exactement_celles_attendues():
    trouvees = {n for n in dir(prod) if n.endswith("_WHITELIST_PAIRS")}
    assert trouvees == ATTENDUES, (
        "la production porte %s ; or-politique reconstruit le mappage pour %s. "
        "Une liste blanche ajoutee ou renommee rend le verdict faux."
        % (sorted(trouvees), sorted(ATTENDUES)))
