"""Le refus de MARGE doit porter son nom, pas « indéterminé ».

⛔ Le 2026-10-09, dix refus de l'or étaient rangés sous
`bridge_refus_indetermine` : le pont refusait parce qu'un ordre de plus aurait
laissé la marge libre sous son plancher de 30 %, et ce motif n'avait pas de
nom.

🔑 C'est pourtant la contrainte qui **plafonne réellement** le nombre de
positions d'or — 186,64 € de marge par position à 0,01 lot. La ranger sous
« indéterminé » la rendait invisible, alors que c'est elle qui décide.

Même maladie que `status 429 → bridge_max_positions`, qui surestimait le
plafond de positions d'un **facteur 10** : une branche par défaut qui se fait
passer pour une mesure.
"""
from __future__ import annotations

import pytest

from backend.services.mt5_bridge import _categoriser_refus


# Le message EXACT du pont, releve en production le 2026-10-09.
MSG_REEL = "Marge libre apres ordre -30.27 < 159.03 (30.0% de 530.11)"


def test_le_message_REEL_du_pont_est_reconnu():
    assert _categoriser_refus(429, MSG_REEL) == "bridge_marge_insuffisante"


@pytest.mark.parametrize("corps", [
    "Marge libre apres ordre -1.00 < 100.00 (30.0% de 333.00)",
    "Marge libre insuffisante",
    "... Marge libre apres ordre 0.0 < 1.0 ...",
])
def test_les_variantes_sont_reconnues(corps):
    assert _categoriser_refus(429, corps) == "bridge_marge_insuffisante"


def test_il_ne_VOLE_PAS_l_etiquette_des_autres():
    """⛔ Le piège de 2026-08-25 : une catégorie trop large avait gonflé
    `bridge_max_positions` d'un facteur 10. Chaque motif garde le sien."""
    cas = {
        "Max open positions reached": "bridge_max_positions",
        "Daily drawdown reached: loss=157": "bridge_perte_journaliere",
        "Duplicate: buy XAUUSD already open": "bridge_doublon",
        "Risque engage trop eleve": "bridge_plafond_risque",
        "retcode 10016 INVALID_STOPS": "bridge_invalid_stops",
    }
    for corps, attendu in cas.items():
        assert _categoriser_refus(429, corps) == attendu, corps


def test_un_refus_INCONNU_reste_indetermine():
    """🔑 On n'emprunte jamais l'étiquette du voisin : un motif qu'on ne sait
    pas lire se déclare, il ne se devine pas."""
    assert _categoriser_refus(429, "quelque chose de neuf") == \
        "bridge_refus_indetermine"


def test_le_libelle_existe():
    """⚠️ Un code sans libellé s'affiche en brut dans les récapitulatifs."""
    # ⚠️ Le dictionnaire s'appelle `REASON_LABELS_FR`. Ma premiere version
    # importait `REASON_LABELS` — un nom que j'avais suppose. Le test echouait
    # sur MON erreur, pas sur le code.
    from backend.services.rejection_service import REASON_LABELS_FR as L
    assert "bridge_marge_insuffisante" in L
    assert "marge" in L["bridge_marge_insuffisante"].lower()
