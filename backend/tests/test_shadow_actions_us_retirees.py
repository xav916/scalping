"""Le shadow H4 des 4 actions US est retiré — la stratégie est réfutée.

Le shadow AAPL/TSLA/NVDA/MSFT tournait depuis le 2026-08-05 (`3c45a32`) sur
``US_EQUITY_TECH_PATTERNS``, c'est-à-dire **le jeu de patterns démontré
contre-productif sur ces titres exacts** :

    Δ = −0,182 R par trade contre une entrée AU HASARD
    IC 95 % [−0,235 ; −0,123]   p < 0,001   n = 994

Seule cellule significative sur 17, survivant à Bonferroni **et**
Benjamini-Hochberg. Cf. [[project_edge_actions_us_h4_2026_08_05]].

Trois raisons de le retirer plutôt que de le laisser « au cas où » :

1. **La question est déjà tranchée, avec bien plus de puissance.** 2 175 trades
   de backtest contre 0,8 setup/semaine/titre en shadow — soit 6 à 9 mois pour
   107 observations. Le shadow corrobore, il ne découvre pas.
2. **Limitation mécanique.** En H4 sur une action US (marché 13:30-20:30 UTC),
   un seul créneau sur trois se referme en séance : **une bougie exploitable
   par jour de cotation**, contre six pour l'or. Le pire rapport
   observation/temps du système.
3. **Il consomme du quota Twelve Data** que l'univers crypto — où la mesure est
   encore vivante — emploie mieux.

⚠️ **XLI et XLK RESTENT.** Leur verdict est « non tranché » (p = 0,243 et
0,239 sur vingt ans), ce qui n'est pas « négatif » : c'est une absence de
justification, pas une réfutation. Et ils sont en **journalier**, donc six
bougies utiles là où le H4 actions n'en donne qu'une.

⚠️ Ce que ce retrait NE dit PAS : que la voie actions est fermée
économiquement. Mesuré le 2026-08-09 sur les distances réelles du shadow, le
coût IBKR vaut **14,7 % à 28,6 %** du TP visé — **sous** la porte de coût de
30 %. C'est l'edge qui manque, pas la marge.
"""
import pytest

from backend.services import shadow_v2_core_long as shadow

RETIREES = ("AAPL", "TSLA", "NVDA", "MSFT")


@pytest.mark.parametrize("titre", RETIREES)
def test_les_4_actions_us_ne_sont_plus_shadowees(titre):
    assert titre not in shadow.SHADOW_CONFIG
    assert titre not in shadow.SHADOW_PAIRS


def test_les_etf_journaliers_restent():
    """XLI/XLK : non tranchés, pas réfutés — et six bougies utiles par jour."""
    for etf in ("XLI", "XLK"):
        assert etf in shadow.SHADOW_CONFIG, etf
        assert shadow.SHADOW_CONFIG[etf]["tf"] == "1d"


def test_plus_aucun_systeme_H4_sur_action_individuelle():
    """Le verrou qui empêche la reconduction par analogie.

    C'est ainsi que les 4 titres étaient entrés : patterns et `risk_pct`
    recopiés depuis XLK « par analogie », sans backtest propre.
    """
    from config.settings import asset_class_for

    for pair, cfg in shadow.SHADOW_CONFIG.items():
        if cfg["tf"] == "4h":
            assert asset_class_for(pair) != "equity", (
                f"{pair} : action individuelle en H4 — une bougie exploitable "
                f"par jour, et l'analogie XLK est réfutée")


def test_le_reste_de_la_configuration_est_intact():
    """Métaux, énergie, crypto et forex ne bougent pas."""
    for pair in ("XAU/USD", "XAG/USD", "WTI/USD", "BTC/USD", "ETH/USD"):
        assert pair in shadow.SHADOW_CONFIG, pair
