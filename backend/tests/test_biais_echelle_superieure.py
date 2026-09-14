"""Le biais de l'echelle superieure — le premier maillon de la chaine.

⛔ **Le piege evite** : agreger les bougies en H4 FIXE ne voudrait rien dire
aux echelles superieures. Le laboratoire mesure chaque motif a quatre echelles
(5 min, 15 min, 30 min, 1 h) ; un « biais H4 » calcule sur des bougies d'une
heure serait un biais de **huit jours** sous le meme nom. Deux fenetres
differentes, un seul nom : c'est exactement le defaut que
`sessions_marche` a ete cree pour empecher ailleurs.

🔑 Le biais est donc **relatif a l'echelle mesuree** : la meme
`_tendance_de_structure` — celle qui existe deja, qui coupe une fenetre en deux
et exige A LA FOIS un plus-haut ET un plus-bas superieurs — appliquee a une
fenetre **8 x plus longue** que celle des detecteurs.

⚠️ **Un seul reglage neuf** : le facteur 8. Chaque seuil supplementaire est un
degre de liberte, donc de l'edge fabrique.
"""
from __future__ import annotations

from backend.services import laboratoire_or as labo


def _bougies(specs):
    """⚠️ Horodatage construit par `timedelta`, pas par f-string.

    Ma premiere version ecrivait `{i // 12:02d}` comme heure : au-dela de la
    288e bougie elle produisait « 34:00 », `fromisoformat` levait, et le `try`
    du predicat rendait **False**. Le test echouait pour une raison qui n'avait
    rien a voir avec ce qu'il mesurait — et un fail-closed honnete ressemble
    alors a un bug du code teste.
    """
    from datetime import datetime, timedelta, timezone
    t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    return [{"t": (t0 + timedelta(minutes=5 * i)).isoformat(),
             "o": o, "h": h, "l": l, "c": c, "tv": 500}
            for i, (o, h, l, c) in enumerate(specs)]


def _monte(n, depart=100.0, pas=0.5):
    return [(depart + i * pas, depart + i * pas + 0.3,
             depart + i * pas - 0.3, depart + i * pas) for i in range(n)]


def _descend(n, depart=300.0, pas=0.5):
    return [(depart - i * pas, depart - i * pas + 0.3,
             depart - i * pas - 0.3, depart - i * pas) for i in range(n)]


def test_les_deux_predicats_existent():
    assert "biais_haussier" in labo._PREDICATS
    assert "biais_baissier" in labo._PREDICATS


def test_un_marche_qui_MONTE_donne_un_biais_haussier():
    b = _bougies(_monte(labo.BIAIS_FENETRE + 10))
    i = len(b)
    assert labo._PREDICATS["biais_haussier"](b, i) is True
    assert labo._PREDICATS["biais_baissier"](b, i) is False


def test_un_marche_qui_DESCEND_donne_un_biais_baissier():
    b = _bougies(_descend(labo.BIAIS_FENETRE + 10))
    i = len(b)
    assert labo._PREDICATS["biais_baissier"](b, i) is True
    assert labo._PREDICATS["biais_haussier"](b, i) is False


def test_sans_ASSEZ_d_HISTOIRE_le_predicat_repond_NON():
    """⛔ Fail-closed. Repondre OUI par defaut ferait declencher la chaine
    partout en pretendant avoir vu un contexte."""
    b = _bougies(_monte(50))
    assert labo._PREDICATS["biais_haussier"](b, len(b)) is False
    assert labo._PREDICATS["biais_baissier"](b, len(b)) is False


def test_le_predicat_ne_regarde_PAS_au_dela_du_signal():
    """⚠️ Meme discipline que `volume_fort` : il lit `bougies[:i]`. Un predicat
    qui voit une bougie de plus mesure l'avenir."""
    montee = _monte(labo.BIAIS_FENETRE + 10)
    chute = _descend(40, depart=montee[-1][3])
    b = _bougies(montee + chute)
    i = len(montee)                       # on se place AVANT la chute
    assert labo._PREDICATS["biais_haussier"](b, i) is True, (
        "la chute posterieure a change le verdict : le predicat lit l'avenir")


def test_la_FENETRE_vaut_HUIT_fois_celle_des_detecteurs():
    """Le seul reglage neuf, et il doit rester derive — pas un nombre pose."""
    assert labo.BIAIS_FACTEUR == 8
    assert labo.BIAIS_FENETRE == labo.BIAIS_FACTEUR * labo.FENETRE


def test_les_deux_chaines_sont_des_SOUS_ENSEMBLES_stricts_du_balayage():
    noms = {c["nom"]: c for c in labo.CHAINES}
    for sens, motif, pred in (("haussier", "liquidity_sweep_up", "biais_haussier"),
                              ("baissier", "liquidity_sweep_down", "biais_baissier")):
        c = noms[f"sweep_avec_biais_{sens}"]
        assert c["motifs"] == (motif,)
        assert c["declencheur"] == motif
        assert c["predicats"] == (pred,)
        assert c["fenetre"] == 0
