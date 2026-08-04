"""L'étiquette d'horizon du shadow V1 doit dire la vérité (2026-08-04).

`shadow_setups.timeframe` recevait la constante ``"1h"``, avec un commentaire
affirmant que « le radar V1 analyse des bougies 1h ». C'est faux : le radar
détecte sur ``CANDLE_INTERVAL`` (5 min en production) et ne récupère les
bougies 1h que pour la confirmation multi-timeframe et le calcul d'ATR.

L'enjeu n'est pas cosmétique. Le routage par horizon prévu par
`docs/superpowers/specs/2026-08-04-trois-routes-horizon-et-couts-design.md`
lit ce champ pour décider quelle destination reçoit quel flux. Bâti sur une
étiquette fausse, il enverrait des setups de scalping vers des routes
dimensionnées pour du 4h — ou n'enverrait rien du tout.

Deux notions étaient confondues dans une seule constante :

- **l'étiquette d'horizon** : sur quelles bougies le setup a été détecté
- **la fenêtre de déduplication** : le regroupement horaire qui empêche
  qu'une même idée de trade, revue à chaque cycle de 5 min, soit comptée
  huit fois

La fenêtre horaire est correcte et doit être préservée : la ramener à 5 min
recréerait l'inflation corrigée le même jour (×960 sur SPX).
"""
from __future__ import annotations

from datetime import datetime, timezone


def test_le_label_suit_l_intervalle_reellement_analyse():
    """L'étiquette ne doit pas pouvoir mentir à nouveau : elle est dérivée."""
    from config.settings import CANDLE_INTERVAL
    from backend.services import shadow_v1

    assert shadow_v1.V1_TIMEFRAME == CANDLE_INTERVAL


def test_le_label_n_est_pas_code_en_dur_a_1h():
    from backend.services import shadow_v1

    assert shadow_v1.V1_TIMEFRAME != "1h", (
        "l'étiquette 1h était le défaut : le radar détecte sur CANDLE_INTERVAL"
    )


def test_la_dedup_horaire_est_preservee():
    """Deux cycles dans la même heure = un seul setup.

    C'est le correctif du 2026-08-04 contre la duplication ×960. Le corriger
    à nouveau vers 5 min réintroduirait le biais.
    """
    from backend.services.shadow_v1 import _bar_timestamp

    t1 = datetime(2026, 8, 4, 14, 3, 12, tzinfo=timezone.utc)
    t2 = datetime(2026, 8, 4, 14, 58, 45, tzinfo=timezone.utc)
    t3 = datetime(2026, 8, 4, 15, 1, 0, tzinfo=timezone.utc)

    assert _bar_timestamp(t1) == _bar_timestamp(t2)
    assert _bar_timestamp(t1) != _bar_timestamp(t3)


def test_la_fenetre_de_dedup_est_nommee_explicitement():
    """Les deux notions ne doivent plus tenir dans une seule constante."""
    from backend.services import shadow_v1

    assert hasattr(shadow_v1, "V1_DEDUP_WINDOW_HOURS")
    assert shadow_v1.V1_DEDUP_WINDOW_HOURS == 1
