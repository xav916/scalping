"""Détection des clôtures de positions (2026-08-09).

Ce qui a motivé ces tests : la détection repose sur une **absence**. Une
position absente du relevé est réputée fermée — or un bridge injoignable rend
lui aussi « aucune position ». La frontière entre « fermé » et « pas su lire »
est la seule chose qui compte ici, et elle est vérifiée dans les deux sens :
la fonction ne conclut pas sur une lecture ratée, et l'instantané ne s'écrase
pas non plus, sinon la vraie clôture suivante serait perdue.

Les tests appellent les fonctions livrées plutôt que de recopier leur
condition. Cf. [[feedback_source_inspection_tests_weak]].
"""
import pytest

from backend.services.positions_fermees import (
    cle_position,
    clotures,
    doit_memoriser,
    indexer,
)


MT5_XAU = {"ticket": 1353960866, "symbol": "XAUUSD", "type": "sell", "volume": 0.01}
MT5_EUR = {"ticket": 82840896, "symbol": "EURUSD", "type": "buy", "volume": 0.02}
KRK_ETH = {"symbol": "PF_ETHUSD", "side": "long", "size": 0.1, "price": 3000.0}
KRK_BTC = {"symbol": "PF_XBTUSD", "side": "short", "size": 0.001, "price": 90000.0}


# ── Identité d'une position, selon le courtier ────────────────────────

def test_mt5_est_identifie_par_son_ticket():
    assert cle_position("mt5", MT5_XAU) == "1353960866"


def test_kraken_est_identifie_par_symbole_et_sens():
    """Kraken Futures n'a pas de ticket : c'est le couple qui fait l'identité."""
    assert cle_position("kraken", KRK_ETH) == "PF_ETHUSD|long"


def test_kraken_deux_sens_sont_deux_positions():
    """Sinon un retournement passerait pour une position inchangée."""
    court = dict(KRK_ETH, side="short")
    assert cle_position("kraken", KRK_ETH) != cle_position("kraken", court)


def test_kraken_spot_partage_la_convention_kraken():
    assert cle_position("kraken_spot", KRK_ETH) == "PF_ETHUSD|long"


def test_une_position_non_identifiable_est_ecartee():
    """Sans clé, elle serait vue fermée puis rouverte à chaque passage."""
    for bancale in ({"symbol": "XAUUSD"}, {"ticket": None}, {"ticket": 0},
                    {"ticket": "abc"}, {}, None):
        assert cle_position("mt5", bancale) is None
    assert cle_position("kraken", {"symbol": "PF_ETHUSD"}) is None, "sens manquant"
    assert cle_position("kraken", {"side": "long"}) is None, "symbole manquant"


def test_indexer_ecarte_silencieusement_les_illisibles():
    index = indexer("mt5", [MT5_XAU, {"ticket": None}, MT5_EUR])
    assert set(index) == {"1353960866", "82840896"}


# ── Le cœur : ce qui est annoncé fermé ────────────────────────────────

def test_une_position_disparue_est_fermee():
    avant = indexer("mt5", [MT5_XAU, MT5_EUR])
    apres = indexer("mt5", [MT5_EUR])
    fermees = clotures("mt5", avant, apres, lecture_reussie=True)
    assert [p["ticket"] for p in fermees] == [1353960866]


def test_une_position_toujours_la_n_est_pas_annoncee():
    avant = indexer("mt5", [MT5_XAU])
    assert clotures("mt5", avant, dict(avant), lecture_reussie=True) == []


def test_une_position_nouvelle_n_est_pas_une_cloture():
    avant = indexer("mt5", [MT5_XAU])
    apres = indexer("mt5", [MT5_XAU, MT5_EUR])
    assert clotures("mt5", avant, apres, lecture_reussie=True) == []


def test_toutes_fermees_est_un_resultat_legitime():
    """Quand la lecture a réussi, un relevé vide veut vraiment dire vide."""
    avant = indexer("mt5", [MT5_XAU, MT5_EUR])
    fermees = clotures("mt5", avant, {}, lecture_reussie=True)
    assert len(fermees) == 2


def test_kraken_retournement_compte_une_cloture():
    avant = indexer("kraken", [KRK_ETH])
    apres = indexer("kraken", [dict(KRK_ETH, side="short")])
    fermees = clotures("kraken", avant, apres, lecture_reussie=True)
    assert [p["side"] for p in fermees] == ["long"]


def test_une_taille_qui_change_n_est_pas_une_cloture():
    """Clôture partielle : la position vit toujours, on n'annonce rien."""
    avant = indexer("kraken", [KRK_ETH])
    apres = indexer("kraken", [dict(KRK_ETH, size=0.05)])
    assert clotures("kraken", avant, apres, lecture_reussie=True) == []


# ── Le garde-fou : un bridge muet ne ferme rien ───────────────────────

def test_lecture_ratee_n_annonce_AUCUNE_cloture():
    """Le défaut que ces tests existent pour empêcher.

    Trente secondes de coupure réseau annonceraient sinon la clôture de toutes
    les positions ouvertes, avec leur P&L inventé.
    """
    avant = indexer("mt5", [MT5_XAU, MT5_EUR])
    assert clotures("mt5", avant, {}, lecture_reussie=False) == []
    assert clotures("mt5", avant, None, lecture_reussie=False) == []


def test_lecture_ratee_ne_memorise_pas():
    """Corollaire : sinon le vide écrase l'instantané et la vraie clôture,
    au passage suivant, n'a plus de référence à laquelle se comparer."""
    assert doit_memoriser(False) is False
    assert doit_memoriser(True) is True


def test_premier_passage_sans_reference_n_annonce_rien():
    for vide in (None, {}):
        assert clotures("mt5", vide, indexer("mt5", [MT5_XAU]), True) == []


@pytest.mark.parametrize("bridge", ["mt5", "kraken", "kraken_spot"])
def test_le_garde_fou_vaut_pour_tous_les_courtiers(bridge):
    avant = indexer(bridge, [MT5_XAU if bridge == "mt5" else KRK_BTC])
    assert clotures(bridge, avant, {}, lecture_reussie=False) == []
