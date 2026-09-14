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
    # ⚠️ On ancre sur la BOUCLE, pas sur l'import : `chaines_de_la_paire`
    # apparait d'abord dans un `from ... import`, et une fenetre de 1 400
    # caracteres a partir de la ratait le code. Le test echouait alors pour une
    # raison etrangere a ce qu'il mesure.
    i = src.index("for c in vues:")
    bloc = src[i:i + 2000]
    assert "all_trade_setups.append" in bloc, (
        "les chaines detectees ne deviennent pas des setups : rien ne peut "
        "partir, quoi qu'on ecrive dans l'.env")
    assert '"chaine": c.pattern' in bloc


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
    i = src.index("for c in vues:")
    assert '"5min"' in src[i:i + 2000], (
        "l'horizon du setup de chaine doit etre celui reellement mesure")
