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
