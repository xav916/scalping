"""Le relais de canaux : ce qu'il accepte, et surtout ce qu'il REFUSE.

Le parseur transforme du texte non fiable en ordres. La valeur d'un tel module
ne se mesure pas à ce qu'il sait lire mais à ce qu'il refuse de deviner : un
message refusé coûte un signal, un message mal lu coûte un ordre à l'envers.

C'est pourquoi la majorité de ce fichier teste des refus.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "relais-signaux"))
from parseur import Refus, construire, lire  # noqa: E402


# --- ce qui doit passer ----------------------------------------------------

@pytest.mark.parametrize("texte,sens,entree,stop,objectif", [
    ("XAUUSD SELL 3900 SL 3920 TP 3880", "sell", 3900.0, 3920.0, 3880.0),
    ("GOLD BUY @ 3899.5 / SL: 3885 / TP1: 3910", "buy", 3899.5, 3885.0, 3910.0),
    ("XAU buy entree 3900, stop 3880", "buy", 3900.0, 3880.0, None),
    ("xauusd sell 3900,5 stop loss 3920,5", "sell", 3900.5, 3920.5, None),
])
def test_les_formes_courantes_sont_lues(texte, sens, entree, stop, objectif):
    s = lire(texte, "orvion")
    assert (s.pair, s.direction) == ("XAU/USD", sens)
    assert (s.entry_price, s.stop_loss, s.take_profit) == (entree, stop, objectif)


# --- ce qui doit être REFUSÉ ----------------------------------------------

@pytest.mark.parametrize("texte,attendu", [
    ("XAUUSD achat, on vise le haut du range", "stop"),
    ("XAU sell 3900-3902 SL 3920", "ZONE"),
    ("XAU buy 3900 sell 3950 SL 3880", "deux sens"),
    ("XAU et XAG sont correles, SL 10", "plusieurs instruments"),
    ("Belle seance aujourd'hui, SL 10", "aucun instrument"),
    ("XAUUSD 3900 SL 3920", "aucun sens"),
    ("", "vide"),
])
def test_un_message_incertain_ne_produit_rien(texte, attendu):
    with pytest.raises(Refus, match=attendu):
        lire(texte, "orvion")


@pytest.mark.parametrize("texte", [
    "SELL OR BUY, a vous de voir",
    "Je n'ai plus d'ARGENT sur ce compte, SL 10",
])
def test_les_mots_francais_ordinaires_ne_sont_pas_des_instruments(texte):
    """⛔ Garde de régression sur une décision, pas sur un bug.

    « OR » et « ARGENT » ont été retirés de la whitelist : ce sont des mots
    courants, et comme ils pointeraient vers une seule paire, le contrôle
    d'ambiguïté ne les rattraperait pas. Les remettre ferait naître un signal
    sur l'or à partir d'un message qui n'en parle pas.
    """
    with pytest.raises(Refus, match="aucun instrument"):
        lire(texte, "orvion")


@pytest.mark.parametrize("sens,entree,stop", [
    ("sell", 3900.0, 3880.0),   # stop SOUS l'entrée sur une vente
    ("buy", 3900.0, 3920.0),    # stop AU-DESSUS sur un achat
])
def test_un_stop_du_mauvais_cote_est_refuse(sens, entree, stop):
    """L'erreur la plus chère : un stop inversé transforme un risque borné en
    risque ouvert."""
    with pytest.raises(Refus, match="stop"):
        construire("orvion", "XAU/USD", sens, entree, stop)


@pytest.mark.parametrize("sens,objectif", [("sell", 3950.0), ("buy", 3850.0)])
def test_un_objectif_du_mauvais_cote_est_refuse(sens, objectif):
    stop = 3920.0 if sens == "sell" else 3880.0
    with pytest.raises(Refus, match="objectif"):
        construire("orvion", "XAU/USD", sens, 3900.0, stop, objectif)


def test_un_instrument_hors_whitelist_est_refuse():
    with pytest.raises(Refus, match="whitelist"):
        construire("orvion", "DOGE/USD", "buy", 1.0, 0.9)


# --- l'identifiant, donc l'idempotence ------------------------------------

def test_le_meme_appel_saisi_deux_fois_porte_le_meme_identifiant():
    """⛔ La propriété qui rend la saisie manuelle sûre : retaper le même appel
    ne doit pas produire un second ordre. L'unicité serveur portant sur
    `(source, external_id)`, un identifiant aléatoire ferait exactement
    l'inverse."""
    a = lire("XAUUSD SELL 3900 SL 3920 TP 3880", "orvion")
    b = lire("xauusd sell 3900 stop 3920 target 3880", "orvion")
    assert a.external_id == b.external_id


def test_deux_appels_identiques_a_deux_heures_sont_deux_signaux():
    """⚠️ Le pendant : `ref` prime, parce qu'un même appel réémis plus tard EST
    un autre signal."""
    a = lire("XAUUSD SELL 3900 SL 3920", "orvion", ref="2026-09-24T09:00")
    b = lire("XAUUSD SELL 3900 SL 3920", "orvion", ref="2026-09-24T14:00")
    assert a.external_id != b.external_id


def test_deux_sources_ne_partagent_pas_leurs_identifiants():
    a = lire("XAUUSD SELL 3900 SL 3920", "orvion")
    b = lire("XAUUSD SELL 3900 SL 3920", "apollo")
    assert a.external_id != b.external_id


# --- le contrat attendu par le serveur ------------------------------------

def test_la_charge_porte_exactement_les_champs_obligatoires():
    """`external_signals._OBLIGATOIRES` — source, external_id, pair, direction,
    entry_price, stop_loss. `take_profit` est optionnel et absent s'il est nul."""
    s = lire("XAU buy 3900 stop 3880", "orvion")
    assert set(s.charge()) == {"source", "external_id", "pair", "direction",
                               "entry_price", "stop_loss"}
    assert "take_profit" in lire("XAU buy 3900 stop 3880 tp 3950", "orvion").charge()
