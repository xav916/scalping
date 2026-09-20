"""Le dictionnaire de vocabulaire — et les quatre refus qui le rendent utile.

## ⛔ Ce qui est vraiment teste ici

Un glossaire n'a de valeur que s'il ne peut pas MENTIR sur trois choses : d'ou
vient ce qu'il dit, ce qui empeche de coder un terme, et le fait qu'il ne
produit AUCUNE regle de trading. Sans ces garde-fous, un terme compris a
moitie finirait par trader — et une synthese produite par un autre assistant
deviendrait « la methode de Vivien » par simple recopie.
"""
from __future__ import annotations

import pytest

from backend.services import notions_vivien as nv


def test_chaque_terme_dit_ce_qu_on_RETIENT_et_ou_on_en_est():
    for terme, v in nv.VOCABULAIRE.items():
        assert v.get("retenu"), f"{terme} : rien de retenu"
        assert v.get("statut") in nv._STATUTS, f"{terme} : statut hors bornes"
        assert "brique" in v, f"{terme} : la brique du depot n'est pas dite"


def test_un_terme_NON_CODABLE_doit_dire_POURQUOI():
    """⛔ Sans raison ecrite, « non codable » est un avis, pas un constat.

    Et la distinction que ce test protege est celle qui compte : un terme peut
    etre parfaitement compris et rester non codable parce que la DONNEE
    n'existe pas. Le confondre avec « definition manquante » ferait chercher
    une definition la ou il faut changer de marche.
    """
    for terme, v in nv.VOCABULAIRE.items():
        if v["statut"] == nv.NON_CODABLE:
            assert v.get("blocage"), f"{terme} : non codable sans raison dite"


def test_la_PROVENANCE_est_une_seule_constante_partagee():
    """Aucune entree ne porte sa propre source : elle ne peut donc pas deriver
    d'un terme a l'autre, ni monter en « Vivien dit » par recopie."""
    assert "NON consultees de premiere main" in nv.SOURCE_SYNTHESE
    for terme, v in nv.VOCABULAIRE.items():
        assert "source" not in v, (
            f"{terme} porte une source propre — la provenance doit rester "
            "UNE constante, sinon elle se durcit en silence")


def test_le_VOCABULAIRE_ne_produit_AUCUNE_chaine():
    """⛔ LE contrôle négatif. `NOTIONS` peut devenir des chaines ; le
    vocabulaire, jamais. Les melanger ferait trader un terme a demi compris."""
    avant = len(nv.chaines())
    assert avant == 0, "aucune notion n'est complete : rien ne doit sortir"
    # Le vocabulaire n'est pas une source de chaines, meme en le passant.
    assert not set(nv.VOCABULAIRE) & {n["nom"] for n in nv.NOTIONS}


def test_statut_inconnu_LEVE():
    with pytest.raises(ValueError):
        nv.vocabulaire_par_statut("PRESQUE")


def test_les_blocages_sont_lisibles_d_un_seul_appel():
    b = nv.blocages()
    assert b, "un dictionnaire sans blocage cache ce qui reste a faire"
    # Les trois briques d'order flow sont bloquees par la DONNEE, pas par une
    # definition : c'est le fait d'ingenierie a ne pas perdre.
    assert "DONNEE ABSENTE" in b["volume_delta"]
