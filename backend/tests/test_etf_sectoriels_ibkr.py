"""ETF sectoriels bon marché — ce qui rend la route IBKR atteignable.

Demande de Xavier le 2026-08-10 : pouvoir acheter des ETF sur IBKR.

⚠️ **XLI et XLK EN SONT DÉJÀ** — ce sont les SPDR sectoriels industrie et
technologie. La route ouverte la veille achète donc déjà des ETF, et
exclusivement. Ce lot élargit l'univers, et surtout le rend **atteignable**.

Sur un compte cash, le prix par part commande tout :

    XLK  184,48 $/part  ⇒  ~1 129 $ de capital pour un risque de 1 %
    XLU   43,60 $/part  ⇒  ~  220 $

⇒ Les sectoriels bon marché divisent par **cinq** le capital requis, et une
part de XLU tient déjà dans le compte à 115 $.

⚠️ **L'analogie est assumée, pas validée.** Aucun backtest n'existe sur ces
cinq-là ; patterns et `risk_pct` sont repris de XLI (exp #35, mean PF 2,14).
C'est le mécanisme même qui avait fait entrer les 4 actions US individuelles,
retirées la veille après réfutation. Deux différences le rendent défendable :

1. le test direct **n'a pas pu** établir que les patterns nuisent sur ETF
   (p = 0,243 et 0,239 sur vingt ans), alors qu'il l'a établi sur les actions
   individuelles (p < 0,001) ;
2. l'analogue est de **même nature** — SPDR sectoriel vs SPDR sectoriel,
   journalier vs journalier — là où les 4 actions empruntaient à un ETF
   diversifié un jeu de patterns ET un horizon H4 sans analogue validé.
"""
import pytest

from backend.services import shadow_v2_core_long as shadow

NOUVEAUX = ("XLU", "XLRE", "XLB", "XLE", "XLF")
# Mesurés le 2026-08-10 via Twelve Data.
PRIX = {"XLU": 43.60, "XLRE": 44.99, "XLB": 52.86, "XLE": 57.48, "XLF": 57.62}


@pytest.mark.parametrize("etf", NOUVEAUX)
def test_les_sectoriels_sont_shadowes_en_journalier(etf):
    """Six bougies utiles par jour de cotation, contre une seule en H4."""
    assert etf in shadow.SHADOW_CONFIG
    assert shadow.SHADOW_CONFIG[etf]["tf"] == "1d"


@pytest.mark.parametrize("etf", NOUVEAUX)
def test_l_analogie_est_celle_de_XLI_le_mieux_mesure(etf):
    """XLI : exp #35, mean PF 2,14 — le meilleur système ETF mesuré.

    Verrouillé pour qu'une divergence future soit un acte délibéré, comme
    l'analogie ETH → BTC/SOL/XRP côté crypto.
    """
    cfg = shadow.SHADOW_CONFIG[etf]
    assert cfg["patterns"] == shadow.TIGHT_LONG_PATTERNS
    assert cfg["patterns"] == shadow.SHADOW_CONFIG["XLI"]["patterns"]
    assert cfg["system_id"] == f"V2_TIGHT_LONG_{etf}_1D"


@pytest.mark.parametrize("etf", NOUVEAUX)
def test_le_risque_reste_sous_celui_de_l_analogue_valide(etf):
    """0,003 contre 0,004 pour XLI : un instrument sans validation propre ne
    prend pas la taille de celui qui en a une."""
    assert shadow.SHADOW_CONFIG[etf]["risk_pct"] == 0.003
    assert shadow.SHADOW_CONFIG[etf]["risk_pct"] < shadow.SHADOW_CONFIG["XLI"]["risk_pct"]


def test_les_ETF_chers_sont_ECARTES():
    """SPY 773 $ et QQQ 723 $ : une seule part dépasse six fois le compte.

    Les ajouter donnerait un univers qui ne peut structurellement pas trader —
    exactement ce que ce lot cherche à corriger.
    """
    for cher in ("SPY", "QQQ"):
        assert cher not in shadow.SHADOW_CONFIG


@pytest.mark.parametrize("etf", NOUVEAUX)
def test_une_part_tient_dans_le_compte_actuel(etf):
    """Le critère de sélection, verrouillé : sous 60 USD la part.

    Le compte IBKR vaut ~115 USD. Un instrument dont une part coûte davantage
    ne peut pas être acheté, quelle que soit la qualité du signal.
    """
    assert PRIX[etf] < 60.0
    assert PRIX[etf] < 115.0


def test_les_deux_ETF_historiques_sont_intacts():
    """XLI et XLK gardent leur configuration mesurée — on élargit, on ne
    réécrit pas."""
    assert shadow.SHADOW_CONFIG["XLI"]["risk_pct"] == 0.004
    assert shadow.SHADOW_CONFIG["XLI"]["patterns"] == shadow.TIGHT_LONG_PATTERNS
    assert shadow.SHADOW_CONFIG["XLK"]["risk_pct"] == 0.004
    assert shadow.SHADOW_CONFIG["XLK"]["patterns"] == shadow.WTI_OPTIMAL_PATTERNS


def test_aucune_action_individuelle_n_est_revenue():
    """Le retrait de la veille tient : l'élargissement porte sur des ETF."""
    for action in ("AAPL", "TSLA", "NVDA", "MSFT"):
        assert action not in shadow.SHADOW_CONFIG
