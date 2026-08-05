"""Tests du retour de pause conditionné au contrôle par comparaison inter-paires.

Remplace le défaut décrit dans la tâche du 2026-08-05 : `evaluate_pair`
rendait l'argent réel à une pair PAUSED après un simple délai écoulé (14j
codé en dur), sans jamais consulter le score calculé. Le retour est
désormais conditionné à « les signaux de la pair font-ils mieux que la
moyenne des autres paires COMPARABLES (même classe d'actif) ? », mesuré par
`backend.services.random_entry_control.paired_block_bootstrap_delta` (module
générique, non modifié) sur des populations construites depuis
`shadow_setups` :

- `pattern` = les setups de la pair testée, ce sens, depuis le 2026-08-04
  (avant cette date : bug de dédup ×960, écarté).
- `domain`  = les setups des pairs de la MÊME CLASSE D'ACTIF que la pair
  testée (`config.settings.asset_class_for`), même sens, même fenêtre — un
  domaine de pairs comparables entre elles (même sens, même distribution
  temporelle, même régime de marché). `pattern` est un sous-ensemble STRICT
  de `domain` (mêmes lignes, filtrées après coup), donc chaque clé `pattern`
  existe forcément dans `domain` — condition nécessaire pour que
  l'appariement du bootstrap ait un sens.

⚠️ Renommé le 2026-08-05 (suite) : l'ancien nom (« contrôle par entrées
aléatoires ») était trompeur — le domaine n'a jamais été une entrée
réellement aléatoire, c'est une comparaison ENTRE PAIRES. Ce contrôle établit
seulement qu'une pair n'est pas pire que ses semblables : il ne dit rien de
la question systémique « les patterns battent-ils une VRAIE entrée
aléatoire ? » (mesurable seulement hors ligne, cf.
`backend/services/random_entry_control.py` et
`backend/tests/test_pair_admission_peer_control_asset_class.py` pour les
tests dédiés à la restriction par classe d'actif et à la disparition des
anciens noms).

Isolation complète : DB temporaire (`tmp_path`), aucun accès réseau ni à
`trades.db` / `backtest.db` du dépôt. `shadow_v2_core_long.ensure_schema()`
est appelé sur ce chemin isolé pour obtenir le schéma `shadow_setups`
PRODUCTION exact (colonnes `bar_timestamp`, `risk_pct`, `pnl_pct_net`,
`outcome`...) — la fixture ne le recopie pas à la main pour ne jamais
diverger du schéma réel.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest


# ─── Fixture d'isolation ─────────────────────────────────────────────────


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
    # Cache du contrôle par comparaison inter-paires : état de process
    # global, à vider entre chaque test pour ne jamais réutiliser le
    # résultat d'un test précédent.
    pac._PEER_CONTROL_CACHE.clear()

    # Schéma shadow_setups PRODUCTION exact (pas une copie à la main).
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


# ─── Helpers de construction shadow_setups ───────────────────────────────

_SINCE = datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)  # dans la fenêtre saine


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
    """Insère une ligne shadow_setups complète. `pnl_pct_net` est dérivé de
    `r_multiple` via la formule inverse de `r_multiple()` (risk_pct=0.01 →
    pnl_pct_net == r_multiple numériquement, pour simplifier les fixtures)."""
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


def _seed_domain_and_pattern(
    db_path,
    *,
    target_pair: str,
    direction: str,
    n_total: int,
    offset_for_target: float,
    other_pairs: tuple[str, ...] = ("EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD"),
    seed: int = 0,
):
    """Peuple `shadow_setups` avec `n_total` lignes réparties entre
    `target_pair` et `other_pairs`, toutes datées après `_SINCE`, ce
    `direction`. `offset_for_target` décale le R multiple des lignes de
    `target_pair` par rapport aux autres (0.0 = aucun effet injecté).

    Round-robin déterministe (pas de `random`) : reproductible sans graine
    fixe à gérer en plus de celle du bootstrap.
    """
    all_pairs = (target_pair,) + other_pairs
    for i in range(n_total):
        pair = all_pairs[i % len(all_pairs)]
        # bruit borné déterministe, centré sur 0
        noise = ((i * 37) % 101) / 101.0 - 0.5  # dans [-0.5, 0.5)
        r = noise + (offset_for_target if pair == target_pair else 0.0)
        _insert_shadow_row(
            db_path,
            pair=pair,
            direction=direction,
            bar_timestamp=_SINCE + timedelta(hours=i),
            r_multiple=r,
            system_id=f"TEST_{pair.replace('/', '')}_{direction}_{i}",
        )


def _set_paused_since(pac_module, pair: str, direction: str, days_ago: float):
    """Force l'état PAUSED avec un `state_since` situé `days_ago` jours dans
    le passé — écriture directe en DB (set_state horodate toujours à `now`)."""
    pac_module.set_state(pair, pac_module.STATE_PAUSED, "test setup", direction=direction)
    since = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    # SQLite ne supporte pas ORDER BY/LIMIT sur UPDATE par défaut (dépend de
    # la compilation) — cible la row la plus récente via id max, portable.
    with sqlite3.connect(pac_module._db_path()) as c:
        row = c.execute(
            "SELECT id FROM pair_admission_state WHERE pair=? AND direction=? AND state='PAUSED' "
            "ORDER BY id DESC LIMIT 1",
            (pair, direction),
        ).fetchone()
        if row:
            c.execute("UPDATE pair_admission_state SET state_since = ? WHERE id = ?", (since, row[0]))


# Réglages permissifs pour un bootstrap net et rapide en test (repris des
# paramètres qui font mordre `test_random_entry_control.py` de façon fiable :
# domaine dense, block_size petit, n_boot modéré).
def _tune_fast_bootstrap(monkeypatch):
    import config.settings as st
    monkeypatch.setattr(st, "PAC_PEER_CONTROL_BLOCK_SIZE", 5)
    monkeypatch.setattr(st, "PAC_PEER_CONTROL_N_BOOT", 1500)
    monkeypatch.setattr(st, "PAC_PEER_CONTROL_MIN_DOMAIN_BLOCKS", 3)
    monkeypatch.setattr(st, "PAC_PEER_CONTROL_SEED", 42)


# ─── 1. Une pair dont les signaux ne battent PAS le hasard reste en pause ──


def test_pattern_sans_effet_reste_en_pause(_isolated_db, monkeypatch):
    from backend.services import pair_admission_controller as pac

    _tune_fast_bootstrap(monkeypatch)
    # 600 lignes réparties sur 5 pairs FOREX (même classe d'actif que la
    # pair testée USD/CAD — le domaine restreint par classe reste donc
    # intact ici), AUCUN offset injecté pour la pair testée : par
    # construction, ses signaux ne se distinguent pas du reste.
    _seed_domain_and_pattern(
        _isolated_db, target_pair="USD/CAD", direction="buy",
        n_total=600, offset_for_target=0.0,
    )
    _set_paused_since(pac, "USD/CAD", "buy", days_ago=20)  # cool-off (14j) largement dépassé

    d = pac.evaluate_pair("USD/CAD", direction="buy")

    assert d["action"] == "keep"
    assert pac.get_current_state("USD/CAD", direction="buy") == pac.STATE_PAUSED
    assert "comparables" in d["reason"].lower()
    assert "hasard" not in d["reason"].lower()
    assert "aléatoire" not in d["reason"].lower()


# ─── 2. Une pair dont les signaux battent NETTEMENT le hasard revient ──────


def test_pattern_avec_effet_franc_revient_en_auto_exec(_isolated_db, monkeypatch):
    from backend.services import pair_admission_controller as pac

    _tune_fast_bootstrap(monkeypatch)
    # USD/CAD + 4 autres pairs forex : même classe d'actif, le domaine
    # restreint par classe couvre donc bien les 5 pairs (cf. helper).
    _seed_domain_and_pattern(
        _isolated_db, target_pair="USD/CAD", direction="buy",
        n_total=600, offset_for_target=0.5,  # effet franc, cf. module de référence
    )
    _set_paused_since(pac, "USD/CAD", "buy", days_ago=20)

    d = pac.evaluate_pair("USD/CAD", direction="buy")

    assert d["action"] == "transition"
    assert d["to_state"] == pac.STATE_AUTO_EXEC
    assert pac.get_current_state("USD/CAD", direction="buy") == pac.STATE_AUTO_EXEC
    assert "hasard" not in d["reason"].lower()
    assert "aléatoire" not in d["reason"].lower()


# ─── 3. Le délai seul ne suffit plus (régression directe du défaut) ───────


def test_delai_seul_ne_suffit_plus_sans_donnees(_isolated_db, monkeypatch):
    """LE test qui mord le défaut d'origine : cool-off largement dépassé,
    AUCUNE donnée shadow — avant le correctif, ceci retournait
    inconditionnellement à AUTO_EXEC (`set_state(..., "cool-off 14j expired,
    re-evaluating live", ...)` sans jamais consulter `score`)."""
    from backend.services import pair_admission_controller as pac

    _tune_fast_bootstrap(monkeypatch)
    # Aucune ligne shadow_setups insérée.
    _set_paused_since(pac, "XAU/USD", "buy", days_ago=100)

    d = pac.evaluate_pair("XAU/USD", direction="buy")

    assert d["action"] == "keep"
    assert pac.get_current_state("XAU/USD", direction="buy") == pac.STATE_PAUSED


# ─── 4. Le disjoncteur anti-cascade prime sur tout, y compris un effet franc ──


def test_disjoncteur_anti_cascade_prime_sur_controle_aleatoire(_isolated_db, monkeypatch):
    from backend.services import pair_admission_controller as pac

    _tune_fast_bootstrap(monkeypatch)
    # Effet FRANC (peer control favorable) — sans le disjoncteur, ceci
    # reviendrait en AUTO_EXEC.
    _seed_domain_and_pattern(
        _isolated_db, target_pair="USD/CAD", direction="buy",
        n_total=600, offset_for_target=0.5,
    )
    # État PAUSED courant (effectif), backdaté de 20j → cool-off dépassé.
    _set_paused_since(pac, "USD/CAD", "buy", days_ago=20)

    # + 2 PAUSED historiques supplémentaires, ANTÉRIEURES à l'état courant
    # (35j et 40j) mais dans la fenêtre de 60j de `_count_recent_pauses` :
    # seuil DEMOTE_MAX_RE_PAUSES_60D (2) atteint SANS changer la résolution
    # de l'état courant (qui reste la row la plus récente par state_since).
    pac._ensure_schema()
    with sqlite3.connect(_isolated_db) as c:
        for days_ago in (35, 40):
            since = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
            c.execute(
                "INSERT INTO pair_admission_state (pair, direction, destination, state, "
                "state_since, reason, transitioned_by) VALUES (?, ?, NULL, 'PAUSED', ?, 'test', 'auto')",
                ("USD/CAD", "buy", since),
            )

    d = pac.evaluate_pair("USD/CAD", direction="buy")

    assert d["action"] == "transition"
    assert d["to_state"] == pac.STATE_DEMOTED
    assert pac.get_current_state("USD/CAD", direction="buy") == pac.STATE_DEMOTED


# ─── 5. INDETERMINATE bloque toujours les rétrogradations (réconciliation) ─


def test_indeterminate_bloque_toujours_les_retrogradations(_isolated_db):
    """Pas de régression sur le garde-fou du 2026-08-05 : une pair AUTO_EXEC
    avec échantillon réel insuffisant (score INDETERMINATE) ne doit JAMAIS
    être rétrogradée, contrôle aléatoire ou pas — ce garde-fou ne concerne
    que le retour de pause, pas les rétrogradations."""
    from backend.services import pair_admission_controller as pac

    pac.set_state("NZD/USD", pac.STATE_AUTO_EXEC, "test init", direction="buy")
    # 0 trade réel : score restera INDETERMINATE quel que soit le contrôle aléatoire.
    d = pac.evaluate_pair("NZD/USD", direction="buy")

    assert d["action"] == "keep"
    assert d["score"]["eligible_for"] == pac.STATE_INDETERMINATE
    assert pac.get_current_state("NZD/USD", direction="buy") == pac.STATE_AUTO_EXEC


# ─── 6. Le réglage du délai est respecté ───────────────────────────────────


def test_reglage_cooloff_est_respecte(_isolated_db, monkeypatch):
    import config.settings as st
    from backend.services import pair_admission_controller as pac

    _tune_fast_bootstrap(monkeypatch)
    monkeypatch.setattr(st, "PAC_PAUSE_COOLOFF_DAYS", 3)
    _seed_domain_and_pattern(
        _isolated_db, target_pair="USD/CAD", direction="buy",
        n_total=600, offset_for_target=0.5,  # effet franc — reviendrait si le délai était passé
    )

    # 2 jours écoulés < 3j réglés → reste en pause malgré l'effet franc.
    _set_paused_since(pac, "USD/CAD", "buy", days_ago=2)
    d = pac.evaluate_pair("USD/CAD", direction="buy")
    assert d["action"] == "keep"
    assert pac.get_current_state("USD/CAD", direction="buy") == pac.STATE_PAUSED

    # 4 jours écoulés >= 3j réglés → revient.
    pac._PEER_CONTROL_CACHE.clear()
    _set_paused_since(pac, "USD/CAD", "buy", days_ago=4)
    d = pac.evaluate_pair("USD/CAD", direction="buy")
    assert d["action"] == "transition"
    assert d["to_state"] == pac.STATE_AUTO_EXEC


# ─── 7. Historique shadow antérieur au 2026-08-04 est écarté ──────────────


def test_shadow_anterieur_au_2026_08_04_est_ecarte(_isolated_db, monkeypatch):
    from backend.services import pair_admission_controller as pac

    _tune_fast_bootstrap(monkeypatch)
    # Toutes les lignes AVANT la fenêtre saine (bug de dédup ×960).
    corrupted_start = _SINCE - timedelta(days=60)
    for i in range(600):
        pair = ("XAU/USD", "EUR/USD", "GBP/USD")[i % 3]
        _insert_shadow_row(
            _isolated_db, pair=pair, direction="buy",
            bar_timestamp=corrupted_start + timedelta(hours=i),
            r_multiple=5.0 if pair == "XAU/USD" else -5.0,  # effet énorme, mais hors fenêtre
            system_id=f"OLD_{pair.replace('/', '')}_{i}",
        )
    _set_paused_since(pac, "XAU/USD", "buy", days_ago=20)

    d = pac.evaluate_pair("XAU/USD", direction="buy")

    # Malgré un effet éénorme injecté, tout est hors fenêtre → aucune donnée
    # exploitable → indécidable → reste en pause (pas un retour sur données corrompues).
    assert d["action"] == "keep"
    assert pac.get_current_state("XAU/USD", direction="buy") == pac.STATE_PAUSED


# ─── 8. Mise en cache : pas de recalcul dans la fenêtre TTL ───────────────


def test_cache_evite_le_recalcul_dans_la_fenetre_ttl(_isolated_db, monkeypatch):
    from backend.services import pair_admission_controller as pac

    _tune_fast_bootstrap(monkeypatch)
    _seed_domain_and_pattern(
        _isolated_db, target_pair="USD/CAD", direction="buy",
        n_total=600, offset_for_target=0.5,
    )

    calls = {"n": 0}
    original = pac.peer_control_for_pair

    def _counting(pair, direction):
        calls["n"] += 1
        return original(pair, direction)

    monkeypatch.setattr(pac, "peer_control_for_pair", _counting)

    r1 = pac.peer_control_for_pair_cached("USD/CAD", "buy")
    r2 = pac.peer_control_for_pair_cached("USD/CAD", "buy")

    assert calls["n"] == 1  # 2e appel servi depuis le cache
    assert r1 == r2


def test_cache_expire_apres_ttl(_isolated_db, monkeypatch):
    from backend.services import pair_admission_controller as pac
    import config.settings as st

    _tune_fast_bootstrap(monkeypatch)
    monkeypatch.setattr(st, "PAC_PEER_CONTROL_CACHE_HOURS", 1)
    _seed_domain_and_pattern(
        _isolated_db, target_pair="USD/CAD", direction="buy",
        n_total=600, offset_for_target=0.5,
    )

    calls = {"n": 0}
    original = pac.peer_control_for_pair

    def _counting(pair, direction):
        calls["n"] += 1
        return original(pair, direction)

    monkeypatch.setattr(pac, "peer_control_for_pair", _counting)

    pac.peer_control_for_pair_cached("USD/CAD", "buy")
    # Simule l'écoulement du TTL en reculant l'entrée de cache dans le passé.
    key = ("USD/CAD", "buy")
    ts, cached_result = pac._PEER_CONTROL_CACHE[key]
    pac._PEER_CONTROL_CACHE[key] = (ts - timedelta(hours=2), cached_result)

    pac.peer_control_for_pair_cached("USD/CAD", "buy")
    assert calls["n"] == 2


# ─── 9. direction=None (pair-level legacy) ne retourne jamais automatiquement ──


def test_direction_none_reste_en_pause(_isolated_db, monkeypatch):
    """Bucket pair-level (direction=None) : le contrôle aléatoire exige un
    sens explicite (même sens que le pattern testé). Repli conservateur :
    reste en pause plutôt que de deviner un sens."""
    from backend.services import pair_admission_controller as pac

    _tune_fast_bootstrap(monkeypatch)
    pac.set_state("XAU/USD", pac.STATE_PAUSED, "test setup")  # direction=None
    with sqlite3.connect(pac._db_path()) as c:
        since = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
        c.execute(
            "UPDATE pair_admission_state SET state_since = ? "
            "WHERE pair='XAU/USD' AND direction IS NULL AND state='PAUSED'",
            (since,),
        )

    d = pac.evaluate_pair("XAU/USD")

    assert d["action"] == "keep"
    assert pac.get_current_state("XAU/USD") == pac.STATE_PAUSED
