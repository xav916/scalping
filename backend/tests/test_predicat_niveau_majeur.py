"""Le prédicat du NIVEAU MAJEUR — et surtout ce qu'il doit REFUSER.

## ⛔ Ce qui est vraiment testé ici

Le test qui compte est `test_un_balayage_qui_DEPASSE_le_niveau_est_REFUSE`.
Sans cette condition, la mesure de recouvrement du 2026-09-20 (fixture figée,
4 598 fenêtres) donnait :

    balayage des HAUTS : 31 déclenchements, dont 80,6 % DÉPASSAIENT
    balayage des BAS   : 53 déclenchements, dont 94,3 % DÉPASSAIENT

La règle sélectionnait donc des CASSURES de la grande fourchette, pas des
niveaux retestés — la population inverse de celle que son nom annonce. Et la
version large était la plus FOURNIE : lire son R aurait donné un résultat
exploitable statistiquement et faux sur le fond.

⚠️ Le second contrôle négatif est le CÔTÉ. Un prédicat `bas` qui accepterait un
setup du côté `haut` mesurerait la chaîne sans sa condition, et le verdict
serait faux sans que rien ne le dise — le défaut du 14/09, où neuf motifs
haussiers vendaient, est né d'un `else` muet.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.services import laboratoire_or as labo

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)

NIVEAU_HAUT = 110.0     # le plus-haut des 400, pose une seule fois
NIVEAU_BAS = 90.0       # le plus-bas des 400
PIC = 50                # loin de la fin : n'entre pas dans l'ATR des 15


def _serie(haut_courant: float, bas_courant: float,
           combien: int = 401) -> list[dict]:
    """`combien` bougies de fond + une bougie courante, au format du labo.

    ⚠️ Chaque bougie a une amplitude de 1,0 : sans amplitude, `_calculate_atr`
    rend 0 et le prédicat est fail-closed — le test ne mesurerait alors que ça.
    """
    out = []
    for k in range(combien):
        h, b = 100.0, 99.0
        if k == PIC:                     # le niveau majeur, dans les 400
            h, b = NIVEAU_HAUT, NIVEAU_BAS
        out.append({"t": T0 + timedelta(minutes=5 * k), "o": b + 0.2,
                    "h": h, "l": b, "c": b + 0.5, "tv": 0.0})
    out.append({"t": T0 + timedelta(minutes=5 * combien),
                "o": 99.5, "h": haut_courant, "l": bas_courant,
                "c": 99.7, "tv": 0.0})
    return out


def _juge(cote: str, bougies: list[dict]) -> bool:
    """Appelle le prédicat comme le laboratoire : `i` = fin de ce qui est vu."""
    return labo._PREDICATS[f"sur_niveau_majeur_{cote}"](bougies, len(bougies))


# ── Ce qui doit passer ────────────────────────────────────────────────

def test_un_balayage_SOUS_le_niveau_et_a_portee_est_RETENU():
    assert _juge("haut", _serie(haut_courant=109.7, bas_courant=99.0)) is True


def test_un_balayage_AU_DESSUS_du_plus_bas_et_a_portee_est_RETENU():
    assert _juge("bas", _serie(haut_courant=100.0, bas_courant=90.2)) is True


# ── LES CONTRÔLES NÉGATIFS — ce sont eux qui font la règle ────────────

def test_un_balayage_qui_DEPASSE_le_niveau_est_REFUSE():
    """⛔ LE test. 80,6 % et 94,3 % des déclenchements étaient dans ce cas."""
    assert _juge("haut", _serie(haut_courant=110.3, bas_courant=99.0)) is False
    assert _juge("bas", _serie(haut_courant=100.0, bas_courant=89.8)) is False


def test_un_balayage_LOIN_du_niveau_est_refuse():
    """La tolérance vaut 0,5 × ATR(14) ≈ 0,5 ici : 2,0 est hors de portée."""
    assert _juge("haut", _serie(haut_courant=108.0, bas_courant=99.0)) is False
    assert _juge("bas", _serie(haut_courant=100.0, bas_courant=92.0)) is False


def test_le_COTE_ne_se_confond_pas():
    """⚠️ Un setup du côté HAUT ne doit rien dire au prédicat du côté BAS."""
    sur_le_haut = _serie(haut_courant=109.7, bas_courant=99.0)
    assert _juge("haut", sur_le_haut) is True
    assert _juge("bas", sur_le_haut) is False


def test_SANS_les_400_bougies_le_predicat_est_fail_CLOSED():
    """Pas d'histoire, pas de niveau — jamais un avis par défaut."""
    court = _serie(haut_courant=109.7, bas_courant=99.0, combien=300)
    assert _juge("haut", court) is False


def test_le_niveau_EXCLUT_la_bougie_courante():
    """Sinon toute bougie faisant un extrême neuf serait à distance ZÉRO.

    La bougie courante porte ici le plus-haut absolu de la série. Si elle
    entrait dans le calcul du niveau, `niveau == atteint` et le prédicat
    serait vrai par construction.
    """
    assert _juge("haut", _serie(haut_courant=200.0, bas_courant=99.0)) is False


@pytest.mark.parametrize("cote", ["haut", "bas"])
def test_une_bougie_PLATE_ne_donne_aucun_avis(cote):
    """ATR nul = pas d'échelle, donc pas de tolérance : fail-closed."""
    plates = [{"t": T0 + timedelta(minutes=5 * k), "o": 100.0, "h": 100.0,
               "l": 100.0, "c": 100.0, "tv": 0.0} for k in range(402)]
    assert _juge(cote, plates) is False
