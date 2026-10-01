"""L'etiquette d'un hors-echantillon se compare au SIGNE DE L'ECHANTILLON.

⛔ Defaut du 2026-10-01. La lecture inline testait `R_oos > 0` et imprimait
<< signe tenu >>. Correct pour `pin_bar_down`, dont l'echantillon valait
+0,1550. Faux des que l'echantillon est negatif : les chaines
`sweep_sur_niveau_majeur` de l'or sont passees de **-0,17 a +0,43** et ont ete
etiquetees **CANDIDAT** alors que leur signe venait de s'INVERSER.

> Un outil de mesure qui se trompe d'etiquette est pire qu'un outil absent :
> il rend un verdict credible et faux.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_chemin = (Path(__file__).resolve().parents[2]
           / "scripts" / "test_hors_echantillon_chaine.py")
_spec = importlib.util.spec_from_file_location("oos_chaine", _chemin)
oos = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oos)

BARRE = 0.798


def test_le_signe_qui_s_inverse_est_INSTABLE_pas_candidat():
    """⛔ Le cas exact qui a produit la fausse etiquette."""
    etiquette = oos.lecture(-0.1662, +0.4297, 1.693, BARRE)
    assert "INSTABLE" in etiquette
    assert "CANDIDAT" not in etiquette


def test_un_negatif_qui_tient_est_CONFIRME_negatif():
    etiquette = oos.lecture(-0.20, -0.15, 0.1, BARRE)
    assert "CONFIRME NEGATIF" in etiquette


def test_un_positif_tenu_qui_franchit_est_candidat():
    """`pin_bar_down` : +0,1550 -> +0,0238, t 0,854 contre 0,798."""
    assert "CANDIDAT" in oos.lecture(+0.1550, +0.0238, 0.854, BARRE)


def test_un_positif_tenu_qui_ne_franchit_PAS_n_est_pas_candidat():
    etiquette = oos.lecture(+0.1550, +0.0238, 0.400, BARRE)
    assert "CANDIDAT" not in etiquette
    assert "NON franchie" in etiquette


def test_un_positif_devenu_negatif_est_INSTABLE_aussi():
    """La symetrie compte : l'inversion est instable dans les deux sens."""
    assert "INSTABLE" in oos.lecture(+0.30, -0.10, 1.5, BARRE)
