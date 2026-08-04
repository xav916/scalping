"""Montants en euros : le notionnel, pas une table figée (2026-08-04).

Le message « trade ouvert » annonçait un montant calculé pour un lot fixe de
0,01, via une table statique par paire — sans lien avec le volume réellement
envoyé au broker :

- MT5 à 0,02 lot : deux fois trop petit par construction ;
- l'or : ~15× trop petit, la table elle-même étant fausse ;
- Kraken : sans signification. Le premier trade réel annonçait
  « Risque −0,01 € » pour environ 0,53 € engagés.

Les valeurs de référence ci-dessous ne sont pas inventées : elles viennent
de trades réellement clôturés en production, dont le P&L enregistré vaut la
formule notionnelle divisée par le taux EUR/USD. Le contrôle a porté sur
douze trades ; onze collent à ×1,15 (le taux), le douzième étant une sortie
partielle.
"""
from __future__ import annotations

import pytest

from backend.services import risk_eur


TAUX = 1.1525  # EUR/USD relevé le 2026-08-04


# --- validation contre des trades réellement clôturés ---------------------

@pytest.mark.parametrize("pair,entry,exit_,lot,pnl_eur,bridge", [
    # paire        entrée    sortie    lot    P&L EUR encaissé   bridge
    ("XAU/USD", 3312.40, 3328.78, 0.02, 28.43, "mt5"),
    ("XAU/USD", 3312.40, 3326.11, 0.01, 11.91, "mt5"),
    ("WTI/USD",   68.00,   69.80, 0.10, 15.64, "mt5"),
    ("ETH/USD", 1868.00, 1872.60, 0.01,  0.04, "mt5"),
])
def test_la_formule_colle_au_pnl_reellement_encaisse(pair, entry, exit_, lot,
                                                     pnl_eur, bridge):
    """C'est la seule vérification qui compte : l'argent réellement compté."""
    r = risk_eur.calculer(pair, entry, exit_, 0, lot, bridge, TAUX)
    assert r is not None
    assert r["risque_eur"] == pytest.approx(pnl_eur, rel=0.03), (
        f"{pair} {lot} lot : formule {r['risque_eur']} vs encaisse {pnl_eur}"
    )


def test_le_premier_trade_kraken_reel():
    """BTC short 0,0023 @ 63924, stop 64192 — le trade du 2026-08-04 17:50."""
    r = risk_eur.calculer("BTC/USD", 63924.0, 64192.0, 63523.0,
                          volume=0.0023, bridge_type="kraken", eur_usd=TAUX)
    assert r["risque_eur"] == pytest.approx(0.53, abs=0.02)
    assert r["gain_eur"] == pytest.approx(0.80, abs=0.02)
    assert r["rr"] == pytest.approx(1.5, abs=0.1)


# --- la distinction qui produisait l'erreur --------------------------------

def test_un_exchange_crypto_ne_multiplie_pas_par_un_contrat():
    """Le volume EST déjà la quantité de sous-jacent."""
    assert risk_eur.taille_contrat("BTC/USD", "kraken") == 1
    assert risk_eur.taille_contrat("ETH/USD", "kraken_spot") == 1
    assert risk_eur.taille_contrat("BTC/USD", "binance") == 1


def test_mt5_applique_la_taille_de_contrat():
    """Une once d'or n'est pas une unité de forex."""
    assert risk_eur.taille_contrat("XAU/USD", "mt5") == 100
    assert risk_eur.taille_contrat("EUR/USD", "mt5") == 100_000
    assert risk_eur.taille_contrat("WTI/USD", "mt5") == 100


def test_la_meme_paire_donne_deux_montants_selon_le_broker():
    """C'est exactement ce que l'ancienne table par paire ne pouvait pas dire."""
    kraken = risk_eur.calculer("ETH/USD", 1868.0, 1878.0, 0, 0.1, "kraken", TAUX)
    mt5 = risk_eur.calculer("ETH/USD", 1868.0, 1878.0, 0, 0.1, "mt5", TAUX)
    assert kraken["risque_eur"] == mt5["risque_eur"], "crypto : cs=1 des deux cotes"

    kr_or = risk_eur.calculer("XAU/USD", 3312.0, 3320.0, 0, 0.02, "kraken", TAUX)
    mt_or = risk_eur.calculer("XAU/USD", 3312.0, 3320.0, 0, 0.02, "mt5", TAUX)
    assert mt_or["risque_eur"] == pytest.approx(kr_or["risque_eur"] * 100, rel=0.01)


# --- proportionnalité au volume -------------------------------------------

def test_doubler_le_volume_double_le_risque():
    """La table figée l'ignorait : elle annonçait le même montant."""
    un = risk_eur.calculer("XAU/USD", 3312.40, 3320.10, 0, 0.01, "mt5", TAUX)
    deux = risk_eur.calculer("XAU/USD", 3312.40, 3320.10, 0, 0.02, "mt5", TAUX)
    assert deux["risque_eur"] == pytest.approx(un["risque_eur"] * 2, rel=0.01)


# --- refuser plutôt que mentir --------------------------------------------

@pytest.mark.parametrize("volume", [0, None, -1])
def test_sans_volume_aucun_montant(volume):
    """Un montant faux est pire qu'un montant absent : il est lu comme vrai."""
    assert risk_eur.calculer("XAU/USD", 3312.0, 3320.0, 0, volume, "mt5") is None


@pytest.mark.parametrize("entry,sl", [(0, 3320.0), (3312.0, 0), (3312.0, 3312.0)])
def test_sans_stop_exploitable_aucun_montant(entry, sl):
    assert risk_eur.calculer("XAU/USD", entry, sl, 0, 0.02, "mt5") is None


def test_une_valeur_illisible_ne_leve_pas():
    assert risk_eur.calculer("XAU/USD", "abc", 3320.0, 0, 0.02, "mt5") is None


# --- le taux de change -----------------------------------------------------

def test_le_taux_reste_dans_une_borne_vraisemblable():
    """Une valeur aberrante en base produirait un montant absurde crédible."""
    t = risk_eur.taux_eur_usd()
    assert 0.5 < t < 2.0


def test_le_taux_n_appelle_que_des_fonctions_existantes():
    """Même garde-fou que pour `record_push` : une faute de nom ne lève
    qu'à l'exécution, ici dans un `except` qui l'avalerait."""
    import ast
    import inspect

    from backend.services import macro_data

    src = inspect.getsource(risk_eur.taux_eur_usd)
    appels = {n.func.attr for n in ast.walk(ast.parse(src.strip()))
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and isinstance(n.func.value, ast.Name)
              and n.func.value.id == "macro_data"}
    assert appels, "aucun appel detecte : le test ne teste rien"
    manquantes = sorted(a for a in appels if not hasattr(macro_data, a))
    assert manquantes == [], f"fonctions inexistantes : {manquantes}"
