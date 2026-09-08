"""Les échelles agrégées : détecter sur M15/M30 depuis les bougies de 5 min.

## ⛔ Le constat qui l'a motivée

Le chemin 5 min n'agrège rien et ne garde aucune mémoire entre les cycles. Son
détecteur le plus profond regarde **30 bougies = 2 h 30**, et `momentum` n'en
regarde que **5, soit 25 minutes**.

## Ce qui a été mesuré AVANT de construire

Rejeu séquentiel, 60 jours, spread facturé, mêmes détecteurs :

```
                 n     R moyen       t    spread payé
XAU/USD   M5   109     +0,029    +0,23      0,029 R
          M30   24     +0,561    +1,98      0,013 R
EUR/USD   M5   124     −0,324    −2,73      0,162 R
          M30   19     +0,004    +0,01      0,055 R
```

🔑 Monotone sur les DEUX instruments, et le mécanisme est visible : **le spread
payé en R s'effondre quand le stop s'élargit**. C'est « le 5 min ne paie pas ses
frais » avec son remède.

⚠️ n=19 à 24 : une piste déclarée, pas une conclusion.
"""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import pytest

from backend.models.schemas import Candle
from backend.services import echelle_agregee as ea


def _serie(n: int, debut_minute: int = 0) -> list[Candle]:
    """n bougies de 5 min, alignées sur l'horloge."""
    t0 = datetime(2026, 9, 8, 10, debut_minute, tzinfo=timezone.utc)
    return [Candle(timestamp=t0 + timedelta(minutes=5 * i),
                   open=100.0 + i, high=101.0 + i, low=99.0 + i,
                   close=100.5 + i, volume=1.0) for i in range(n)]


# ── L'agrégation ─────────────────────────────────────────────────────

def test_trois_bougies_de_5_min_en_font_une_de_15():
    a = ea.agreger(_serie(30), 3)
    assert len(a) == 10


def test_l_agregation_prend_le_bon_open_close_haut_bas():
    """🔑 Ouverture de la PREMIÈRE, clôture de la DERNIÈRE, extrêmes du groupe.
    Se tromper ici fabriquerait un instrument qui n'existe pas."""
    a = ea.agreger(_serie(3), 3)
    assert len(a) == 1
    b = a[0]
    assert b.open == 100.0          # ouverture de la 1re
    assert b.close == 102.5         # clôture de la 3e
    assert b.high == 103.0          # plus haut des trois
    assert b.low == 99.0            # plus bas des trois


def test_l_agregation_est_ALIGNEE_sur_l_horloge():
    """⛔ Alignée sur les minutes rondes, jamais par paquets successifs : un
    découpage décalé produirait des bougies qu'aucun courtier ne cote."""
    # Série démarrant à 10h05 : la première bougie de 15 min est celle de 10h00,
    # incomplète, donc écartée.
    a = ea.agreger(_serie(12, debut_minute=5), 3)
    assert all(b.timestamp.minute % 15 == 0 for b in a)


def test_une_bougie_INCOMPLETE_est_ecartee():
    """⚠️ Sinon la détection verrait un plus haut qui n'est pas encore le sien,
    et changerait d'avis à chaque cycle sur la même bougie."""
    a = ea.agreger(_serie(7), 3)      # 2 groupes pleins + 1 entamé
    assert len(a) == 2


def test_un_facteur_de_1_ne_change_rien():
    s = _serie(10)
    assert ea.agreger(s, 1) == s


def test_une_serie_VIDE_ne_casse_pas():
    assert ea.agreger([], 3) == []


# ── L'horizon, qui porte la portée ───────────────────────────────────

def test_l_horizon_correspond_a_l_echelle():
    assert ea.horizon_pour(3) == "15min"
    assert ea.horizon_pour(6) == "30min"


def test_ces_horizons_EXISTENT_dans_le_vocabulaire():
    """⛔ Un horizon inconnu de `normalize()` serait remis à `5min` par
    `enrich_trade_setup` — et partirait donc sur l'ARGENT RÉEL."""
    from backend.services.horizon import normalize
    for f in ea.FACTEURS:
        h = ea.horizon_pour(f)
        assert normalize(h) == h, h


# ── La porte de route : ce qui décide vraiment qui les reçoit ────────
#
# ⛔ Ma première version raisonnait la portée au lieu de la SOUMETTRE : je me
# reposais sur `MT5_BRIDGE_LIVE_ALLOWED_HORIZONS=5min,4h` pour écarter le réel.
# Juste pour le réel, FAUX pour le démo — `_mt5_horizons` filtre sur
# `{CANDLE_INTERVAL}` des DEUX côtés. Les setups agrégés n'auraient atteint
# personne, et rien ne l'aurait dit. Ces tests passent la vraie fonction.

def test_AUCUNE_route_ne_les_recoit_par_defaut(monkeypatch):
    """⛔ Fermé par défaut. Écrire le code n'ouvre pas la porte."""
    from backend.services import bridge_destinations as bd
    monkeypatch.delenv("MT5_ECHELLES_AGREGEES_ROUTES", raising=False)
    for dest in ("admin_legacy", "admin_live"):
        servis = bd._mt5_horizons(dest) or frozenset()
        for f in ea.FACTEURS:
            assert ea.horizon_pour(f) not in servis, (dest, f)


def test_le_DEMO_les_recoit_une_fois_declare(monkeypatch):
    """🔑 Le test qui aurait attrapé mon défaut : sans lui, « ça n'atteint que
    le démo » restait une phrase, jamais une mesure."""
    from backend.services import bridge_destinations as bd
    monkeypatch.setenv("MT5_ECHELLES_AGREGEES_ROUTES", "admin_legacy")
    servis = bd._mt5_horizons("admin_legacy")
    for f in ea.FACTEURS:
        assert ea.horizon_pour(f) in servis, f
    assert "5min" in servis          # ⚠️ le chemin qui trade reste servi


def test_le_REEL_reste_ferme_MEME_declare(monkeypatch):
    """⛔ Le second verrou. Ajouter `admin_live` à la liste ne suffit pas :
    la déclaration du réel restreint par INTERSECTION."""
    from backend.services import bridge_destinations as bd
    monkeypatch.setenv("MT5_ECHELLES_AGREGEES_ROUTES", "admin_legacy,admin_live")
    import config.settings
    monkeypatch.setattr(config.settings, "MT5_BRIDGE_LIVE_ALLOWED_HORIZONS",
                        ["5min", "4h"])
    servis = bd._mt5_horizons("admin_live")
    for f in ea.FACTEURS:
        assert ea.horizon_pour(f) not in servis, f


def test_les_horizons_de_la_porte_sont_DERIVES_du_reglage(monkeypatch):
    """⛔ Codés en dur, ils se désynchroniseraient du scheduler au premier
    changement d'échelle : des setups produits puis refusés, sans trace."""
    from backend.services import bridge_destinations as bd
    monkeypatch.setattr(ea, "FACTEURS", (12,))       # M60
    assert bd._horizons_agreges() == frozenset({"60min"})


# ── La sécurité du branchement ───────────────────────────────────────

def test_l_echelle_se_DESARME_par_configuration():
    """⚠️ Une piste en observation doit pouvoir s'éteindre sans redéploiement."""
    src = io.open("backend/services/echelle_agregee.py", encoding="utf-8").read()
    assert 'os.getenv("ECHELLES_AGREGEES"' in src


def test_un_echec_d_echelle_ne_casse_PAS_le_cycle():
    """⛔ Une piste en observation ne doit jamais pouvoir casser le flux qui,
    lui, trade."""
    class _Casse:
        timestamp = "pas une date"
    assert ea.setups_agreges([_Casse()], "XAU/USD") == []


def test_trop_peu_de_bougies_ne_produit_RIEN():
    """⚠️ `detect_patterns` regarde jusqu'à 30 bougies : en dessous, il verrait
    des motifs sur un échantillon qui n'en porte pas."""
    assert ea.setups_agreges(_serie(30), "XAU/USD") == []


def test_le_scheduler_ENRICHIT_les_setups_agreges():
    """⛔ Défaut attrapé avant déploiement : sans enrichissement ils n'ont pas
    de score, et `filter_high_confidence_setups` les écarte EN SILENCE."""
    src = io.open("backend/services/scheduler.py", encoding="utf-8").read()
    debut = src.index("setups_agreges")
    bloc = src[debut:debut + 1200]
    assert "enrich_trade_setup" in bloc
    assert "compute_verdict" in bloc


# ── La trace ─────────────────────────────────────────────────────────

def test_une_production_est_DITE_au_niveau_info(caplog):
    """⛔ Sans trace positive on ne saurait pas distinguer « le marché n'offre
    rien » de « c'est casse ». Le mode de defaillance deja rencontre trois fois
    dans ce projet — enregistrer n'est pas dire."""
    import logging
    faux = type("S", (), {"horizon": None,
                          "pattern": type("P", (), {"pattern": type(
                              "E", (), {"value": "momentum_up"})()})()})
    monkey = {"n": 0}

    def _detect(candles, pair):
        return ["motif"]

    def _calc(pair, motif, candles, is_simulated=False):
        monkey["n"] += 1
        return faux()

    import backend.services.pattern_detector as pd
    old_d, old_c = pd.detect_patterns, pd.calculate_trade_setup
    pd.detect_patterns, pd.calculate_trade_setup = _detect, _calc
    try:
        with caplog.at_level(logging.INFO, logger=ea.__name__):
            ea.setups_agreges(_serie(300), "XAU/USD")
    finally:
        pd.detect_patterns, pd.calculate_trade_setup = old_d, old_c
    assert any("echelle_agregee:" in r.message for r in caplog.records)
    assert any("momentum_up" in str(r.getMessage()) for r in caplog.records)


def test_un_echec_est_DIT_lui_aussi(caplog):
    """⚠️ Il était en `debug` : un module qui echoue a chaque cycle serait
    invisible en production."""
    import io as _io
    src = _io.open("backend/services/echelle_agregee.py", encoding="utf-8").read()
    assert "logger.warning(\"echelle_agregee %s x%d" in src


def test_le_nom_du_motif_traverse_les_DEUX_emballages():
    """⛔ `setup.pattern` est un objet Pattern dont `.pattern` est l'enum. Ma
    sonde s'est trompee de niveau et a rendu « n=1 » partout."""
    enum = type("E", (), {"value": "breakout_up"})()
    p = type("P", (), {"pattern": enum})()
    assert ea._motif(type("S", (), {"pattern": p})()) == "breakout_up"


# ── Le tampon : la vraie cause d'inertie ─────────────────────────────
#
# ⛔ Le cycle ne fournit que CANDLE_COUNT=50 bougies de 5 min. Agrégées : 16 en
# M15, 8 en M30 — sous le minimum, écartées, et RIEN n'aurait jamais été
# produit. Invisible, parce que le `continue` ne disait rien.

@pytest.fixture(autouse=True)
def _tampon_neuf():
    ea._memoire.clear()
    ea._dit.clear()
    yield
    ea._memoire.clear()
    ea._dit.clear()


def test_les_cycles_SUCCESSIFS_s_accumulent():
    """🔑 « Capitaliser et agréger les analyses » — la demande de Xavier, prise
    au mot. Sans cela, 50 bougies ne suffiront jamais."""
    ea.memoriser("XAU/USD", _serie(50))
    t0 = datetime(2026, 9, 8, 10, tzinfo=timezone.utc)
    suite = [Candle(timestamp=t0 + timedelta(minutes=5 * i), open=1.0, high=2.0,
                    low=0.5, close=1.5, volume=1.0) for i in range(45, 95)]
    total = ea.memoriser("XAU/USD", suite)
    assert len(total) == 95            # 50 + 50 - 5 de recouvrement


def test_le_recouvrement_ne_DUPLIQUE_pas():
    """Deux cycles consécutifs se recouvrent presque entièrement."""
    ea.memoriser("XAU/USD", _serie(50))
    assert len(ea.memoriser("XAU/USD", _serie(50))) == 50


def test_le_tampon_est_BORNE():
    """⚠️ Sinon il grandit sans fin sur un processus qui tourne des semaines."""
    grand = ea.MAX_MEMOIRE + 120
    t0 = datetime(2026, 9, 8, tzinfo=timezone.utc)
    ea.memoriser("XAU/USD", [Candle(timestamp=t0 + timedelta(minutes=5 * i),
                                    open=1.0, high=2.0, low=0.5, close=1.5,
                                    volume=1.0) for i in range(grand)])
    assert len(ea._memoire["XAU/USD"]) == ea.MAX_MEMOIRE


def test_le_tampon_garde_les_bougies_les_plus_RECENTES():
    """⛔ Tronquer par le mauvais bout donnerait une détection sur un passé
    mort, sans que rien ne le signale."""
    t0 = datetime(2026, 9, 8, tzinfo=timezone.utc)
    n = ea.MAX_MEMOIRE + 10
    ea.memoriser("EUR/USD", [Candle(timestamp=t0 + timedelta(minutes=5 * i),
                                    open=1.0, high=2.0, low=0.5, close=1.5,
                                    volume=1.0) for i in range(n)])
    gardees = sorted(ea._memoire["EUR/USD"])
    assert gardees[-1] == t0 + timedelta(minutes=5 * (n - 1))


def test_les_paires_ne_se_MELANGENT_pas():
    ea.memoriser("XAU/USD", _serie(20))
    ea.memoriser("EUR/USD", _serie(7))
    assert ea.etat_memoire() == {"EUR/USD": 7, "XAU/USD": 20}


def test_l_ATTENTE_est_DITE_une_seule_fois(caplog):
    """⛔ Le defaut d'origine : un `continue` muet. Mais le dire a chaque cycle
    ferait 8 500 lignes par jour — on le dit au CHANGEMENT d'etat."""
    import logging
    with caplog.at_level(logging.INFO, logger=ea.__name__):
        for _ in range(4):
            ea.setups_agreges(_serie(50), "XAU/USD")
    attentes = [r for r in caplog.records if "en attente" in r.getMessage()]
    assert len(attentes) == len(ea.FACTEURS), [r.getMessage() for r in attentes]
    assert "tampon" in attentes[0].getMessage()


# ── Le pre-remplissage ───────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _preremplies_neuves():
    ea._preremplies.clear()
    yield
    ea._preremplies.clear()


async def _fetch_factice(appels, n=400):
    """⛔ Rend le VRAI contrat : un tuple `(bougies, simule)`.

    Ma premiere version rendait une liste. Le code de production passait donc
    le tuple entier a `memoriser`, qui n'y trouvait aucune bougie et n'ajoutait
    RIEN — « 0 bougie », sans erreur, et le test vert. Un faux qui ne
    reproduit pas le contrat valide du code faux.
    """
    async def _f(pair, interval="5min", outputsize=50):
        appels.append((pair, interval, outputsize))
        return _serie(min(n, outputsize)), False
    return _f


@pytest.mark.asyncio
async def test_le_preremplissage_remplit_le_tampon_d_un_coup():
    """⛔ Sans lui, ~16 h pour servir M30 — et chaque redeploiement remet a
    zero. Le dispositif ne se serait jamais allume."""
    appels = []
    f = await _fetch_factice(appels)
    ajoutees = await ea.preremplir("XAU/USD", f)
    assert ajoutees > ea.MIN_BOUGIES * max(ea.FACTEURS) - 10
    assert appels[0][1] == "5min"
    assert appels[0][2] >= ea.MIN_BOUGIES * max(ea.FACTEURS)


@pytest.mark.asyncio
async def test_il_n_a_lieu_qu_UNE_fois_par_paire():
    """⚠️ Un appel par cycle et par paire saturerait le quota — qui a deja
    rendu 954 refus 429."""
    appels = []
    f = await _fetch_factice(appels)
    for _ in range(5):
        await ea.preremplir("XAU/USD", f)
    assert len(appels) == 1


@pytest.mark.asyncio
async def test_un_ECHEC_ne_se_retente_pas_a_chaque_cycle():
    """⛔ Le marqueur est pose AVANT l'appel : sinon une paire en erreur
    rappellerait la source a chaque passage, indefiniment."""
    appels = []

    async def _casse(pair, interval="5min", outputsize=50):
        appels.append(pair)
        raise RuntimeError("source indisponible")

    for _ in range(3):
        try:
            await ea.preremplir("XAU/USD", _casse)
        except RuntimeError:
            pass
    assert len(appels) == 1


@pytest.mark.asyncio
async def test_un_tampon_DEJA_plein_n_appelle_rien():
    appels = []
    f = await _fetch_factice(appels)
    ea.memoriser("XAU/USD", _serie(ea.MAX_MEMOIRE))
    assert await ea.preremplir("XAU/USD", f) == 0
    assert appels == []


def test_le_scheduler_PREREMPLIT_avant_de_detecter():
    """⛔ Le branchement doit exister : le module seul ne se declenche pas."""
    src = io.open("backend/services/scheduler.py", encoding="utf-8").read()
    debut = src.index("setups_agreges")
    bloc = src[max(0, debut - 400):debut + 1200]
    assert "await preremplir(pair, fetch_candles_sans_cache)" in bloc


def test_le_preremplissage_passe_par_la_lecture_SANS_CACHE():
    """⛔ Le cache est indexe sur (paire, intervalle) SANS la taille : avec
    `fetch_candles`, le tampon aurait resservi les 50 bougies du cycle et ne
    serait jamais monte. Trouve en production, pas en test."""
    src = io.open("backend/services/scheduler.py", encoding="utf-8").read()
    debut = src.index("preremplir(pair")
    assert "fetch_candles_sans_cache" in src[debut - 200:debut + 120]


@pytest.mark.asyncio
async def test_un_fetch_qui_rend_un_TUPLE_est_compris():
    """Le contrat reel de `price_service`."""
    ea._memoire.clear(); ea._preremplies.clear()

    async def _f(pair, interval="5min", outputsize=50):
        return _serie(outputsize), False

    assert await ea.preremplir("XAU/USD", _f) > 100


@pytest.mark.asyncio
async def test_la_lecture_sans_cache_NE_LIT_ni_n_ECRIT_le_cache(monkeypatch):
    """⚠️ Ecrire 280 bougies sous la cle du chemin 5 min les servirait au
    chemin qui TRADE pendant tout le TTL. Un essai ne change pas la production."""
    from backend.services import price_service as ps
    appels = {"lu": 0, "ecrit": 0}
    monkeypatch.setattr(ps, "_cache_get_candles",
                        lambda *a: appels.__setitem__("lu", appels["lu"] + 1))
    monkeypatch.setattr(ps, "_cache_store_candles",
                        lambda *a: appels.__setitem__("ecrit", appels["ecrit"] + 1))

    async def _source(pair, interval, outputsize):
        return _serie(outputsize), False

    monkeypatch.setattr(ps, "_fetch_depuis_source", _source)
    bougies, _ = await ps.fetch_candles_sans_cache("XAU/USD", "5min", 280)
    assert len(bougies) == 280
    assert appels == {"lu": 0, "ecrit": 0}
