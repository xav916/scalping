"""Le laboratoire mesure UN courtier. Il ne doit fermer que chez celui-la.

⛔ **Le defaut, trouve le 2026-09-14.** `_bougies_et_spread` lit les bougies
et le spread d'UNE destination — `admin_live`, IC Markets. Mais la couche
soustractive de `mt5_bridge._patterns_autorises` appliquait ses fermetures par
`(paire, horizon)` **sans aucune portee** : une fermeture decidee sur le
spread IC Markets fermait le meme motif sur **Kraken**, sur Binance, et chez
les comptes Premium.

Ce n'est pas theorique. Mesure du meme jour, chez IC Markets :

    DOT/USD   spread 0,066  ·  amplitude M5 moyenne 0,0028  ->  23,4 x
    LTC/USD   spread 2,08   ·  amplitude M5 moyenne 0,126   ->  16,5 x

Le spread de DOT vaut **23 bougies de 5 min**. Tout motif y perd, toujours, et
le laboratoire allait le refuter — puis fermer ce motif sur Kraken, ou la meme
paire se traite bien plus serre. Un verdict vrai chez l'un, faux chez l'autre.

🔑 **La portee est lue LA OU les donnees sont lues.** `DESTINATION_MESUREE`
sert a la fois a chercher les bougies et a etiqueter la fermeture : les deux ne
peuvent pas diverger sans qu'un test le dise.

⚠️ **Une destination INCONNUE garde la protection.** `dest=None` est le chemin
mono-tenant historique, c'est-a-dire le pont MT5 lui-meme. Ne rien appliquer y
serait un desserrage silencieux — on ne desserre pas une porte par defaut.

Cf. [[project_admission_destination_scope_bug_2026_08_04]] — meme famille :
une decision juste, appliquee a une portee qu'elle n'a jamais couverte.
"""
from __future__ import annotations

import sqlite3

import pytest

from backend.services import laboratoire_or as labo
from backend.services import reglage_or as rg
from backend.tests.test_reglage_or import (_base_neuve, _huit_motifs,  # noqa: F401
                                           _mesure, _nuits)


class _E:
    def __init__(self, v): self.value = v


class _S:
    pair = "XAU/USD"
    horizon = "5min"
    pattern = _E("poc_return_up")


class _D:
    """Une destination, reduite a ce que `_patterns_autorises` lui demande."""
    allowed_patterns = None

    def __init__(self, ident, extras=("poc_return_up", "poc_return_down")):
        self.destination_id = ident
        self.extra_patterns = list(extras)


def _ferme_un_motif():
    """Trois nuits de refus sur `poc_return_up` — la fermeture est decidee."""
    _nuits([_huit_motifs("poc_return_up")] * rg.NUITS_CONSECUTIVES)
    rg.decider(_mesure(_huit_motifs("poc_return_up")))
    rg._cache.clear()


def test_la_portee_est_lue_LA_OU_les_donnees_sont_lues():
    """Anti-derive : l'etiquette et la source doivent etre le meme nom."""
    from backend.services.destinations_registry import DESTINATIONS
    assert rg.DESTINATION_MESUREE in DESTINATIONS, (
        f"{rg.DESTINATION_MESUREE} n'est pas une destination declaree")
    import inspect
    for fonction in (rg._bougies_et_spread, rg.instruments_servis):
        src = inspect.getsource(fonction)
        assert "DESTINATION_MESUREE" in src, (
            f"{fonction.__name__} designe sa source en dur : l'etiquette de la "
            f"fermeture et la source des bougies pourraient diverger")


def test_la_fermeture_porte_le_nom_de_la_destination_mesuree():
    _ferme_un_motif()
    with sqlite3.connect(rg._db()) as c:
        lignes = c.execute(
            "SELECT destination, motif FROM labo_or_fermetures").fetchall()
    assert lignes == [(rg.DESTINATION_MESUREE, "poc_return_up")]


def test_une_fermeture_ne_SORT_PAS_de_la_destination_mesuree():
    _ferme_un_motif()
    chez_soi = rg.fermetures(destination=rg.DESTINATION_MESUREE, frais=True)
    ailleurs = rg.fermetures(destination="admin_kraken", frais=True)
    assert ("5min", "poc_return_up") in chez_soi
    assert ailleurs == set(), (
        "une fermeture mesuree chez un courtier s'applique chez un autre")


def test_en_PRODUCTION_le_motif_se_ferme_ici_et_reste_ouvert_la_bas():
    """🔑 Le test qui compte : par le chemin reel de la decision de push."""
    from backend.services import mt5_bridge as mb
    ici, ailleurs = _D(rg.DESTINATION_MESUREE), _D("admin_kraken")
    assert "poc_return_up" in mb._patterns_autorises(_S(), ici)
    _ferme_un_motif()
    assert "poc_return_up" not in mb._patterns_autorises(_S(), ici)
    assert "poc_return_up" in mb._patterns_autorises(_S(), ailleurs), (
        "Kraken perd un motif sur un verdict rendu chez IC Markets")
    # l'autre jambe reste ouverte des deux cotes
    assert "poc_return_down" in mb._patterns_autorises(_S(), ici)


def test_une_destination_INCONNUE_garde_la_protection():
    """⚠️ `dest=None` = chemin mono-tenant historique, donc le pont MT5.

    Ne rien appliquer y serait un desserrage silencieux."""
    from backend.services import mt5_bridge as mb
    _ferme_un_motif()
    assert "poc_return_up" not in mb._patterns_autorises(_S(), None)


def test_les_anciennes_lignes_sans_destination_reviennent_a_la_mesuree():
    """La migration ne doit RIEN perdre : une fermeture existante reste une
    fermeture, attribuee au courtier que le laboratoire mesurait deja."""
    with sqlite3.connect(rg._db()) as c:
        c.execute("""CREATE TABLE labo_or_fermetures (
            pair TEXT NOT NULL, horizon TEXT NOT NULL, motif TEXT NOT NULL,
            sens TEXT, ferme_le TEXT NOT NULL, preuve TEXT,
            PRIMARY KEY (pair, horizon, motif))""")
        c.execute("INSERT INTO labo_or_fermetures VALUES "
                  "('XAU/USD','5min','poc_return_up','buy','2026-09-10 03:40:00','{}')")
    trouve = rg.fermetures(destination=rg.DESTINATION_MESUREE, frais=True)
    assert ("5min", "poc_return_up") in trouve
    assert rg.fermetures(destination="admin_kraken", frais=True) == set()


def test_le_cache_ne_melange_pas_deux_destinations():
    """⛔ Un cache indexe sur la seule paire rendrait le resultat du dernier
    appelant a tout le monde — la portee serait juste en base et fausse en vol."""
    _ferme_un_motif()
    rg.fermetures(destination="admin_kraken")          # remplit le cache
    assert ("5min", "poc_return_up") in rg.fermetures(
        destination=rg.DESTINATION_MESUREE)


def test_le_mecanisme_ne_sait_toujours_que_RESSERRER():
    """Garde-fou du garde-fou : la portee ne doit pas devenir une porte qui
    OUVRE. Une destination sans fermeture recoit la liste inchangee."""
    from backend.services import mt5_bridge as mb
    _ferme_un_motif()
    avant = mb._patterns_autorises(_S(), _D("admin_kraken"))
    assert avant >= {"poc_return_up", "poc_return_down"}
