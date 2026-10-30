"""Le mappage destination <-> liste blanche est le SEUL fait reconstruit.

Il n'existe que sous forme de `if dest_id_wl == "admin_live"` dans la porte.
Si la production ajoute, retire ou renomme une liste blanche, le verdict de
`or-politique` devient faux EN SILENCE. Ce test echoue a la place.

Il ne tourne que dans le conteneur (il importe la production) et se saute
proprement ailleurs.
"""
import inspect

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


def test_le_mappage_destination_vers_liste_blanche_est_bien_celui_code():
    """Le fait reconstruit est DOUBLE : les noms de constantes (couverts
    ci-dessus) ET les clauses `dest_id_wl == "admin_live"` /
    `dest_id_wl == "admin_legacy"` dans `check_destination_allows` --
    c'est CA qui applique le mappage, pas la seule existence des constantes.
    Renommer une destination dans ces clauses, en retirer une ou etendre la
    porte a une 3e destination laisserait ce test vert sans ce controle, et
    `or-politique` rendrait CONFORME une destination que la porte ne filtre
    plus -- un faux-sur."""
    source = inspect.getsource(prod)
    assert 'dest_id_wl == "admin_live"' in source, (
        "la clause qui applique LIVE_WHITELIST_PAIRS a admin_live a disparu "
        "ou a ete renommee -- le mappage que or-politique reconstruit n'est "
        "plus celui que la porte applique")
    assert 'dest_id_wl == "admin_legacy"' in source, (
        "la clause qui applique LEGACY_WHITELIST_PAIRS a admin_legacy a "
        "disparu ou a ete renommee -- le mappage que or-politique "
        "reconstruit n'est plus celui que la porte applique")
