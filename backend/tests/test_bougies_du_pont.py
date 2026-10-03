"""Certaines paires decident sur les bougies DU COURTIER, pas sur Twelve Data.

⛔ **Le constat du 2026-10-03.** Le dernier trade WTI remonte au **4 aout**, et
`signal_rejections` compte **13 078 refus `price_divergence`** en 7 jours — le
seuil est a 0,5 %. Mesure a l'instant sur tout l'univers du reel :

    WTI/USD   XTIUSD   radar  90,3076   courtier  93,4800   ecart 3,394 %  <- SEUL
    UNI/USD            radar   9,2370   courtier   9,2235   ecart 0,146 %  <- le 2e
    les 22 autres                                           ecart <= 0,07 %

Le WTI est seul, et de 23 fois. Ce n'est pas de la latence : un ecart constant
de cette taille, ce sont **deux instruments differents** — le << WTI/USD >> de
Twelve Data n'est pas le `XTIUSD` d'IC Markets. Et il GRANDIT : 1,6 a 1,9 % le
29/08, 3,4 % aujourd'hui.

🔑 Le radar DECIDE sur un prix et le courtier EXECUTE sur un autre, a 3,4 % de
distance. Avec un stop WTI de l'ordre de 1 %, cela fait trois stops d'erreur
avant que le marche ait bouge. La porte a raison de refuser ; c'est la SOURCE
qu'il faut corriger.

## ⚠️ Une source unique ne peut pas servir les deux destinations

    IC Markets  XTIUSD     93,4800
    Pepperstone SpotCrude  94,1770     <- 0,75 % d'ecart entre les deux COURTIERS

0,75 % depasse le seuil de 0,5 %. En sourcant depuis le pont du REEL, le WTI
passe sur le reel et reste refuse sur la demo. Aujourd'hui il est refuse
PARTOUT : c'est donc strictement mieux, et le refus de la demo devient honnete
— il refusera parce que son propre courtier est en desaccord, ce qui est vrai.

## ⛔ Et PAS de repli sur Twelve Data

Un pont injoignable rend une liste VIDE : la paire est simplement absente du
cycle. Retomber sur Twelve Data reintroduirait en silence la divergence qu'on
corrige, et la porte refuserait de toute facon — on aurait paye un appel
reseau pour le meme refus.

Precedent suivi : la crypto est deja routee vers Binance plutot que Twelve
Data, derriere un drapeau, pour la meme raison (<< plus fidele au marche reel
que Twelve Data CFD-routed >>).
"""
from __future__ import annotations

import json
import urllib.parse
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import bougies_du_pont as bp


def _reponse(n=50, base=93.0):
    t0 = datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc)
    return {"bougies": [
        {"t": (t0 + timedelta(minutes=5 * i)).isoformat(),
         "o": base + i * 0.01, "h": base + i * 0.01 + 0.05,
         "l": base + i * 0.01 - 0.05, "c": base + i * 0.01 + 0.02,
         "tv": 120 + i}
        for i in range(n)]}


@pytest.fixture
def pont(monkeypatch):
    """⚠️ La destination doit etre doublee AUSSI, sinon `fetch_candles` rend
    une liste vide avant meme d'interroger le pont — et les tests passeraient
    pour une raison qui n'a rien a voir avec ce qu'ils annoncent."""
    from types import SimpleNamespace as NS

    etat = {"reponse": _reponse(), "appels": []}
    faux_dest = NS(destination_id="admin_live", bridge_url="http://pont.invalide",
                   bridge_api_key="k", bridge_type="mt5", user_id=None,
                   symbol_map={"WTI/USD": "XTIUSD"})

    def _lire(dest, symbole, timeframe, combien):
        etat["appels"].append((getattr(dest, "destination_id", None),
                               symbole, timeframe, combien))
        return etat["reponse"]

    monkeypatch.setattr(bp, "_destination", lambda: faux_dest)
    monkeypatch.setattr(bp, "_lire_rates", _lire)
    monkeypatch.setattr(bp, "PAIRES_DU_PONT", frozenset({"WTI/USD"}),
                        raising=False)
    return etat


# --- Le routage ----------------------------------------------------------

def test_une_paire_declaree_passe_par_le_pont(pont):
    assert bp.paire_du_pont("WTI/USD") is True


def test_une_paire_NON_declaree_n_est_pas_touchee(pont):
    for p in ("XAU/USD", "EUR/USD", "BTC/USD"):
        assert bp.paire_du_pont(p) is False, p


def test_sans_reglage_RIEN_ne_change(monkeypatch):
    """⚠️ Defaut vide : le comportement d'avant, pour toutes les paires."""
    monkeypatch.setattr(bp, "PAIRES_DU_PONT", frozenset(), raising=False)
    assert bp.paire_du_pont("WTI/USD") is False


# --- La lecture ----------------------------------------------------------

@pytest.mark.asyncio
async def test_les_bougies_sont_converties_et_triees(pont):
    bougies = await bp.fetch_candles("WTI/USD", "5min", 50)
    assert len(bougies) == 50
    assert bougies[0].timestamp < bougies[-1].timestamp
    assert bougies[-1].close == pytest.approx(93.0 + 49 * 0.01 + 0.02)
    assert bougies[-1].volume == pytest.approx(169)


@pytest.mark.asyncio
async def test_l_echelle_est_traduite_pour_le_pont(pont):
    """Le radar dit `5min`, MT5 dit `M5`. Une traduction ratee rendrait des
    bougies d'une AUTRE echelle, sans erreur."""
    attendu = {"5min": "M5", "15min": "M15", "30min": "M30",
               "1h": "H1", "4h": "H4", "1d": "D1"}
    for radar, mt5 in attendu.items():
        pont["appels"].clear()
        await bp.fetch_candles("WTI/USD", radar, 10)
        assert pont["appels"][0][2] == mt5, (radar, pont["appels"][0])


@pytest.mark.asyncio
async def test_le_symbole_demande_est_celui_DU_COURTIER(pont):
    """`WTI/USD` vaut `XTIUSD` chez IC Markets et `SpotCrude` chez
    Pepperstone — demander << WTIUSD >> ne trouverait rien."""
    await bp.fetch_candles("WTI/USD", "5min", 10)
    assert pont["appels"][0][1] in ("XTIUSD", "SpotCrude", "WTIUSD")


@pytest.mark.asyncio
async def test_une_echelle_inconnue_ne_demande_RIEN(pont):
    assert await bp.fetch_candles("WTI/USD", "7min", 10) == []
    assert pont["appels"] == []


# --- Les refus -----------------------------------------------------------

@pytest.mark.asyncio
async def test_un_pont_muet_rend_une_liste_VIDE(monkeypatch, pont):
    """⛔ PAS de repli sur Twelve Data : il reintroduirait en silence la
    divergence qu'on corrige, et la porte refuserait de toute facon."""
    monkeypatch.setattr(bp, "_lire_rates",
                        lambda dest, symbole, timeframe, combien: None)
    assert await bp.fetch_candles("WTI/USD", "5min", 50) == []


@pytest.mark.asyncio
async def test_une_bougie_malformee_est_ECARTEE_sans_tout_perdre(pont):
    reponse = _reponse(10)
    reponse["bougies"][4]["c"] = "quatre-vingt-treize"
    pont["reponse"] = reponse
    bougies = await bp.fetch_candles("WTI/USD", "5min", 10)
    assert len(bougies) == 9, "une bougie abimee ne doit pas emporter le cycle"


@pytest.mark.asyncio
async def test_une_reponse_sans_bougies_rend_une_liste_vide(pont):
    pont["reponse"] = {"bougies": []}
    assert await bp.fetch_candles("WTI/USD", "5min", 50) == []


# --- Les parametres REELLEMENT envoyes au pont ---------------------------
#
# ⛔ Defaut attrape avant le deploiement : la 1re version envoyait `count`.
# Le pont ne connait PAS ce parametre — il exige `from` et `to` en ISO 8601 et
# rend sinon un 400 << from et to requis >>. Comme `_lire_rates` avale toute
# panne pour rendre `None`, et que `fetch_candles` traduit `None` en liste
# vide, le WTI aurait ete absent de CHAQUE cycle, pour toujours, sans qu'une
# seule erreur ne remonte. Les tests ci-dessus passaient tous : ils doublaient
# `_lire_rates`, donc precisement la fonction qui etait fausse.

def _urlopen_double(etat):
    """Double de `urlopen` qui enregistre l'URL demandee."""
    import contextlib
    import io

    @contextlib.contextmanager
    def _faux(req, timeout=None):
        etat["url"] = req.full_url
        etat["entetes"] = dict(req.headers)
        yield io.BytesIO(json.dumps({"bougies": []}).encode())

    return _faux


def test_le_pont_recoit_from_et_to_et_PAS_count(monkeypatch):
    from types import SimpleNamespace as NS
    etat = {}
    monkeypatch.setattr(bp.urllib.request, "urlopen", _urlopen_double(etat))
    dest = NS(bridge_url="http://pont.invalide", bridge_api_key="k")

    bp._lire_rates(dest, "XTIUSD", "M5", 50)

    q = urllib.parse.parse_qs(urllib.parse.urlparse(etat["url"]).query)
    assert "count" not in q, "le pont ignore `count` et rend un 400"
    assert q["from"] and q["to"], "from et to sont EXIGES"
    assert q["pair"] == ["XTIUSD"] and q["timeframe"] == ["M5"]
    # La cle d'API voyage en entete, pas dans l'URL.
    assert "XTIUSD" in etat["url"] and "k" not in q


def test_les_bornes_sont_de_l_ISO_8601_que_le_pont_sait_lire(monkeypatch):
    """Le pont fait `datetime.fromisoformat(from.replace("Z","+00:00"))`.
    Un format qu'il ne sait pas lire rendrait un 400, pas des bougies."""
    from types import SimpleNamespace as NS
    etat = {}
    monkeypatch.setattr(bp.urllib.request, "urlopen", _urlopen_double(etat))
    bp._lire_rates(NS(bridge_url="http://x", bridge_api_key=None),
                   "XTIUSD", "H1", 30)

    q = urllib.parse.parse_qs(urllib.parse.urlparse(etat["url"]).query)
    for borne in (q["from"][0], q["to"][0]):
        lu = datetime.fromisoformat(borne.replace("Z", "+00:00"))
        assert lu.tzinfo is not None, borne


def test_la_fenetre_couvre_PLUS_que_la_duree_theorique():
    """⚠️ 50 bougies de 5 min font 250 minutes en theorie, mais le marche
    ferme : elles peuvent enjamber 60 heures. Une fenetre trop courte rendrait
    moins de bougies que le detecteur n'en attend, en silence."""
    maintenant = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)  # un lundi
    debut, fin = bp._fenetre("M5", 50, maintenant=maintenant)
    assert fin == maintenant
    assert fin - debut >= timedelta(days=2), "le week-end doit tenir dedans"


def test_la_fenetre_grandit_avec_l_echelle():
    maintenant = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    larg = {tf: bp._fenetre(tf, 100, maintenant=maintenant)[0]
            for tf in ("M5", "M30", "H4", "D1")}
    assert larg["D1"] < larg["H4"] < larg["M30"] < larg["M5"] <= maintenant
    # 100 bougies journalieres ne se trouvent pas dans deux jours.
    assert maintenant - larg["D1"] >= timedelta(days=100)


def test_une_echelle_inconnue_de_la_fenetre_ne_demande_RIEN():
    assert bp._fenetre("M7", 50) == (None, None)
    assert bp._fenetre("M5", 0) == (None, None)


@pytest.mark.asyncio
async def test_une_reponse_TRONQUEE_est_refusee(pont):
    """⛔ Le pont coupe avec `brut[:5000]` : il garde les plus ANCIENNES.
    Prendre la fin d'une reponse tronquee rendrait des bougies vieilles de
    plusieurs semaines, et le detecteur deciderait dessus en silence."""
    reponse = _reponse(50)
    reponse["tronque"] = True
    reponse["n"] = 5000
    pont["reponse"] = reponse
    assert await bp.fetch_candles("WTI/USD", "5min", 50) == []


@pytest.mark.asyncio
async def test_une_reponse_NON_tronquee_passe(pont):
    reponse = _reponse(50)
    reponse["tronque"] = False
    pont["reponse"] = reponse
    assert len(await bp.fetch_candles("WTI/USD", "5min", 50)) == 50


# --- LE BRANCHEMENT dans price_service -----------------------------------
#
# ⛔ Un module juste et un cablage faux donnent le meme resultat qu'aucun
# module : le WTI resterait sur Twelve Data, et rien ne le dirait. Ces tests
# eprouvent la cascade de `price_service`, pas `bougies_du_pont`.

def _bougie(close):
    from backend.models.schemas import Candle
    return Candle(timestamp=datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc),
                  open=close, high=close, low=close, close=close, volume=1.0)


@pytest.fixture
def _sans_twelve_data(monkeypatch):
    """Toute retombee sur Twelve Data devient un ECHEC VISIBLE."""
    from backend.services import price_service as ps

    def _interdit(*a, **k):
        raise AssertionError("Twelve Data appele — la divergence revient")

    monkeypatch.setattr(ps, "_cache_store_candles", lambda *a, **k: None)
    for nom in ("_fetch_twelvedata", "fetch_twelvedata_candles",
                "_fetch_depuis_twelvedata"):
        if hasattr(ps, nom):
            monkeypatch.setattr(ps, nom, _interdit)
    return ps


@pytest.mark.asyncio
async def test_une_paire_du_pont_NE_passe_PAS_par_twelve_data(
        monkeypatch, _sans_twelve_data):
    ps = _sans_twelve_data
    monkeypatch.setattr(bp, "paire_du_pont", lambda p: p == "WTI/USD")

    async def _du_pont(pair, interval, outputsize):
        return [_bougie(93.47)]

    monkeypatch.setattr(bp, "fetch_candles", _du_pont)

    bougies, simule = await ps._fetch_depuis_source("WTI/USD", "5min", 50)
    assert [b.close for b in bougies] == [93.47], "le prix DU COURTIER"
    assert simule is False


@pytest.mark.asyncio
async def test_un_pont_vide_ne_RETOMBE_PAS_sur_twelve_data(
        monkeypatch, _sans_twelve_data):
    """⛔ Mieux vaut la paire absente du cycle qu'un prix qui ment de 3,4 %."""
    ps = _sans_twelve_data
    monkeypatch.setattr(bp, "paire_du_pont", lambda p: True)

    async def _vide(pair, interval, outputsize):
        return []

    monkeypatch.setattr(bp, "fetch_candles", _vide)
    bougies, _ = await ps._fetch_depuis_source("WTI/USD", "5min", 50)
    assert bougies == []


@pytest.mark.asyncio
async def test_une_paire_NON_declaree_garde_la_cascade_d_avant(monkeypatch):
    """⚠️ Le branchement ne doit rien changer pour les 24 autres paires."""
    from backend.services import price_service as ps
    monkeypatch.setattr(bp, "paire_du_pont", lambda p: False)

    def _jamais(*a, **k):
        raise AssertionError("le pont a ete interroge pour une paire non declaree")

    monkeypatch.setattr(bp, "fetch_candles", _jamais)
    vu = {}

    async def _mt5(pair, interval, outputsize):
        vu["appel"] = pair
        return [_bougie(1.1)], False

    monkeypatch.setattr(ps.mt5_service, "fetch_candles", _mt5)
    monkeypatch.setattr(ps, "PRICE_SOURCE", "mt5")
    await ps._fetch_depuis_source("EUR/USD", "5min", 50)
    assert vu["appel"] == "EUR/USD"


# --- Les echelles telles que le RADAR les nomme --------------------------
#
# ⛔ Releve en production le 2026-10-03, 40 s apres le deploiement :
#     bougies_du_pont: echelle '1day' inconnue du pont — rien
# Ma table disait `1d`, le radar dit `1day`. Les bougies journalieres du WTI
# rendaient donc une liste vide, en silence. Les noms viennent du code appelant,
# pas de ce que je trouve lisible.

@pytest.mark.parametrize("radar,mt5", [
    ("1min", "M1"), ("5min", "M5"), ("15min", "M15"), ("30min", "M30"),
    ("1h", "H1"), ("60min", "H1"), ("4h", "H4"),
    ("1day", "D1"), ("1d", "D1"),
])
def test_toutes_les_echelles_du_radar_sont_traduites(radar, mt5):
    assert bp._ECHELLES.get(radar) == mt5


def test_l_hebdomadaire_est_ABSENT_a_dessein():
    """⛔ Le pont ne connait que M1,M5,M15,M30,H1,H4,D1 — pas de W1. Le
    declarer enverrait un timeframe que le pont refuse par un 400, et la paire
    serait muette sans qu'on sache pourquoi. L'absence est le bon comportement :
    `fetch_candles` dit `echelle inconnue du pont` et rend une liste vide.
    ⚠️ Sans consequence ici : `1week` n'apparait que dans la table Binance
    (crypto) et n'est jamais demande pour les paires du pont."""
    assert "1week" not in bp._ECHELLES


# --- Le PRIX COURANT, l'autre chemin ------------------------------------
#
# ⛔ `fetch_current_price` est un chemin SEPARE de `fetch_candles`, reste sur
# Twelve Data apres mon premier correctif. Consequence mesurable : les trades
# fantomes OPEN sont juges par `backtest_service` avec ce prix. L'entree venant
# des bougies du courtier (93,47) et le juge de Twelve Data (90,31), un ecart de
# 3,4 % ECRASE n'importe quel stop — chaque trade WTI aurait ete declare touche
# a tort, et le journal fantome empoisonne en silence.
# 🔑 Une paire a moitie routee est PIRE qu'une paire non routee.

def test_le_prix_courant_vient_du_pont(monkeypatch):
    from types import SimpleNamespace as NS
    etat = {}
    monkeypatch.setattr(bp.urllib.request, "urlopen", _urlopen_double(etat))
    monkeypatch.setattr(bp, "_destination",
                        lambda: NS(bridge_url="http://x", bridge_api_key="k"))
    monkeypatch.setattr(bp, "_lire_tick", bp._lire_tick)
    assert bp.prix_courant("WTI/USD") is None   # la reponse doublee n'a pas de bid


def test_le_prix_courant_est_le_MILIEU_du_tick(monkeypatch):
    from types import SimpleNamespace as NS
    monkeypatch.setattr(bp, "_destination",
                        lambda: NS(bridge_url="http://x", bridge_api_key="k"))
    monkeypatch.setattr(bp, "_lire_tick",
                        lambda d, s: {"bid": 93.46, "ask": 93.50})
    assert bp.prix_courant("WTI/USD") == pytest.approx(93.48)


def test_un_tick_sans_bid_ou_ask_rend_None(monkeypatch):
    from types import SimpleNamespace as NS
    monkeypatch.setattr(bp, "_destination",
                        lambda: NS(bridge_url="http://x", bridge_api_key="k"))
    for t in ({}, {"bid": 0, "ask": 93.5}, {"bid": 93.4}, None):
        monkeypatch.setattr(bp, "_lire_tick", lambda d, s, _t=t: _t)
        assert bp.prix_courant("WTI/USD") is None, t


@pytest.mark.asyncio
async def test_price_service_prend_le_prix_du_pont_et_PAS_twelve_data(
        monkeypatch):
    from backend.services import price_service as ps
    monkeypatch.setattr(bp, "paire_du_pont", lambda p: p == "WTI/USD")
    monkeypatch.setattr(bp, "prix_courant", lambda p: 93.48)
    monkeypatch.setattr(ps, "_cache_get_price", lambda p: None)
    monkeypatch.setattr(ps, "_cache_store_price", lambda *a: None)
    monkeypatch.setattr(ps, "TWELVEDATA_API_KEY", "")   # Twelve Data = None
    assert await ps.fetch_current_price("WTI/USD") == pytest.approx(93.48)


@pytest.mark.asyncio
async def test_un_pont_muet_ne_RETOMBE_PAS_sur_twelve_data_pour_le_prix(
        monkeypatch):
    """⛔ Mieux vaut AUCUN prix qu'un prix d'un autre contrat : le juge des
    trades fantomes prefere ne rien conclure (`current is None: continue`)."""
    from backend.services import price_service as ps
    monkeypatch.setattr(bp, "paire_du_pont", lambda p: True)
    monkeypatch.setattr(bp, "prix_courant", lambda p: None)
    monkeypatch.setattr(ps, "_cache_get_price", lambda p: None)

    def _interdit(*a, **k):
        raise AssertionError("Twelve Data appele — la divergence revient")

    monkeypatch.setattr(ps.httpx, "AsyncClient", _interdit)
    assert await ps.fetch_current_price("WTI/USD") is None


# --- LE COCKPIT, troisieme chemin ---------------------------------------
#
# ⛔ `cockpit_service._current_price` prefere le tick du flux WebSocket Twelve
# Data, et ne retombe sur la bougie qu'a defaut. Pour une position WTI reelle
# entree a 93,48 chez le courtier, il calculait donc le P&L latent et la
# distance au stop contre 90,31 : une perte fictive de 3,4 % et un `near_sl`
# allume a tort, sous les yeux de Xavier.
# 🔑 Ses bougies viennent deja du scheduler, donc du courtier : il suffit
# d'ECARTER le tick Twelve Data pour ces paires.

def test_le_cockpit_ignore_le_tick_twelve_data_pour_une_paire_du_pont(
        monkeypatch):
    from types import SimpleNamespace as NS
    from backend.services import cockpit_service as cs
    monkeypatch.setattr(bp, "paire_du_pont", lambda p: p == "WTI/USD")
    monkeypatch.setattr(cs, "get_latest_ticks",
                        lambda: {"WTI/USD": NS(price=90.31)})
    monkeypatch.setattr(cs, "get_candles_for_pair",
                        lambda p: [_bougie(93.47)])
    assert cs._current_price("WTI/USD") == pytest.approx(93.47), \
        "le tick Twelve Data cote un AUTRE contrat"


def test_le_cockpit_garde_le_tick_pour_les_autres_paires(monkeypatch):
    """⚠️ Le temps reel reste prefere partout ailleurs — c'est son interet."""
    from types import SimpleNamespace as NS
    from backend.services import cockpit_service as cs
    monkeypatch.setattr(bp, "paire_du_pont", lambda p: False)
    monkeypatch.setattr(cs, "get_latest_ticks",
                        lambda: {"XAU/USD": NS(price=4139.72)})
    monkeypatch.setattr(cs, "get_candles_for_pair",
                        lambda p: [_bougie(4137.62)])
    assert cs._current_price("XAU/USD") == pytest.approx(4139.72)


# --- LE JUGE DES TRADES FANTOMES ----------------------------------------
#
# ⛔ DEGAT CONSTATE LE 2026-10-03, cause par le changement de source lui-meme.
# Mesure en base, 20 min apres le basculement :
#
#     LOSS      n=26  entry 88,34-90,55  exit TOUTES a 93,48  R moyen -1,00
#     WIN_TP1   n= 7  entry 88,99-89,79  exit TOUTES a 93,48  R moyen +1,80
#     WIN_TP2   n=11  entry 88,62-90,64  exit TOUTES a 93,48  R moyen +3,00
#     ... 82 lignes au total
#
# 🔑 AUCUNE n'a ete fermee par le marche : toutes par l'ecart de 3,4 % entre
# les deux instruments. Une ligne nee avec une entree Twelve Data (88-92) ne
# PEUT PAS etre jugee sur un prix courtier (93,48) — l'ecart ECRASE tous les
# stops, et le verdict est un artefact qui ressemble a un resultat.
#
# ⚠️ Et le danger se repete a CHAQUE futur changement de source pour n'importe
# quelle paire. Le garde ne porte donc pas sur le WTI : il porte sur la date.

def test_une_ligne_nee_AVANT_le_basculement_n_est_PAS_jugee(monkeypatch):
    from backend.services import backtest_service as bs
    monkeypatch.setattr(bp, "paire_du_pont", lambda p: p == "WTI/USD")
    monkeypatch.setattr(bs, "BASCULEMENT_SOURCE", "2026-10-03T00:00:00+00:00")
    assert bs._jugeable("WTI/USD", "2026-10-02T18:16:48+00:00") is False
    assert bs._jugeable("WTI/USD", "2026-10-03T07:00:00+00:00") is True


def test_les_autres_paires_ne_sont_PAS_touchees_par_le_garde(monkeypatch):
    """⚠️ Le garde ne doit pas geler les 24 autres paires."""
    from backend.services import backtest_service as bs
    monkeypatch.setattr(bp, "paire_du_pont", lambda p: p == "WTI/USD")
    monkeypatch.setattr(bs, "BASCULEMENT_SOURCE", "2026-10-03T00:00:00+00:00")
    assert bs._jugeable("XAU/USD", "2026-09-01T10:00:00+00:00") is True


def test_sans_date_de_basculement_RIEN_ne_change(monkeypatch):
    from backend.services import backtest_service as bs
    monkeypatch.setattr(bp, "paire_du_pont", lambda p: True)
    monkeypatch.setattr(bs, "BASCULEMENT_SOURCE", "")
    assert bs._jugeable("WTI/USD", "2026-01-01T00:00:00+00:00") is True


def test_une_date_illisible_ne_bloque_PAS_le_juge(monkeypatch):
    """⚠️ Un garde qui explose sur une date abimee gelerait TOUT le juge."""
    from backend.services import backtest_service as bs
    monkeypatch.setattr(bp, "paire_du_pont", lambda p: True)
    monkeypatch.setattr(bs, "BASCULEMENT_SOURCE", "2026-10-03T00:00:00+00:00")
    for d in (None, "", "hier", 42):
        assert bs._jugeable("WTI/USD", d) is True, d


# Le garde cable DANS `check_open_trades`, pas seulement la fonction.
# ⛔ Deux fois aujourd'hui le module etait juste et le cablage faux. Ici le prix
# est bien au-dela du TP : sans le garde, la ligne se ferme.

@pytest.mark.asyncio
async def test_check_open_trades_HONORE_le_garde(tmp_path, monkeypatch):
    import sqlite3
    from backend.services import backtest_service as bs

    monkeypatch.setattr(bs, "_DB_PATH", tmp_path / "backtest.db")
    bs._init_schema()
    c = sqlite3.connect(str(tmp_path / "backtest.db"), isolation_level=None)
    for pair, ne_le in (("WTI/USD", "2026-10-02T18:00:00Z"),   # AVANT
                        ("WTI/USD", "2026-10-03T09:00:00Z"),   # APRES
                        ("XAU/USD", "2026-10-02T18:00:00Z")):  # non routee
        c.execute(
            "INSERT INTO trades (pair, direction, entry_price, stop_loss, "
            "take_profit_1, take_profit_2, emitted_at, outcome) "
            "VALUES (?, 'buy', 90.0, 89.0, 93.0, 94.0, ?, 'OPEN')",
            (pair, ne_le))
    c.close()

    async def _prix(pair):
        return 93.48          # ⬆ bien au-dela de TP1=93 : ferme sans le garde

    monkeypatch.setattr(bs, "fetch_current_price", _prix)
    monkeypatch.setattr(bs, "BASCULEMENT_SOURCE", "2026-10-03T00:00:00+00:00")
    monkeypatch.setattr(bp, "paire_du_pont", lambda p: p == "WTI/USD")

    await bs.check_open_trades()

    c = sqlite3.connect(str(tmp_path / "backtest.db"))
    etats = {(r[0], r[1]): r[2] for r in c.execute(
        "SELECT pair, emitted_at, outcome FROM trades")}
    assert etats[("WTI/USD", "2026-10-02T18:00:00Z")] == "OPEN", \
        "une ligne nee sur l'autre instrument ne doit PAS etre jugee"
    assert etats[("WTI/USD", "2026-10-03T09:00:00Z")] != "OPEN"
    assert etats[("XAU/USD", "2026-10-02T18:00:00Z")] != "OPEN", \
        "le garde ne doit pas geler les paires non routees"


# --- LES ETIQUETTES DU PONT NE SONT PAS SUR LA GRILLE -------------------
#
# ⛔ MESURE DU 2026-10-03, sur le pont reel, deux appels identiques d'affilee :
#
#     page 1 : decalage_serveur_sec = -26905   1re bougie 2026-06-01T08:28:25
#     page 2 : decalage_serveur_sec = -26906   1re bougie 2026-06-01T08:28:26
#
# Les OHLC sont IDENTIQUES ; seules les etiquettes bougent, d'une seconde par
# appel, parce que `_decalage_serveur_sec()` du pont se mesure sur le DERNIER
# TICK et que le marche est ferme — le tick vieillit, le decalage derive.
#
# 🔑 Deux degats, et le second touche la PRODUCTION :
#   1. la mesure n'est pas reproductible : le banc a rendu une cellule RETENUE
#      a R=+0,4798 au 1er passage et la MEME cellule a R=-0,1530 au second ;
#   2. `echelle_agregee` range les tranches par `minute // pas * pas`. Avec des
#      etiquettes a :28, :33, :38 au lieu de :30, :35, :40, une bougie de
#      15 min est batie sur les MAUVAISES trois, et sa composition change
#      quand le decalage franchit une borne.
#
# Calibration qui tranche : regrouper les M5 en triplets consecutifs depuis le
# debut de la serie reproduit **246/246** des M15 NATIVES du courtier (100 %),
# et aucun autre depart n'en reproduit une seule. Les prix et leur ordre sont
# donc justes — il n'y a que l'etiquette a remettre sur la grille.

def test_les_etiquettes_sont_remises_sur_la_grille(monkeypatch):
    from datetime import timedelta
    t0 = datetime(2026, 6, 1, 8, 28, 25, tzinfo=timezone.utc)
    brut = [{"t": (t0 + timedelta(minutes=5 * i)).isoformat(),
             "o": 93.0, "h": 93.1, "l": 92.9, "c": 93.05, "tv": 1}
            for i in range(12)]
    cal = bp._sur_la_grille([bp._en_candle(x) for x in brut], 5)
    for c in cal:
        assert c.timestamp.second == 0 and c.timestamp.microsecond == 0
        assert c.timestamp.minute % 5 == 0, c.timestamp


def test_la_correction_est_UNIFORME_donc_l_ordre_est_garde(monkeypatch):
    from datetime import timedelta
    t0 = datetime(2026, 6, 1, 8, 28, 25, tzinfo=timezone.utc)
    brut = [{"t": (t0 + timedelta(minutes=5 * i)).isoformat(),
             "o": 90.0 + i, "h": 90.0 + i, "l": 90.0 + i, "c": 90.0 + i, "tv": 1}
            for i in range(12)]
    cal = bp._sur_la_grille([bp._en_candle(x) for x in brut], 5)
    assert [c.close for c in cal] == [90.0 + i for i in range(12)], \
        "la correction ne doit JAMAIS reordonner ni reaffecter les prix"
    ecarts = {(b.timestamp - a.timestamp).total_seconds()
              for a, b in zip(cal, cal[1:])}
    assert ecarts == {300.0}, "les bougies restent espacees de 5 minutes"


def test_deux_decalages_differents_donnent_la_MEME_grille():
    """⛔ C'est la reproductibilite : une derive d'une seconde ne doit plus
    changer le resultat de la mesure."""
    from datetime import timedelta
    grilles = []
    for seconde in (25, 26, 44):          # les trois decalages observes
        t0 = datetime(2026, 6, 1, 8, 28, seconde, tzinfo=timezone.utc)
        brut = [{"t": (t0 + timedelta(minutes=5 * i)).isoformat(),
                 "o": 93.0, "h": 93.1, "l": 92.9, "c": 93.05, "tv": 1}
                for i in range(12)]
        cal = bp._sur_la_grille([bp._en_candle(x) for x in brut], 5)
        grilles.append([c.timestamp for c in cal])
    assert grilles[0] == grilles[1] == grilles[2]


def test_une_serie_DEJA_sur_la_grille_n_est_pas_touchee():
    """⚠️ Le correctif ne doit rien faire quand il n'y a rien a corriger."""
    from datetime import timedelta
    t0 = datetime(2026, 6, 1, 8, 30, tzinfo=timezone.utc)
    brut = [{"t": (t0 + timedelta(minutes=5 * i)).isoformat(),
             "o": 93.0, "h": 93.1, "l": 92.9, "c": 93.05, "tv": 1}
            for i in range(12)]
    bougies = [bp._en_candle(x) for x in brut]
    cal = bp._sur_la_grille(bougies, 5)
    assert [c.timestamp for c in cal] == [b.timestamp for b in bougies]


def test_une_serie_trop_courte_n_est_pas_corrigee():
    """⚠️ Une mediane sur une bougie n'est pas une calibration."""
    b = [bp._en_candle({"t": "2026-06-01T08:28:25+00:00", "o": 93.0,
                        "h": 93.1, "l": 92.9, "c": 93.05, "tv": 1})]
    assert bp._sur_la_grille(b, 5) == b


@pytest.mark.asyncio
async def test_fetch_candles_rend_des_bougies_SUR_LA_GRILLE(pont):
    """Le câblage : `fetch_candles` doit appliquer la correction."""
    from datetime import timedelta
    t0 = datetime(2026, 6, 1, 8, 28, 25, tzinfo=timezone.utc)
    pont["reponse"] = {"bougies": [
        {"t": (t0 + timedelta(minutes=5 * i)).isoformat(), "o": 93.0,
         "h": 93.1, "l": 92.9, "c": 93.05, "tv": 1} for i in range(20)]}
    bougies = await bp.fetch_candles("WTI/USD", "5min", 20)
    assert bougies, "la reponse doublee doit produire des bougies"
    for c in bougies:
        assert c.timestamp.second == 0 and c.timestamp.minute % 5 == 0, c.timestamp


def test_un_CHANGEMENT_D_HEURE_au_milieu_de_la_serie(monkeypatch):
    """⛔ POURQUOI UN RESIDU MEDIAN UNIQUE NE SUFFIT PAS. La fenetre du banc
    couvre 412 jours : elle traverse des changements d'heure, donc le decalage
    serveur CHANGE au milieu. Un residu global est alors faux pour une moitie
    de la serie, et lequel est median peut basculer d'un appel a l'autre —
    c'est ce qui laissait les chargements instables malgre la 1re correction.
    """
    from datetime import timedelta
    moitie1 = [datetime(2026, 6, 1, 8, 28, 25, tzinfo=timezone.utc)
               + timedelta(minutes=5 * i) for i in range(20)]
    # +1 h de decalage : les etiquettes passent a :28:25 de l'autre regime
    # ⚠️ +240 s, le second regime MESURE en vrai. Une heure n'aurait rien
    # prouve : 3 600 est un multiple de 300, donc le residu serait identique.
    moitie2 = [datetime(2026, 11, 1, 8, 32, 25, tzinfo=timezone.utc)
               + timedelta(minutes=5 * i) for i in range(20)]
    brut = [{"t": t.isoformat(), "o": 93.0, "h": 93.1, "l": 92.9,
             "c": 93.05, "tv": 1} for t in moitie1 + moitie2]
    cal = bp._sur_la_grille([bp._en_candle(x) for x in brut], 5)
    for c in cal:
        assert c.timestamp.second == 0 and c.timestamp.minute % 5 == 0, \
            f"{c.timestamp} — les DEUX regimes doivent etre sur la grille"
    ecarts = {(b.timestamp - a.timestamp).total_seconds()
              for a, b in zip(cal[:20], cal[1:20])}
    assert ecarts == {300.0}


def test_une_derive_d_une_seconde_ne_change_RIEN_meme_avec_deux_regimes():
    """La reproductibilite, dans le cas qui l'avait cassee en vrai."""
    from datetime import timedelta
    grilles = []
    for d in (0, 1, 2):
        m1 = [datetime(2026, 6, 1, 8, 28, 25 + d, tzinfo=timezone.utc)
              + timedelta(minutes=5 * i) for i in range(20)]
        m2 = [datetime(2026, 11, 1, 8, 32, 25 + d, tzinfo=timezone.utc)
              + timedelta(minutes=5 * i) for i in range(20)]
        brut = [{"t": t.isoformat(), "o": 93.0, "h": 93.1, "l": 92.9,
                 "c": 93.05, "tv": 1} for t in m1 + m2]
        cal = bp._sur_la_grille([bp._en_candle(x) for x in brut], 5)
        grilles.append([c.timestamp for c in cal])
    assert grilles[0] == grilles[1] == grilles[2]
