"""Les annonces d'ouverture de session ne doivent pas revenir (2026-08-04).

Cinq messages étaient émis cinq minutes avant chaque ouverture — Tokyo,
London, New York, cash SPX/NDX en semaine, Sydney le dimanche — soit environ
vingt-et-un messages par semaine sur le canal des trades.

Ils supposent un trader qui se met devant son écran. Le système trade seul :
savoir que Londres ouvre dans cinq minutes n'appelle aucune action. C'était le
plus gros volume de bruit restant après le retrait de l'alerte « Beaucoup de
signaux refusés ».

Aucune donnée n'est perdue : l'heure est déjà une feature du modèle
(``hour_sin``, ``hour_cos``, ``dow``, ``_session_utc``) et ``session_service``
continue de qualifier la session courante pour le scoring.
"""
from __future__ import annotations

import inspect


def test_le_cycle_d_alerte_n_existe_plus():
    from backend.services import scheduler

    assert not hasattr(scheduler, "session_alert_cycle")
    assert not hasattr(scheduler, "_session_alerts_sent")


def test_aucune_tache_ne_le_replanifie():
    from backend.services import scheduler

    src = inspect.getsource(scheduler)
    assert "session_alert" not in src
    assert "Ouverture" not in src


def test_l_heure_reste_une_feature_du_modele():
    """Retirer la notification ne doit rien retirer au ML."""
    from backend.services import ml_features

    src = inspect.getsource(ml_features)
    for feature in ("hour_sin", "hour_cos", "dow"):
        assert feature in src


def test_la_session_reste_qualifiee_pour_le_scoring():
    from backend.services import session_service

    assert hasattr(session_service, "active_sessions")
    assert hasattr(session_service, "activity_multiplier")
