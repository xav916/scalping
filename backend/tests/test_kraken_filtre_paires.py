"""Filtre de paires côté BACKEND pour `admin_kraken` (2026-10-30).

Le trou mesuré le 29/10 : `admin_kraken` tient de l'argent réel, est
joignable, porte 22 buckets `AUTO_EXEC` — et **aucun filtre de paires ne
s'applique à lui**. Ce n'est pas un oubli de configuration : la liste
blanche de `mt5_bridge` est conditionnée `bridge_type == "mt5"`
(`mt5_bridge.py:1097-1117`), donc la porte **saute entièrement** une
destination Kraken. Le compte IC Markets (`admin_live`), lui, est filtré à
une seule paire depuis toujours.

⛔ **Opt-in STRICT, décidé le 30/10** : la liste est **vide par défaut**, donc
rien ne passe tant qu'une paire n'y est pas inscrite explicitement. C'est
l'inverse de la sémantique MT5, où une liste vide signifie « pas de
filtrage » (`if LIVE_WHITELIST_PAIRS and ...`). La même absence veut donc
dire « protection maximale » ici et « aucune protection » là-bas, et c'est
voulu.

🔑 La propriété qui compte n'est pas le refus, c'est que le refus arrive
**AVANT le réseau** : un ordre refusé ne doit pas avoir été envoyé, et ne
doit laisser aucune réservation de push derrière lui.
"""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace as NS

import httpx
import pytest

from backend.services import kraken_bridge_client as kbc
from backend.services import mt5_pushes_service


@pytest.fixture
def base(tmp_path, monkeypatch):
    db = tmp_path / "trades.db"
    monkeypatch.setattr(mt5_pushes_service, "_db_path", lambda: str(db))
    rejets: list[dict] = []
    monkeypatch.setattr(
        "backend.services.rejection_service.record_rejection",
        lambda **kw: rejets.append(kw),
    )
    mt5_pushes_service._ensure_schema()
    return NS(path=str(db), rejets=rejets)


def _setup(pair="BTC/USD", entry=60000.0):
    return NS(pair=pair, direction=NS(value="buy"), entry_price=entry,
              stop_loss=entry * 0.997, take_profit_1=entry * 1.005,
              confidence_score=72.0, verdict_action="TAKE")


def _dest():
    return NS(destination_id="admin_kraken", user_id=None,
              bridge_url="http://bridge.test", bridge_api_key="k",
              bridge_type="kraken")


def _lignes(base) -> list[sqlite3.Row]:
    with sqlite3.connect(base.path) as c:
        c.row_factory = sqlite3.Row
        return c.execute("SELECT * FROM mt5_pushes").fetchall()


def _transport(monkeypatch):
    """Compte les envois HTTP. Aucun ne doit partir sur un refus."""
    envois: list[dict] = []

    async def _post(self, url, json=None, headers=None):
        envois.append({"url": url, "json": json})
        return httpx.Response(200, json={"ok": True, "order_id": "x"},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", _post)
    return envois


# --- la liste est VIDE par defaut : rien ne passe -------------------------

def test_la_liste_est_vide_par_defaut():
    """L'opt-in strict se lit dans la constante, pas dans un commentaire."""
    assert kbc._KRAKEN_WHITELIST_PAIRS == frozenset(), (
        "la liste doit etre VIDE par defaut : une destination en argent reel "
        "ne s'ouvre que par inscription explicite")


@pytest.mark.asyncio
async def test_une_paire_hors_liste_est_refusee_SANS_envoi(base, monkeypatch):
    """La propriete centrale : le refus precede le reseau."""
    envois = _transport(monkeypatch)
    monkeypatch.setattr(kbc, "_KRAKEN_WHITELIST_PAIRS", frozenset())

    await kbc.push_to_kraken(_setup("BTC/USD"), {"risk_money": 1.0}, _dest())

    assert envois == [], "un ordre refuse ne doit PAS avoir ete envoye"
    assert [r["reason_code"] for r in base.rejets] == [
        "kraken_pair_not_whitelisted"]
    assert _lignes(base) == [], \
        "aucune reservation de push ne doit rester apres un refus"


@pytest.mark.asyncio
async def test_le_refus_nomme_la_paire_et_la_liste(base, monkeypatch):
    """Un refus sans la liste autorisee laisse l'operateur deviner."""
    _transport(monkeypatch)
    monkeypatch.setattr(kbc, "_KRAKEN_WHITELIST_PAIRS", frozenset({"ETH/USD"}))

    await kbc.push_to_kraken(_setup("BTC/USD"), {"risk_money": 1.0}, _dest())

    d = base.rejets[0]["details"]
    assert d["pair"] == "BTC/USD"
    assert d["autorisees"] == ["ETH/USD"]


@pytest.mark.asyncio
async def test_une_paire_INSCRITE_passe_la_porte(base, monkeypatch):
    """Temoin POSITIF : sans lui, une porte qui refuse TOUT passerait pour
    correcte, y compris apres qu'on y ait inscrit une paire."""
    envois = _transport(monkeypatch)
    monkeypatch.setattr(kbc, "_KRAKEN_WHITELIST_PAIRS", frozenset({"BTC/USD"}))

    await kbc.push_to_kraken(_setup("BTC/USD"), {"risk_money": 1.0}, _dest())

    assert len(envois) == 1, "une paire inscrite doit atteindre le pont"
    assert not [r for r in base.rejets
                if r["reason_code"] == "kraken_pair_not_whitelisted"]


@pytest.mark.asyncio
async def test_le_filtre_precede_la_porte_de_verdict(base, monkeypatch):
    """Ordre des portes : une paire hors liste est refusee POUR CETTE raison,
    meme si le verdict l'aurait aussi arretee. Sinon le motif rapporte serait
    le mauvais, et on corrigerait la mauvaise chose."""
    _transport(monkeypatch)
    monkeypatch.setattr(kbc, "_KRAKEN_WHITELIST_PAIRS", frozenset())
    s = _setup("DOGE/USD")
    s.verdict_action = "SKIP"

    await kbc.push_to_kraken(s, {"risk_money": 1.0}, _dest())

    assert base.rejets[0]["reason_code"] == "kraken_pair_not_whitelisted"


def test_le_motif_a_un_libelle_francais():
    """Neuf motifs s'affichent deja en code brut faute de libelle : ne pas
    en ajouter un dixieme."""
    from backend.services.rejection_service import REASON_LABELS_FR
    assert "kraken_pair_not_whitelisted" in REASON_LABELS_FR
    assert REASON_LABELS_FR["kraken_pair_not_whitelisted"].strip() != ""
