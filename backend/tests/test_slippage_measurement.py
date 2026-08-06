"""Mesure du coût d'exécution : `fill_price` et `slippage_pips`.

Contexte (audit 2026-08-06) : ces deux colonnes existaient au schéma et
étaient vides sur **1581/1581** trades réels. La cause n'était pas un champ
manquant mais une comparaison creuse — le bridge écrit le prix OBTENU dans sa
colonne `entry`, et le backend la relisait comme le prix PLANIFIÉ. Le
glissement était donc calculé entre le fill et lui-même, soit toujours zéro,
soit `None` faute de `fill_price`.

Ces tests font tourner le calcul sur des lignes d'audit réalistes. Ils ne
lisent pas le source — cf. la leçon `feedback_source_inspection_tests_weak` :
un test qui cherche une chaîne dans un fichier passe encore quand la ligne est
commentée.
"""
import sqlite3

import pytest

from backend.services import mt5_sync


@pytest.fixture
def db(tmp_path, monkeypatch):
    """personal_trades minimal + neutralisation des dépendances externes."""
    f = tmp_path / "trades.db"
    conn = sqlite3.connect(f)
    conn.execute("""
        CREATE TABLE personal_trades (
            id INTEGER PRIMARY KEY,
            user TEXT, pair TEXT, direction TEXT,
            entry_price REAL, stop_loss REAL, take_profit REAL,
            size_lot REAL, signal_pattern TEXT, signal_confidence REAL,
            checklist_passed INTEGER, notes TEXT, status TEXT,
            created_at TEXT, mt5_ticket INTEGER UNIQUE, is_auto INTEGER,
            post_entry_sl INTEGER, post_entry_tp INTEGER, post_entry_size INTEGER,
            context_macro TEXT, signal_id INTEGER,
            fill_price REAL, slippage_pips REAL
        )
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr(mt5_sync, "_db_path", lambda: str(f))
    monkeypatch.setattr(
        mt5_sync.macro_context_service, "get_macro_snapshot", lambda: None
    )
    return str(f)


def _sync(db_path, **overrides):
    """Joue une ligne d'audit `filled` et rend (fill_price, slippage_pips)."""
    ticket = overrides.pop("ticket", 1)
    row = {
        "ticket": ticket,
        "pair": "EUR/USD",
        "direction": "buy",
        "lots": 0.01,
        "sl": 1.0950,
        "tp": 1.1050,
        # Le bridge écrit le prix OBTENU ici — reproduit fidèlement.
        "entry": overrides.get("fill_price"),
    }
    row.update(overrides)
    mt5_sync._upsert_open_trade(row, "trader@test.com")
    with sqlite3.connect(db_path) as c:
        return c.execute(
            "SELECT fill_price, slippage_pips FROM personal_trades WHERE mt5_ticket=?",
            (ticket,),
        ).fetchone()


# ── Signe et magnitude ────────────────────────────────────────────────

def test_achat_rempli_plus_bas_est_favorable(db):
    """Acheter sous le prix demandé fait gagner : slippage POSITIF."""
    fill, slip = _sync(
        db, direction="buy", entry_requested=1.1000,
        fill_price=1.0998, fill_source="result",
    )
    assert fill == 1.0998
    assert slip == pytest.approx(2.0)


def test_achat_rempli_plus_haut_est_defavorable(db):
    fill, slip = _sync(
        db, direction="buy", entry_requested=1.1000,
        fill_price=1.1003, fill_source="result",
    )
    assert slip == pytest.approx(-3.0)


def test_vente_remplie_plus_haut_est_favorable(db):
    """Vendre au-dessus du prix demandé fait gagner : slippage POSITIF."""
    _, slip = _sync(
        db, direction="sell", entry_requested=1.1000,
        fill_price=1.1002, fill_source="result",
    )
    assert slip == pytest.approx(2.0)


def test_vente_remplie_plus_bas_est_defavorable(db):
    _, slip = _sync(
        db, direction="sell", entry_requested=1.1000,
        fill_price=1.0997, fill_source="result",
    )
    assert slip == pytest.approx(-3.0)


# ── Refus de mesurer quand la mesure n'est pas observable ──────────────

def test_repli_sur_le_prix_demande_ne_produit_aucune_mesure(db):
    """`fill_source='requested'` = le bridge n'a PAS observé le fill et s'est
    replié sur le prix demandé. Le glissement vaudrait zéro par construction ;
    un faux zéro tirerait la moyenne vers l'absence de coût. On préfère
    l'absence de mesure."""
    fill, slip = _sync(
        db, direction="buy", entry_requested=1.1000,
        fill_price=1.1000, fill_source="requested",
    )
    assert fill == 1.1000, "le prix reste enregistré : il sert au R:R"
    assert slip is None, "mais il n'est pas compté comme un glissement nul"


def test_ancien_bridge_sans_prix_demande_ne_mesure_rien(db):
    """Rétrocompatibilité : un bridge non déployé n'envoie ni
    `entry_requested` ni `fill_source`. Aucune mesure, aucune erreur."""
    fill, slip = _sync(db, direction="buy", fill_price=1.0998)
    assert fill == 1.0998
    assert slip is None


# ── Régression : le bug d'origine ─────────────────────────────────────

def test_regression_la_reference_est_le_prix_demande_pas_entry(db):
    """LE test qui aurait attrapé le bug de 2026-08-06.

    Le bridge écrit le prix OBTENU dans `entry`. Ici `entry == fill_price`,
    exactement comme en production. Si le calcul prenait `entry` pour
    référence, il comparerait le fill à lui-même et rendrait 0.0 — la valeur
    qui a rendu la colonne inexploitable pendant onze mois.
    """
    fill, slip = _sync(
        db, direction="buy",
        entry=1.0998,             # ce que le bridge écrit : le prix obtenu
        entry_requested=1.1000,   # le prix réellement demandé
        fill_price=1.0998,
        fill_source="result",
    )
    assert slip is not None, "un glissement réel doit être mesuré"
    assert slip != 0.0, "comparer le fill à lui-même rendrait exactement 0.0"
    assert slip == pytest.approx(2.0)


# ── Taille du pip selon l'instrument ──────────────────────────────────

@pytest.mark.parametrize(
    "pair,planned,fill,attendu",
    [
        ("EUR/USD", 1.1000, 1.0998, 2.0),      # forex standard : pip = 0.0001
        ("USD/JPY", 150.00, 149.97, 3.0),      # quote JPY       : pip = 0.01
        ("XAU/USD", 4100.00, 4099.50, 50.0),   # métal           : pip = 0.01
        ("XAG/USD", 31.500, 31.480, 2.0),      # métal           : pip = 0.01
    ],
)
def test_taille_du_pip_par_instrument(db, pair, planned, fill, attendu):
    """Un même écart de prix ne vaut pas le même nombre de pips selon
    l'instrument — sans ça, l'or écraserait le forex dans toute moyenne."""
    _, slip = _sync(
        db, pair=pair, direction="buy",
        entry_requested=planned, fill_price=fill, fill_source="result",
    )
    assert slip == pytest.approx(attendu)


def test_deux_trades_distincts_sont_mesures_independamment(db):
    """Garde-fou sur le dedup : `INSERT OR IGNORE` sur mt5_ticket ne doit pas
    faire retomber le second trade sur la mesure du premier."""
    _sync(db, ticket=10, direction="buy", entry_requested=1.1000,
          fill_price=1.0998, fill_source="result")
    _, slip2 = _sync(db, ticket=11, direction="sell", entry_requested=1.1000,
                     fill_price=1.0997, fill_source="result")
    assert slip2 == pytest.approx(-3.0)
