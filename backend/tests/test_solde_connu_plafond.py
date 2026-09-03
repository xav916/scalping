"""Le plafond journalier doit POUVOIR lire le solde réel, pas seulement savoir le lire.

Le volet capital du 2026-09-03 lisait `sizing._cache_get`, un cache alimenté
uniquement sur le chemin du dispatch et périmé en 5 minutes. Mesuré juste après
déploiement : `capital_reel_connu` rendait ``None`` pour les trois comptes, donc
le plafond retombait sur les 650 € de `TRADING_CAPITAL` — la logique était
correcte et n'était jamais atteinte. Même défaut que le détecteur de positions
nues, et que `_check_rejection` sans sa destination.

Deux choses verrouillées ici :

  1. Le solde survit à la péremption du cache de sizing (5 min). Sans quoi le
     seuil oscillerait entre −19,50 € et −21,58 € selon l'instant du signal —
     un garde-fou de risque ne doit pas dépendre de l'heure à laquelle on le
     regarde.
  2. Il ne survit PAS indéfiniment. Un solde d'il y a trois heures peut
     ÉLARGIR le plafond à tort ; au-delà de la borne, on retombe sur la
     constante, qui est le seuil le plus serré.
"""
from __future__ import annotations

import pytest

from backend.services import sizing


@pytest.fixture(autouse=True)
def caches_neufs(monkeypatch):
    """Deux caches vierges par test — sinon les soldes fuient d'un test à l'autre."""
    monkeypatch.setattr(sizing, "_BALANCE_CACHE", {}, raising=False)
    monkeypatch.setattr(sizing, "_SOLDE_CONNU", {}, raising=False)


# ── Le solde tient au-delà du cache de sizing ─────────────────────────────

def test_le_solde_survit_a_la_peremption_du_cache_de_sizing():
    """5 min plus tard, le sizing a oublié — le plafond, non."""
    sizing._cache_put("admin_live", 719.18)
    assert sizing.capital_reel_connu("admin_live") == pytest.approx(719.18)

    # Le cache de sizing expire : on vide celui-là, pas l'autre.
    sizing._BALANCE_CACHE.clear()

    assert sizing._cache_get("admin_live") is None, "le sizing a bien oublié"
    assert sizing.capital_reel_connu("admin_live") == pytest.approx(719.18), (
        "le plafond doit garder le dernier solde connu")


def test_le_solde_perime_au_dela_de_la_borne(monkeypatch):
    """Trois heures plus tard, on ne sait plus : retour à la constante."""
    import time

    sizing._cache_put("admin_live", 719.18)
    # Rembobine l'échéance dans le passé plutôt que d'attendre une heure.
    solde, _ = sizing._SOLDE_CONNU["admin_live"]
    sizing._SOLDE_CONNU["admin_live"] = (solde, time.monotonic() - 1)

    assert sizing.capital_reel_connu("admin_live") is None, (
        "un solde trop vieux peut ÉLARGIR le plafond — il ne doit pas servir")


def test_un_compte_jamais_vu_ne_rend_rien():
    assert sizing.capital_reel_connu("admin_kraken") is None


# ── Le job qui alimente le cache ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_le_job_rafraichit_AUSSI_la_demo(monkeypatch):
    """Depuis le 04/09, la démo lit son propre solde et non celui du réel.

    Elle était écartée tant qu'elle empruntait le capital du réel via
    `capital_mirror` : son solde propre ne servait à rien. Ce miroir retiré,
    l'oublier ici la ferait retomber sur `TRADING_CAPITAL` les jours sans
    dimensionnement — autonomie à moitié faite, et silencieuse.
    """
    vus: list[str] = []

    class _D:
        def __init__(self, i):
            self.destination_id = i
            self.bridge_url = f"http://{i}"

    monkeypatch.setattr(
        "backend.services.bridge_destinations.admin_destinations",
        lambda: [_D("admin_live"), _D("admin_legacy"), _D("admin_kraken")])

    async def _faux(dest):
        vus.append(dest.destination_id)
        return 500.0

    monkeypatch.setattr(sizing, "refresh_destination_capital", _faux)

    await sizing.rafraichir_soldes_reels()

    assert sorted(vus) == ["admin_kraken", "admin_legacy", "admin_live"]


@pytest.mark.asyncio
async def test_une_destination_sans_bridge_est_ignoree(monkeypatch):
    """Pas d'URL, rien à interroger — inutile de tenter un appel réseau."""
    vus: list[str] = []

    class _D:
        def __init__(self, i, url=None):
            self.destination_id = i
            self.bridge_url = url

    monkeypatch.setattr(
        "backend.services.bridge_destinations.admin_destinations",
        lambda: [_D("admin_live", "http://live"), _D("orpheline", None)])

    async def _faux(dest):
        vus.append(dest.destination_id)
        return 500.0

    monkeypatch.setattr(sizing, "refresh_destination_capital", _faux)
    await sizing.rafraichir_soldes_reels()
    assert vus == ["admin_live"]


@pytest.mark.asyncio
async def test_un_bridge_injoignable_n_empeche_pas_les_autres(monkeypatch):
    """Un compte muet ne doit pas priver les autres de leur solde.

    C'est le mode de défaillance qui a bloqué Kraken pendant des mois : une
    lecture qui échoue et emporte tout le reste avec elle.
    """
    class _D:
        def __init__(self, i):
            self.destination_id = i
            self.bridge_url = f"http://{i}"

    monkeypatch.setattr(
        "backend.services.bridge_destinations.admin_destinations",
        lambda: [_D("admin_live"), _D("admin_kraken")])

    async def _faux(dest):
        if dest.destination_id == "admin_live":
            raise RuntimeError("bridge muet")
        return 106.31

    monkeypatch.setattr(sizing, "refresh_destination_capital", _faux)

    resultat = await sizing.rafraichir_soldes_reels()

    assert resultat["admin_live"] is None
    assert resultat["admin_kraken"] == pytest.approx(106.31)


@pytest.mark.asyncio
async def test_le_job_ne_leve_jamais(monkeypatch):
    """Le scheduler ne doit pas perdre le job sur une exception de fond."""
    monkeypatch.setattr(
        "backend.services.bridge_destinations.admin_destinations",
        lambda: (_ for _ in ()).throw(RuntimeError("registre cassé")))

    assert await sizing.rafraichir_soldes_reels() == {}


# ── La vue doit montrer le chiffre qui DÉCIDE ─────────────────────────────

def test_la_vue_expose_le_seuil_REELLEMENT_applique(monkeypatch, tmp_path):
    """Le solde vit en mémoire du serveur : sans cette sortie, invérifiable.

    Un `docker exec` démarre un interpréteur neuf, au cache vide. C'est ainsi
    que le volet capital est resté inerte une heure après son déploiement sans
    que la mesure ne le révèle — elle mesurait le mauvais processus.
    """
    import sqlite3

    from backend.services import kill_switch as ks
    from backend.services import trade_log_service as t

    chemin = tmp_path / "trades.db"
    monkeypatch.setattr(t, "_DB_PATH", chemin, raising=False)
    t._init_schema()
    c = sqlite3.connect(chemin)
    c.execute("""CREATE TABLE IF NOT EXISTS mt5_pushes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, destination_id TEXT,
        bridge_response TEXT)""")
    c.commit()
    c.close()

    sizing._cache_put("admin_live", 719.18)
    vue = ks._daily_loss_par_destination()

    assert vue["admin_live"]["capital"] == pytest.approx(719.18)
    assert vue["admin_live"]["seuil"] == pytest.approx(-21.58, abs=0.01)
    assert vue["admin_live"]["source"] == "live"
    # Un compte dont le solde n'est pas connu doit le DIRE, pas afficher un
    # capital d'apparence normale.
    assert vue["admin_kraken"]["source"] == "configure"
