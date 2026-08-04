"""Délai minimum entre deux ordres sur un même symbole (2026-08-04).

Le 2026-08-04, six ordres ETH sont partis en vingt-sept minutes sur le compte
Kraken, dont deux de sens opposés à la même seconde :

    17:50:47 sell · 17:56:42 sell · 17:59:41 sell
    18:14:38 buy  · 18:17:37 sell · 18:17:37 buy

La déduplication existante ne l'empêche pas : elle porte sur
``(destination, jour, paire, sens, prix d'entrée)``, donc un prix d'entrée qui
bouge d'un centime rouvre la porte. Le plafond de notionnel borne la taille
d'un ordre, pas leur fréquence.

Le réglage est **par destination**, et ces tests le verrouillent : mesuré sur
trente jours, un délai global de quinze minutes bloquerait 45 % des ordres de
Cédric, dont le rythme est sain (médiane 18 min, aucun sous 5 min pour
``admin_live``). Corriger notre compte ne doit pas changer le sien.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest

from backend.services import destinations_registry as reg
from backend.services import order_cooldown as oc


@pytest.fixture
def base(tmp_path, monkeypatch):
    db = tmp_path / "trades.db"
    with sqlite3.connect(db) as c:
        c.execute("""CREATE TABLE mt5_pushes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, destination_id TEXT NOT NULL,
            date TEXT NOT NULL, pair TEXT NOT NULL, direction TEXT NOT NULL,
            entry_price_5dp TEXT NOT NULL, pushed_at TEXT NOT NULL,
            ok INTEGER NOT NULL, bridge_response TEXT)""")
    monkeypatch.setattr(oc, "_db_path", lambda: str(db))
    return str(db)


def _pousser(db, dest_id, pair, il_y_a_secondes, ok=1):
    t = (datetime.now(timezone.utc) - timedelta(seconds=il_y_a_secondes)).isoformat()
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO mt5_pushes (destination_id,date,pair,direction,"
                  "entry_price_5dp,pushed_at,ok) VALUES (?,?,?,?,?,?,?)",
                  (dest_id, "2026-08-04", pair, "sell", "1.00000", t, ok))


def _dest(dest_id="admin_kraken"):
    return NS(destination_id=dest_id)


# --- le cas réel -----------------------------------------------------------

def test_la_rafale_eth_du_2026_08_04_serait_reduite(base):
    """Six ordres en 27 minutes deviennent deux.

    Le scénario traverse `en_cooldown` pour de vrai : chaque ordre accepté
    est écrit en base, comme le ferait la réservation de push, et l'ordre
    suivant est réévalué contre cet état.
    """
    depart = datetime.now(timezone.utc) - timedelta(minutes=40)
    minutes = [0, 6, 9, 24, 27, 27]  # les six pushs reels depuis 17:50:47
    acceptes = []

    for m in minutes:
        maintenant = depart + timedelta(minutes=m)

        class _Horloge(datetime):
            @classmethod
            def now(cls, tz=None):
                return maintenant

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(oc, "datetime", _Horloge)
            bloque, _ = oc.en_cooldown(_dest(), "ETH/USD")
        if bloque:
            continue
        acceptes.append(m)
        with sqlite3.connect(base) as c:
            c.execute("INSERT INTO mt5_pushes (destination_id,date,pair,"
                      "direction,entry_price_5dp,pushed_at,ok) VALUES "
                      "('admin_kraken','2026-08-04','ETH/USD','sell','1.0',?,1)",
                      (maintenant.isoformat(),))

    assert acceptes == [0, 24], f"attendu 2 ordres aux minutes 0 et 24, obtenu {acceptes}"


def test_un_ordre_juste_apres_un_autre_est_bloque(base):
    _pousser(base, "admin_kraken", "ETH/USD", il_y_a_secondes=180)
    bloque, restant = oc.en_cooldown(_dest(), "ETH/USD")
    assert bloque is True
    assert 700 < restant <= 720


def test_passe_le_delai_l_ordre_repart(base):
    _pousser(base, "admin_kraken", "ETH/USD", il_y_a_secondes=901)
    assert oc.en_cooldown(_dest(), "ETH/USD") == (False, 0)


def test_le_premier_ordre_n_est_jamais_bloque(base):
    assert oc.en_cooldown(_dest(), "ETH/USD") == (False, 0)


# --- la portée : un symbole, une destination ------------------------------

def test_un_autre_symbole_n_est_pas_bloque(base):
    """Kraken nette par symbole : BTC et ETH sont indépendants."""
    _pousser(base, "admin_kraken", "ETH/USD", il_y_a_secondes=60)
    assert oc.en_cooldown(_dest(), "BTC/USD") == (False, 0)


def test_une_autre_destination_n_est_pas_bloquee(base):
    """Le même signal peut légitimement partir chez deux brokers."""
    _pousser(base, "admin_kraken", "ETH/USD", il_y_a_secondes=60)
    assert oc.en_cooldown(_dest("admin_live"), "ETH/USD") == (False, 0)


def test_deux_destinations_a_delai_restent_independantes(base):
    """Comparer à une destination SANS délai ne prouve rien : la fonction
    sort avant même d'interroger la base. Il faut deux comptes qui portent
    tous deux un délai — sinon un filtre `destination_id` manquant passerait
    inaperçu, et un ordre Futures bloquerait un ordre Spot."""
    _pousser(base, "admin_kraken", "ETH/USD", il_y_a_secondes=60)
    assert oc.delai_requis(_dest("admin_kraken_spot")) > 0, "test sans portee"
    assert oc.en_cooldown(_dest("admin_kraken_spot"), "ETH/USD") == (False, 0)


def test_les_deux_sens_partagent_le_delai(base):
    """Un achat juste après une vente, c'est l'aller-retour qu'on vise —
    le 2026-08-04, vente et achat sont partis à la MÊME seconde."""
    _pousser(base, "admin_kraken", "ETH/USD", il_y_a_secondes=10)
    bloque, _ = oc.en_cooldown(_dest(), "ETH/USD")
    assert bloque is True


# --- Cédric ne doit pas être touché ---------------------------------------

@pytest.mark.parametrize("dest_id", ["admin_live", "admin_legacy",
                                     "admin_binance", "user:2"])
def test_les_comptes_au_rythme_sain_restent_libres(base, dest_id):
    """45 % des ordres de Cédric sont à moins de 15 minutes : un délai global
    lui bloquerait presque un ordre sur deux."""
    _pousser(base, dest_id, "EUR/USD", il_y_a_secondes=10)
    assert oc.en_cooldown(_dest(dest_id), "EUR/USD") == (False, 0)


@pytest.mark.parametrize("dest_id", ["admin_kraken", "admin_kraken_spot",
                                     "admin_kraken_stocks"])
def test_seules_les_destinations_kraken_portent_un_delai(dest_id):
    assert reg.DESTINATIONS[dest_id].order_cooldown_sec == 900


@pytest.mark.parametrize("dest_id", ["admin_live", "admin_legacy", "admin_binance"])
def test_les_autres_destinations_sont_a_zero(dest_id):
    assert reg.DESTINATIONS[dest_id].order_cooldown_sec == 0


def test_le_defaut_global_est_desactive():
    """Un défaut non nul changerait des comptes qu'on n'a pas mesurés."""
    assert oc.ORDER_COOLDOWN_SEC == 0


# --- un ordre non confirmé compte quand même ------------------------------

def test_une_reservation_non_confirmee_compte(base):
    """`ok=0` signifie qu'un ordre a PEUT-ÊTRE atteint le marché. L'ignorer
    autoriserait un doublon juste après un timeout."""
    _pousser(base, "admin_kraken", "ETH/USD", il_y_a_secondes=60, ok=0)
    bloque, _ = oc.en_cooldown(_dest(), "ETH/USD")
    assert bloque is True


# --- ne jamais bloquer le trading sur une panne ---------------------------

def test_base_illisible_autorise_l_ordre(monkeypatch):
    """Un délai est une optimisation de coût, pas une protection."""
    monkeypatch.setattr(oc, "_db_path", lambda: "/inexistant/nulle-part.db")
    assert oc.en_cooldown(_dest(), "ETH/USD") == (False, 0)


def test_un_horodatage_illisible_autorise_l_ordre(base):
    with sqlite3.connect(base) as c:
        c.execute("INSERT INTO mt5_pushes (destination_id,date,pair,direction,"
                  "entry_price_5dp,pushed_at,ok) VALUES "
                  "('admin_kraken','2026-08-04','ETH/USD','sell','1.0','pas-une-date',1)")
    assert oc.en_cooldown(_dest(), "ETH/USD") == (False, 0)


def test_sans_destination_aucun_delai(base):
    assert oc.en_cooldown(None, "ETH/USD") == (False, 0)


# --- le branchement --------------------------------------------------------

def test_le_delai_est_bien_pose_dans_le_gate_de_dispatch():
    """Un module jamais appelé ne bloque rien."""
    import inspect

    from backend.services import mt5_bridge
    src = inspect.getsource(mt5_bridge._check_rejection)
    assert "en_cooldown" in src
    assert "cooldown_symbole" in src


def test_le_gate_recoit_bien_la_destination():
    """Sans `dest`, le délai par destination serait toujours celui du défaut."""
    import inspect

    from backend.services import mt5_bridge
    args = list(inspect.signature(mt5_bridge._check_rejection).parameters)
    assert args[:2] == ["setup", "dest"]
