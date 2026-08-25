"""Un 429 du bridge ne dit PAS pourquoi il refuse — il faut lire le corps.

⛔ Le défaut, mesuré le 2026-08-25. `_categoriser_refus` rangeait tout
`status 429` sous `bridge_max_positions`. Or le bridge répond 429 pour TOUS ses
garde-fous. Sur le compte réel :

    108 lignes etiquetees « places pleines »
     76  en realite : coupe-circuit de perte journaliere
     19  en realite : doublon (fenetre de dedup)
     10  vraiment  : max open positions
      3  en realite : plafond de risque engage

⇒ Toute lecture par `reason_code` surestimait le plafond de positions **d'un
facteur 10**, et rendait invisibles trois mécanismes distincts. C'est la même
maladie que `close_reason=MANUAL` (215 trades), `pnl=0.0`, `entry_price=0.0` :
**une branche par défaut qui se fait passer pour une mesure.**

⚠️ Le commentaire au-dessus du code disait déjà qu'un audit avait démêlé trois
causes confondues « pendant des mois ». Il en avait démêlé une et laissé
celle-ci — d'où un test plutôt qu'un commentaire.

Cf. [[feedback_detection_par_absence]] · [[feedback_private_reason_codes_silent_drop]]
"""
import pytest

from backend.services.mt5_bridge import _categoriser_refus


@pytest.mark.parametrize("corps,attendu", [
    ('{"blocked":true,"reason":"Max open positions reached: 3 >= 3"}',
     "bridge_max_positions"),
    ('{"blocked":true,"reason":"Daily drawdown reached: loss=130.00 >= limit=8.72"}',
     "bridge_perte_journaliere"),
    ('{"blocked":true,"reason":"Duplicate: sell XAUUSD already open (age 12s)"}',
     "bridge_doublon"),
    ('{"blocked":true,"reason":"Risque engage 7.2 > 6.0 (6% de 300)"}',
     "bridge_plafond_risque"),
])
def test_chaque_garde_fou_du_bridge_a_son_propre_code(corps, attendu):
    """Quatre mécanismes distincts, quatre codes. Les confondre, c'est perdre
    la seule information qui permettrait d'agir sur l'un d'eux."""
    assert _categoriser_refus(429, corps) == attendu


def test_un_429_INCONNU_n_est_pas_range_dans_max_positions():
    """⛔ Le cœur du défaut. Un refus qu'on ne sait pas lire doit se déclarer
    indéterminé, jamais emprunter l'étiquette du voisin — sinon il gonfle un
    compteur qu'on croira mesuré."""
    code = _categoriser_refus(429, '{"blocked":true,"reason":"quelque chose de neuf"}')

    assert code != "bridge_max_positions"
    assert code == "bridge_refus_indetermine"


def test_un_corps_vide_ne_conclut_rien_non_plus():
    assert _categoriser_refus(429, "") == "bridge_refus_indetermine"


def test_les_autres_codes_http_ne_changent_pas():
    """Le démêlage du 429 ne doit rien casser des branches déjà justes."""
    assert _categoriser_refus(422, "") == "bridge_risque_incoherent"
    assert _categoriser_refus(500, "risque_realise trop grand") == "bridge_risque_incoherent"
    assert _categoriser_refus(400, "retcode 10016 INVALID_STOPS") == "bridge_invalid_stops"
    assert _categoriser_refus(503, "boom") == "bridge_error"


def test_le_texte_prime_sur_le_code_http():
    """Un bridge qui renverrait « Max open positions » avec un autre statut doit
    quand même être compris : c'est le message qui porte la cause, le statut
    n'est qu'un transport."""
    assert _categoriser_refus(400, '{"reason":"Max open positions reached: 3 >= 3"}') \
        == "bridge_max_positions"


def test_tous_les_codes_produits_ont_un_libelle():
    """Un code sans libellé s'affiche brut dans la viz — et un code inconnu du
    registre passe inaperçu jusqu'à ce que quelqu'un le lise par hasard."""
    from backend.services.rejection_service import REASON_LABELS_FR

    produits = {
        _categoriser_refus(429, c) for c in (
            '{"reason":"Max open positions reached: 3 >= 3"}',
            '{"reason":"Daily drawdown reached: loss=1"}',
            '{"reason":"Duplicate: sell XAUUSD already open"}',
            '{"reason":"Risque engage 7 > 6"}',
            '{"reason":"inconnu"}')
    }
    manquants = produits - set(REASON_LABELS_FR)
    assert not manquants, f"codes sans libellé : {manquants}"
