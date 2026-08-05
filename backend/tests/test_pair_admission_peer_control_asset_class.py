"""Tests de la restriction du domaine par classe d'actif + disparition des
anciens noms « aléatoire/hasard » du contrôle de retour de pause.

Contexte (tâche du 2026-08-05, suite) : `pair_admission_controller` comparait
une pair PAUSED à TOUTES les autres pairs (toutes classes d'actif confondues)
pour décider si elle « bat le hasard ». Deux défauts corrigés ici :

1. **Nom trompeur** : le domaine n'a jamais été une entrée réellement
   aléatoire — c'est le recensement de toutes les pairs d'un même sens, donc
   une comparaison ENTRE PAIRES. Toute la terminologie (fonctions, réglages,
   messages `reason` écrits en base) est renommée en conséquence
   (`peer_control_*` / `PAC_PEER_CONTROL_*`), sans toucher au module générique
   `random_entry_control.py` (correct en lui-même, non modifié).

2. **Domaine trop large** : comparer une crypto à des pairs forex n'a pas de
   sens même comme comparaison ENTRE PAIRES (régimes, volatilité,
   corrélations différents). Le domaine est désormais restreint à la MÊME
   CLASSE D'ACTIF que la pair testée (`config.settings.asset_class_for`,
   fonction existante, pas réécrite).

Isolation complète : DB temporaire (`tmp_path`), aucun accès réseau ni à
`trades.db` / `backtest.db` du dépôt — même fixture que
`test_pair_admission_pause_return.py`.
"""
from __future__ import annotations

import inspect
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest


# ─── Fixture d'isolation (identique à test_pair_admission_pause_return.py) ──


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "trades.db"

    from backend.services import (
        trade_log_service,
        backtest_service,
        pair_admission_controller as pac,
        pair_pnl_regulator,
        ea_closed_trades_service,
        shadow_v2_core_long,
    )

    monkeypatch.setattr(trade_log_service, "_DB_PATH", db_path)
    monkeypatch.setattr(backtest_service, "_DB_PATH", tmp_path / "backtest.db")
    monkeypatch.setattr(shadow_v2_core_long, "DB_PATH", db_path)
    monkeypatch.setattr(pac, "_SCHEMA_ENSURED", False)
    monkeypatch.setattr(pair_pnl_regulator, "_SCHEMA_ENSURED", False)
    monkeypatch.setattr(ea_closed_trades_service, "_SCHEMA_ENSURED", False)
    pac._PEER_CONTROL_CACHE.clear()

    shadow_v2_core_long.ensure_schema()

    with sqlite3.connect(db_path) as c:
        c.execute(
            """
            CREATE TABLE personal_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT, direction TEXT, status TEXT, pnl REAL,
                is_auto INTEGER, closed_at TEXT, close_reason TEXT
            )
            """
        )
    yield db_path


_SINCE = datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)


def _insert_shadow_row(
    db_path,
    *,
    pair: str,
    direction: str,
    bar_timestamp: datetime,
    r_multiple: float,
    risk_pct: float = 0.01,
    system_id: str,
    outcome: str = "TP1",
):
    pnl_pct_net = r_multiple * risk_pct * 100
    bar_iso = bar_timestamp.isoformat()
    with sqlite3.connect(db_path) as c:
        c.execute(
            """
            INSERT INTO shadow_setups (
                cycle_at, bar_timestamp, system_id, pair, timeframe, direction,
                pattern, entry_price, stop_loss, take_profit_1, risk_pct, rr,
                sizing_capital_eur, sizing_risk_pct, sizing_position_eur,
                sizing_max_loss_eur, outcome, pnl_pct_net
            ) VALUES (?, ?, ?, ?, 'H1', ?, 'test_pattern', 1.0, 0.99, 1.02, ?, 2.0,
                      10000, 0.005, 500, 50, ?, ?)
            """,
            (bar_iso, bar_iso, system_id, pair, direction, risk_pct, outcome, pnl_pct_net),
        )


def _tune_fast_bootstrap(monkeypatch):
    import config.settings as st
    monkeypatch.setattr(st, "PAC_PEER_CONTROL_BLOCK_SIZE", 5)
    monkeypatch.setattr(st, "PAC_PEER_CONTROL_N_BOOT", 1500)
    monkeypatch.setattr(st, "PAC_PEER_CONTROL_MIN_DOMAIN_BLOCKS", 3)
    monkeypatch.setattr(st, "PAC_PEER_CONTROL_SEED", 42)


# ─── 1. Le domaine d'une pair crypto ne contient QUE des lignes crypto ─────


def test_domaine_dune_pair_crypto_ne_contient_que_des_lignes_crypto(_isolated_db):
    """Preuve par mutation : si le filtre de classe d'actif était retiré (ou
    cassé), les 400 lignes forex à r_multiple=50 contamineraient le domaine
    et feraient exploser sa moyenne très au-dessus de ~0. Avec le filtre
    correct, seules les 20 lignes crypto (bruit proche de 0) doivent rester —
    à la fois en TAILLE EXACTE et en MOYENNE."""
    from backend.services import pair_admission_controller as pac

    # 20 lignes crypto (BTC/USD + ETH/USD), bruit borné proche de 0.
    for i in range(20):
        pair = "BTC/USD" if i % 2 == 0 else "ETH/USD"
        noise = ((i * 37) % 101) / 101.0 - 0.5  # [-0.5, 0.5)
        _insert_shadow_row(
            _isolated_db, pair=pair, direction="buy",
            bar_timestamp=_SINCE + timedelta(hours=i), r_multiple=noise,
            system_id=f"CRYPTO_{pair.replace('/', '')}_{i}",
        )
    # 400 lignes forex, r_multiple=50 — devraient être EXCLUES du domaine
    # d'une pair crypto. Si elles fuitent dedans, la moyenne du domaine
    # explose loin de 0.
    for i in range(400):
        pair = ("EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD")[i % 4]
        _insert_shadow_row(
            _isolated_db, pair=pair, direction="buy",
            bar_timestamp=_SINCE + timedelta(hours=1000 + i), r_multiple=50.0,
            system_id=f"FOREX_{pair.replace('/', '')}_{i}",
        )

    domain, pattern = pac._build_peer_control_populations("BTC/USD", "buy")

    assert len(domain) == 20  # les 400 lignes forex n'entrent jamais dans le domaine
    assert len(pattern) == 10  # seules les lignes BTC/USD (moitié des 20 crypto)
    domain_mean = sum(t.r_multiple for t in domain) / len(domain)
    assert abs(domain_mean) < 1.0  # loin de 50 : la contamination forex n'a pas eu lieu


# ─── 2. Classe à effectif insuffisant → indécidable, pas tranché sur 3 lignes ──


def test_classe_effectif_insuffisant_rend_indecidable_pas_tranche(_isolated_db, monkeypatch):
    """energy = WTI/USD seule dans WATCHED_PAIRS par défaut (cf. config.settings
    .asset_class_for) : même avec un effet énorme injecté, si le nombre de
    lignes reste sous le seuil du bootstrap (block_size × min_domain_blocks),
    le résultat DOIT être indéterminé (`significant is None`), jamais tranché
    sur une poignée de lignes."""
    from backend.services import pair_admission_controller as pac

    _tune_fast_bootstrap(monkeypatch)  # block_size=5, min_domain_blocks=3 → seuil 15

    # Seulement 3 lignes WTI/USD (energy) — largement sous le seuil de 15.
    for i in range(3):
        _insert_shadow_row(
            _isolated_db, pair="WTI/USD", direction="buy",
            bar_timestamp=_SINCE + timedelta(hours=i), r_multiple=5.0,  # effet énorme
            system_id=f"WTI_{i}",
        )

    result = pac.peer_control_for_pair("WTI/USD", "buy")

    assert result.significant is None
    assert result.insufficient_reason is not None
    assert "trop petit" in result.insufficient_reason.lower()


# ─── 3. Classe mono-pair (une seule pair dans la classe) : indécidable structurel ──


def test_classe_mono_pair_reste_structurellement_indecidable_meme_avec_assez_de_lignes(
    _isolated_db, monkeypatch,
):
    """Si WTI/USD est la SEULE pair de la classe `energy`, le domaine restreint
    par classe est identique au pattern (aucune AUTRE pair pour comparer) :
    delta_observed doit être exactement 0, et le contrôle ne peut JAMAIS
    trancher en faveur de la pair — même avec beaucoup de données et un
    "effet" apparent, puisqu'il n'y a personne d'autre à qui la comparer."""
    from backend.services import pair_admission_controller as pac

    _tune_fast_bootstrap(monkeypatch)

    for i in range(200):
        _insert_shadow_row(
            _isolated_db, pair="WTI/USD", direction="buy",
            bar_timestamp=_SINCE + timedelta(hours=i), r_multiple=3.0,  # "très bon" en apparence
            system_id=f"WTI_{i}",
        )

    domain, pattern = pac._build_peer_control_populations("WTI/USD", "buy")
    assert len(domain) == len(pattern) == 200  # self-comparison : domaine == pattern

    result = pac.peer_control_for_pair("WTI/USD", "buy")
    assert result.delta_observed == pytest.approx(0.0)
    assert result.significant is not True  # jamais favorable : ne peut pas être True
    assert not pac._beats_peer_control(result)


# ─── 4. Comportement de décision inchangé à domaine égal (même paires, même sens) ──


def test_decision_inchangee_a_domaine_egal(_isolated_db, monkeypatch):
    """Deux pairs forex (même classe), domaine = exactement les mêmes lignes
    qu'avant la restriction (puisque toutes les pairs insérées sont déjà
    forex) : le comportement de `evaluate_pair` doit rester identique à ce
    qu'il était avant le correctif — seuil de preuve, cool-off et disjoncteur
    inchangés, seule la construction du domaine a changé de mécanisme."""
    from backend.services import pair_admission_controller as pac

    _tune_fast_bootstrap(monkeypatch)
    all_pairs = ("EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD")
    for i in range(600):
        pair = all_pairs[i % len(all_pairs)]
        noise = ((i * 37) % 101) / 101.0 - 0.5
        offset = 0.5 if pair == "EUR/USD" else 0.0
        _insert_shadow_row(
            _isolated_db, pair=pair, direction="buy",
            bar_timestamp=_SINCE + timedelta(hours=i), r_multiple=noise + offset,
            system_id=f"{pair.replace('/', '')}_{i}",
        )
    pac.set_state("EUR/USD", pac.STATE_PAUSED, "test setup", direction="buy")
    since = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    with sqlite3.connect(pac._db_path()) as c:
        row = c.execute(
            "SELECT id FROM pair_admission_state WHERE pair=? AND direction=? AND state='PAUSED' "
            "ORDER BY id DESC LIMIT 1",
            ("EUR/USD", "buy"),
        ).fetchone()
        c.execute("UPDATE pair_admission_state SET state_since = ? WHERE id = ?", (since, row[0]))

    d = pac.evaluate_pair("EUR/USD", direction="buy")

    assert d["action"] == "transition"
    assert d["to_state"] == pac.STATE_AUTO_EXEC


# ─── 5. Les anciens noms ont disparu, partout, y compris des chaînes reason ──


def test_anciens_noms_disparus_du_controleur():
    from backend.services import pair_admission_controller as pac

    for old_name in (
        "random_control_for_pair", "random_control_for_pair_cached",
        "_random_control_block_size", "_random_control_n_boot",
        "_random_control_min_domain_blocks", "_random_control_seed",
        "_random_control_cache_hours", "_random_control_since_iso",
        "_fetch_random_control_rows", "_build_random_control_populations",
        "_random_control_summary", "_beats_random_control",
        "_random_control_keep_reason", "_RANDOM_CONTROL_CACHE",
    ):
        assert not hasattr(pac, old_name), f"ancien nom encore présent : {old_name}"

    for new_name in (
        "peer_control_for_pair", "peer_control_for_pair_cached",
        "_peer_control_block_size", "_peer_control_n_boot",
        "_peer_control_min_domain_blocks", "_peer_control_seed",
        "_peer_control_cache_hours", "_peer_control_since_iso",
        "_fetch_peer_control_rows", "_build_peer_control_populations",
        "_peer_control_summary", "_beats_peer_control",
        "_peer_control_keep_reason", "_PEER_CONTROL_CACHE",
    ):
        assert hasattr(pac, new_name), f"nouveau nom manquant : {new_name}"

    # Scan du SOURCE (pas juste des attributs) : plus aucun identifiant
    # « random_control » (le nom trompeur d'origine) nulle part dans ce
    # fichier. On ne bannit PAS le mot « aléatoire »/« hasard » lui-même :
    # la doc du fichier doit légitimement CONTRASTER ce contrôle (comparaison
    # entre pairs) avec la vraie question systémique « bat une entrée
    # réellement aléatoire ? » (exigence de la tâche : condition nécessaire,
    # jamais suffisante). Ce qui compte est vérifié plus bas et par mutation
    # réelle (`test_reason_strings_ecrites_en_base_ne_mentionnent_plus_le_hasard`) :
    # les messages `reason` ÉCRITS EN BASE, ceux qu'un humain sans contexte
    # lira plus tard, ne doivent plus jamais dire que CE contrôle-ci teste le
    # hasard.
    source = inspect.getsource(pac)
    lower = source.lower()
    assert "random_control" not in lower


def test_anciens_noms_disparus_des_reglages():
    import config.settings as st

    old_settings = (
        "PAC_RANDOM_CONTROL_BLOCK_SIZE", "PAC_RANDOM_CONTROL_N_BOOT",
        "PAC_RANDOM_CONTROL_MIN_DOMAIN_BLOCKS", "PAC_RANDOM_CONTROL_SEED",
        "PAC_RANDOM_CONTROL_CACHE_HOURS",
    )
    new_settings = (
        "PAC_PEER_CONTROL_BLOCK_SIZE", "PAC_PEER_CONTROL_N_BOOT",
        "PAC_PEER_CONTROL_MIN_DOMAIN_BLOCKS", "PAC_PEER_CONTROL_SEED",
        "PAC_PEER_CONTROL_CACHE_HOURS",
    )
    source = inspect.getsource(st)
    for old in old_settings:
        assert not hasattr(st, old), f"ancien réglage encore présent : {old}"
        assert old not in source, f"ancien réglage encore mentionné en source : {old}"
    for new in new_settings:
        assert hasattr(st, new), f"nouveau réglage manquant : {new}"


def test_reason_strings_ecrites_en_base_ne_mentionnent_plus_le_hasard(_isolated_db, monkeypatch):
    """Mutation réelle : fait vraiment revenir une pair en AUTO_EXEC via le
    contrôle par comparaison inter-paires, puis vérifie le `reason` ÉCRIT EN
    BASE (pas juste le dict retourné) — celui que lira un humain sans
    contexte plus tard."""
    from backend.services import pair_admission_controller as pac

    _tune_fast_bootstrap(monkeypatch)
    all_pairs = ("EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD")
    for i in range(600):
        pair = all_pairs[i % len(all_pairs)]
        noise = ((i * 37) % 101) / 101.0 - 0.5
        offset = 0.5 if pair == "EUR/USD" else 0.0
        _insert_shadow_row(
            _isolated_db, pair=pair, direction="buy",
            bar_timestamp=_SINCE + timedelta(hours=i), r_multiple=noise + offset,
            system_id=f"{pair.replace('/', '')}_{i}",
        )
    pac.set_state("EUR/USD", pac.STATE_PAUSED, "test setup", direction="buy")
    since = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    with sqlite3.connect(pac._db_path()) as c:
        row = c.execute(
            "SELECT id FROM pair_admission_state WHERE pair=? AND direction=? AND state='PAUSED' "
            "ORDER BY id DESC LIMIT 1",
            ("EUR/USD", "buy"),
        ).fetchone()
        c.execute("UPDATE pair_admission_state SET state_since = ? WHERE id = ?", (since, row[0]))

    pac.evaluate_pair("EUR/USD", direction="buy")

    with sqlite3.connect(pac._db_path()) as c:
        row = c.execute(
            "SELECT reason FROM pair_admission_state WHERE pair='EUR/USD' AND direction='buy' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
    stored_reason = row[0].lower()
    assert "hasard" not in stored_reason
    assert "aléatoire" not in stored_reason
    assert "comparable" in stored_reason
