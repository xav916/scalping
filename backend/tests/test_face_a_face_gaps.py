"""Le face-à-face des gaps doit dire le SENS, pas des nombres.

⛔ Ce que ces tests protègent : un écart entre deux motifs peut naître du seul
bruit d'échantillonnage. Annoncer « la distinction existe » sur n=12 serait
fabriquer une découverte — exactement ce que ce dépôt a passé la journée à
débusquer. La traduction du chiffre en verdict est la seule partie qui peut se
tromper **en silence**.

Cf. [[project_controle_aleatoire_verdict_2026_08_05]] · [[project_laboratoire_or_2026_09_08]]
"""
import importlib.util
from pathlib import Path

import pytest

_SRC = (Path(__file__).resolve().parents[2] / "scripts"
        / "mesurer_face_a_face_gaps.py")


@pytest.fixture(scope="module")
def m():
    spec = importlib.util.spec_from_file_location("face_a_face_gaps", _SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_un_ecart_sur_PEU_de_fenetres_ne_conclut_pas(m):
    """⛔ Le piège : +0,4 R sur n=12 se lit comme une découverte."""
    court, phrase = m.verdict(0.40, 12, 0.00, 80, 2.5)
    assert "trop tot" in court
    assert "bruit" in phrase


def test_un_ecart_NUL_dit_que_c_est_le_meme_evenement(m):
    """La réponse la plus probable, et elle doit être dite clairement."""
    court, phrase = m.verdict(0.05, 200, 0.02, 180, 2.5)
    assert "AUCUNE difference" in court
    assert "meme evenement" in phrase


def test_un_ecart_NET_nomme_le_gagnant_ET_sa_reserve(m):
    """⚠️ On vérifie la PROPRIÉTÉ — le gagnant est nommé — et non un mot figé.
    La sonde sert plusieurs confrontations : « retracement » n'a aucun sens
    pour BOS contre breakout. Un verdict juste sous une étiquette fausse est
    pire qu'un verdict absent."""
    court, phrase = m.verdict(0.35, 200, 0.05, 180, 2.55,
                              "cassure AVEC contexte", "cassure NUE")
    assert "cassure AVEC contexte" in court
    assert "cassure NUE" not in court
    assert "2.55" in phrase, "le plafond du hasard doit etre rappele"


def test_le_sens_INVERSE_est_nomme_aussi(m):
    court, _ = m.verdict(0.02, 200, 0.40, 180, 2.5,
                         "cassure AVEC contexte", "cassure NUE")
    assert "cassure NUE" in court


def test_les_confrontations_comparent_des_familles_DISJOINTES(m):
    """⛔ Si une famille apparaissait des deux côtés, l'écart serait un
    artefact : la même cellule alimenterait les deux moyennes."""
    for conf in m.CONFRONTATIONS:
        assert not (set(conf["a"]) & set(conf["b"])), conf["titre"]


def test_une_famille_VIDE_ne_passe_pas_pour_une_egalite(m):
    """⛔ « Aucune fenêtre » et « aucun écart » sont deux faits différents."""
    court, _ = m.verdict(0.0, 0, 0.3, 100, 2.5)
    assert "pas encore mesurable" in court


def test_aucune_mesure_le_DIT(m):
    titre, corps = m.construire(None, [])
    assert "rien a lire" in titre
    assert "n'a pas eu lieu" in corps


def test_le_message_n_a_AUCUNE_balise(m):
    """L'endpoint échappe le HTML : une balise s'afficherait telle quelle."""
    cellules = [{"horizon": "5min", "motif": "gap_retrace_up", "sens": "buy",
                 "n": 50, "r": 0.2, "t": 1.1, "plafond": 2.5}]
    _, corps = m.construire("2026-09-10", cellules)
    assert "<" not in corps and ">" not in corps


def test_la_moyenne_est_PONDEREE_par_le_nombre_de_fenetres(m):
    """⛔ Une cellule à n=3 pèserait autant qu'une à n=300 sinon."""
    cellules = [
        {"motif": "gap_retrace_up", "n": 300, "r": 0.10, "horizon": "5min",
         "sens": "buy", "t": 1.0, "plafond": 2.5},
        {"motif": "gap_retrace_down", "n": 3, "r": 5.00, "horizon": "5min",
         "sens": "sell", "t": 1.0, "plafond": 2.5},
    ]
    r, n = m._moyenne_ponderee(cellules, m.RETRACE)
    assert n == 303
    assert r < 0.16, f"la cellule a n=3 a domine la moyenne : {r}"
