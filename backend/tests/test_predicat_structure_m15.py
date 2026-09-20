"""La structure de l'échelle agrégée — et ce qu'elle doit REFUSER.

## ⛔ Ce qui est vraiment testé

Le prédicat lit `_tendance_de_structure` sur des bougies M15 **agrégées** depuis
le 5 min. Trois façons de se tromper en silence, et un test pour chacune :

1. **le côté** — un prédicat baissier qui accepterait une série haussière
   mesurerait la chaîne sans sa condition. C'est le défaut du 14/09, où neuf
   motifs haussiers vendaient, né d'un `else` muet ;
2. **l'histoire** — sans assez de bougies, l'agrégation rend moins que
   `FENETRE` et le prédicat doit se taire, jamais trancher par défaut ;
3. **l'agrégation** — si elle était contournée, le prédicat lirait la structure
   du 5 min sous le nom du M15. Le test compare les deux échelles sur une série
   construite pour qu'elles DIVERGENT.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.services import laboratoire_or as labo

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
BESOIN = (labo.FENETRE + 2) * labo.M15_FACTEUR


def _serie(pente: float, combien: int = BESOIN + 10) -> list[dict]:
    """Une série régulière : `pente` > 0 monte, < 0 descend, 0 = plate."""
    out = []
    for k in range(combien):
        base = 100.0 + pente * k
        out.append({"t": T0 + timedelta(minutes=5 * k), "o": base,
                    "h": base + 0.5, "l": base - 0.5, "c": base + 0.2,
                    "tv": 0.0})
    return out


def _juge(nom: str, bougies: list[dict]) -> bool:
    return labo._PREDICATS[nom](bougies, len(bougies))


def test_une_serie_qui_MONTE_donne_une_structure_haussiere():
    assert _juge("structure_m15_haussiere", _serie(+0.30)) is True


def test_une_serie_qui_DESCEND_donne_une_structure_baissiere():
    assert _juge("structure_m15_baissiere", _serie(-0.30)) is True


def test_le_COTE_ne_se_confond_pas():
    """⛔ Le contrôle négatif du 14/09."""
    monte = _serie(+0.30)
    assert _juge("structure_m15_haussiere", monte) is True
    assert _juge("structure_m15_baissiere", monte) is False


@pytest.mark.parametrize("nom", ["structure_m15_haussiere",
                                 "structure_m15_baissiere"])
def test_SANS_assez_d_histoire_le_predicat_est_fail_CLOSED(nom):
    court = _serie(+0.30, combien=BESOIN - 1)
    assert _juge(nom, court) is False


@pytest.mark.parametrize("nom", ["structure_m15_haussiere",
                                 "structure_m15_baissiere"])
def test_une_serie_PLATE_ne_donne_aucun_avis(nom):
    assert _juge(nom, _serie(0.0)) is False


def test_le_predicat_lit_bien_l_echelle_AGREGEE():
    """⚠️ Si l'agrégation était contournée, il lirait le 5 min sous le nom M15.

    La série monte franchement sur l'ensemble, mais ses trois dernières bougies
    de 5 min plongent — assez pour changer la lecture du 5 min sur sa fin, pas
    assez pour retourner la structure des 50 bougies M15.
    """
    b = _serie(+0.30)
    for x in b[-3:]:
        x["h"] -= 20.0
        x["l"] -= 20.0
        x["o"] -= 20.0
        x["c"] -= 20.0
    assert _juge("structure_m15_haussiere", b) is True


def test_une_bougie_MALFORMEE_ne_fait_pas_lever():
    b = _serie(+0.30)
    b[-5]["h"] = None
    assert _juge("structure_m15_haussiere", b) is False


def test_le_facteur_est_celui_du_M15():
    """3 x 5 min. Un autre facteur mesurerait une autre échelle sous ce nom."""
    assert labo.M15_FACTEUR == 3
