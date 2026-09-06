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

    src = inspect.getsource(risk_eur._close_macro)
    appels = {n.func.attr for n in ast.walk(ast.parse(src.strip()))
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and isinstance(n.func.value, ast.Name)
              and n.func.value.id == "macro_data"}
    assert appels, "aucun appel detecte : le test ne teste rien"
    manquantes = sorted(a for a in appels if not hasattr(macro_data, a))
    assert manquantes == [], f"fonctions inexistantes : {manquantes}"


def test_les_SYMBOLES_demandes_sont_reellement_COLLECTES():
    """⛔ LE test qui manquait. Le précédent vérifiait le nom de la FONCTION,
    pas celui du SYMBOLE — et c'est le symbole qui était faux :
    `taux_eur_usd()` demandait « EURUSD=X », absent de `SYMBOL_MAP` depuis
    toujours. Résultat : le taux de chaque notification était la constante
    1,155, et le repli « exceptionnel » était permanent.

    Un symbole jamais collecté ne lève rien. Il rend `None`, et le repli
    fait passer l'absence pour une valeur."""
    from backend.services.macro_data import SYMBOL_MAP

    demandes = {s for s, _ in risk_eur._SERIE_PAR_DEVISE.values()} | {"eurusd"}
    manquants = sorted(d for d in demandes if d not in SYMBOL_MAP)
    assert manquants == [], (
        f"series demandees mais jamais collectees : {manquants}")


# ── La devise de COTATION (2026-09-06) ─────────────────────────────────────
#
# ⛔ Le défaut, lu sur un vrai message du compte réel :
#
#     🟢 ACHAT Dollar / Yen · IC Markets · LIVE (argent réel)
#     Risque −909,09 €  →  Objectif +1636,36 €
#     Entrée 156,09700 · 0,01 lot · SL 155,04700
#
# Le risque réel de cette position est d'environ 5,80 €. Le produit
# |entrée−stop| × volume × contrat vaut 1 050 — mais en YENS. Il était divisé
# par EUR/USD comme s'il s'agissait de dollars, d'où un facteur 156, qui est
# le cours USD/JPY lui-même.
#
# 🔑 Seules les paires cotées en dollars étaient justes — dont l'or, l'argent
# et le WTI. C'est ce qui a permis au défaut de vivre.

import pytest


@pytest.mark.parametrize("pair,entry,sl,attendu", [
    # Cotées en dollars : c'est ce qui masquait le défaut.
    ("XAU/USD", 4450.0, 4420.0, 25.97),
    # ⚠️ EUR/USD fait exception, et en MIEUX : son prix d'entrée EST le taux
    # euro/dollar. On l'emploie plutôt que la constante macro — 4,61 € au taux
    # vivant 1,0850, contre 4,33 € au 1,155 figé. Le montant bouge donc, et
    # c'est l'ancien qui était approximatif.
    ("EUR/USD", 1.0850, 1.0800, 4.61),
    # Cotées en yens : c'était 909,09 €.
    ("USD/JPY", 156.097, 155.047, 5.82),
    ("EUR/JPY", 180.50, 179.45, 5.82),
    # Sous-estimée de 30 %, puis surestimée de 40 %.
    ("EUR/GBP", 0.8650, 0.8600, 5.78),
    ("USD/CAD", 1.3800, 1.3750, 3.14),
])
def test_le_montant_suit_la_devise_de_cotation(pair, entry, sl, attendu):
    m = risk_eur.calculer(pair, entry, sl, 0, 0.01, "mt5", 1.155)
    assert m["risque_eur"] == pytest.approx(attendu, abs=0.02), pair


def test_le_cas_EXACT_du_message_reel():
    """⛔ 909,09 € annoncés pour 5,82 € engagés — sur de l'argent réel."""
    m = risk_eur.calculer("USD/JPY", 156.097, 155.047, 157.987, 0.01,
                          "mt5", 1.155)
    assert m["risque_eur"] == pytest.approx(5.82, abs=0.02)
    assert m["gain_eur"] == pytest.approx(10.48, abs=0.02)
    assert m["risque_eur"] < 10, "le montant ne doit plus etre de l'ordre de 900"


def test_le_RR_reste_juste_meme_quand_les_euros_manquent():
    """🔑 Numérateur et dénominateur sont dans la même devise : elle s'annule.
    C'est ce qui reste à dire quand la conversion est indécidable."""
    m = risk_eur.calculer("GBP/JPY", 202.50, 201.45, 204.39, 0.01, "mt5", 1.155)
    assert m["rr"] == pytest.approx(1.8, abs=0.01)


def test_une_croisee_SANS_taux_rend_None_pas_un_chiffre_faux(monkeypatch):
    """⛔ Sur GBP/JPY le prix d'entrée ne porte aucun taux exploitable.
    Inventer une approximation recréerait le défaut qu'on répare."""
    monkeypatch.setattr(risk_eur, "_close_macro", lambda s: None)
    m = risk_eur.calculer("GBP/JPY", 202.50, 201.45, 204.39, 0.01, "mt5", 1.155)
    assert m["risque_eur"] is None and m["gain_eur"] is None


def test_une_croisee_AVEC_taux_est_convertie(monkeypatch):
    monkeypatch.setattr(risk_eur, "_close_macro",
                        lambda s: 156.097 if s == "usdjpy" else None)
    m = risk_eur.calculer("GBP/JPY", 202.50, 201.45, 204.39, 0.01, "mt5", 1.155)
    # 1,05 × 1000 = 1050 JPY -> /156,097 = 6,73 USD -> /1,155 = 5,82 EUR
    assert m["risque_eur"] == pytest.approx(5.82, abs=0.02)


def test_un_symbole_SANS_barre_est_cote_en_dollars():
    """SPX, NDX, WTI chez IC Markets. Les traiter comme une croisee leur
    ferait perdre leur montant."""
    assert risk_eur.devises("SPX") == ("SPX", "USD")
    m = risk_eur.calculer("SPX", 5000.0, 4990.0, 5018.0, 0.01, "mt5", 1.155)
    assert m["risque_eur"] is not None


def test_le_taux_n_est_cherche_QUE_pour_les_croisees(monkeypatch):
    """⚠️ Faire dependre un message de trade d'une base qui peut manquer,
    alors que le prix d'entree suffit, serait une fragilite gratuite."""
    lus = []
    monkeypatch.setattr(risk_eur, "_close_macro",
                        lambda s: lus.append(s) or 156.0)
    risk_eur.calculer("USD/JPY", 156.097, 155.047, 157.987, 0.01, "mt5", 1.155)
    assert lus == [], "USD/JPY se convertit avec son propre prix"
