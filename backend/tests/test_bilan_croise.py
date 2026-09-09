"""Le bilan croisé doit dire le SENS, et refuser d'enjoliver un motif isolé.

⛔ Ce que ces tests protègent : `PBO = 0,579` sur l'argent réel — sélectionner
sur la performance mesurée ne généralise pas. Un message qui titrerait sur un R
élevé obtenu sur UN instrument automatiserait exactement le geste que ce chiffre
condamne.

La traduction du chiffre en verdict est la seule partie qui peut se tromper
**en silence**.
"""
import importlib.util
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "scripts" / "mesurer_bilan_croise.py"


@pytest.fixture(scope="module")
def m():
    spec = importlib.util.spec_from_file_location("bilan_croise", _SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_aucune_mesure_ne_passe_pas_pour_rien_a_signaler(m):
    """⛔ « Aucune mesure » et « aucun motif » sont deux faits différents."""
    court, phrase = m.verdict({}, 0)
    assert "aucune mesure" in court
    assert "n'a pas eu lieu" in phrase


def test_rien_au_dessus_du_plafond_est_le_resultat_ATTENDU(m):
    """Le dire évite de lire un silence comme une panne."""
    court, phrase = m.verdict({}, 20)
    assert "rien ne bat le hasard" in court
    assert "ATTENDU" in phrase


def test_un_motif_ISOLE_est_signale_comme_SUSPECT(m):
    """⛔ Le cœur : un seul instrument, c'est précisément ce que le PBO
    condamne. Le message doit le dire, pas le célébrer."""
    conc = {"fvg_up": {"instruments": 1, "sur": 20, "paires": ["XAU/USD"],
                       "sens": "gagnant"}}
    court, phrase = m.verdict(conc, 20)
    assert "ISOLE" in court
    assert "0,579" in phrase or "0.579" in phrase
    assert "pas a armer" in phrase.lower() or "pas à armer" in phrase.lower()


def test_une_CONCORDANCE_large_est_nommee_pour_ce_qu_elle_est(m):
    conc = {"fvg_up": {"instruments": 7, "sur": 20, "paires": ["A"],
                       "sens": "gagnant"}}
    court, phrase = m.verdict(conc, 20)
    assert "7 instruments" in court
    assert "plusieurs nuits" in phrase, "la reserve temporelle manque"


def test_le_message_n_a_AUCUNE_balise(m):
    par_paire = {"XAU/USD": [{"pair": "XAU/USD", "horizon": "5min",
                              "motif": "fvg_up", "sens": "buy", "n": 60,
                              "r_moyen": 0.2, "t": 4.0, "plafond": 3.0}]}
    _, corps = m.construire("2026-09-10", par_paire, 3.0,
                            {"fvg_up": {"instruments": 1, "sur": 1,
                                        "paires": ["XAU/USD"], "sens": "gagnant"}})
    assert "<" not in corps and ">" not in corps


def test_le_message_NOMME_les_instruments_mesures(m):
    """Un bilan sans la liste ne permet pas de voir qu'il en manque."""
    par_paire = {p: [] for p in ("XAU/USD", "EUR/USD")}
    _, corps = m.construire("2026-09-10", par_paire, 3.0, {})
    assert "XAU/USD" in corps and "EUR/USD" in corps
    assert "2 instrument" in corps
