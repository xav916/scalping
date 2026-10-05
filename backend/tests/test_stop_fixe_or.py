"""Le stop de l'or est un POURCENTAGE DU PRIX — plus un montant fixe en euros.

## ⛔ POURQUOI LA REGLE CHANGE, le 2026-10-05

Xavier avait fixe le stop de l'or a **10 €** le 2026-10-02. Ce jour-la l'or a
produit **10 ordres**, son record. Puis plus rien pendant trois jours.

🔑 La cause, mesuree le 05/10 : la **porte des frais**. Elle ne regarde pas le
spread — elle facture le rapport NOTIONNEL / RISQUE :

    cout_R = (entree / distance_du_stop) x 0,00005 x 2 jambes

Un stop fixe en euros devient RELATIVEMENT plus serre a mesure que l'or monte.
A 4 129 $, 11,20 $ ne valent plus que **0,271 %** du prix :

    cout = (4129 / 11,20) x 1e-4 = 0,03688 R
    plafond = 30 % d'un edge declare a 0,10 = 0,0300 R     ⇒ BLOQUE de 23 %

**La porte s'est refermee toute seule, par la hausse de l'or.** Ni bug, ni
panne, ni verdict de banc : de la geometrie.

⚠️ Et le 2 octobre elle passait : l'or valait moins cher, donc 11,20 $ pesaient
relativement plus.

## La regle qui remplace

Un stop en **pourcentage du prix** : il suit le cours, donc la porte ne peut
plus se refermer par derive.

🔑 **Le pourcentage n'est pas choisi pour « passer »** — c'est le modele de
cout lui-meme qui dit a partir de quelle largeur un trade est viable :

    distance minimale = entree x 1e-4 / 0,0300 = 0,333 % du prix

On pose **0,35 %**, soit le seuil de viabilite du modele plus une marge. Un
stop plus serre serait declare non rentable par le systeme lui-meme.

⚠️ Ce que cela coute : le risque par trade n'est plus fixe en euros. A 4 129 $
il vaut 14,45 $ soit ~12,8 € — **28 % de plus** que les 10 € decides le 02/10.
C'est le prix d'un stop que la porte accepte.

## ⛔ Ce qui n'est PAS fait

La regle GLOBALE `distance_sl_pourcentage` reste **inerte**. La cabler pour
toutes les paires casse les quatre controles du laboratoire
(cf. `test_stop_pourcentage_prix.py`). L'or, lui, avait DEJA un stop uniforme
depuis le 02/10 : on passe d'un uniforme en euros a un uniforme en pourcentage,
sans rien changer a sa structure.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.models.schemas import Candle
from backend.services import pattern_detector as pd


PRIX = 4150.0


def _bougies(n=60, base=PRIX):
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


def _motif(nom="momentum_up"):
    """Un motif construit A LA MAIN.

    ⚠️ La 1re version passait par `detect_patterns` sur une serie synthetique —
    qui ne declenchait AUCUN motif, et le test echouait pour une raison sans
    rapport avec ce qu'il mesure. On teste `calculate_trade_setup`, pas les
    detecteurs.
    """
    from backend.models.schemas import PatternDetection, PatternType
    return PatternDetection(pattern=PatternType(nom), confidence=0.75,
                            description="construit pour le test",
                            detected_at=datetime(2026, 10, 2, 9, 0,
                                                 tzinfo=timezone.utc))


def _setup_or(nom="momentum_up", bougies=None):
    b = bougies or _bougies()
    return pd.calculate_trade_setup("XAU/USD", _motif(nom), b), b


# ─── La distance, en pourcentage ────────────────────────────────────────────

def test_la_distance_de_l_or_est_un_POURCENTAGE_du_prix():
    d = pd._distance_sl_or(4129.0)
    assert d == pytest.approx(4129.0 * pd.XAU_SL_PCT / 100.0)
    assert d == pytest.approx(14.45, abs=0.05)


def test_elle_SUIT_le_cours_au_lieu_de_se_figer():
    """⛔ LE DEFAUT QUE CETTE REGLE CORRIGE. Un montant fixe devient
    relativement plus serre quand l'or monte, jusqu'a passer sous le seuil de
    viabilite de la porte des frais — sans que rien ne le dise."""
    bas, haut = pd._distance_sl_or(3000.0), pd._distance_sl_or(5000.0)
    assert haut > bas
    assert bas / 3000.0 == pytest.approx(haut / 5000.0), \
        "la proportion doit etre constante, c'est tout l'interet"


def test_le_pourcentage_FRANCHIT_le_seuil_de_la_porte_des_frais():
    """🔑 Le seuil n'est pas invente : il se deduit du modele de cout.

        cout = (entree / distance) x taux_par_jambe x 2   doit rester
        sous 30 % d'un edge de 0,10, soit 0,0300 R
        ⇒ distance > entree x 1e-4 / 0,03 = 0,333 % du prix
    """
    taux_par_jambe, edge, part = 5e-05, 0.10, 0.30
    mini_pct = (taux_par_jambe * 2 / (part * edge)) * 100.0
    assert mini_pct == pytest.approx(0.3333, abs=1e-3)
    assert pd.XAU_SL_PCT > mini_pct, (
        f"{pd.XAU_SL_PCT} % ne franchit pas le seuil de viabilite "
        f"{mini_pct:.4f} % — l'or resterait bloque")
    for prix in (2000.0, 4129.0, 8000.0):
        cout = (prix / pd._distance_sl_or(prix)) * taux_par_jambe * 2
        assert cout < part * edge, f"a {prix} $ le cout {cout:.5f} depasse"


def test_le_reglage_se_change_SANS_redeploiement(monkeypatch):
    monkeypatch.setattr(pd, "XAU_SL_PCT", 0.50)
    assert pd._distance_sl_or(4000.0) == pytest.approx(20.0)


def test_un_pourcentage_NUL_ou_un_prix_absent_rend_None():
    """Repli sur l'ATR plutot qu'un stop de taille inconnue."""
    assert pd._distance_sl_or(0) is None
    assert pd._distance_sl_or(None) is None


def test_un_pourcentage_nul_desarme_la_regle(monkeypatch):
    monkeypatch.setattr(pd, "XAU_SL_PCT", 0.0)
    assert pd._distance_sl_or(4000.0) is None


# ─── Le setup complet ───────────────────────────────────────────────────────

def test_un_achat_or_a_son_stop_SOUS_l_entree_a_la_bonne_distance():
    s, _ = _setup_or("momentum_up")
    assert s is not None
    attendu = s.entry_price * pd.XAU_SL_PCT / 100.0
    assert s.entry_price - s.stop_loss == pytest.approx(attendu, abs=0.02)


def test_une_vente_or_a_son_stop_AU_DESSUS_de_l_entree():
    s, _ = _setup_or("momentum_down")
    assert s is not None
    attendu = s.entry_price * pd.XAU_SL_PCT / 100.0
    assert s.stop_loss - s.entry_price == pytest.approx(attendu, abs=0.02)


def test_la_cible_reste_un_MULTIPLE_du_risque():
    s, _ = _setup_or("momentum_up")
    assert s is not None
    risque = abs(s.entry_price - s.stop_loss)
    gain = abs(s.take_profit_1 - s.entry_price)
    assert gain / risque == pytest.approx(pd.PATTERN_TP1_RR, abs=0.05)


def test_les_AUTRES_paires_gardent_le_stop_ATR():
    """⛔ La regle est propre a l'or. L'etendre en silence changerait le risque
    de tout le compte."""
    b = [Candle(timestamp=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)
                + timedelta(minutes=5 * i),
                open=1.16 + (i % 5) * 0.0004, high=1.1615 + (i % 5) * 0.0004,
                low=1.1585 + (i % 5) * 0.0004, close=1.1605 + (i % 5) * 0.0004,
                volume=100) for i in range(60)]
    s = pd.calculate_trade_setup("EUR/USD", _motif("momentum_up"), b)
    if s is None:
        pytest.skip("pas de setup produit")
    d = abs(s.entry_price - s.stop_loss)
    assert d != pytest.approx(s.entry_price * pd.XAU_SL_PCT / 100.0, abs=1e-6), \
        "EUR/USD a herite de la regle de l'or"


def test_l_ARGENT_ne_suit_PAS_la_regle_de_l_or():
    """⚠️ `_est_de_l_or` teste « XAU », pas « metal » : XAG garde l'ATR."""
    assert pd._est_de_l_or("XAU/USD") is True
    assert pd._est_de_l_or("XAG/USD") is False
    assert pd._est_de_l_or("WTI/USD") is False


# ─── Le laboratoire garde SON stop ──────────────────────────────────────────

def test_le_LABORATOIRE_garde_l_ATR_quoi_que_fasse_la_production():
    """⛔ LE DEFAUT QUE CE DRAPEAU FERME, et il etait DEJA EN PRODUCTION.

    Le laboratoire appelle `calculate_trade_setup`. Avec un stop uniforme sur
    l'or, toutes ses cellules portent le MEME risque — et son controle
    aleatoire, apparie au risque median, devient indiscernable des cellules
    qu'il doit departager. Mesure : controle +1,599 contre +1,572 pour la
    meilleure cellule, et certaines series ne produisent PLUS AUCUNE cellule
    peuplee.

    ⚠️ Ce n'etait pas theorique : le stop fixe a 10 € est en production depuis
    le 2026-10-02. Les tests ne le voyaient pas parce que `_eur_usd_courant()`
    rend `None` hors production — l'or y retombait sur l'ATR et les controles
    passaient PAR ACCIDENT.
    """
    b = _bougies()
    prod = pd.calculate_trade_setup("XAU/USD", _motif("momentum_up"), b)
    labo = pd.calculate_trade_setup("XAU/USD", _motif("momentum_up"), b,
                                    stop_uniforme=False)
    assert prod is not None and labo is not None
    d_prod = abs(prod.entry_price - prod.stop_loss)
    d_labo = abs(labo.entry_price - labo.stop_loss)
    assert d_prod == pytest.approx(prod.entry_price * pd.XAU_SL_PCT / 100.0,
                                   abs=0.02), "la production a perdu sa regle"
    assert d_labo != pytest.approx(d_prod, abs=0.02), \
        "le laboratoire a herite du stop uniforme — son controle est aveugle"


def test_le_drapeau_ne_change_RIEN_pour_les_autres_paires():
    """Il ne concerne que l'or : ailleurs l'ATR s'applique dans les deux cas."""
    b = [Candle(timestamp=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)
                + timedelta(minutes=5 * i),
                open=1.16 + (i % 5) * 0.0004, high=1.1615 + (i % 5) * 0.0004,
                low=1.1585 + (i % 5) * 0.0004, close=1.1605 + (i % 5) * 0.0004,
                volume=100) for i in range(60)]
    a = pd.calculate_trade_setup("EUR/USD", _motif("momentum_up"), b)
    c = pd.calculate_trade_setup("EUR/USD", _motif("momentum_up"), b,
                                 stop_uniforme=False)
    if a is None or c is None:
        pytest.skip("pas de setup produit")
    assert abs(a.entry_price - a.stop_loss) == pytest.approx(
        abs(c.entry_price - c.stop_loss), abs=1e-9)


def test_le_laboratoire_appelle_bien_avec_le_drapeau():
    """⚠️ Verrou de forme, assume : un test de comportement ne peut pas
    atteindre l'appel du laboratoire sans sa base ni son reseau. Il vient EN
    PLUS, jamais a la place."""
    import inspect
    from backend.services import laboratoire_or
    src = inspect.getsource(laboratoire_or.detections)
    assert "stop_uniforme=False" in src, (
        "le laboratoire a perdu son stop propre : il mesurerait l'or a risque "
        "uniforme, et son controle aleatoire serait aveugle")
