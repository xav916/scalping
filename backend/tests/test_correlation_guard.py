"""Garde-fou de corrélation : ne pas prendre deux fois le même pari.

Le 2026-08-04, le compte Kraken portait simultanément un short BTC et un
short ETH. Leurs rendements horaires corrèlent à **0,81** sur les données
réelles du système : c'était un seul pari, pris deux fois, pour 33 USD de
marge sur un compte de 103.

Le point délicat est le **signe**. ``EUR/USD`` et ``USD/CHF`` corrèlent à
−0,80 : un groupement naïf par « paniers » les mettrait ensemble et
bloquerait deux achats, alors que deux achats s'y compensent. Ce sont les
sens *opposés* qui y constituent le même pari.
"""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace as NS

import pytest

from backend.services import correlation_guard as cg
from backend.services import destinations_registry as reg


def _dest(dest_id="admin_kraken"):
    return NS(destination_id=dest_id)


# --- LE point : le signe de la corrélation --------------------------------

def test_deux_shorts_crypto_sont_le_meme_pari():
    """Le cas du 2026-08-04 : BTC et ETH corrèlent fortement.

    ⚠️ Exprimé via ``correlation()`` et non en dur : la valeur est passée de
    0,81 (prix d'entrée de signaux, 2026-08-04) à 0,889 (bougies horaires
    continues, 2026-08-09). Ce test porte sur le **signe** et le franchissement
    du seuil, pas sur la magnitude — figer celle-ci le ferait échouer à chaque
    nouvelle mesure.
    """
    expo = cg.exposition("BTC/USD", "sell", "ETH/USD", "sell")
    assert expo == pytest.approx(cg.correlation("BTC/USD", "ETH/USD"))
    assert expo >= cg.SEUIL_CORRELATION


def test_deux_sens_opposes_sur_paires_correlees_se_compensent():
    expo = cg.exposition("BTC/USD", "buy", "ETH/USD", "sell")
    assert expo == pytest.approx(-cg.correlation("BTC/USD", "ETH/USD"))
    assert expo < cg.SEUIL_CORRELATION


def test_une_correlation_negative_inverse_la_lecture():
    """EUR/USD et USD/CHF sont fortement ANTI-corrélés : acheter l'un et
    VENDRE l'autre, c'est le même pari. Un groupement par paniers se
    tromperait de sens.

    ⚠️ On verrouille la **propriété** (le signe s'inverse, le seuil tranche
    dans les deux sens), pas la valeur. Épingler `0,80` faisait tomber ce
    test à chaque remesure : la mesure forex du 2026-08-23 rend −0,819 là où
    la table historique disait −0,80. Un test qui casse quand la donnée
    s'améliore ne protège rien.
    """
    r = cg.correlation("EUR/USD", "USD/CHF")
    assert r is not None and r <= -cg.SEUIL_CORRELATION, (
        f"couple attendu fortement anti-corrélé, mesuré {r}")

    meme = cg.exposition("EUR/USD", "buy", "USD/CHF", "sell")
    oppose = cg.exposition("EUR/USD", "buy", "USD/CHF", "buy")
    assert meme == pytest.approx(-r)
    assert oppose == pytest.approx(r)
    assert meme >= cg.SEUIL_CORRELATION
    assert oppose < cg.SEUIL_CORRELATION


def test_une_paire_avec_elle_meme_est_totalement_correlee():
    assert cg.correlation("BTC/USD", "BTC/USD") == 1.0


def test_la_correlation_est_symetrique():
    for a, b in (("BTC/USD", "ETH/USD"), ("EUR/USD", "USD/CHF")):
        assert cg.correlation(a, b) == cg.correlation(b, a)


# --- non mesuré n'est pas décorrélé ---------------------------------------

def test_une_paire_jamais_mesuree_renvoie_none():
    """`None` plutôt que `0.0` : « non mesuré » et « indépendant » sont deux
    états différents, les confondre affirmerait une indépendance non vérifiée."""
    assert cg.correlation("EUR/USD", "BTC/USD") is None
    assert cg.exposition("EUR/USD", "buy", "BTC/USD", "buy") is None


def test_une_paire_non_mesuree_ne_bloque_pas(base, monkeypatch):
    monkeypatch.setattr(cg, "positions_ouvertes",
                        lambda d: [("EUR/USD", "buy")])
    pris, _ = cg.pari_deja_pris(_dest(), "BTC/USD", "buy")
    assert pris is False


# --- la table de corrélations ---------------------------------------------

def test_chaque_correlation_porte_son_nombre_d_observations():
    """Une corrélation sur 237 points ne vaut pas celle sur 1 468."""
    for couple, (valeur, n) in cg.CORRELATIONS.items():
        assert -1.0 <= valeur <= 1.0, couple
        assert n >= 100, f"{couple} : {n} observations, trop peu"


def test_les_couples_ne_sont_declares_qu_une_fois():
    """Un doublon inverse rendrait la table ambiguë."""
    vus = set()
    for a, b in cg.CORRELATIONS:
        assert (b, a) not in vus, f"({a}, {b}) declare dans les deux sens"
        vus.add((a, b))


# --- le comptage des positions --------------------------------------------

@pytest.fixture
def base(tmp_path, monkeypatch):
    db = tmp_path / "trades.db"
    with sqlite3.connect(db) as c:
        c.execute("""CREATE TABLE personal_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, pair TEXT, direction TEXT,
            status TEXT, is_auto INTEGER, mt5_ticket)""")
    monkeypatch.setattr(cg, "_db_path", lambda: str(db))
    return str(db)


def _ouvrir(db, pair, direction, ticket, status="OPEN"):
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO personal_trades (pair,direction,status,is_auto,"
                  "mt5_ticket) VALUES (?,?,?,1,?)", (pair, direction, status, ticket))


def test_un_second_pari_identique_est_bloque(base, monkeypatch):
    _ouvrir(base, "BTC/USD", "sell", "t1")
    monkeypatch.setattr("backend.services.telegram_service.destination_for_ticket",
                        lambda t: "admin_kraken")
    pris, en_cause = cg.pari_deja_pris(_dest(), "ETH/USD", "sell")
    assert pris is True
    assert en_cause == ["BTC/USD sell"]


def test_un_pari_oppose_reste_autorise(base, monkeypatch):
    _ouvrir(base, "BTC/USD", "sell", "t1")
    monkeypatch.setattr("backend.services.telegram_service.destination_for_ticket",
                        lambda t: "admin_kraken")
    pris, _ = cg.pari_deja_pris(_dest(), "ETH/USD", "buy")
    assert pris is False


def test_une_position_fermee_ne_compte_pas(base, monkeypatch):
    _ouvrir(base, "BTC/USD", "sell", "t1", status="CLOSED")
    monkeypatch.setattr("backend.services.telegram_service.destination_for_ticket",
                        lambda t: "admin_kraken")
    assert cg.pari_deja_pris(_dest(), "ETH/USD", "sell")[0] is False


def test_une_position_d_un_autre_compte_ne_compte_pas(base, monkeypatch):
    """Sans rattachement par ticket, une position MT5 bloquerait Kraken."""
    _ouvrir(base, "BTC/USD", "sell", "t1")
    monkeypatch.setattr("backend.services.telegram_service.destination_for_ticket",
                        lambda t: "admin_live")
    assert cg.pari_deja_pris(_dest("admin_kraken"), "ETH/USD", "sell")[0] is False


def test_le_premier_pari_passe_toujours(base, monkeypatch):
    monkeypatch.setattr("backend.services.telegram_service.destination_for_ticket",
                        lambda t: "admin_kraken")
    assert cg.pari_deja_pris(_dest(), "ETH/USD", "sell") == (False, [])


# --- réglage par destination ----------------------------------------------

@pytest.mark.parametrize("dest_id", ["admin_kraken", "admin_kraken_spot",
                                     "admin_kraken_stocks"])
def test_les_destinations_kraken_limitent_a_un_pari(dest_id):
    assert reg.DESTINATIONS[dest_id].max_correlated_positions == 1


@pytest.mark.parametrize("dest_id", ["admin_live", "admin_legacy"])
def test_les_comptes_MT5_limitent_a_un_pari_depuis_le_23_08(dest_id):
    """Posé le 2026-08-23, après avoir MESURÉ deux choses.

    1. Les 55 couples forex/métaux chez le courtier : la table historique
       n'en couvrait que cinq, donc le garde ne comptait rien sur presque
       tout ce que ces comptes tradent.
    2. L'impact rejoué sur 60 jours — **6 trades sur 55 refusés sur le réel
       (11 %) et 6 sur 39 sur le démo (15 %)**, essentiellement des doublons
       du même instrument.

    ⚠️ Le « 281 chevauchements sur 568 trades » du module comptait les
    chevauchements **deux à deux**, pas les trades refusés : un trade qui en
    recoupe trois compte pour trois. Les deux chiffres répondent à des
    questions différentes, et c'est le second qui décide.

    Les deux comptes portent la MÊME limite : une porte posée d'un seul côté
    n'est pas une porte.
    """
    assert reg.DESTINATIONS[dest_id].max_correlated_positions == 1


def test_binance_reste_illimitee():
    """Destination désactivée : on ne change pas ce qu'on ne mesure pas."""
    assert reg.DESTINATIONS["admin_binance"].max_correlated_positions == 0


def test_une_destination_sans_limite_ne_bloque_jamais(base, monkeypatch):
    """⚠️ Prend `admin_binance` et non `admin_live` : depuis le 2026-08-23 les
    deux comptes MT5 sont limités à 1, donc `admin_live` ne démontrerait plus
    ce qu'il est censé démontrer. BTC/USD et ETH/USD corrèlent à 0,81 — même
    sens, même pari — et doivent passer QUAND MÊME sur une destination sans
    limite."""
    _ouvrir(base, "BTC/USD", "sell", "t1")
    monkeypatch.setattr("backend.services.telegram_service.destination_for_ticket",
                        lambda t: "admin_binance")
    assert reg.DESTINATIONS["admin_binance"].max_correlated_positions == 0
    assert cg.pari_deja_pris(_dest("admin_binance"), "ETH/USD", "sell")[0] is False


def test_sans_destination_aucun_blocage(base):
    assert cg.pari_deja_pris(None, "ETH/USD", "sell") == (False, [])


# --- ne pas bloquer le trading sur une panne ------------------------------

def test_base_illisible_autorise_l_ordre(monkeypatch):
    monkeypatch.setattr(cg, "_db_path", lambda: "/inexistant/nulle-part.db")
    assert cg.pari_deja_pris(_dest(), "ETH/USD", "sell")[0] is False


# --- le branchement --------------------------------------------------------

def test_le_garde_fou_est_pose_dans_le_gate_de_dispatch():
    import inspect

    from backend.services import mt5_bridge
    src = inspect.getsource(mt5_bridge._check_rejection)
    assert "pari_deja_pris" in src
    assert "correlated_exposure" in src


def test_les_positions_kraken_ouvertes_sont_materialisees():
    """Elles n'existaient nulle part avant leur clôture : le garde-fou, comme
    le cap par paire, n'aurait rien vu."""
    import inspect

    from backend.services import kraken_sync
    src = inspect.getsource(kraken_sync.reconcile)
    assert "materialiser_ouvertures" in src
    assert "'OPEN'" in inspect.getsource(kraken_sync.materialiser_ouvertures)
