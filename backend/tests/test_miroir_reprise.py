"""Le miroir doit INSISTER quand le refus du courtier est passager.

Le 2026-08-12 a 13h10, un achat XAUUSD est rempli sur le demo et refuse sur le
reel : `retcode=10006`, « Request rejected ». Le journal MT5 dit « accepted »
puis « rejected » a la meme milliseconde, sans motif — un refus generique du
serveur d'IC Markets, avec **106,69 ms de latence** mesuree.

Le miroir a reessaye **deux fois en 400 ms**, donc dans exactement les memes
conditions, et a abandonne. Quelques minutes plus tard, `order_check` rendait
`retcode 0` / « Done » : **l'ordre serait passe**.

Resultat : le demo porte une position, le reel n'en a pas. C'est precisement la
divergence que le miroir existe pour supprimer.

⚠️ Un miroir strictement exact est IMPOSSIBLE — deux courtiers, deux serveurs,
deux carnets. Ce qui est atteignable, c'est de ne pas abandonner sur un refus
qui n'aurait pas survecu a dix secondes d'attente.

⚠️ On ne reessaie QUE sur un refus transitoire. Une marge insuffisante ou un
coupe-circuit journalier ne changeront pas d'avis : insister ne ferait
qu'ajouter du bruit et retarder le renoncement.
"""
import pytest

from backend.services import mt5_bridge


# --- ce qui merite une reprise ---------------------------------------------

@pytest.mark.parametrize("reponse", [
    {"retcode": 10006, "message": "Request rejected"},
    {"message": "Request rejected", "retcode": 10006, "ok": False},
    {"retcode": 10004},          # requote
    {"retcode": 10021},          # prix hors marche
    {"retcode": 10008},          # ordre place mais non confirme
])
def test_les_refus_passagers_sont_rejouables(reponse):
    assert mt5_bridge._refus_transitoire(reponse) is True


# --- ce qui n'en merite pas -------------------------------------------------

@pytest.mark.parametrize("reponse", [
    {"message": "Marge insuffisante : marge_insuffisante_meme_au_lot_minimum"},
    {"blocked": True, "reason": "Daily drawdown reached: loss=129.46 >= limit=16.22"},
    {"blocked": True, "reason": "Duplicate: buy XAUUSD already open"},
    {"reason": "risque_realise_trop_eleve"},
    {"retcode": 10016},          # stops invalides : rejouer ne les corrigera pas
    {"retcode": 10019},          # pas assez d'argent
])
def test_les_refus_definitifs_ne_sont_PAS_rejoues(reponse):
    """⚠️ Insister sur une marge insuffisante ne fait qu'ajouter du bruit et
    retarder le moment ou l'on constate qu'il n'y a rien a faire."""
    assert mt5_bridge._refus_transitoire(reponse) is False


def test_une_reponse_vide_ou_illisible_n_est_pas_rejouee():
    """Ne pas savoir n'est pas une raison d'insister : sans information, on
    s'arrete et on laisse la trace."""
    for reponse in ({}, None, {"ok": False}, "texte brut"):
        assert mt5_bridge._refus_transitoire(reponse) is False


def test_un_succes_n_est_evidemment_pas_rejoue():
    assert mt5_bridge._refus_transitoire({"ok": True, "ticket": 123}) is False


# --- la politique de reprise -------------------------------------------------

def test_les_delais_laissent_le_marche_bouger():
    """Reessayer dans la meme milliseconde reproduit les memes conditions —
    c'est ce que faisait le bridge, et les deux tentatives ont echoue a 400 ms
    d'intervalle. Les delais doivent etre croissants et couvrir plusieurs
    secondes."""
    delais = mt5_bridge.MIROIR_DELAIS_REPRISE
    assert len(delais) >= 2, "une seule reprise ne vaut guere mieux qu'aucune"
    assert list(delais) == sorted(delais), "les delais doivent croitre"
    assert delais[0] >= 1, "une reprise immediate reproduit les memes conditions"
    assert sum(delais) <= 60, (
        "au-dela d'une minute le prix n'a plus rien a voir avec le signal : "
        "ce ne serait plus une copie"
    )
