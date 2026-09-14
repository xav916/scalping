"""Le chemin complet : une chaine armee produit-elle un ordre ?

⛔ **Le defaut evite le 2026-09-15.** Le registre `CHAINES_AUTORISEES` a ete
livre avant le cablage. Ecrire une ligne dans l'`.env` a ce moment-la n'aurait
RIEN arme : le scan se contentait de logger les chaines, et le pont ne
consultait pas le registre. On aurait cru avoir arme une methode, et le silence
qui aurait suivi aurait ressemble a « la chaine ne se declenche pas ».

Ces tests tiennent les deux bouts du fil.
"""
from __future__ import annotations

import pytest

from backend.services import chaines_autorisees as ca
from backend.services import mt5_bridge as mb


@pytest.fixture(autouse=True)
def _registre_neuf():
    ca._cache = None
    yield
    ca._cache = None


class _E:
    def __init__(self, v): self.value = v


class _S:
    """Un setup de chaine : il porte le motif DECLENCHEUR et le nom de la chaine."""
    pair = "XAU/USD"

    def __init__(self, motif, chaine, horizon="4h"):
        self.pattern = _E(motif)
        self.chaine = chaine
        self.horizon = horizon


class _D:
    allowed_patterns = None
    extra_patterns = None

    def __init__(self, ident): self.destination_id = ident


VRAIE = "chaine:sweep_sur_order_block_haussier"


def test_sans_registre_le_motif_du_declencheur_reste_REFUSE(monkeypatch):
    """L'etat actuel : `order_block_up` n'est dans aucune liste blanche."""
    monkeypatch.delenv("CHAINES_AUTORISEES", raising=False)
    ca._cache = None
    autorises = mb._patterns_autorises(_S("order_block_up", VRAIE), _D("admin_live"))
    assert "order_block_up" not in autorises


def test_une_chaine_ARMEE_ouvre_le_motif_de_SON_declencheur(monkeypatch):
    """🔑 Le fil complet. La chaine n'ouvre QUE le motif qui la declenche, et
    seulement sur la destination et l'horizon declares."""
    monkeypatch.setenv("CHAINES_AUTORISEES",
                       '{"admin_live": {"4h": ["%s"]}}' % VRAIE)
    ca._cache = None
    autorises = mb._patterns_autorises(_S("order_block_up", VRAIE), _D("admin_live"))
    assert "order_block_up" in autorises


def test_elle_n_ouvre_PAS_les_autres_motifs(monkeypatch):
    """⛔ Une chaine armee ne doit pas elargir la porte pour tout le monde."""
    monkeypatch.setenv("CHAINES_AUTORISEES",
                       '{"admin_live": {"4h": ["%s"]}}' % VRAIE)
    ca._cache = None
    autorises = mb._patterns_autorises(_S("order_block_up", VRAIE), _D("admin_live"))
    # un setup SANS chaine, meme motif, meme destination : toujours refuse
    sans = mb._patterns_autorises(_S("order_block_up", None), _D("admin_live"))
    assert "order_block_up" in autorises
    assert "order_block_up" not in sans


def test_elle_n_ouvre_PAS_une_autre_destination(monkeypatch):
    monkeypatch.setenv("CHAINES_AUTORISEES",
                       '{"admin_legacy": {"4h": ["%s"]}}' % VRAIE)
    ca._cache = None
    assert "order_block_up" in mb._patterns_autorises(
        _S("order_block_up", VRAIE), _D("admin_legacy"))
    assert "order_block_up" not in mb._patterns_autorises(
        _S("order_block_up", VRAIE), _D("admin_live"))


def test_elle_n_ouvre_PAS_un_autre_horizon(monkeypatch):
    monkeypatch.setenv("CHAINES_AUTORISEES",
                       '{"admin_live": {"4h": ["%s"]}}' % VRAIE)
    ca._cache = None
    assert "order_block_up" not in mb._patterns_autorises(
        _S("order_block_up", VRAIE, horizon="5min"), _D("admin_live"))


def test_la_couche_du_LABORATOIRE_reste_APRES_et_peut_refermer(monkeypatch):
    """⛔ L'ordre compte : ce que le labo ferme ne doit pas etre rouvert par une
    chaine. Sinon armer une chaine contournerait un verdict."""
    import inspect
    src = inspect.getsource(mb._patterns_autorises)
    i_chaine = src.index("chaines_autorisees")
    i_labo = src.index("from backend.services.reglage_or import fermetures")
    assert i_chaine < i_labo, (
        "la couche soustractive du laboratoire doit s'appliquer APRES "
        "l'ouverture par chaine")


def test_le_SETUP_porte_le_nom_de_la_chaine():
    """Le modele doit pouvoir transporter l'identite de la chaine jusqu'au
    pont — sinon la porte ne saurait jamais qu'une chaine est en cause."""
    from backend.models.schemas import TradeSetup
    assert "chaine" in TradeSetup.model_fields


def test_une_chaine_DETECTEE_devient_un_SETUP_qui_porte_son_nom():
    """🔑 Le dernier maillon du fil : sans ce pas, le scan ne fait que logger
    et l'`.env` n'arme rien du tout."""
    import inspect
    from backend.services import scheduler
    src = inspect.getsource(scheduler)
    # ⚠️ ANCRAGE SUR DES MARQUEURS, PAS SUR UNE FENETRE DE CARACTERES. Mes
    # deux premieres versions decoupaient N caracteres apres un point de
    # depart : elles ont casse deux fois de suite parce que le bloc grossit a
    # chaque commentaire ajoute. Un test qui echoue quand on documente le code
    # ne mesure pas ce qu'il pretend.
    assert 'update={"chaine": c.pattern' in src, (
        "aucun setup ne porte le nom de la chaine")
    assert "all_trade_setups.append(_sc)" in src, (
        "les chaines detectees ne deviennent pas des setups : rien ne peut "
        "partir, quoi qu'on ecrive dans l'.env")


def test_le_setup_de_chaine_porte_l_horizon_MESURE():
    """⛔ Le laboratoire mesure les echelles x1, x3, x6, x12 — soit 5 min a
    1 h. Il n'y a AUCUNE echelle 4 h : une chaine 4 h ne serait mesuree par
    rien. L'horizon pose en production doit etre un horizon mesure."""
    from backend.services import laboratoire_or as labo
    assert 1 in labo.ECHELLES
    assert 48 not in labo.ECHELLES, (
        "une echelle 4 h est apparue : la declarer d'abord dans le carnet")
    import inspect
    from backend.services import scheduler
    src = inspect.getsource(scheduler)
    assert '"horizon": "5min"' in src, (
        "l'horizon du setup de chaine doit etre celui reellement mesure")


def test_le_setup_de_chaine_est_SCORE_comme_les_autres():
    """⛔ Mesure du 2026-09-15 : sans enrichissement, un setup de chaine arrive
    avec `confidence_score = 0` et 0 sur 40 passe le seuil du pont (66). On
    aurait arme du THEATRE — rien ne serait jamais parti, et le silence aurait
    ressemble a « la chaine ne se declenche pas ».

    🔑 Une chaine ouvre la porte du MOTIF. Elle n'achete aucun passe-droit sur
    le score, le verdict ou les autres refus.
    """
    import inspect
    from backend.services import scheduler
    src = inspect.getsource(scheduler)
    # ⚠️ On COMPACTE les espaces au lieu d'ecrire un saut de ligne dans le
    # motif recherche : le code est indente, et un test qui casse a la
    # premiere reindentation ne mesure pas ce qu'il pretend.
    compact = " ".join(src.split())
    assert "enrich_trade_setup( _sc," in compact, (
        "le setup de chaine n'est pas score : il sera filtre en silence")
    assert "compute_verdict( _sc," in compact, (
        "le setup de chaine n'a pas de verdict")


def test_un_setup_de_chaine_NON_ARMEE_est_refuse_meme_si_son_motif_est_autorise(monkeypatch):
    """⛔ LE DANGER TROUVE EN PRODUCTION LE 2026-09-15, une heure apres avoir
    arme.

    Huit chaines sur dix-huit ont un declencheur DEJA present dans la liste
    blanche de l'or 5 min (`engulfing_bullish`, `breakout_up`,
    `range_bounce_up`...). Leur setup n'avait donc pas besoin du registre : il
    passait comme un motif ordinaire. Et le chemin normal produit DEJA ce
    motif, depuis Twelve Data, avec un prix legerement different — donc la
    deduplication par prix d'entree ne les rapproche pas.

    Resultat : **deux ordres pour un seul signal**, sur de l'argent reel.

    🔑 Un setup de chaine EST un setup de chaine. Si sa chaine n'est pas armee,
    il ne trade pas — peu importe que son motif declencheur soit autorise par
    ailleurs.
    """
    monkeypatch.setenv("CHAINES_AUTORISEES",
                       '{"admin_live": {"5min": ["%s"]}}' % VRAIE)
    ca._cache = None
    # ⚠️ La liste blanche vient de l'`.env` : elle est VIDE en test. On la pose
    # donc explicitement, comme en production sur l'or 5 min.
    monkeypatch.setattr(mb, "MT5_BRIDGE_ALLOWED_PATTERNS",
                        frozenset({"engulfing_bullish"}))
    ordinaire = mb._patterns_autorises(_S("engulfing_bullish", None, "5min"),
                                       _D("admin_live"))
    assert "engulfing_bullish" in ordinaire, (
        "prerequis du test : le motif doit etre autorise par ailleurs")

    # ... mais un setup issu d'une chaine NON armee ne doit RIEN pouvoir pousser
    de_chaine = mb._patterns_autorises(
        _S("engulfing_bullish", "chaine:avalement_en_discount_haussier", "5min"),
        _D("admin_live"))
    assert de_chaine == set(), (
        "un setup de chaine non armee passe par la porte des motifs simples : "
        "deux ordres partiraient pour un seul signal")
