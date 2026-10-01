"""Le garde de corrélation doit compter LE MONDE, pas sa propre mémoire.

⛔ **L'incident du 2026-10-01, 01h06 UTC.** Un seul cycle a poussé trois ordres
corrélés sur `admin_live` : GBP/JPY buy, puis USD/JPY buy 0,7 s plus tard, puis
USD/CAD buy. À la MÊME seconde, le journal montre le refus sur l'autre compte :

    01:06:35,723  correlation[admin_legacy] USD/JPY buy : meme pari que GBP/JPY buy

r(GBP/JPY, USD/JPY) = 0,876 chez le courtier, seuil 0,60,
`max_correlated_positions` = 1 sur les quatre comptes. L'ordre AURAIT dû être
refusé sur le réel aussi.

🔑 **La cause.** `positions_ouvertes()` lisait `personal_trades`. Or AUCUN
chemin de push n'écrit dans cette table : le seul `INSERT` est
`mt5_sync.py:324`, sur un ordonnanceur à **60 secondes**. Les trois lignes sont
apparues à `01:07:06`, trente secondes après le dernier ordre. Entre-temps, le
garde lisait un carnet **vide** et n'avait rien à opposer.

> **Une porte qui compte dans sa propre mémoire ne compte pas le monde.**

C'est le titre, mot pour mot, sous lequel le cap par paire a été migré vers les
positions du courtier le 2026-08-28, après les 47 ordres WTI du 31/07. La
jumelle de corrélation ne l'avait jamais été — [[feedback_doublure_de_test_absente_en_prod]],
un correctif ne se propage pas seul.

⚠️ Conséquence assumée : le courtier rend AUSSI les positions ouvertes à la
main. Ce sont de vraies positions simultanées, donc une vraie concentration —
même lecture que `_compter_positions_courtier`, qui les compte depuis le 28/08.
"""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace as NS

import pytest

from backend.services import bridge_destinations as bd
from backend.services import correlation_guard as cg
from backend.services import mt5_bridge as mb


def _dest(dest_id="admin_live"):
    """Un `BridgeConfig` réduit à ce que lisent les deux fonctions visées."""
    return NS(destination_id=dest_id, bridge_url="http://pont.invalide",
              bridge_api_key="k", symbol_map=None, user_id=None)


@pytest.fixture
def courtier(monkeypatch):
    """Branche le registre et le pont sur des doublures RÉELLEMENT filtrantes.

    ⛔ Une doublure qui rendrait ses positions quel que soit le compte ferait
    passer les tests pour une mauvaise raison — le défaut déjà payé sur
    `slippage_pips` et relevé dans `test_correlation_guard_identifiant`.
    """
    etat = {"positions": [], "compte": "admin_live", "vus": []}

    def _admin_destinations():
        return [_dest("admin_live"), _dest("admin_legacy")]

    def _positions(dest, sans_cache=False):
        # ⚠️ La doublure porte la MEME signature que la vraie. Sans le
        # `sans_cache`, elle levait un TypeError des que la production a
        # commence a le passer — une doublure qui n'a pas la FORME de ce
        # qu'elle remplace ne protege rien.
        etat["vus"].append(getattr(dest, "destination_id", None))
        if getattr(dest, "destination_id", None) != etat["compte"]:
            return []
        return etat["positions"]

    monkeypatch.setattr(bd, "admin_destinations", _admin_destinations)
    monkeypatch.setattr(mb, "_positions_courtier", _positions)
    return etat


# --- Le défaut lui-même ---------------------------------------------------

def test_une_position_du_courtier_est_vue_avant_toute_synchronisation(courtier):
    """⛔ Le cœur : la position existe chez le courtier, PAS dans la base.

    C'est l'état du système entre `01:06:35` et `01:07:06`. Avant ce
    correctif, cette fonction rendait `[]` — donc aucun pari en cause, donc
    rien de bloqué, sur de l'argent réel.
    """
    courtier["positions"] = [{"symbol": "GBPJPY", "type": "buy",
                              "ticket": 1360116453}]
    assert cg.positions_ouvertes("admin_live") == [("GBP/JPY", "buy")]


def test_le_deuxieme_ordre_du_meme_cycle_est_refuse(courtier):
    """La séquence de 03h06 Paris, rejouée : GBP/JPY passe, USD/JPY non."""
    courtier["positions"] = [{"symbol": "GBPJPY", "type": "buy",
                              "ticket": 1360116453}]
    pris, en_cause = cg.pari_deja_pris(_dest("admin_live"), "USD/JPY", "buy")
    assert pris is True, (
        "le garde a laissé passer le même pari une seconde fois — "
        "r(GBP/JPY, USD/JPY) = %s" % cg.correlation("GBP/JPY", "USD/JPY"))
    assert en_cause == ["GBP/JPY buy"]


def test_le_compte_voisin_ne_contamine_pas(courtier):
    """Les positions d'`admin_legacy` ne comptent pas pour `admin_live`.

    ⚠️ La seconde assertion n'est pas décorative. Sans elle, ce test passait
    AVANT le correctif — la base vide rendait déjà `[]`, pour une raison qui
    n'avait rien à voir. Exiger que le courtier ait été interrogé, et pour le
    bon compte, est ce qui le rend capable d'échouer.
    """
    courtier["positions"] = [{"symbol": "GBPJPY", "type": "buy", "ticket": 1}]
    courtier["compte"] = "admin_legacy"
    assert cg.positions_ouvertes("admin_live") == []
    assert courtier["vus"] == ["admin_live"]


# --- Le repli, qui ne doit JAMAIS rendre un carnet vide -------------------

def test_un_pont_injoignable_replie_sur_la_base_et_non_sur_le_vide(
        courtier, monkeypatch, tmp_path):
    """⛔ `None` = « je ne sais pas », et ne doit pas valoir « rien d'ouvert ».

    Le contrat du module est de réduire la concentration sans bloquer sur une
    panne. Mais répondre « carnet vide » à une panne réseau, c'est exactement
    le défaut qu'on corrige : on retombe donc sur l'état d'AVANT —
    `personal_trades` — plutôt que sur rien.
    """
    base = tmp_path / "trades.db"
    with sqlite3.connect(base) as c:
        c.execute("CREATE TABLE personal_trades (pair TEXT, direction TEXT, "
                  "is_auto INT, status TEXT, mt5_ticket INT)")
        c.execute("INSERT INTO personal_trades VALUES ('XAU/USD','sell',1,"
                  "'OPEN',777)")
    monkeypatch.setattr(cg, "_db_path", lambda: str(base))
    monkeypatch.setattr("backend.services.telegram_service.destination_for_ticket",
                        lambda t: "admin_live")
    monkeypatch.setattr(mb, "_positions_courtier",
                        lambda dest, sans_cache=False: None)

    assert cg.positions_ouvertes("admin_live") == [("XAU/USD", "sell")]


# --- Ce que le courtier rend et que le radar ne sait pas nommer -----------

def test_un_symbole_inconnu_reste_nomme_au_lieu_d_etre_jete(courtier):
    """Un symbole sans correspondance n'est pas perdu : il remonte tel quel.

    `exposition()` y répondra `None`, donc il comptera comme couple NON MESURÉ
    — tracé, pas bloquant. C'est le comportement déjà déclaré du module. Le
    jeter silencieusement ferait disparaître une exposition réelle.
    """
    courtier["positions"] = [{"symbol": "ZZZPERP", "type": "sell", "ticket": 9}]
    assert cg.positions_ouvertes("admin_live") == [("ZZZPERP", "sell")]


# --- La forme du champ `sens`, qui ne doit jamais faire perdre une position --

def test_le_sens_numerique_de_MT5_est_compris(courtier):
    """MT5 code le sens en entier : 0 = achat, 1 = vente.

    Le pont sert aujourd'hui `"buy"` / `"sell"`, mais un pont qui changerait
    de forme ferait disparaitre la position — et le carnet redeviendrait vide
    sans que rien ne le dise. C'est exactement le defaut qu'on corrige.
    """
    courtier["positions"] = [{"symbol": "XAUUSD", "type": 1, "ticket": 5}]
    assert cg.positions_ouvertes("admin_live") == [("XAU/USD", "sell")]


def test_un_sens_illisible_replie_sur_la_base_plutot_que_d_oublier(
        courtier, monkeypatch, tmp_path):
    """Une position dont on ne sait pas lire le sens EXISTE quand meme.

    La jeter rendrait un carnet incomplet qui a l'air complet. On repli donc
    sur `personal_trades`, et on le DIT.
    """
    base = tmp_path / "trades.db"
    with sqlite3.connect(base) as c:
        c.execute("CREATE TABLE personal_trades (pair TEXT, direction TEXT, "
                  "is_auto INT, status TEXT, mt5_ticket INT)")
        c.execute("INSERT INTO personal_trades VALUES ('XAU/USD','sell',1,"
                  "'OPEN',777)")
    monkeypatch.setattr(cg, "_db_path", lambda: str(base))
    monkeypatch.setattr("backend.services.telegram_service.destination_for_ticket",
                        lambda t: "admin_live")
    courtier["positions"] = [{"symbol": "XAUUSD", "type": "???", "ticket": 5}]

    assert cg.positions_ouvertes("admin_live") == [("XAU/USD", "sell")]


# --- Le cache de 10 s, qui rendrait tout le correctif cosmetique ----------

def test_le_garde_ne_se_fie_pas_au_cache_de_dix_secondes(monkeypatch):
    """Les trois ordres du 01/10 sont partis en 1,8 s. Le cache vaut 10 s.

    ⛔ Lire le courtier ne suffit pas : `_positions_courtier` sert une liste
    mise en cache pour dix secondes, et le cap par paire la remplit JUSTE
    AVANT que ce garde ne soit consulte. Le deuxieme ordre du meme cycle
    relirait donc le carnet d'AVANT le premier — exactement le carnet vide
    qu'on corrige, avec un aller-retour HTTP de plus pour faire illusion.

    Ce test fait changer le carnet entre les deux lectures. Un garde qui se
    fie au cache ne verra pas la premiere position.
    """
    from unittest.mock import MagicMock, patch

    carnets = [{"positions": []},
               {"positions": [{"symbol": "GBPJPY", "type": "buy",
                               "ticket": 1360116453}]}]
    reponses = []
    for c in carnets:
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = c
        reponses.append(r)

    client = MagicMock()
    client.__enter__ = lambda s: client
    client.__exit__ = lambda *a: False
    client.get.side_effect = reponses

    monkeypatch.setattr(bd, "admin_destinations",
                        lambda: [_dest("admin_live")])
    mb._positions_cache.clear()
    try:
        with patch.object(mb.httpx, "Client", return_value=client):
            # Le cap par paire lit le premier : carnet VIDE, mis en cache.
            assert mb._positions_courtier(_dest("admin_live")) == []
            # 0,7 s plus tard, le garde est consulte. Le courtier porte
            # desormais la position que le cycle vient d'ouvrir.
            assert cg.positions_ouvertes("admin_live") == [("GBP/JPY", "buy")]
    finally:
        mb._positions_cache.clear()
