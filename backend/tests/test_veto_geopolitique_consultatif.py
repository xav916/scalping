"""Mode consultatif du veto géopolitique (2026-08-08).

Constat qui l'a motivé : la règle `gdelt_stress` est documentée pour les
**indices européens**, son seuil a été assoupli de `high` à `{high, elevated}`
parce qu'elle « ne matchait jamais », puis son périmètre étendu à BTC/ETH. Les
deux seules fois où elle s'est déclenchée en 30 jours — **2 refus sur
72 081**, soit 0,00 % — elle a bloqué **100 % du flux crypto journalier** : les
deux seuls setups exécutables du 2026-08-07.

⚠️ Ce que ces tests verrouillent :
  - une paire non listée reste bloquée, sinon on aurait désarmé le veto au
    lieu de le rendre consultatif ;
  - la règle elle-même n'est PAS restreinte : le shadow appelle la même
    `geopolitical_veto.apply` pour son verdict contrefactuel, et la sortir du
    périmètre détruirait la donnée qui permettra un jour de la juger ;
  - la liste est vide par défaut.

Les tests appellent `veto_geopolitique_consultatif` — la fonction livrée —
plutôt que de recopier sa condition : un test qui réimplémente la logique
teste sa propre copie. Cf. [[feedback_source_inspection_tests_weak]].
"""
import importlib

import pytest

from backend.services import analysis_engine


@pytest.fixture
def liste(monkeypatch):
    """Règle la liste consultative telle que la lit la fonction livrée."""
    def _set(pairs):
        monkeypatch.setattr(
            analysis_engine, "GEOPOLITICAL_VETO_ADVISORY_PAIRS", frozenset(pairs)
        )
    return _set


# ── Défauts ───────────────────────────────────────────────────────────

def test_liste_vide_par_defaut(monkeypatch):
    """Sans réglage, aucun comportement ne change."""
    monkeypatch.delenv("GEOPOLITICAL_VETO_ADVISORY_PAIRS", raising=False)
    import config.settings as st
    importlib.reload(st)
    assert st.GEOPOLITICAL_VETO_ADVISORY_PAIRS == frozenset()


def test_la_liste_est_normalisee(monkeypatch):
    monkeypatch.setenv("GEOPOLITICAL_VETO_ADVISORY_PAIRS", " btc/usd , eth/usd , ")
    import config.settings as st
    importlib.reload(st)
    assert st.GEOPOLITICAL_VETO_ADVISORY_PAIRS == frozenset({"BTC/USD", "ETH/USD"})
    monkeypatch.delenv("GEOPOLITICAL_VETO_ADVISORY_PAIRS", raising=False)
    importlib.reload(st)


# ── Le cœur de la décision ────────────────────────────────────────────

def test_une_paire_listee_est_consultative(liste):
    liste({"BTC/USD", "ETH/USD"})
    assert analysis_engine.veto_geopolitique_consultatif("BTC/USD") is True
    assert analysis_engine.veto_geopolitique_consultatif("ETH/USD") is True


def test_une_paire_NON_listee_reste_bloquante(liste):
    """Sinon on n'aurait pas rendu le veto consultatif, on l'aurait désarmé."""
    liste({"BTC/USD"})
    for autre in ("SPX", "DAX", "EUR/JPY", "XAU/USD"):
        assert analysis_engine.veto_geopolitique_consultatif(autre) is False, (
            f"{autre} ne doit pas échapper au veto"
        )


def test_liste_vide_ne_dispense_personne(liste):
    liste(set())
    assert analysis_engine.veto_geopolitique_consultatif("BTC/USD") is False


def test_casse_indifferente(liste):
    liste({"BTC/USD"})
    assert analysis_engine.veto_geopolitique_consultatif("btc/usd") is True


def test_paire_vide_ne_plante_pas(liste):
    liste({"BTC/USD"})
    assert analysis_engine.veto_geopolitique_consultatif("") is False
    assert analysis_engine.veto_geopolitique_consultatif(None) is False


# ── La règle n'est PAS touchée : le contrefactuel survit ──────────────

def test_la_regle_continue_de_se_prononcer_sur_la_crypto():
    """Le shadow appelle `apply` pour son verdict contrefactuel. Si BTC/ETH
    sortaient du périmètre de la règle, on perdrait la seule donnée capable de
    dire un jour si ce veto sert à quelque chose."""
    from backend.services.geopolitical_veto import _INDICES_FOR_GDELT_STRESS

    for pair in ("BTC/USD", "ETH/USD"):
        assert pair in _INDICES_FOR_GDELT_STRESS, (
            f"{pair} a été retiré du périmètre de la règle — le verdict "
            f"contrefactuel du shadow serait perdu. Le mode consultatif doit "
            f"filtrer à la CONSOMMATION, jamais dans la règle."
        )
