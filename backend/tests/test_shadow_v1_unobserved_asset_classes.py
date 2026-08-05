"""Journalisation shadow V1 des paires crypto hors admission OBSERVED (2026-08-05).

Contexte : `log_v1_shadows_for_tracked_pairs` (ex `..._for_observed_pairs`) ne
journalisait que les (pair, direction) en état OBSERVED. Mesuré en prod ce
jour : aucune paire crypto n'atteint cet état (BTC/USD, ETH/USD sont DEMOTED
en global ou AUTO_EXEC par destination) → 1 seule ligne shadow crypto/semaine
contre ~2900 côté actions observées, alors qu'un veto crypto
(`kraken_funding_scoring`) attend justement d'être validé sur ces lignes.

La crypto est bloquée au dispatch par la porte d'horizon et la porte de coût
(cf. `project_crypto_fees_kill_edge`) : jamais de vraie exécution, donc
économiquement dans la même situation qu'une paire observée. Ce fichier
verrouille le nouveau comportement : `SHADOW_V1_UNOBSERVED_ASSET_CLASSES`
(config/settings.py, défaut "crypto") élargit la journalisation à ces
classes d'actif indépendamment de l'état d'admission, sans rien changer
pour les paires déjà observées ni pour les paires ni crypto ni observées.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.services import shadow_v1
from backend.services import shadow_v2_core_long as shadow


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "shadow_v1_unobserved_test.db"
    monkeypatch.setattr(shadow, "DB_PATH", db_path)
    monkeypatch.setattr(shadow_v1, "DB_PATH", db_path)
    monkeypatch.setattr(shadow_v1, "is_market_open_for", lambda pair, now=None: True)
    shadow.ensure_schema()
    return db_path


def _setup(pair, direction="buy", entry=60000.0, sl=59000.0, tp=62000.0):
    return SimpleNamespace(
        pair=pair,
        direction=SimpleNamespace(value=direction),
        entry_price=entry,
        stop_loss=sl,
        take_profit_1=tp,
        take_profit_2=None,
        pattern=None,
    )


def _rows(db_path, pair):
    import sqlite3
    with sqlite3.connect(db_path) as c:
        return c.execute(
            "SELECT pair, funding_features_json FROM shadow_setups WHERE pair = ?",
            (pair,),
        ).fetchall()


CYCLE = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)


def _not_observed_state(pac):
    """N'importe quel état != OBSERVED (DEMOTED, choisi arbitrairement)."""
    return pac.STATE_DEMOTED


# ─── 1. Paire crypto NON observée → désormais journalisée (par défaut) ────


def test_paire_crypto_non_observee_est_journalisee_par_defaut(temp_db, monkeypatch):
    from backend.services import pair_admission_controller as pac

    monkeypatch.setattr(pac, "get_current_state", lambda pair, direction: _not_observed_state(pac))
    # Défaut du réglage = "crypto" ; on ne le monkeypatch pas ici pour
    # prouver que le comportement par défaut (pas seulement forcé en test)
    # journalise bien la crypto.
    assert shadow_v1.SHADOW_V1_UNOBSERVED_ASSET_CLASSES == ["crypto"]

    # Simuler _capture_funding_snapshot pour éviter un appel réseau réel vers Kraken.
    # Tous les autres tests touchant la crypto le font, pour garder la cohérence.
    marker = {"captured_at": "2026-08-05T12:00:00Z", "symbol": "PF_XBTUSD", "rate": 1.0e-5}
    def _fake_capture(pair, direction):
        return marker
    monkeypatch.setattr(shadow, "_capture_funding_snapshot", _fake_capture)

    setups = [_setup("BTC/USD", "buy")]
    counts = shadow_v1.log_v1_shadows_for_tracked_pairs(setups, cycle_at=CYCLE)

    assert counts["logged"] == 1
    assert counts["skipped_not_tracked"] == 0
    assert len(_rows(temp_db, "BTC/USD")) == 1


# ─── 2. Paire observée continue d'être journalisée exactement comme avant ─


def test_paire_observee_continue_detre_journalisee(temp_db, monkeypatch):
    from backend.services import pair_admission_controller as pac

    monkeypatch.setattr(pac, "get_current_state", lambda pair, direction: pac.STATE_OBSERVED)

    setups = [_setup("EUR/USD", "buy", entry=1.08, sl=1.075, tp=1.09)]
    counts = shadow_v1.log_v1_shadows_for_tracked_pairs(setups, cycle_at=CYCLE)

    assert counts["logged"] == 1
    assert counts["skipped_not_tracked"] == 0
    assert len(_rows(temp_db, "EUR/USD")) == 1


# ─── 3. Paire ni crypto ni observée → toujours pas journalisée ────────────


def test_paire_ni_crypto_ni_observee_nest_pas_journalisee(temp_db, monkeypatch):
    from backend.services import pair_admission_controller as pac

    monkeypatch.setattr(pac, "get_current_state", lambda pair, direction: _not_observed_state(pac))

    setups = [_setup("EUR/USD", "buy", entry=1.08, sl=1.075, tp=1.09)]
    counts = shadow_v1.log_v1_shadows_for_tracked_pairs(setups, cycle_at=CYCLE)

    assert counts["logged"] == 0
    assert counts["skipped_not_tracked"] == 1
    assert _rows(temp_db, "EUR/USD") == []


# ─── 4. Réglage à vide restaure strictement le comportement d'avant ───────


def test_reglage_vide_restaure_comportement_dorigine(temp_db, monkeypatch):
    """Liste vide == le gate d'origine : seule l'admission OBSERVED compte.

    Piège visé : monkeypatcher `config.settings.SHADOW_V1_UNOBSERVED_ASSET_CLASSES`
    ne suffirait pas — `shadow_v1.py` a importé le nom par valeur au chargement
    du module (`from config.settings import ...`). C'est bien l'attribut du
    module `shadow_v1` qui doit être patché ici, comme le fait le code appelant
    réel au runtime (relecture au niveau module, pas ré-import par appel).
    """
    from backend.services import pair_admission_controller as pac

    monkeypatch.setattr(shadow_v1, "SHADOW_V1_UNOBSERVED_ASSET_CLASSES", [])
    monkeypatch.setattr(pac, "get_current_state", lambda pair, direction: _not_observed_state(pac))

    setups = [_setup("BTC/USD", "buy")]
    counts = shadow_v1.log_v1_shadows_for_tracked_pairs(setups, cycle_at=CYCLE)

    assert counts["logged"] == 0
    assert counts["skipped_not_tracked"] == 1
    assert _rows(temp_db, "BTC/USD") == []


# ─── 5. Une ligne crypto nouvellement journalisée porte un funding non vide ─


def test_ligne_crypto_non_observee_porte_un_instantane_funding(temp_db, monkeypatch):
    """L'objet même du chantier : la ligne crypto nouvellement ouverte par le
    réglage doit déclencher `_capture_funding_snapshot`, pas seulement les
    lignes déjà OBSERVED (déjà couvert par test_shadow_v1_funding.py)."""
    import json

    from backend.services import pair_admission_controller as pac

    monkeypatch.setattr(pac, "get_current_state", lambda pair, direction: _not_observed_state(pac))

    marker = {"captured_at": "2026-08-05T12:00:00Z", "symbol": "PF_XBTUSD", "rate": 1.0e-5}
    appels = []

    def _fake_capture(pair, direction):
        appels.append((pair, direction))
        return marker

    monkeypatch.setattr(shadow, "_capture_funding_snapshot", _fake_capture)

    setups = [_setup("BTC/USD", "buy")]
    counts = shadow_v1.log_v1_shadows_for_tracked_pairs(setups, cycle_at=CYCLE)

    assert counts["logged"] == 1
    assert appels == [("BTC/USD", "buy")], "la capture funding doit être appelée pour la ligne crypto non-observée"

    rows = _rows(temp_db, "BTC/USD")
    assert len(rows) == 1
    raw = rows[0][1]
    assert raw is not None
    parsed = json.loads(raw)
    assert parsed == marker
    assert parsed  # non vide
