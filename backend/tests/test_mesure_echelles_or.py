"""La sonde « échelles M15/M30 sur l'or » doit dire le SENS, pas des nombres.

⛔ **Ce que ces tests protègent.** Le 09/09 j'ai mesuré que 156 des 156 signaux
M15/M30 de l'or tombaient la nuit, et j'en ai conclu que les échelles agrégées
produisaient « au moment où l'or coûte trop cher ». C'était faux : le module
n'avait que treize heures d'existence, presque toutes nocturnes. *Un motif
horaire mesuré sur une fenêtre qui ne contient qu'une seule phase n'est pas un
motif horaire.*

La sonde existe pour rendre le chiffre qui manquait. Ces tests verrouillent la
seule partie qui peut se tromper **en silence** : la traduction du chiffre en
verdict. Un compte juste assorti d'une conclusion fausse est pire qu'un compte
absent — c'est exactement l'erreur qu'on répare.

Cf. [[project_echelles_agregees_m15_m30_2026_09_08]]
"""
import importlib.util
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "scripts" / "mesurer_echelles_or.py"


@pytest.fixture(scope="module")
def m():
    spec = importlib.util.spec_from_file_location("mesure_echelles_or", _SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ─── Le verdict ──────────────────────────────────────────────────────

def test_aucun_signal_en_journee_dit_que_l_ouverture_ne_sert_a_rien(m):
    """Le cas attendu au premier passage — et il doit rester prudent."""
    court, phrase = m.verdict(jour_n=0, nuit_n=140, motifs_jour={}, trades=0)
    assert "aucun signal" in court
    assert "RIEN" in phrase
    assert "une seule séance" in phrase.lower() or "plusieurs" in phrase


def test_des_trades_passes_est_le_cas_qui_JUSTIFIE_d_ouvrir(m):
    """Seul un trade réellement ouvert prouve que la chaîne est franchissable."""
    court, phrase = m.verdict(
        jour_n=12, nuit_n=40, motifs_jour={"below_confidence": 3}, trades=2)
    assert "trades sont passés" in court
    assert "2 trade" in phrase


def test_le_spread_dominant_dit_que_l_ouverture_ne_servirait_a_rien(m):
    """⛔ Le piège : des signaux en journée pourraient faire croire au feu vert.

    S'ils meurent quand même sur la porte de spread, ouvrir l'horizon ne fait
    que déplacer le refus d'une porte.
    """
    court, phrase = m.verdict(
        jour_n=9, nuit_n=30,
        motifs_jour={m.PORTE_SUIVANTE: 7, "below_confidence": 2}, trades=0)
    assert "spread" in court
    assert "ne servirait à rien" in phrase


def test_un_AUTRE_motif_dominant_designe_la_bonne_porte(m):
    """Si ce n'est pas le spread, le message doit le DIRE — sinon on irait
    desserrer la mauvaise porte, sur de l'argent réel."""
    court, phrase = m.verdict(
        jour_n=9, nuit_n=30,
        motifs_jour={"pattern_not_allowed": 8, m.PORTE_SUIVANTE: 1}, trades=0)
    assert "ailleurs" in court
    assert "pattern_not_allowed" in phrase
    assert "PAS la porte de spread" in phrase


def test_des_trades_PRIMENT_sur_un_motif_dominant(m):
    """Un refus dominant n'annule pas un trade réellement passé : la preuve
    positive gagne sur la statistique des refus."""
    court, _ = m.verdict(
        jour_n=9, nuit_n=30, motifs_jour={m.PORTE_SUIVANTE: 50}, trades=1)
    assert "trades sont passés" in court


# ─── Le message ──────────────────────────────────────────────────────

def _lignes(jour=(), nuit=(), reel=0):
    out = [(h, "admin_legacy", m_) for h, m_ in jour]
    out += [(h, "admin_legacy", m_) for h, m_ in nuit]
    out += [("02", "admin_live", "horizon_not_allowed")] * reel
    return out


def test_le_message_separe_le_jour_de_la_nuit(m):
    lignes = _lignes(jour=[("10", "below_confidence"), ("14", "below_confidence")],
                     nuit=[("02", "heure_spread_defavorable")] * 5)
    titre, corps = m.construire(lignes, trades=0, jour="2026-09-09")
    assert "journée 06-19h UTC : 2" in corps
    assert "nuit 20-05h : 5" in corps


def test_le_message_porte_TOUJOURS_la_reserve_demo_vs_reel(m):
    """⛔ « Le démo pilote le réel » est faux hors miroir. Un chiffre dont on
    tait le sens de l'erreur ferait décider à l'aveugle."""
    _, corps = m.construire(_lignes(jour=[("10", "x")]), trades=0,
                            jour="2026-09-09")
    assert "borne basse" in corps
    assert "PLUS filtré" in corps


def test_le_message_dit_son_BUT(m):
    """Une sonde qui ne dit pas pourquoi elle parle finit ignorée."""
    _, corps = m.construire([], trades=0, jour="2026-09-09")
    assert corps.startswith("BUT —")


def test_une_journee_VIDE_ne_passe_pas_pour_une_journee_saine(m):
    """⛔ Zéro signal et « rien à signaler » sont deux faits différents."""
    titre, corps = m.construire([], trades=0, jour="2026-09-09")
    assert "aucun signal" in titre
    assert "M15/M30 du 2026-09-09 : 0" in corps


def test_les_refus_du_REEL_ne_polluent_pas_les_motifs_du_demo(m):
    """⛔ Le compte réel tue tout à `horizon_not_allowed` : compter ses refus
    parmi les motifs du démo ferait croire que l'horizon est le mur, alors
    que c'est précisément la porte qu'on envisage d'ouvrir."""
    lignes = _lignes(jour=[("10", "below_confidence")], reel=40)
    _, corps = m.construire(lignes, trades=0, jour="2026-09-09")
    assert "horizon_not_allowed — 40" not in corps
    assert "sur le réel : 40" in corps
