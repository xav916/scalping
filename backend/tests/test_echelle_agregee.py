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
