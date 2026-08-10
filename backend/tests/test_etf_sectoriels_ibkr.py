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
def test_l_analogie_est_celle_de_XLK_qui_porte_range_bounce(etf):
    """⚠️ RÉVISION du choix pris le matin même — XLI → XLK.

    L'analogie initiale visait XLI (exp #35, mean PF 2,14, le meilleur système
    ETF mesuré). Elle rendait ces ETF **intradables** : la whitelist globale de
    patterns n'admet que `range_bounce_up/down`, et `TIGHT_LONG` ne contient
    ni l'un ni l'autre. Chaque setup serait mort en `pattern_not_allowed`.

    Le passage à `WTI_OPTIMAL` (celui de XLK) **ajoute** `range_bounce_up` sans
    rien retirer. Ce n'est pas un contournement de la porte :

        range_bounce_up = +0,133 R sur 16 996 trades
        seuil de confiance seul = +0,030 R

    C'est la meilleure espérance mesurée du système, et c'est précisément
    pourquoi la whitelist n'admet que lui. Aligner les ETF dessus les met sur le
    pattern le mieux soutenu, pas sur un pattern de complaisance.

    ⚠️ XLI garde `TIGHT_LONG` : sa configuration est MESURÉE, on n'y touche pas.
    """
    cfg = shadow.SHADOW_CONFIG[etf]
    assert cfg["patterns"] == shadow.WTI_OPTIMAL_PATTERNS
    assert cfg["patterns"] == shadow.SHADOW_CONFIG["XLK"]["patterns"]
    assert "range_bounce_up" in cfg["patterns"]
    assert cfg["system_id"] == f"V2_WTI_OPTIMAL_{etf}_1D"


# Valeur RÉELLE de `MT5_BRIDGE_ALLOWED_PATTERNS` en production, relevée le
# 2026-08-10. Écrite en dur À DESSEIN : un test qui lit l'environnement passe
# en prod et saute en local, donc ne protège rien là où on développe. C'est la
# fragilité corrigée le matin même sur le routage par classe d'actif.
WHITELIST_PROD = {"range_bounce_up", "range_bounce_down"}


@pytest.mark.parametrize("etf", NOUVEAUX)
def test_les_patterns_franchissent_la_whitelist_de_dispatch(etf):
    """LE test qui manquait, et qui aurait évité une demi-journée.

    Un instrument dont aucun pattern n'est admis au dispatch ne tradera
    **jamais**, quelle que soit sa promotion en `AUTO_EXEC`. Les cinq ETF sont
    entrés sur `TIGHT_LONG` le matin du 2026-08-10 — sans intersection avec la
    whitelist — et leur promotion l'après-midi était donc inopérante.
    """
    communs = shadow.SHADOW_CONFIG[etf]["patterns"] & WHITELIST_PROD
    assert communs, (
        f"{etf} : aucun de ses patterns n'est admis au dispatch — "
        f"tout setup mourrait en pattern_not_allowed")


def test_la_whitelist_de_prod_est_toujours_celle_qu_on_croit():
    """Garde-fou du garde-fou : si la prod change, ce fichier doit suivre.

    Ne s'exécute que là où la variable est renseignée.
    """
    from config.settings import MT5_BRIDGE_ALLOWED_PATTERNS

    if not MT5_BRIDGE_ALLOWED_PATTERNS:
        pytest.skip("whitelist non renseignée dans cet environnement")
    assert set(MT5_BRIDGE_ALLOWED_PATTERNS) == WHITELIST_PROD


def test_XLI_garde_sa_configuration_mesuree():
    """Le seul ETF dont la config vient d'un backtest propre ne bouge pas."""
    assert shadow.SHADOW_CONFIG["XLI"]["patterns"] == shadow.TIGHT_LONG_PATTERNS
    assert shadow.SHADOW_CONFIG["XLI"]["risk_pct"] == 0.004


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
