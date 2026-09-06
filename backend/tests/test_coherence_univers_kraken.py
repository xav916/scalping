"""Les trois listes de l'univers Kraken doivent s'accorder (2026-09-06).

Deux défauts dans la même journée, même cause : `SHADOW_CONFIG` (les signaux),
`WATCHED_PAIRS_ADMIN_KRAKEN` (le routage) et la whitelist du bridge
(l'exécution) sont éditées à la main et rien ne comparait.

⚠️ Les deux sens de divergence n'ont PAS la même gravité :
  - routable sans être exécutable ⇒ du travail jeté à chaque signal → ALERTE ;
  - exécutable sans être routable ⇒ une autorisation qui dort. C'est l'état
    normal après un retrait → rapporté, jamais alerté. Une alerte qui se
    déclenche sur du normal est une alerte qu'on apprend à ignorer.
"""
from __future__ import annotations

import pytest

from backend.services import coherence_univers_kraken as c


@pytest.fixture
def monde(monkeypatch):
    """Portée, configs et whitelist entièrement contrôlées."""
    def poser(portee, configs, whitelist):
        from config import settings
        from backend.services import shadow_v2_core_long as sh
        monkeypatch.setattr(settings, "WATCHED_PAIRS_PAR_DESTINATION",
                            {"admin_kraken": frozenset(portee)})
        monkeypatch.setattr(sh, "SHADOW_CONFIG", {p: {} for p in configs})
        monkeypatch.setattr(c, "_whitelist_du_bridge", lambda: whitelist)
    return poser


def test_tout_concorde_aucune_alerte(monde):
    monde({"BTC/USD", "ETH/USD"}, {"BTC/USD", "ETH/USD"},
          {"PF_XBTUSD", "PF_ETHUSD"})
    r = c.verifier()
    assert r["alerte"] is False
    assert r["sans_config"] == [] and r["sans_whitelist"] == []


def test_routable_SANS_config_alerte(monde):
    """⛔ Le defaut du 06/09 au soir : six paires ouvertes et muettes."""
    monde({"BTC/USD", "ZEC/USD"}, {"BTC/USD"}, {"PF_XBTUSD", "PF_ZECUSD"})
    r = c.verifier()
    assert r["alerte"] is True
    assert r["sans_config"] == ["ZEC/USD"]


def test_routable_SANS_whitelist_alerte(monde):
    """Ses signaux partiraient pour se faire refuser a l'execution."""
    monde({"BTC/USD", "ZEC/USD"}, {"BTC/USD", "ZEC/USD"}, {"PF_XBTUSD"})
    r = c.verifier()
    assert r["alerte"] is True
    assert any("ZEC/USD" in x for x in r["sans_whitelist"])


def test_whitelist_EN_TROP_ne_declenche_RIEN(monde):
    """⚠️ L'etat normal apres un retrait de portee (ETHFI le 06/09). Alerter
    la-dessus apprendrait a ignorer l'alerte."""
    monde({"BTC/USD"}, {"BTC/USD"}, {"PF_XBTUSD", "PF_ETHFIUSD", "PF_XAUUSD"})
    r = c.verifier()
    assert r["alerte"] is False
    assert r["whitelist_en_trop"] == ["PF_ETHFIUSD", "PF_XAUUSD"]


def test_bridge_INJOIGNABLE_ne_conclut_pas_a_une_divergence(monde):
    """⛔ « Je n'ai pas pu lire » et « rien n'est autorise » menent a des
    conclusions opposees. La whitelist vide en repli serait une fausse alerte
    sur TOUTES les paires."""
    monde({"BTC/USD"}, {"BTC/USD"}, None)
    r = c.verifier()
    assert r["lisible"] is False
    assert r["sans_whitelist"] == []
    assert r["alerte"] is False, "un bridge muet n'est pas une incoherence"


def test_bridge_injoignable_MAIS_config_manquante_alerte_quand_meme(monde):
    """La partie lisible reste jugee : ne pas savoir pour l'une n'excuse pas
    de taire l'autre."""
    monde({"BTC/USD", "ZEC/USD"}, {"BTC/USD"}, None)
    r = c.verifier()
    assert r["alerte"] is True
    assert r["sans_config"] == ["ZEC/USD"]


def test_symbole_INDERIVABLE_compte_comme_non_executable(monde, monkeypatch):
    from backend.services import kraken_funding_scoring as kfs
    monkeypatch.setattr(kfs, "symbole_pour",
                        lambda p: None if p == "ZZZ/USD" else "PF_XBTUSD")
    monde({"BTC/USD", "ZZZ/USD"}, {"BTC/USD", "ZZZ/USD"}, {"PF_XBTUSD"})
    r = c.verifier()
    assert r["alerte"] is True
    assert any("indérivable" in x for x in r["sans_whitelist"])


# ── Le message ───────────────────────────────────────────────────────

def test_le_message_NOMME_les_paires_en_cause(monde):
    monde({"BTC/USD", "ZEC/USD"}, {"BTC/USD"}, {"PF_XBTUSD", "PF_ZECUSD"})
    titre, corps = c.texte(c.verifier())
    assert "INCOHÉRENT" in titre
    assert "ZEC/USD" in corps, "un rapport qui ne nomme rien n'est pas actionnable"


def test_le_message_sain_dit_la_verification_PARTIELLE(monde):
    """Un « tout va bien » qui cache qu'on n'a pas tout regarde est pire que
    rien."""
    monde({"BTC/USD"}, {"BTC/USD"}, None)
    titre, corps = c.texte(c.verifier())
    assert "cohérent" in titre
    assert "partielle" in corps
