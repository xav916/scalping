"""R-28 : deux canaux qui relaient le même appel ne doivent pas doubler la position.

L'unicité `(source, external_id)` fait bien ce pour quoi elle a été écrite —
empêcher UN fournisseur de rejouer sa file. Elle ne voit pas DEUX fournisseurs
émettant le même appel. Or les canaux de signaux se recopient entre eux : c'est
la norme du milieu, et c'est ce que ce fichier interdit.

⛔ L'écart se mesure en **R**, jamais en prix ni en pourcentage. Ce dépôt a déjà
payé trois fois le défaut inverse (R-16, R-19, `TRADING_CAPITAL`) : une constante
dont le sens change d'un instrument à l'autre. Plusieurs tests ici vérifient
précisément cette propriété.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest


def _charge(**kw):
    base = {"source": "orvion", "external_id": "o-1", "pair": "XAU/USD",
            "direction": "sell", "entry_price": 3900.0, "stop_loss": 3920.0,
            "confidence": 80.0}
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def _base_isolee(tmp_path, monkeypatch):
    from backend.services import external_signals, trade_log_service
    monkeypatch.setattr(trade_log_service, "_DB_PATH", tmp_path / "trades.db")
    monkeypatch.setattr(external_signals, "_SCHEMA_ENSURED", False)
    yield


def _poser(charge):
    """Enregistre un signal comme s'il avait été reçu, sans passer par les portes."""
    from backend.services import external_signals as es
    es._ensure_schema()
    assert es.enregistrer(charge) is True


def _verdict(charge):
    from backend.services import external_signals as es
    return es.doublon_semantique(charge)


# ── Ce que le contrôle doit ATTRAPER ──────────────────────────────────────

def test_deux_canaux_relayant_le_meme_appel():
    """Le cas de R-28, mot pour mot : même paire, même sens, même entrée,
    deux sources et deux identifiants distincts."""
    _poser(_charge(source="orvion", external_id="o-1"))
    doublon, detail = _verdict(_charge(source="apollo", external_id="a-99"))
    assert doublon is True
    assert "orvion" in detail


def test_un_canal_qui_republie_son_propre_appel():
    """⚠️ Même source, nouvel identifiant : l'unicité `(source, external_id)`
    laisse passer, le contrôle sémantique non."""
    _poser(_charge(external_id="o-1"))
    doublon, _ = _verdict(_charge(external_id="o-2"))
    assert doublon is True


def test_une_entree_legerement_differente_reste_le_meme_trade():
    """3900 contre 3903, sur un risque de 20 : 0,15 R. C'est le même trade."""
    _poser(_charge(source="orvion", external_id="o-1", entry_price=3900.0))
    doublon, _ = _verdict(_charge(source="apollo", external_id="a-1",
                                  entry_price=3903.0))
    assert doublon is True


# ── Ce qu'il doit LAISSER PASSER ──────────────────────────────────────────

@pytest.mark.parametrize("modif", [
    {"direction": "buy"},
    {"pair": "XAG/USD"},
    {"entry_price": 3890.0},   # 10 points d'écart sur 20 de risque = 0,5 R
])
def test_un_trade_reellement_different_passe(modif):
    _poser(_charge(source="orvion", external_id="o-1"))
    doublon, _ = _verdict(_charge(source="apollo", external_id="a-1", **modif))
    assert doublon is False


def test_hors_de_la_fenetre_ce_n_est_plus_un_doublon(monkeypatch):
    """⚠️ Un même appel réémis bien plus tard EST un autre trade."""
    from backend.services import external_signals as es
    _poser(_charge(source="orvion", external_id="o-1"))
    monkeypatch.setattr(es, "_FENETRE_DOUBLON_MIN", 0.0)
    doublon, _ = _verdict(_charge(source="apollo", external_id="a-1"))
    assert doublon is False


# ── L'unité : R, et rien d'autre ──────────────────────────────────────────

@pytest.mark.parametrize("paire,entree,stop,proche,loin", [
    # or : risque 20, tolérance 5     | forex : risque 0,0020, tolérance 0,0005
    ("XAU/USD", 3900.0, 3920.0, 3903.0, 3890.0),
    ("EUR/USD", 1.0800, 1.0820, 1.08030, 1.07900),
])
def test_le_seuil_se_comporte_pareil_sur_des_instruments_a_50x_d_ecart(
        paire, entree, stop, proche, loin):
    """⛔ LE test qui justifie le choix de l'unité.

    L'or cote 3 900, l'euro 1,08 — un facteur 3 600. Un seuil en prix absolu
    n'aurait aucun sens, et un seuil en % du prix aurait donné 3,90 sur l'or
    contre 0,001 sur l'euro, sans rapport avec le risque de chaque trade. En R,
    les deux instruments se comportent identiquement.
    """
    _poser(_charge(source="orvion", external_id="o-1", pair=paire,
                   entry_price=entree, stop_loss=stop))
    proche_doublon, _ = _verdict(_charge(source="apollo", external_id="a-1",
                                         pair=paire, entry_price=proche,
                                         stop_loss=stop))
    loin_doublon, _ = _verdict(_charge(source="apollo", external_id="a-2",
                                       pair=paire, entry_price=loin,
                                       stop_loss=stop))
    assert proche_doublon is True, "un écart de 0,15 R est le même trade"
    assert loin_doublon is False, "un écart de 0,5 R est un autre trade"


# ── Sur le doute, on refuse ───────────────────────────────────────────────

@pytest.mark.parametrize("modif,attendu", [
    ({"entry_price": None}, "illisibles"),
    ({"entry_price": "abc"}, "illisibles"),
    ({"stop_loss": 3900.0}, "risque nul"),     # stop == entrée
])
def test_une_charge_inexploitable_est_refusee(modif, attendu):
    """⚠️ Ne pas pouvoir vérifier n'autorise pas à passer — même doctrine que
    `enregistrer`, qui refuse déjà sur doute plutôt que risquer un doublon."""
    doublon, detail = _verdict(_charge(**modif))
    assert doublon is True and attendu in detail


def test_un_registre_illisible_refuse_plutot_que_de_laisser_passer(monkeypatch):
    from backend.services import external_signals as es
    monkeypatch.setattr(es, "_db_path", lambda: "/interdit/nulle-part.db")
    doublon, detail = _verdict(_charge())
    assert doublon is True and "impossible" in detail


# ── L'ordre des deux contrôles n'est pas libre ────────────────────────────

def test_le_second_canal_est_REFUSE_de_bout_en_bout(fournisseurs_ok):
    """⛔ LE test qui compte, et qui manquait à la première version de ce fichier.

    Les autres appellent `doublon_semantique` directement : ils éprouvent la
    fonction, pas son branchement. Or une déduplication parfaite qui n'est jamais
    appelée ne protège rien — vérifié en neutralisant l'appel dans `ingerer`, ce
    qui laissait les treize autres tests au vert.

    Celui-ci passe par `ingerer`, donc par le chemin réel.
    """
    from backend.services import external_signals as es
    premier = asyncio.run(es.ingerer(
        _charge(source="orvion", external_id="o-1"), "jeton"))
    assert premier["accepte"] is True, premier

    second = asyncio.run(es.ingerer(
        _charge(source="apollo", external_id="a-9"), "jeton_apollo"))
    assert second["accepte"] is False, "R-28 : le second canal doit être refusé"
    assert second["cause"] == es.CAUSE_DOUBLON
    assert "orvion" in second["motif"]


def test_le_signal_entrant_ne_se_voit_pas_lui_meme_comme_doublon(fournisseurs_ok):
    """⛔ Le contrôle sémantique doit passer AVANT l'enregistrement. Après, le
    signal serait déjà en base et se refuserait lui-même."""
    from backend.services import external_signals as es
    verdict = asyncio.run(es.ingerer(_charge(), "jeton"))
    assert verdict["accepte"] is True, verdict


@pytest.fixture
def fournisseurs_ok(monkeypatch):
    import config.settings as st
    monkeypatch.setattr(st, "EXTERNAL_SIGNAL_TOKENS",
                        {"orvion": "jeton", "apollo": "jeton_apollo"},
                        raising=False)
    from backend.services import mt5_bridge
    async def _rien(_setup):
        return None
    monkeypatch.setattr(mt5_bridge, "send_setup", _rien)
