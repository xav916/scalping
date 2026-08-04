"""Identification du broker dans les pushes Telegram (2026-08-04).

Deux listes de libellés vivaient séparément dans `telegram_service` :

- `_ADMIN_DEST_LABELS`, qui ne connaissait que `admin_legacy` et `admin_live`
- une chaîne `if/elif` dans `_format_trade_opened`, qui y ajoutait
  `admin_binance` et `user:N`

**Aucune des deux ne connaissait les trois destinations Kraken.** Un trade
parti chez Kraken Futures s'affichait donc sous son identifiant technique
dans le push de setup, et — plus grave — sous le libellé générique
« Démo » dans le message d'ouverture, alors qu'il engage de l'argent réel.

Même famille de péremption que `VALID_DESTINATIONS` : une constante écrite
avant l'ajout des destinations, jamais remise à jour. Le test
`test_toute_destination_connue_a_un_libelle` est là pour que ça ne
recommence pas.
"""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from backend.services.telegram_service import (
    DESTINATION_LABELS,
    destination_label,
)


# --- le garde-fou anti-péremption ------------------------------------------

def test_toute_destination_connue_a_un_libelle():
    """Ajouter une destination sans son libellé doit faire échouer ce test."""
    from backend.services import pair_admission_controller as pac
    manquantes = sorted(pac.VALID_DESTINATIONS - set(DESTINATION_LABELS))
    assert manquantes == [], f"destinations sans libellé Telegram : {manquantes}"


def test_les_trois_destinations_kraken_sont_couvertes():
    """C'est l'oubli qui a motivé le correctif."""
    for d in ("admin_kraken", "admin_kraken_spot", "admin_kraken_stocks"):
        assert d in DESTINATION_LABELS
        assert "Kraken" in destination_label(d, "badge")


@pytest.mark.parametrize("champ", ["badge", "mode"])
def test_chaque_libelle_est_non_vide(champ):
    for d in DESTINATION_LABELS:
        assert destination_label(d, champ).strip()


# --- la distinction argent réel / démo -------------------------------------

def test_les_destinations_reelles_le_disent():
    """Un message ne doit jamais laisser croire à du démo sur du réel."""
    for d, meta in DESTINATION_LABELS.items():
        if meta["reel"]:
            assert "réel" in destination_label(d, "mode").lower(), d
        else:
            assert "réel" not in destination_label(d, "mode").lower(), d


def test_kraken_est_declare_argent_reel():
    for d in ("admin_kraken", "admin_kraken_spot", "admin_kraken_stocks"):
        assert DESTINATION_LABELS[d]["reel"] is True


# --- le repli sur l'inconnu ------------------------------------------------

def test_destination_inconnue_montre_son_identifiant():
    """Mieux vaut « admin_truc » qu'un « Démo » trompeur sur du réel."""
    assert destination_label("admin_truc", "mode") == "admin_truc"
    assert "Démo" not in destination_label("admin_truc", "mode")


def test_destination_absente_est_explicite():
    assert destination_label(None, "badge") == "broker non identifié"
    assert destination_label("", "mode") == "broker non identifié"


def test_les_users_premium_ont_leur_libelle():
    assert destination_label("user:2", "badge") == "👤 Compte Premium"
    assert destination_label("user:17", "mode") == "Premium · Démo"


# --- l'usage réel dans les messages ----------------------------------------

def _setup():
    return NS(pair="ETH/USD", direction=NS(value="sell"),
              entry_price=1868.0, stop_loss=1876.7, take_profit_1=1852.0,
              take_profit_2=None, risk_pips=8.7, reward_pips_1=16.0,
              reward_pips_2=0.0, risk_reward_1=1.8, risk_reward_2=0.0,
              confidence_score=70.0, asset_class="crypto")


@pytest.mark.parametrize("dest_id,attendu", [
    ("admin_kraken", "Kraken Futures"),
    ("admin_live", "IC Markets"),
    ("admin_legacy", "Pepperstone"),
    ("user:2", "Premium"),
])
def test_le_message_douverture_nomme_le_broker(dest_id, attendu):
    """Exerce `_format_trade_opened`, pas la table seule."""
    from backend.services import telegram_service as ts
    text = ts._format_trade_opened(
        _setup(), ticket="123", fill_price=1868.0, volume=0.1,
        mode="LIVE", destination_id=dest_id,
    )
    assert attendu in text, f"broker absent du message pour {dest_id}"


def test_le_message_douverture_ne_ment_pas_sur_le_reel():
    """Le cas concret : un trade Kraken affichait « Démo »."""
    from backend.services import telegram_service as ts
    text = ts._format_trade_opened(
        _setup(), ticket="123", fill_price=1868.0, volume=0.1,
        mode="LIVE", destination_id="admin_kraken",
    )
    assert "argent réel" in text


def test_le_badge_du_push_de_setup_nomme_le_broker(monkeypatch):
    """`_describe_admin_destinations` doit rendre le libellé, pas l'identifiant.

    ⚠️ Cette fonction avale ses exceptions et renvoie `[]` : sans destination
    gréée, le test passerait quoi qu'il arrive. D'où le stub.
    """
    from backend.services import telegram_service as ts, bridge_destinations as bd
    from unittest.mock import patch

    dest = NS(destination_id="admin_kraken", user_id=None, auto_exec_enabled=True,
              min_confidence=0, allowed_asset_classes={"crypto"})
    with patch("config.settings.MT5_BRIDGE_ALLOWED_PATTERNS", frozenset()), \
         patch.object(bd, "resolve_destinations", return_value=[dest]):
        labels = ts._describe_admin_destinations(_setup())

    assert labels == ["🐙 Kraken Futures"], labels
