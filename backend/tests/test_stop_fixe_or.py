"""Le stop de l'or vaut DIX EUROS de l'entree — pas 10,85 dollars figes.

Decision de Xavier le 2026-10-02 : << tous les trades OR ont desormais un SL a
10 euros de l'entree >>.

⛔ **La premiere implementation posait un litteral en DOLLARS** —
`pip_distance = 10.85`, commente << ~10 euros >>. Mesure le jour meme avec
`risk_eur.calculer` au lot minimum :

    stop 10,85 $  ->   9,39 EUR        <- ce que le litteral livrait
    stop 11,55 $  ->  10,00 EUR        <- ce qui etait demande
    taux implicite EUR/USD : 1,1547

**6,1 % de moins que demande**, et l'ecart grandit a chaque mouvement de
l'EUR/USD sans que rien ne le dise. C'est le piege d'unite que ce depot a deja
paye deux fois : un montant en euros ecrit en devise de cotation.

🔑 **Le reglage est donc en EUROS**, et la distance de prix s'en deduit au taux
courant. L'or est plafonne a `0,01 lot` chez le courtier
(`max_lot_per_class: {metal: 0.01}`) et `0,01 lot = 1 once`
(`contract_size 100`, `volume_min 0,01`, lus sur `/symbol_specs`) : la distance
de prix en dollars vaut donc exactement `euros x EUR/USD`.

⚠️ **Repli sur l'ATR si le taux est illisible.** Poser un stop de taille
inconnue sur l'argent reel est pire que de garder l'ancien. On ne devine pas un
taux.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.models.schemas import Candle
from backend.services import pattern_detector as pd


TAUX = 1.1547          # EUR/USD mesure le 2026-10-02
ATTENDU_USD = 10.0 * TAUX   # 11,547 $ pour 10 €


def _bougies(n=60, base=4150.0):
    """Une serie d'or plausible, assez longue pour l'ATR et les detecteurs."""
    t0 = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)
    out = []
    for i in range(n):
        o = base + (i % 7) * 0.9 - 3
        c = o + ((-1) ** i) * 1.4
        out.append(Candle(timestamp=t0 + timedelta(minutes=5 * i),
                          open=o, high=max(o, c) + 2.2,
                          low=min(o, c) - 2.2, close=c, volume=100))
    return out


@pytest.fixture
def taux(monkeypatch):
    monkeypatch.setattr(pd, "_eur_usd_courant", lambda: TAUX, raising=False)


# --- La distance, en euros ----------------------------------------------

def test_la_distance_de_l_or_vaut_dix_euros_au_taux_courant(taux):
    assert pd._distance_sl_or() == pytest.approx(ATTENDU_USD)


def test_le_reglage_est_en_EUROS_et_se_change_sans_redeploiement(monkeypatch, taux):
    monkeypatch.setattr(pd, "XAU_SL_FIXE_EUR", 25.0, raising=False)
    assert pd._distance_sl_or() == pytest.approx(25.0 * TAUX)


def test_un_taux_illisible_ne_rend_PAS_une_distance(monkeypatch):
    """⛔ On ne devine pas un taux : sans lui, pas de stop fixe."""
    monkeypatch.setattr(pd, "_eur_usd_courant", lambda: None, raising=False)
    assert pd._distance_sl_or() is None
    monkeypatch.setattr(pd, "_eur_usd_courant", lambda: 0.0, raising=False)
    assert pd._distance_sl_or() is None


# --- Appliquee au setup --------------------------------------------------

def test_un_achat_or_a_son_stop_a_dix_euros_SOUS_l_entree(taux):
    bougies = _bougies()
    motif = pd.PatternDetection(pattern=pd.PatternType.MOMENTUM_UP,
                                confidence=0.7, description="",
                                detected_at=datetime.now(timezone.utc))
    s = pd.calculate_trade_setup("XAU/USD", motif, bougies)
    assert s is not None
    assert s.entry_price - s.stop_loss == pytest.approx(ATTENDU_USD, abs=0.02)


def test_une_vente_or_a_son_stop_a_dix_euros_AU_DESSUS(taux):
    bougies = _bougies()
    motif = pd.PatternDetection(pattern=pd.PatternType.MOMENTUM_DOWN,
                                confidence=0.7, description="",
                                detected_at=datetime.now(timezone.utc))
    s = pd.calculate_trade_setup("XAU/USD", motif, bougies)
    assert s is not None
    assert s.stop_loss - s.entry_price == pytest.approx(ATTENDU_USD, abs=0.02)


def test_la_cible_reste_un_multiple_du_risque(taux):
    """Le stop change, le rapport gain/risque NON : TP1 = 1,8 R."""
    bougies = _bougies()
    motif = pd.PatternDetection(pattern=pd.PatternType.MOMENTUM_UP,
                                confidence=0.7, description="",
                                detected_at=datetime.now(timezone.utc))
    s = pd.calculate_trade_setup("XAU/USD", motif, bougies)
    risque = s.entry_price - s.stop_loss
    assert (s.take_profit_1 - s.entry_price) / risque == pytest.approx(
        pd.PATTERN_TP1_RR, abs=0.01)


def test_le_risque_en_euros_vaut_bien_DIX(taux):
    """⛔ La verification qui compte : on repasse par `risk_eur`, l'appareil
    qui a montre que 10,85 $ valait 9,39 €."""
    from backend.services.risk_eur import calculer
    bougies = _bougies()
    motif = pd.PatternDetection(pattern=pd.PatternType.MOMENTUM_UP,
                                confidence=0.7, description="",
                                detected_at=datetime.now(timezone.utc))
    s = pd.calculate_trade_setup("XAU/USD", motif, bougies)
    r = calculer(pair="XAU/USD", entry=s.entry_price, sl=s.stop_loss,
                 tp=s.take_profit_1, volume=0.01, bridge_type="mt5",
                 eur_usd=TAUX)
    assert r["risque_eur"] == pytest.approx(10.0, abs=0.05)


# --- Ce qui ne doit PAS changer -----------------------------------------

def test_les_AUTRES_paires_gardent_le_stop_ATR(taux):
    """⛔ << tous les trades OR >> veut dire l'or. Le reste est intact."""
    bougies = _bougies(base=1.1700)
    bougies = [Candle(timestamp=b.timestamp, open=b.open / 3547, high=b.high / 3547,
                      low=b.low / 3547, close=b.close / 3547, volume=b.volume)
               for b in bougies]
    motif = pd.PatternDetection(pattern=pd.PatternType.MOMENTUM_UP,
                                confidence=0.7, description="",
                                detected_at=datetime.now(timezone.utc))
    s = pd.calculate_trade_setup("EUR/USD", motif, bougies)
    if s is None:
        pytest.skip("pas de setup sur cette serie — le test ne porte pas sur l'or")
    distance = abs(s.entry_price - s.stop_loss)
    assert distance != pytest.approx(ATTENDU_USD, abs=0.02)


def test_sans_taux_l_or_RETOMBE_sur_l_ATR_au_lieu_de_refuser(monkeypatch):
    """⚠️ Le repli : un stop de taille inconnue serait pire que l'ancien,
    mais ne rien produire couperait le flux pour une panne de taux."""
    monkeypatch.setattr(pd, "_eur_usd_courant", lambda: None, raising=False)
    bougies = _bougies()
    motif = pd.PatternDetection(pattern=pd.PatternType.MOMENTUM_UP,
                                confidence=0.7, description="",
                                detected_at=datetime.now(timezone.utc))
    s = pd.calculate_trade_setup("XAU/USD", motif, bougies)
    assert s is not None, "le repli doit produire un setup, pas rien"
    assert abs(s.entry_price - s.stop_loss) != pytest.approx(ATTENDU_USD, abs=0.02)
