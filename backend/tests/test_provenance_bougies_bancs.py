"""Un banc ne doit pas affirmer lire le COURTIER quand il lit Twelve Data.

⛔ LE DÉFAUT DU 2026-10-10. `/app/data/candles_5min.db` est écrit par
`scripts/ml_fetch_candles_5min.py`, dont la première ligne dit « Récupère
l'historique 5 min de **Twelve Data** ». Or six bancs le lisent, et **trois**
affirmaient dans leur propre en-tête « bougies **DU COURTIER** » :

    banc_contre_fil_moins_deux_euros.py   « Bougies **DU COURTIER** »
    banc_contre_fil_apres_gain.py         « **Bougies DU COURTIER** »
    banc_filtre_tendance_or.py            « bougies 5 min du COURTIER »

🔑 Le coût : l'écart mesuré entre les deux sources sur l'or est de **0,53 à
0,76 $** de médiane au meilleur alignement mutuel, et seulement **7 à 10 %**
des clôtures tombent à moins de 0,10 $. C'est 0,015 % d'un cours à 4 100 $ —
mais **22 à 34 % d'un objectif de 2,24 $**. Un banc qui éprouve un objectif ou
un stop sur ces prix mesure donc une borne que le courtier n'a pas cotée, tout
en affirmant le contraire dans sa propre documentation.

⚠️ Ce test ne juge PAS la qualité de Twelve Data. Il interdit seulement à un
fichier de se tromper sur sa propre source — c'est-à-dire de rendre son lecteur
incapable de savoir ce qu'il lit.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
SCRIPTS = RACINE / "scripts"

# Le magasin Twelve Data, et le script qui l'écrit.
MAGASIN_TWELVE = "candles_5min.db"
ECRIVAIN = "ml_fetch_candles_5min.py"

# ⛔ Une affirmation de provenance « courtier » : le mot COURTIER en capitales,
# tel que les en-têtes et les sorties l'employaient. On l'autorise uniquement
# quand la même ligne dit explicitement que ce n'en est PAS un.
_AFFIRME_COURTIER = re.compile(r"COURTIER")
_DEMENTI = re.compile(r"pas du courtier|TWELVE|Twelve|note ci-dessous"
                      r"|dans leur en-tete")


def _lecteurs_du_magasin() -> list[Path]:
    out = []
    for p in sorted(SCRIPTS.glob("*.py")):
        if p.name == ECRIVAIN:
            continue
        if MAGASIN_TWELVE in p.read_text(encoding="utf-8"):
            out.append(p)
    return out


def test_le_magasin_est_bien_ecrit_par_twelve_data():
    """🔑 La prémisse du test. Si l'écrivain changeait de source, ce test doit
    tomber pour qu'on relise les en-têtes au lieu de les figer sur une
    provenance périmée."""
    tete = (SCRIPTS / ECRIVAIN).read_text(encoding="utf-8")[:400]
    assert "Twelve Data" in tete, (
        f"{ECRIVAIN} ne mentionne plus Twelve Data en tête : la provenance de "
        f"{MAGASIN_TWELVE} a peut-être changé, et les en-têtes des bancs "
        "doivent être relus.")


def test_il_y_a_bien_des_bancs_qui_lisent_ce_magasin():
    """⚠️ Sinon le test suivant passerait en ne vérifiant rien."""
    lecteurs = _lecteurs_du_magasin()
    assert len(lecteurs) >= 5, (
        f"seulement {len(lecteurs)} lecteur(s) de {MAGASIN_TWELVE} trouvé(s) — "
        "le test ne protège plus rien")


@pytest.mark.parametrize("chemin", _lecteurs_du_magasin(),
                         ids=lambda p: p.name)
def test_aucun_banc_n_affirme_lire_le_courtier(chemin: Path):
    """⛔ LE DÉFAUT RÉINJECTABLE : remettre « bougies DU COURTIER » dans
    l'en-tête d'un de ces fichiers doit faire tomber ce test."""
    fautes = []
    for n, ligne in enumerate(chemin.read_text(encoding="utf-8").splitlines(),
                              start=1):
        if _AFFIRME_COURTIER.search(ligne) and not _DEMENTI.search(ligne):
            fautes.append(f"{chemin.name}:{n}: {ligne.strip()}")
    assert not fautes, (
        f"{chemin.name} lit {MAGASIN_TWELVE} (Twelve Data) mais affirme une "
        "provenance COURTIER :\n  " + "\n  ".join(fautes))
