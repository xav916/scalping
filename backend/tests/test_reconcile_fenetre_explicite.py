"""La SOUDURE : `fetch_5min_for_window` sait enfin demander une PLAGE DE DATES.

Posee le 2026-10-26. Les deux paliers de rattrapage ont repare le PASSE (21 805
setups), mais le chemin de production gardait la cause racine : il demandait
`outputsize=1500` puis filtrait, soit ~5,2 jours de couverture. Si la
reconciliation s'arrete plus de 5 jours, **le trou se reouvre a l'identique**.

⛔ CE QUE CES TESTS PROTEGENT, ET POURQUOI L'ORDRE COMPTE. La plage de dates
n'est tentee QU'APRES l'echec du chemin rapide. Ce n'est pas un detail de
performance : le chemin rapide lit un cache de 200 s et coute UNE requete, alors
que le plan Twelve Data donne 55 credits par MINUTE partages avec le cycle qui
trade. Mettre la plage de dates en premier ferait 50 requetes non cachees par
passage de reconciliation et affamerait la detection.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from backend.models.schemas import Candle
from backend.services import shadow_reconciliation as recon


def _bougies(debut: datetime, n: int) -> list[Candle]:
    return [Candle(timestamp=debut + timedelta(minutes=5 * i),
                   open=1.0, high=1.1, low=0.9, close=1.0, volume=0)
            for i in range(n)]


@pytest.fixture
def espions(monkeypatch):
    """Instrumente les trois voies, et neutralise le repli DB locale."""
    trace: dict[str, list] = {"rapide": [], "td": [], "binance": [], "pont": []}

    async def _rapide(pair, interval="5min", outputsize=50):
        trace["rapide"].append((pair, outputsize))
        return trace.get("_rapide_rend", []), False

    async def _td(pair, interval, debut, fin, **kw):
        trace["td"].append((pair, debut, fin))
        return trace.get("_td_rend", [])

    async def _binance(pair, interval, debut, fin, **kw):
        trace["binance"].append((pair, debut, fin))
        return trace.get("_binance_rend", [])

    import backend.services.price_service as ps
    import backend.services.binance_klines_service as bks
    import backend.services.bougies_du_pont as pont

    monkeypatch.setattr(ps, "fetch_candles", _rapide)
    monkeypatch.setattr(ps, "fetch_candles_fenetre", _td)
    monkeypatch.setattr(bks, "fetch_klines_fenetre", _binance)
    monkeypatch.setattr(pont, "paire_du_pont",
                        lambda p: trace.get("_pont") == p)
    monkeypatch.setattr(recon, "_REPLI_DB_LOCALE", False)
    recon.reinitialise_budget_fenetres()
    return trace


def test_une_fenetre_RECENTE_n_appelle_PAS_la_plage_de_dates(espions):
    """Coût nul en regime normal : le chemin rapide suffit et il est cache."""
    debut = datetime.now(timezone.utc) - timedelta(hours=10)
    espions["_rapide_rend"] = _bougies(debut, 20)

    sortie = asyncio.run(recon.fetch_5min_for_window(
        "EUR/USD", debut, debut + timedelta(hours=1)))

    assert sortie, "le chemin rapide devait suffire"
    assert espions["rapide"], "le chemin rapide n'a pas ete tente"
    assert espions["td"] == [], "plage de dates appelee pour rien"
    assert espions["binance"] == [], "plage de dates appelee pour rien"


def test_une_fenetre_ANCIENNE_passe_par_la_PLAGE_DE_DATES(espions):
    """LE COEUR DE LA SOUDURE.

    Chemin rapide vide sur une fenetre d'aout : c'est le cas exact qui a laisse
    22 592 setups bloques 65 jours. Desormais on redemande avec des bornes.
    """
    debut = datetime(2026, 8, 20, 4, tzinfo=timezone.utc)
    espions["_rapide_rend"] = []
    espions["_td_rend"] = _bougies(debut, 30)

    sortie = asyncio.run(recon.fetch_5min_for_window(
        "EUR/USD", debut, debut + timedelta(hours=2)))

    assert len(sortie) == 30, "la plage de dates n'a pas servi"
    assert espions["td"] == [("EUR/USD", debut, debut + timedelta(hours=2))], \
        espions["td"]


def test_la_CRYPTO_va_chez_BINANCE_et_pas_chez_TWELVE_DATA(espions):
    """Meme routage que la cascade de production.

    ⛔ Twelve Data cote les cryptos en « forex-routed » : volume a 0 et
    contrat different de celui que Binance publie. Resoudre un setup BTC avec
    ces prix melangerait deux sources dans la meme colonne.
    """
    debut = datetime(2026, 8, 20, 4, tzinfo=timezone.utc)
    espions["_rapide_rend"] = []
    espions["_binance_rend"] = _bougies(debut, 12)

    sortie = asyncio.run(recon.fetch_5min_for_window(
        "BTC/USD", debut, debut + timedelta(hours=1)))

    assert len(sortie) == 12
    assert espions["binance"], "la crypto n'est pas passee par Binance"
    assert espions["td"] == [], "la crypto est passee par Twelve Data"


def test_une_paire_du_PONT_ne_demande_RIEN_a_TWELVE_DATA(espions):
    """XAU et WTI sont cotes par le COURTIER.

    ⛔ Mesure deja inscrite dans la cascade : sur le WTI, Twelve Data divergeait
    de 3,394 % du contrat reellement trade. Un ecart de 3,4 % ECRASE n'importe
    quel stop, donc chaque setup serait declare touche a tort.
    🔑 Mieux vaut un setup qui RESTE en file qu'une issue fabriquee.
    """
    debut = datetime(2026, 8, 20, 4, tzinfo=timezone.utc)
    espions["_pont"] = "XAU/USD"
    espions["_rapide_rend"] = []
    espions["_td_rend"] = _bougies(debut, 50)

    sortie = asyncio.run(recon.fetch_5min_for_window(
        "XAU/USD", debut, debut + timedelta(hours=1)))

    assert sortie == [], "l'or a ete resolu avec des prix d'un autre contrat"
    assert espions["td"] == [], espions["td"]
    assert espions["binance"] == [], espions["binance"]


def test_le_nombre_de_PLAGES_par_passage_est_BORNE(espions):
    """Un passage de reconciliation sert 50 setups : sans plafond, 50 requetes
    non cachees par passage videraient les 55 credits/min de la production.
    """
    debut = datetime(2026, 8, 20, 4, tzinfo=timezone.utc)
    espions["_rapide_rend"] = []
    espions["_td_rend"] = _bougies(debut, 5)

    for i in range(recon.FENETRES_MAX_PAR_RUN + 7):
        asyncio.run(recon.fetch_5min_for_window(
            f"P{i}/USD", debut, debut + timedelta(hours=1)))

    assert len(espions["td"]) == recon.FENETRES_MAX_PAR_RUN, (
        len(espions["td"]), recon.FENETRES_MAX_PAR_RUN)


def test_le_budget_de_plages_est_REMIS_A_ZERO_a_chaque_passage(espions):
    """Sinon le premier passage le consomme et plus aucun autre n'en a.

    ⛔ Un plafond qui ne se recharge pas n'est pas un plafond, c'est un
    interrupteur a usage unique -- et il serait MUET.
    """
    debut = datetime(2026, 8, 20, 4, tzinfo=timezone.utc)
    espions["_rapide_rend"] = []
    espions["_td_rend"] = _bougies(debut, 5)

    for i in range(recon.FENETRES_MAX_PAR_RUN + 3):
        asyncio.run(recon.fetch_5min_for_window(
            f"A{i}/USD", debut, debut + timedelta(hours=1)))
    epuise = len(espions["td"])

    recon.reinitialise_budget_fenetres()
    asyncio.run(recon.fetch_5min_for_window(
        "B/USD", debut, debut + timedelta(hours=1)))

    assert len(espions["td"]) == epuise + 1, "le budget ne s'est pas recharge"


def test_l_EPUISEMENT_du_budget_est_JOURNALISE(espions, caplog):
    """Se taire ferait croire la periode couverte. 🔑 La lecon du matin."""
    import logging

    debut = datetime(2026, 8, 20, 4, tzinfo=timezone.utc)
    espions["_rapide_rend"] = []
    espions["_td_rend"] = _bougies(debut, 5)

    with caplog.at_level(logging.WARNING,
                         logger="backend.services.shadow_reconciliation"):
        for i in range(recon.FENETRES_MAX_PAR_RUN + 2):
            asyncio.run(recon.fetch_5min_for_window(
                f"C{i}/USD", debut, debut + timedelta(hours=1)))

    lignes = [r.getMessage() for r in caplog.records]
    assert any("budget" in l.lower() or "plafond" in l.lower() for l in lignes), \
        lignes


def test_une_plage_VIDE_rend_vide_sans_lever(espions):
    """La source a ete correctement interrogee et n'a rien : c'est un fait."""
    debut = datetime(2026, 8, 20, 4, tzinfo=timezone.utc)
    espions["_rapide_rend"] = []
    espions["_td_rend"] = []

    sortie = asyncio.run(recon.fetch_5min_for_window(
        "EUR/USD", debut, debut + timedelta(hours=1)))

    assert sortie == []
    assert espions["td"], "la plage de dates n'a meme pas ete tentee"
