"""Un motif haussier doit ACHETER. Neuf ne le faisaient pas.

⛔ **Le defaut, trouve le 2026-09-14.** `calculate_trade_setup` decidait le
sens avec une liste ECRITE A LA MAIN de sept motifs :

    is_buy = pattern.pattern in (BREAKOUT_UP, MOMENTUM_UP, RANGE_BOUNCE_UP,
                                 MEAN_REVERSION_UP, ENGULFING_BULLISH,
                                 PIN_BAR_UP, POC_RETURN_UP)
    direction = BUY if is_buy else SELL

Tout motif ajoute APRES cette liste tombait donc dans le `else` — en VENTE,
sans un mot. Neuf motifs haussiers y sont tombes : `fvg_up`, `gap_retrace_up`,
`gap_breakaway_up`, `liquidity_sweep_up`, `double_sweep_up`, `order_block_up`,
`bos_up`, `choch_up`, `fvg_inverse_up`.

⚠️ **Ce que ca coutait.** Mesure du 2026-09-14 : **602 cellules sur 3 286
(18,3 %)** et 109 536 trades rejoues mesuraient le trade MIROIR. Le
laboratoire publiait des verdicts sur l'inverse de ce que le motif annonce.

🔑 **Aucun ordre reel n'est parti a l'envers** : les neuf motifs ne sont armes
sur aucune destination (verifie sur 90 jours de `mt5_pushes`). Le defaut
vivait entierement dans la mesure — mais la mesure decide des fermetures.

## Pourquoi une REGLE et pas une liste corrigee

Rallonger la liste aurait reproduit le defaut au motif suivant. Le sens est
deja dans le NOM (`_up` / `_down`, `_bullish` / `_bearish`), et les 32 motifs
le portent tous. La regle le lit, et **LEVE** sur un nom qu'elle ne sait pas
classer : un motif mal nomme doit casser la construction, jamais glisser
silencieusement du cote vendeur.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.models.schemas import Candle, PatternType, TradeDirection
from backend.services.pattern_detector import (_est_un_achat,
                                               calculate_trade_setup,
                                               detect_patterns)

_FIXTURE = Path(__file__).parent / "fixtures" / "bougies_xauusd_5min.json"
FENETRE = 50

_HAUSSIER = ("_UP", "_BULLISH")
_BAISSIER = ("_DOWN", "_BEARISH")


def test_chaque_motif_porte_son_sens_dans_son_nom():
    """La regle ne peut etre totale que si tous les noms sont classables."""
    orphelins = [p.name for p in PatternType
                 if not p.name.endswith(_HAUSSIER + _BAISSIER)]
    assert orphelins == [], (
        f"motifs sans suffixe directionnel : {orphelins} — la regle de sens "
        f"ne peut pas les classer, il faut les nommer ou les declarer")


@pytest.mark.parametrize("motif", list(PatternType))
def test_le_sens_suit_le_nom(motif):
    attendu = motif.name.endswith(_HAUSSIER)
    assert _est_un_achat(motif) is attendu, (
        f"{motif.value} : sens {'achat' if attendu else 'vente'} attendu")


def test_les_neuf_motifs_du_defaut_achetent_bien():
    """Regression nommee : ces neuf-la vendaient."""
    for motif in (PatternType.FVG_UP, PatternType.GAP_RETRACE_UP,
                  PatternType.GAP_BREAKAWAY_UP, PatternType.LIQUIDITY_SWEEP_UP,
                  PatternType.DOUBLE_SWEEP_UP, PatternType.ORDER_BLOCK_UP,
                  PatternType.BOS_UP, PatternType.CHOCH_UP,
                  PatternType.FVG_INVERSE_UP):
        assert _est_un_achat(motif) is True, f"{motif.value} vend encore"


def test_un_nom_inconnu_LEVE_au_lieu_de_vendre():
    """⛔ Le coeur du defaut : le `else` silencieux. Fail-closed."""
    with pytest.raises(ValueError):
        _est_un_achat("motif_invente_sans_suffixe")


def test_sur_de_VRAIES_bougies_le_stop_est_du_bon_cote():
    """Le test qui aurait attrape le defaut : on passe par la production.

    Un test du seul `_est_un_achat` passerait au vert avec une regle jamais
    branchee — c'est exactement ce qui a laisse la liste ecrite a la main
    decider pendant que les motifs s'ajoutaient.
    """
    brut = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    bougies = [Candle(timestamp=t0 + timedelta(minutes=5 * i),
                      open=o, high=h, low=b, close=c, volume=0)
               for i, (o, h, b, c) in enumerate(brut)]
    vus = set()
    for i in range(FENETRE, len(bougies)):
        fen = bougies[i - FENETRE:i]
        for motif in detect_patterns(fen, "XAU/USD"):
            s = calculate_trade_setup("XAU/USD", motif, fen, is_simulated=False)
            if s is None:
                continue
            nom = motif.pattern
            haussier = nom.name.endswith(_HAUSSIER)
            vus.add(nom.value)
            attendu = TradeDirection.BUY if haussier else TradeDirection.SELL
            assert s.direction == attendu, (
                f"{nom.value} rend {s.direction} au lieu de {attendu}")
            if s.direction == TradeDirection.BUY:
                assert s.stop_loss < s.entry_price, f"{nom.value}: stop au-dessus"
                assert s.take_profit_1 > s.entry_price, f"{nom.value}: cible en dessous"
            else:
                assert s.stop_loss > s.entry_price, f"{nom.value}: stop en dessous"
                assert s.take_profit_1 < s.entry_price, f"{nom.value}: cible au-dessus"
    # ⚠️ Sans ce garde-fou, une fixture muette rendrait le test vert a vide.
    assert len(vus) >= 10, f"seulement {len(vus)} motifs declenches : {sorted(vus)}"
