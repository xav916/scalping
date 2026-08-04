"""L'alerte « Beaucoup de signaux refusés » ne doit pas revenir (2026-08-04).

Elle se déclenchait dès que plus de dix refus partageaient le même motif en
une heure. C'est l'état **normal** du système : le radar analyse seize paires
dans les deux sens à chaque cycle, et 84 % des refus tombent avant tout
routage, sur les filtres globaux. Au moment du retrait, huit motifs
dépassaient le seuil simultanément — dont 930 ``below_confidence`` sur une
seule heure.

Le message ne signalait donc pas un incident : il mesurait que le filtre
filtre. Et le seul correctif qu'il suggérait — baisser les seuils — est
précisément ce que l'analyse d'edge a montré destructeur.

L'information vit désormais dans le récap quotidien, en une ligne.
"""
from __future__ import annotations

import inspect
import pathlib


def test_le_module_d_alerte_n_existe_plus():
    racine = pathlib.Path(__file__).resolve().parents[1] / "services"
    assert not (racine / "rejection_alerts.py").exists()


def test_aucune_tache_ne_la_replanifie():
    from backend.services import scheduler
    src = inspect.getsource(scheduler)
    assert "rejection_alerts_check" not in src
    assert "_rej_alerts" not in src


def test_les_rejections_restent_enregistrees():
    """C'est dans `signal_rejections` qu'on diagnostique, pas dans une alerte.

    Les retirer aussi aurait supprimé le seul moyen de savoir POURQUOI un
    signal n'a pas été exécuté — précisément ce qui a permis d'identifier les
    quatre blocages Kraken.
    """
    from backend.services import rejection_service
    assert hasattr(rejection_service, "record_rejection")
    assert hasattr(rejection_service, "get_rejections")


def test_le_recap_porte_toujours_la_ligne():
    """Supprimer l'alerte ne doit pas faire perdre l'information."""
    depot = pathlib.Path(__file__).resolve().parents[2]
    recap = depot / "scripts" / "daily_recap.py"
    if not recap.exists():  # le script vit côté serveur sur certains déploiements
        import pytest
        pytest.skip("daily_recap.py absent de ce dépôt")
    texte = recap.read_text(encoding="utf-8")
    assert "signaux refusés" in texte
