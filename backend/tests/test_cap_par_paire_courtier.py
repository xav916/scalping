"""Le cap par paire compte chez le COURTIER, plus dans notre base (2026-08-28).

Le 2026-07-31, **47 ordres `XTIUSD buy`** ont franchi un cap fixé à 1 pour
l'énergie. La porte comptait dans `personal_trades` — la base du radar — qui
voyait zéro WTI ouvert pendant que le courtier en tenait un. Rien ne les a
arrêtés côté radar : seul un **bug de pendule** dans l'anti-doublon du bridge
(cf. `test_bridge_horloge_serveur`) les a bloqués, et sa correction retirait
donc le seul filet qui restait.

> **Une porte qui compte dans sa propre mémoire ne compte pas le monde.**

Ce qui est verrouillé ici :

1. le compte vient de `/positions` du bridge, pas de la base locale ;
2. la paire du radar est traduite en symbole du courtier — `WTI/USD` vaut
   `XTIUSD` chez IC Markets et `SpotCrude` chez Pepperstone, et comparer sans
   traduire compterait toujours zéro ;
3. ⛔ **une lecture ratée n'est pas un zéro** : elle rend la porte
   *indécidable* et refuse, au lieu de conclure qu'il reste de la place ;
4. les routes EA queue (users Premium), qui n'ont aucun bridge à interroger,
   gardent le compte local — sinon elles seraient refusées en permanence.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.services import mt5_bridge


def _dest(bridge_url="http://bridge:8787", user_id=None, symbol_map=None):
    from backend.services.bridge_destinations import BridgeConfig
    return BridgeConfig(
        destination_id="admin_live" if user_id is None else f"user:{user_id}",
        user_id=user_id,
        bridge_url=bridge_url,
        bridge_api_key="cle",
        min_confidence=50,
        allowed_asset_classes=frozenset({"energy", "forex", "metal"}),
        auto_exec_enabled=True,
        symbol_map=symbol_map,
    )


def _setup(pair="WTI/USD"):
    s = SimpleNamespace()
    s.pair = pair
    s.entry_price = 65.00
    s.stop_loss = 64.00
    s.take_profit_1 = 67.00
    s.take_profit_2 = None
    s.confidence_score = 80
    s.verdict_action = "TAKE"
    s.verdict_blockers = []
    s.is_simulated = False
    s.direction = "buy"
    return s


def _position(symbole):
    return {"ticket": 1, "symbol": symbole, "type": "buy", "volume": 0.01,
            "price_open": 65.0, "price_current": 65.1, "sl": 64.0, "tp": 0.0,
            "profit": 1.0, "time": None, "comment": ""}


# ── Traduire la paire ──────────────────────────────────────────────────────

def test_la_symbol_map_traduit_la_paire():
    d = _dest(symbol_map={"WTI/USD": "SpotCrude"})
    assert mt5_bridge._symbole_courtier_pour("WTI/USD", d) == "SpotCrude"


def test_sans_symbol_map_on_retire_la_barre_oblique():
    assert mt5_bridge._symbole_courtier_pour("WTI/USD", _dest()) == "WTIUSD"


# ── Compter ────────────────────────────────────────────────────────────────

def test_seules_les_positions_de_LA_paire_comptent():
    d = _dest(symbol_map={"WTI/USD": "XTIUSD"})
    positions = [_position("XTIUSD"), _position("XAUUSD"), _position("xtiusd")]
    with patch.object(mt5_bridge, "_positions_courtier", return_value=positions):
        assert mt5_bridge._compter_positions_courtier("WTI/USD", d) == 2


def test_aucune_position_vaut_ZERO_pas_indecidable():
    d = _dest(symbol_map={"WTI/USD": "XTIUSD"})
    with patch.object(mt5_bridge, "_positions_courtier", return_value=[]):
        assert mt5_bridge._compter_positions_courtier("WTI/USD", d) == 0


def test_une_lecture_ratee_rend_None_JAMAIS_zero():
    """⛔ Toute la porte tient là-dessus : « on ne sait pas » ≠ « il reste de
    la place »."""
    d = _dest(symbol_map={"WTI/USD": "XTIUSD"})
    with patch.object(mt5_bridge, "_positions_courtier", return_value=None):
        assert mt5_bridge._compter_positions_courtier("WTI/USD", d) is None


def test_un_bridge_qui_repond_500_est_une_lecture_ratee():
    reponse = MagicMock()
    reponse.status_code = 500
    client = MagicMock()
    client.__enter__ = lambda s: client
    client.__exit__ = lambda *a: False
    client.get.return_value = reponse
    with patch.object(mt5_bridge.httpx, "Client", return_value=client):
        assert mt5_bridge._positions_courtier(_dest()) is None


def test_une_destination_SANS_bridge_ne_prétend_pas_lire():
    assert mt5_bridge._positions_courtier(_dest(bridge_url="")) is None


def test_le_compte_est_mis_en_cache():
    """Consulté une fois par setup : sans cache, une vague de signaux ferait
    autant d'aller-retours HTTP."""
    reponse = MagicMock()
    reponse.status_code = 200
    reponse.json.return_value = {"positions": [_position("XTIUSD")]}
    client = MagicMock()
    client.__enter__ = lambda s: client
    client.__exit__ = lambda *a: False
    client.get.return_value = reponse
    d = _dest()
    mt5_bridge._positions_cache.clear()
    with patch.object(mt5_bridge.httpx, "Client", return_value=client) as fabrique:
        mt5_bridge._positions_courtier(d)
        mt5_bridge._positions_courtier(d)
    assert fabrique.call_count == 1
    mt5_bridge._positions_cache.clear()


# ── Branchement : la porte lit-elle vraiment le courtier ? ─────────────────

def _neutre():
    return [
        patch("backend.services.mt5_bridge.is_market_open_for_destination",
              return_value=True),
        patch("backend.services.mt5_bridge.MT5_BRIDGE_BLOCKED_DIRECTIONS", set()),
        patch("backend.services.mt5_bridge.MT5_BRIDGE_AVOID_HOURS_UTC", set()),
        patch("backend.services.mt5_bridge.MT5_BRIDGE_BLOCKED_PAIRS", frozenset()),
        patch("backend.services.bridge_tick_validator.validate_tick_pre_push",
              return_value=None),
        # ⛔ Le gel energie du VENDREDI SOIR. Sans lui, ces tests passaient du
        # lundi au jeudi et echouaient le vendredi apres 20 h UTC — sur
        # `energy_pre_weekend_freeze`, une porte qui n'a rien a voir avec le
        # cap par paire. Une horloge dans un test est une bombe a retardement
        # qui n'explose qu'un jour sur sept.
        patch("config.settings.NO_FRIDAY_LATE_OPEN_ENERGY_ENABLED", False),
    ]


def _juger(dest, **surcharges):
    correctifs = _neutre()
    for p in surcharges.pop("extra", []):
        correctifs.append(p)
    for c in correctifs:
        c.start()
    try:
        return mt5_bridge._check_rejection(_setup(), dest)
    finally:
        for c in reversed(correctifs):
            c.stop()


def test_LE_CAS_DU_31_07_le_courtier_dit_1_la_base_locale_dit_0():
    """Le cap énergie vaut 1. La base locale voyait 0, le courtier tenait 1 :
    c'est ce désaccord qui a laissé partir 47 ordres."""
    d = _dest(symbol_map={"WTI/USD": "XTIUSD"})
    verdict = _juger(d, extra=[
        patch("backend.services.mt5_bridge._count_open_trades_for_pair",
              return_value=0),
        patch("backend.services.mt5_bridge._positions_courtier",
              return_value=[_position("XTIUSD")]),
    ])
    assert verdict == "max_positions_per_pair"


def test_un_bridge_MUET_rend_la_porte_indecidable_et_refuse():
    d = _dest(symbol_map={"WTI/USD": "XTIUSD"})
    verdict = _juger(d, extra=[
        patch("backend.services.mt5_bridge._count_open_trades_for_pair",
              return_value=0),
        patch("backend.services.mt5_bridge._positions_courtier",
              return_value=None),
    ])
    assert verdict == "max_positions_per_pair_indecidable"


def test_le_courtier_vide_laisse_passer_la_porte():
    d = _dest(symbol_map={"WTI/USD": "XTIUSD"})
    verdict = _juger(d, extra=[
        patch("backend.services.mt5_bridge._count_open_trades_for_pair",
              return_value=9),          # la base locale ment : sans effet
        patch("backend.services.mt5_bridge._positions_courtier",
              return_value=[]),
    ])
    assert verdict not in ("max_positions_per_pair",
                           "max_positions_per_pair_indecidable")


def test_une_route_EA_QUEUE_garde_le_compte_local():
    """⛔ Sans ce garde, les users Premium — qui n'ont aucun bridge HTTP —
    seraient refusés en permanence."""
    d = _dest(bridge_url="", user_id=42)

    def _interdit(_dest):
        raise AssertionError("le courtier ne doit PAS être interrogé ici")

    verdict = _juger(d, extra=[
        patch("backend.services.mt5_bridge._count_open_trades_for_pair",
              return_value=3),
        patch("backend.services.mt5_bridge._positions_courtier", _interdit),
    ])
    assert verdict == "max_positions_per_pair"


def test_le_code_de_refus_a_UNE_ETIQUETTE():
    """Un code qui n'est pas dans la table s'affiche brut dans les tableaux."""
    from backend.services.rejection_service import REASON_LABELS_FR
    assert "max_positions_per_pair_indecidable" in REASON_LABELS_FR


# ── Les deux pièges relevés EN PRODUCTION, dans l'heure du déploiement ─────

def test_le_MT5_SYMBOL_MAP_global_sert_de_seconde_table():
    """⛔ `admin_legacy` n'a aucune `symbol_map` de destination : son mapping
    vit dans le `MT5_SYMBOL_MAP` global (`WTI/USD:SpotCrude`). S'arrêter à la
    première table rendait `WTIUSD` pour une position nommée `SpotCrude` — un
    compte à zéro sur la paire même qui a motivé ce garde-fou."""
    d = _dest(symbol_map=None)
    with patch.object(mt5_bridge, "MT5_SYMBOL_MAP", {"WTI/USD": "SpotCrude"}):
        assert mt5_bridge._symbole_courtier_pour("WTI/USD", d) == "SpotCrude"
        with patch.object(mt5_bridge, "_positions_courtier",
                          return_value=[_position("SpotCrude")]):
            assert mt5_bridge._compter_positions_courtier("WTI/USD", d) == 1


def test_la_table_de_la_DESTINATION_prime_sur_la_globale():
    """Le même WTI/USD vaut `SpotCrude` chez Pepperstone et `XTIUSD` chez IC
    Markets : la table la plus spécifique gagne."""
    d = _dest(symbol_map={"WTI/USD": "XTIUSD"})
    with patch.object(mt5_bridge, "MT5_SYMBOL_MAP", {"WTI/USD": "SpotCrude"}):
        assert mt5_bridge._symbole_courtier_pour("WTI/USD", d) == "XTIUSD"


def test_une_destination_KRAKEN_n_est_PAS_jugee_par_cette_porte():
    """⛔ `admin_kraken` porte aussi une `bridge_url` et un `user_id` nul, mais
    son `/positions` parle une autre langue. Sans le filtre `bridge_type`,
    toute la route Kraken tombait en « indécidable » — un refus total posé par
    un garde-fou qui ne la concerne pas."""
    d_kraken = SimpleNamespace(
        destination_id="admin_kraken", user_id=None,
        bridge_url="http://kraken:8790", bridge_api_key="cle",
        bridge_type="kraken", min_confidence=50,
        allowed_asset_classes=frozenset({"energy", "forex", "metal"}),
        auto_exec_enabled=True, symbol_map=None,
    )

    def _interdit(_dest):
        raise AssertionError("le /positions MT5 ne doit PAS être interrogé ici")

    verdict = _juger(d_kraken, extra=[
        patch("backend.services.mt5_bridge._count_open_trades_for_pair",
              return_value=0),
        patch("backend.services.mt5_bridge._positions_courtier", _interdit),
    ])
    assert verdict != "max_positions_per_pair_indecidable"
