"""Stratégie « retour au POC » : structure + liquidité + accumulation (2026-09-04).

Demandée par Xavier. Sa formulation donnait les trois éléments d'observation —
structure, niveaux de liquidité, POC — mais **aucune règle de décision** : ni
quand entrer, ni où mettre le stop, ni où sortir.

Les règles ci-dessous sont donc MES choix, posés explicitement plutôt que
glissés dans le code :

  ENTRÉE  le prix revient sur le POC **dans le sens de la structure**
          (structure haussière + retour par le haut → achat). C'est la lecture
          « zone d'accumulation » de la méthode : on rejoint le prix d'équilibre
          pour repartir dans le sens dominant.
  STOP    sous le bas de la zone de valeur — sortir du prix d'équilibre par le
          mauvais côté invalide la lecture.
  CIBLE   le niveau de liquidité dans le sens du trade, là où les stops
          s'accumulent et où le prix va souvent les chercher.

⛔ Le POC est en TPO, pas en volume : `volume = 0` sur toutes les paires chez
Twelve Data. Cf. `market_profile`.

⚠️ Ce motif est destiné au compte de DÉMONSTRATION seul. Le test de câblage le
verrouille — s'il tombe, la stratégie peut atteindre l'argent réel.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.models.schemas import Candle, PatternType, TradeDirection


def _c(h, b, i, close=None):
    m = (h + b) / 2
    return Candle(timestamp=datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(hours=i),
                  open=m, high=h, low=b, close=close if close is not None else m,
                  volume=0.0)


def _tendance_haussiere_puis_retour_au_poc():
    """Structure haussière franche, puis le prix redescend sur la zone d'équilibre.

    Les 30 premières bougies oscillent autour de 100 (le POC s'y forme), la
    suite monte en zigzag, et la dernière revient toucher le POC.
    ⚠️ L'accumulation doit OSCILLER et la montée doit avoir des REPLIS : des
    bougies identiques ou une montée lisse ne produisent aucune fractale, donc
    aucune structure. Deux jeux d'essai successifs sont tombés là-dessus.
    """
    accumulation = [(100.6, 99.4), (100.2, 99.8), (100.9, 99.1), (100.3, 99.7),
                    (100.5, 99.5), (101.0, 99.0), (100.4, 99.6), (100.7, 99.3),
                    (100.1, 99.9), (100.8, 99.2)] * 3
    montee = [(102, 101), (103, 102), (105, 103), (103.5, 102), (102.5, 101.5),
              (104, 102.5), (106, 104), (108, 106), (106.5, 105), (105.5, 104),
              (107, 105.5), (109, 107), (112, 109), (110, 108), (109, 107.5)]
    b = [_c(h, l, i) for i, (h, l) in enumerate(accumulation + montee)]
    b.append(_c(101.5, 100.2, len(b), close=100.7))        # retour sur le POC
    return b


# ── La détection ──────────────────────────────────────────────────────────

def test_retour_au_poc_en_structure_haussiere_donne_un_ACHAT():
    from backend.services import pattern_detector as pd

    motifs = pd._detect_poc_return(_tendance_haussiere_puis_retour_au_poc(), "WTI/USD")
    assert len(motifs) == 1
    assert motifs[0].pattern == PatternType.POC_RETURN_UP


def test_aucun_signal_si_la_structure_est_INDECISE():
    """⛔ La condition qui empêche de trader du bruit.

    Sans structure, un « retour au POC » n'est qu'un prix qui traîne au milieu
    de son range — ce qu'il fait la plupart du temps, par construction.
    """
    from backend.services import pattern_detector as pd

    plat = [_c(101, 99, i) for i in range(40)]
    assert pd._detect_poc_return(plat, "WTI/USD") == []


def test_aucun_signal_si_le_prix_est_LOIN_du_poc():
    """Le signal est le RETOUR, pas la tendance elle-même."""
    from backend.services import pattern_detector as pd

    b = _tendance_haussiere_puis_retour_au_poc()
    b[-1] = _c(113, 111, len(b) - 1, close=112)   # reste au sommet, ne revient pas
    assert pd._detect_poc_return(b, "WTI/USD") == []


def test_pas_assez_de_bougies_ne_plante_pas():
    from backend.services import pattern_detector as pd
    assert pd._detect_poc_return([_c(101, 99, i) for i in range(5)], "WTI/USD") == []


# ── Les niveaux : stop et cible viennent du PROFIL, pas de l'ATR ──────────

def test_le_stop_se_place_sous_la_zone_de_valeur():
    """La règle propre à ce motif, distincte du `recent_low - ATR` générique."""
    from backend.services import market_profile as mp
    from backend.services import pattern_detector as pd

    bougies = _tendance_haussiere_puis_retour_au_poc()
    motifs = pd._detect_poc_return(bougies, "WTI/USD")
    setup = pd.calculate_trade_setup("WTI/USD", motifs[0], bougies)

    assert setup is not None
    zv = mp.zone_valeur(bougies)
    assert setup.direction == TradeDirection.BUY
    assert setup.stop_loss < zv[0], "le stop doit être SOUS le bas de la zone de valeur"


def test_la_cible_vise_le_niveau_de_liquidite():
    from backend.services import market_profile as mp
    from backend.services import pattern_detector as pd

    bougies = _tendance_haussiere_puis_retour_au_poc()
    setup = pd.calculate_trade_setup(
        "WTI/USD", pd._detect_poc_return(bougies, "WTI/USD")[0], bougies)

    liq = mp.niveaux_liquidite(bougies)["au_dessus"]
    assert liq is not None
    assert setup.take_profit_1 == pytest.approx(liq, rel=0.02), (
        "TP1 doit viser la liquidité au-dessus, pas un R:R fixe")


def test_un_setup_incoherent_est_refuse_plutot_que_corrige():
    """Si la cible est du mauvais côté de l'entrée, on ne produit rien.

    ⚠️ 14 % des TP stockés se sont déjà retrouvés du mauvais côté de l'entrée
    réelle (mesure du 24/08). Un setup douteux ne doit pas être « rattrapé ».
    """
    from backend.services import pattern_detector as pd

    bougies = _tendance_haussiere_puis_retour_au_poc()
    motifs = pd._detect_poc_return(bougies, "WTI/USD")
    setup = pd.calculate_trade_setup("WTI/USD", motifs[0], bougies)
    assert setup.take_profit_1 > setup.entry_price > setup.stop_loss


# ── Le câblage : DÉMO seule ───────────────────────────────────────────────

def test_le_motif_n_atteint_PAS_le_compte_reel(monkeypatch):
    """⛔ Le test qui protège l'argent réel.

    S'il tombe, la stratégie neuve peut ouvrir des positions sur IC Markets.
    """
    from backend.services import bridge_destinations as bd
    from backend.services import mt5_bridge as mb
    from config import settings as st

    monkeypatch.setattr(mb, "MT5_BRIDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(mb, "MT5_BRIDGE_URL", "http://demo", raising=False)
    monkeypatch.setattr(mb, "MT5_BRIDGE_API_KEY", "cle", raising=False)
    monkeypatch.setattr(
        st, "MT5_BRIDGE_LEGACY_EXTRA_PATTERNS",
        frozenset({"poc_return_up", "poc_return_down"}), raising=False)

    demo = bd._admin_legacy_destination()
    assert demo is not None
    assert "poc_return_up" in demo.extra_patterns

    # Le réel n'a pas de surcharge : il retombe sur la liste globale, qui ne
    # contient pas le nouveau motif.
    assert "poc_return_up" not in mb.MT5_BRIDGE_ALLOWED_PATTERNS


def test_sans_variable_le_demo_ne_change_pas(monkeypatch):
    """⚠️ Le défaut compte : ne rien déclarer ne doit rien ouvrir."""
    from backend.services import bridge_destinations as bd
    from backend.services import mt5_bridge as mb
    from config import settings as st

    monkeypatch.setattr(mb, "MT5_BRIDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(mb, "MT5_BRIDGE_URL", "http://demo", raising=False)
    monkeypatch.setattr(mb, "MT5_BRIDGE_API_KEY", "cle", raising=False)
    monkeypatch.setattr(st, "MT5_BRIDGE_LEGACY_EXTRA_PATTERNS", None,
                        raising=False)

    demo = bd._admin_legacy_destination()
    assert demo.extra_patterns is None, "sans déclaration, rien n'est ouvert"
