"""Le chargement des bougies du banc WTI — les deux pieges qui falsifient tout.

⛔ Un banc qui perd des bougies en silence rend un verdict faux et plausible.
Les deux pieges sont verifies sur le pont REEL le 2026-10-03 :

  1. Une fenetre anterieure a l'historique M5 du courtier (2025-05-07) rend
     UNE bougie hors plage, datee du 2025-05-07T15:49 :

         2024-01-10 -> n=1  du 2025-05-07T15:49 au 2025-05-07T15:49
         2025-01-10 -> n=1  du 2025-05-07T15:49 au 2025-05-07T15:49

     La recoller deguiserait un trou de seize mois en continuite.

  2. `tronque=true` : le pont coupe avec `brut[:5000]` et garde les plus
     ANCIENNES. Mesure : une demande H1 sur 1 000 jours rend 5 000 bougies
     s'arretant en novembre 2024. En prendre la fin donnerait des bougies de
     l'annee precedente, presentees comme recentes.
"""
from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_CHEMIN = Path(__file__).resolve().parents[2] / "scripts" / "banc_wti_bougies_courtier.py"
_spec = importlib.util.spec_from_file_location("banc_wti", _CHEMIN)
banc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(banc)


def _bougies(debut: datetime, n: int, pas_min: int = 5) -> list[dict]:
    return [{"t": (debut + timedelta(minutes=pas_min * i)).isoformat(),
             "o": 93.0, "h": 93.1, "l": 92.9, "c": 93.05, "tv": 100, "s": 2}
            for i in range(n)]


@pytest.fixture
def pont(monkeypatch):
    """Double de `_page`, qui enregistre les fenetres demandees."""
    etat: dict = {"demandes": [], "reponse": None}

    def _page(dest, debut, fin):
        etat["demandes"].append((debut, fin))
        if callable(etat["reponse"]):
            return etat["reponse"](debut, fin)
        return etat["reponse"]

    monkeypatch.setattr(banc, "_page", _page)
    return etat


def test_les_bougies_HORS_PLAGE_sont_ecartees(pont):
    """⛔ Le piege n°1 : une unique bougie du 2025-05-07 pour une fenetre de
    2024. Sans ce filtre, le banc mesure une serie trouee de seize mois."""
    vieille = datetime(2025, 5, 7, 15, 49, tzinfo=timezone.utc)

    def _reponse(debut, fin):
        # Le pont rend toujours la meme bougie hors plage.
        return {"point": 0.01, "tronque": False, "n": 1,
                "bougies": [{"t": vieille.isoformat(), "o": 93.0, "h": 93.1,
                             "l": 92.9, "c": 93.05, "tv": 1, "s": 2}]}

    pont["reponse"] = _reponse
    bougies, info = banc.charger(None, "2024-01-01", "2024-02-01")
    assert bougies == [], "une bougie hors de la fenetre ne doit JAMAIS entrer"
    assert info["bougies_hors_plage"] > 0, "et le compte doit le DIRE"


def test_une_page_TRONQUEE_est_refusee(pont):
    """⛔ Le piege n°2 : le pont garde les plus ANCIENNES."""
    pont["reponse"] = {"point": 0.01, "tronque": True, "n": 5000,
                       "bougies": _bougies(
                           datetime(2025, 5, 15, tzinfo=timezone.utc), 10)}
    bougies, info = banc.charger(None, "2025-05-15", "2025-05-20")
    assert bougies == []
    assert info["pages_refusees"] == 1


def test_une_page_refusee_n_arrete_PAS_les_suivantes(pont):
    """⚠️ Meme defaut que le backfill d'admission du 02/10 : un refus au
    milieu ne doit pas emporter le reste de la fenetre."""
    d0 = datetime(2025, 5, 15, tzinfo=timezone.utc)

    def _reponse(debut, fin):
        tronque = debut == d0            # la PREMIERE page seulement
        return {"point": 0.01, "tronque": tronque, "n": 10,
                "bougies": _bougies(debut, 10)}

    pont["reponse"] = _reponse
    bougies, info = banc.charger(None, "2025-05-15", "2025-06-26")
    assert info["pages_refusees"] == 1
    assert info["pages"] == 3
    assert len(bougies) == 20, "les deux pages saines doivent rester"


def test_la_fenetre_est_couverte_EN_ENTIER_sans_trou_ni_chevauchement(pont):
    """Les bornes des pages doivent s'enchainer exactement."""
    pont["reponse"] = {"point": 0.01, "tronque": False, "n": 0, "bougies": []}
    banc.charger(None, "2025-05-15", "2025-06-30")
    demandes = pont["demandes"]
    assert demandes[0][0] == datetime(2025, 5, 15, tzinfo=timezone.utc)
    assert demandes[-1][1] == datetime(2025, 6, 30, tzinfo=timezone.utc)
    for (_, fin), (debut, _) in zip(demandes, demandes[1:]):
        assert fin == debut, "ni trou ni chevauchement entre deux pages"


def test_les_doublons_de_bordure_sont_retires(pont):
    """Deux pages adjacentes peuvent se toucher sur une bougie."""
    d0 = datetime(2025, 5, 15, tzinfo=timezone.utc)

    def _reponse(debut, fin):
        # Chaque page rend aussi la 1re bougie de la page suivante, hors plage,
        # donc deja ecartee ; et sa propre 1re bougie en double.
        b = _bougies(debut, 5)
        return {"point": 0.01, "tronque": False, "n": len(b) + 1,
                "bougies": b + [b[0]]}

    pont["reponse"] = _reponse
    # ⚠️ 28 jours = DEUX pages de 14. Une fenetre de 14 jours n'en ferait
    # qu'une, et le test ne prouverait rien sur la bordure.
    bougies, info = banc.charger(None, "2025-05-15", "2025-06-12")
    assert len(bougies) == 10, "5 bougies par page, sans le doublon"
    assert info["doublons"] == 2
    assert [b["t"] for b in bougies] == sorted(b["t"] for b in bougies)
    assert bougies[0]["t"] == d0


def test_le_spread_est_lu_dans_les_bougies_pas_suppose(pont):
    """🔑 C'est la faiblesse connue du banc de l'or qui disparait ici : MT5
    stocke un spread PAR BOUGIE, en points."""
    d0 = datetime(2025, 5, 15, tzinfo=timezone.utc)
    b = _bougies(d0, 10)
    for i, x in enumerate(b):
        x["s"] = 2 if i < 9 else 40        # une pointe
    pont["reponse"] = {"point": 0.01, "tronque": False, "n": 10, "bougies": b}
    _, info = banc.charger(None, "2025-05-15", "2025-05-20")
    assert info["spread_points_median"] == 2
    assert info["spread_points_max"] == 40, "la pointe doit rester VISIBLE"
    assert info["point"] == 0.01


def test_les_fenetres_declarees_sont_DISJOINTES():
    """⛔ Les nuits du labo se recouvraient a 89/90 : ce n'etaient pas des
    replications. Ici les deux fenetres ne doivent pas se toucher."""
    d_fin = datetime.fromisoformat(banc.FENETRES["dans"][1])
    h_debut = datetime.fromisoformat(banc.FENETRES["hors"][0])
    assert d_fin < h_debut
    assert banc.FENETRES["dans"][0] == "2025-05-15"
    assert banc.FENETRES["hors"][1] == "2026-10-02"


def test_le_banc_remet_les_etiquettes_sur_la_grille(pont):
    """⛔ Sans ça le banc n'est pas reproductible : il a rendu une cellule
    RETENUE à R=+0,4798 au premier passage et la MÊME à R=−0,1530 au second,
    parce que `decalage_serveur_sec` du pont dérive d'une seconde par appel."""
    d0 = datetime(2026, 6, 1, 8, 28, 25, tzinfo=timezone.utc)
    pont["reponse"] = {"point": 0.01, "tronque": False, "n": 12,
                       "bougies": _bougies(d0, 12)}
    bougies, info = banc.charger(None, "2026-06-01", "2026-06-08")
    assert bougies, "les bougies doivent passer"
    for b in bougies:
        assert b["t"].second == 0 and b["t"].minute % 5 == 0, b["t"]
    assert info["residu_grille_sec"] > 0, "et le résidu doit être DIT"


def test_deux_derives_differentes_donnent_la_MEME_serie(pont):
    series = []
    for seconde in (25, 26, 44):
        d0 = datetime(2026, 6, 1, 8, 28, seconde, tzinfo=timezone.utc)
        pont["reponse"] = {"point": 0.01, "tronque": False, "n": 12,
                           "bougies": _bougies(d0, 12)}
        b, _ = banc.charger(None, "2026-06-01", "2026-06-08")
        series.append([x["t"] for x in b])
    assert series[0] == series[1] == series[2], \
        "une dérive d'une seconde ne doit plus changer la mesure"


# --- LE GEL DES BOUGIES -------------------------------------------------
#
# ⛔ MESURE DU 2026-10-03. Trois passages du banc sur la MEME fenetre ont rendu
# 0, puis 1, puis 0 cellule retenue, avec 57 / 54 / 50 cellules a R positif —
# alors que les bougies etaient au nombre identique (79 474) et les cellules
# aussi (250).
#
# L'experience qui tranche : bougies FIGEES dans un fichier, mesure relancee
# dans TROIS processus separes -> resultat identique au bit (meme empreinte de
# cellules, meme t_vs_max +3,140). `laboratoire_or.mesurer` est donc
# parfaitement pure, et toute l'instabilite venait du CHARGEMENT.
#
# 🔑 Le decalage serveur du pont derive, donc le residu de grille change entre
# deux chargements ; quand il franchit la demi-periode, la serie glisse d'un
# cran de 5 minutes et l'agregation forme ses bougies de 15 min avec d'AUTRES
# triplets. ⚠️ Un banc dont les donnees sont refetchees a chaque passage n'est
# pas un banc.

def test_le_gel_evite_un_SECOND_chargement(tmp_path, monkeypatch, pont):
    monkeypatch.setattr(banc, "_fige", lambda cle: tmp_path / f"{cle}.json")
    monkeypatch.setitem(banc.FENETRES, "essai", ("2026-06-01", "2026-06-08"))
    d0 = datetime(2026, 6, 1, 8, 28, 25, tzinfo=timezone.utc)
    pont["reponse"] = {"point": 0.01, "tronque": False, "n": 12,
                       "bougies": _bougies(d0, 12)}

    b1, i1 = banc.charger_ou_figer(None, "essai")
    appels_apres_gel = len(pont["demandes"])
    b2, i2 = banc.charger_ou_figer(None, "essai")

    assert len(pont["demandes"]) == appels_apres_gel, \
        "le second appel doit RELIRE le gel, pas re-interroger le pont"
    assert [x["t"] for x in b1] == [x["t"] for x in b2]
    assert [x["c"] for x in b1] == [x["c"] for x in b2]


def test_le_gel_conserve_la_fenetre_ET_le_releve(tmp_path, monkeypatch, pont):
    """⚠️ Le gel doit etre auditable : la fenetre et le spread mesure avec."""
    import json
    monkeypatch.setattr(banc, "_fige", lambda cle: tmp_path / f"{cle}.json")
    monkeypatch.setitem(banc.FENETRES, "essai", ("2026-06-01", "2026-06-08"))
    pont["reponse"] = {"point": 0.01, "tronque": False, "n": 12,
                       "bougies": _bougies(
                           datetime(2026, 6, 1, 8, 28, 25, tzinfo=timezone.utc), 12)}
    banc.charger_ou_figer(None, "essai")
    d = json.loads((tmp_path / "essai.json").read_text())
    assert d["fenetre"] == ["2026-06-01", "2026-06-08"]
    assert d["info"]["spread_points_median"] == 2
    assert d["info"]["point"] == 0.01
    assert len(d["bougies"]) == 12


def test_le_gel_n_est_PAS_dans_un_repertoire_volatile(monkeypatch, tmp_path):
    """⛔ Le 2026-10-03 le gel etait dans /tmp du conteneur : un deploiement
    l'a efface entre la mesure dans l'echantillon et celle hors echantillon.
    Un artefact de banc doit survivre a un redeploiement."""
    assert "/tmp" not in str(banc.REPERTOIRE_GEL), \
        f"{banc.REPERTOIRE_GEL} ne survivrait pas a un deploiement"
    monkeypatch.setattr(banc, "REPERTOIRE_GEL", tmp_path / "bancs")
    chemin = banc._fige("dans")
    assert chemin.parent.exists(), "le repertoire doit etre cree"
    assert chemin.name == "banc_wti_dans.json"
