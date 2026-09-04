"""Porte de rapport gain/risque sur le retour au POC (2026-09-04).

Mesuré sur 414 setups réels (BTC, ETH, SOL — 3 ans), la stratégie telle que je
l'avais spécifiée produisait :

    R:R médian 0,84  ·  59 % des setups sous 1,0  ·  54 % de réussite requise

⛔ **Ce déséquilibre vient de MES règles, pas de la méthode d'origine.** Le stop
descend sous la zone de valeur — large, puisqu'elle couvre 70 % du temps — et
la cible vise le niveau de liquidité le plus proche, souvent proche. Sur mon
jeu d'essai synthétique j'obtenais 5,62 et je l'ai présenté comme une
validation : la liquidité y était loin et la zone étroite.

Seuil mesuré, pas choisi :

    seuil   retenus   R:R médian   réussite requise
     0,0     100 %       0,84           54 %
     1,0      41 %       1,65           38 %      <- retenu
     1,5      24 %       2,15           32 %
     2,0      14 %       2,68           27 %

1,0 est le saut décisif — 54 % vers 38 % de réussite requise, en gardant 41 %
du volume. Au-delà on paie cher en signaux pour peu de gain, et le banc d'essai
a besoin d'accumuler.

🔑 Posé MAINTENANT parce que l'échantillon réel ne compte que 2 signaux :
corriger aujourd'hui ne coûte rien, corriger dans trois semaines remettrait le
compteur à zéro.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.models.schemas import Candle, PatternDetection, PatternType


def _c(h, b, i, close=None):
    m = (h + b) / 2
    return Candle(timestamp=datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(hours=i),
                  open=m, high=h, low=b, close=close if close is not None else m,
                  volume=0.0)


def _tendance_avec_retour(cible_haute=112):
    """Structure haussière puis retour au POC ; `cible_haute` règle le R:R."""
    acc = [(100.6, 99.4), (100.2, 99.8), (100.9, 99.1), (100.3, 99.7),
           (100.5, 99.5), (101.0, 99.0), (100.4, 99.6), (100.7, 99.3),
           (100.1, 99.9), (100.8, 99.2)] * 3
    h = cible_haute
    montee = [(102, 101), (103, 102), (105, 103), (103.5, 102), (102.5, 101.5),
              (104, 102.5), (106, 104), (108, 106), (106.5, 105), (105.5, 104),
              (107, 105.5), (109, 107), (h, 109), (h - 2, 108), (h - 3, 107.5)]
    b = [_c(x, y, i) for i, (x, y) in enumerate(acc + montee)]
    b.append(_c(101.5, 100.2, len(b), close=100.7))
    return b


def test_un_rapport_suffisant_produit_bien_un_setup():
    from backend.services import pattern_detector as pd

    bougies = _tendance_avec_retour(cible_haute=112)
    setup = pd.calculate_trade_setup(
        "WTI/USD", pd._detect_poc_return(bougies, "WTI/USD")[0], bougies)

    assert setup is not None
    assert setup.risk_reward_1 >= pd.POC_RR_MIN


def test_un_rapport_INSUFFISANT_ne_produit_AUCUN_setup(monkeypatch):
    """⛔ Aucun setup — et surtout PAS un repli sur les niveaux génériques.

    Le chemin générique dérive le stop d'un ATR et la cible d'un R:R fixe : un
    `poc_return` construit ainsi ne serait plus la stratégie, juste un trade
    portant son nom. C'était le comportement de ma première version.
    """
    from backend.services import pattern_detector as pd

    bougies = _tendance_avec_retour(cible_haute=112)
    motifs = pd._detect_poc_return(bougies, "WTI/USD")
    assert motifs, "le jeu d'essai doit produire un motif"

    # Seuil relevé au-dessus de ce que ce setup offre : il doit disparaître,
    # pas se transformer en trade générique.
    monkeypatch.setattr(pd, "POC_RR_MIN", 999.0, raising=False)
    assert pd.calculate_trade_setup("WTI/USD", motifs[0], bougies) is None


def test_les_AUTRES_motifs_ne_sont_PAS_soumis_a_cette_porte(monkeypatch):
    """⚠️ Le seuil est propre au retour au POC.

    L'appliquer aux motifs de forme changerait le comportement de tout le
    système pour un raisonnement qui ne les concerne pas — ils tirent leur
    cible d'un R:R fixe de 1,8, pas d'un niveau observé.
    """
    from backend.services import pattern_detector as pd

    bougies = _tendance_avec_retour()
    monkeypatch.setattr(pd, "POC_RR_MIN", 999.0, raising=False)
    autre = PatternDetection(
        pattern=PatternType.MOMENTUM_UP, confidence=0.7,
        description="", detected_at=datetime.now(timezone.utc))

    assert pd.calculate_trade_setup("WTI/USD", autre, bougies) is not None, (
        "un motif de forme ne doit pas être filtré par la porte du POC")


def test_le_seuil_est_declare_et_vaut_1():
    """Le seuil vit dans une constante nommée, pas en nombre magique."""
    from backend.services import pattern_detector as pd
    assert pd.POC_RR_MIN == 1.0
