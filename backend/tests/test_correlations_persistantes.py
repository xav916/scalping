"""Une mesure régénérée doit SURVIVRE au déploiement et être RELUE.

⛔ **Ce qui rendait le cron décoratif** (constaté le 2026-09-09, avant de le
poser). Deux obstacles se cumulaient :

1. `_charger_fichier` lisait `os.path.dirname(__file__)` — **dans l'image**.
   Un fichier régénéré par un cron y aurait été effacé au premier
   `docker build`, sans que rien ne le dise.
2. `CORRELATIONS_MESUREES` était chargé **une seule fois, à l'import**. Même
   écrit au bon endroit, un fichier frais n'aurait pas été relu avant un
   redémarrage.

⇒ Un cron ajouté seul aurait produit une mesure **morte** : écrite, jamais lue,
puis effacée. C'est le mode de défaillance déjà payé par ce dépôt — *les crons
lisent `/opt`, pas le clone*, et *un correctif non déployé est un correctif
mort*.

Le remède est celui que `reglage_or.fermetures` applique déjà : **fichier dans
le volume persistant, relu à chaud avec un cache court**. Une décision qui
exigerait un redéploiement pour s'appliquer ne s'appliquerait pas.

⚠️ Le repli sur l'instantané versionné est CONSERVÉ : il couvre le premier
démarrage, un volume vide, et tout environnement sans cron. Retirer une
protection existante pour en poser une neuve n'est pas un progrès.
"""
import json

import pytest

from backend.services import correlation_guard as cg


def _ecrire(chemin, couples):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps({"couples": couples}), encoding="utf-8")


COUPLE_INSTANTANE = [{"a": "XAU/USD", "b": "AUD/USD", "r": 0.607, "n": 1018}]
COUPLE_FRAIS = [{"a": "XAU/USD", "b": "AUD/USD", "r": 0.412, "n": 2000}]


def test_le_fichier_PERSISTANT_prime_sur_l_instantane(tmp_path, monkeypatch):
    """⛔ Le cœur : sans cela, le cron écrirait dans le vide."""
    _ecrire(tmp_path / "data" / "correlations_forex_1h.json", COUPLE_FRAIS)
    _ecrire(tmp_path / "src" / "correlations_forex_1h.json", COUPLE_INSTANTANE)
    monkeypatch.setattr(cg, "_DOSSIER_PERSISTANT", str(tmp_path / "data"))
    monkeypatch.setattr(cg, "_DOSSIER_SOURCE", str(tmp_path / "src"))

    table = cg._charger_fichier("correlations_forex_1h.json")
    assert table[("XAU/USD", "AUD/USD")] == (0.412, 2000)


def test_l_instantane_versionne_reste_le_REPLI(tmp_path, monkeypatch):
    """Premier démarrage, volume vide : la protection d'avant doit tenir."""
    _ecrire(tmp_path / "src" / "correlations_forex_1h.json", COUPLE_INSTANTANE)
    monkeypatch.setattr(cg, "_DOSSIER_PERSISTANT", str(tmp_path / "vide"))
    monkeypatch.setattr(cg, "_DOSSIER_SOURCE", str(tmp_path / "src"))

    table = cg._charger_fichier("correlations_forex_1h.json")
    assert table[("XAU/USD", "AUD/USD")] == (0.607, 1018)


def test_aucun_fichier_ne_leve_PAS(tmp_path, monkeypatch):
    """Une table absente ne doit pas empêcher le service de démarrer — et
    `{}` signifie « non mesuré », que `correlation()` traduit en `None`."""
    monkeypatch.setattr(cg, "_DOSSIER_PERSISTANT", str(tmp_path / "a"))
    monkeypatch.setattr(cg, "_DOSSIER_SOURCE", str(tmp_path / "b"))
    assert cg._charger_fichier("correlations_forex_1h.json") == {}


def test_une_mesure_FRAICHE_est_relue_sans_redemarrage(tmp_path, monkeypatch):
    """⛔ Le second obstacle : chargée à l'import, la table restait figée.

    Un cron hebdomadaire aurait alors mis jusqu'à une semaine — ou un
    redéploiement — à produire le moindre effet.
    """
    persistant = tmp_path / "data"
    _ecrire(persistant / "correlations_forex_1h.json", COUPLE_INSTANTANE)
    monkeypatch.setattr(cg, "_DOSSIER_PERSISTANT", str(persistant))
    monkeypatch.setattr(cg, "_DOSSIER_SOURCE", str(tmp_path / "vide"))
    monkeypatch.setattr(cg, "_TTL_MESURE_S", 0.0)  # relecture à chaque appel
    cg._rafraichir_mesures(force=True)
    assert cg.correlation("XAU/USD", "AUD/USD") == 0.607

    _ecrire(persistant / "correlations_forex_1h.json", COUPLE_FRAIS)
    assert cg.correlation("XAU/USD", "AUD/USD") == 0.412


def test_le_rafraichissement_garde_le_MEME_dict(tmp_path, monkeypatch):
    """⚠️ `CORRELATIONS_MESUREES` est référencé ailleurs et dans les tests.
    Le remplacer casserait ces références en silence : on met à jour EN PLACE.
    """
    _ecrire(tmp_path / "data" / "correlations_forex_1h.json", COUPLE_FRAIS)
    monkeypatch.setattr(cg, "_DOSSIER_PERSISTANT", str(tmp_path / "data"))
    monkeypatch.setattr(cg, "_DOSSIER_SOURCE", str(tmp_path / "vide"))

    avant = cg.CORRELATIONS_MESUREES
    cg._rafraichir_mesures(force=True)
    assert cg.CORRELATIONS_MESUREES is avant


def test_un_fichier_ABIME_ne_vide_pas_la_table_en_place(tmp_path, monkeypatch):
    """⛔ Fail-CLOSED sur la protection : un JSON corrompu écrit par un cron
    interrompu ne doit pas effacer les corrélations connues — sinon le garde
    se désarmerait sur une panne d'écriture, en silence."""
    persistant = tmp_path / "data"
    _ecrire(persistant / "correlations_forex_1h.json", COUPLE_INSTANTANE)
    monkeypatch.setattr(cg, "_DOSSIER_PERSISTANT", str(persistant))
    monkeypatch.setattr(cg, "_DOSSIER_SOURCE", str(tmp_path / "vide"))
    cg._rafraichir_mesures(force=True)
    assert cg.CORRELATIONS_MESUREES

    (persistant / "correlations_forex_1h.json").write_text("{ tronqu", encoding="utf-8")
    cg._rafraichir_mesures(force=True)
    assert cg.CORRELATIONS_MESUREES, (
        "un fichier abîmé a vidé la table : le garde s'est désarmé sur une panne"
    )


@pytest.fixture(autouse=True)
def _restaurer():
    """Ce module bidouille une table GLOBALE : on la remet en état, sinon les
    autres tests hériteraient d'un `tmp_path` disparu."""
    yield
    cg._rafraichir_mesures(force=True)
