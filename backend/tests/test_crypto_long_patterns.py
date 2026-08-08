"""Jeu de motifs du crypto journalier, élargi le 2026-08-08.

À 3 motifs, les 4 instruments crypto ne produisaient que **1,31 setup par
semaine** (15 en 80 jours) — et seuls BTC/ETH passent la porte de coût, SOL et
XRP étant refusés sur le portage. La route ne tradait quasiment jamais.

⚠️ Ce que ces tests verrouillent :
  - l'ajout ne déborde pas sur les métaux, qui gardent `CORE_LONG_PATTERNS` ;
  - le jeu reste LONG ONLY — aucun motif baissier ne doit s'y glisser ;
  - `range_bounce_up` est bien présent : c'est le motif à la meilleure
    espérance mesurée, et la raison d'être de l'élargissement.
"""
import pytest

from backend.services.shadow_v2_core_long import (
    CORE_LONG_PATTERNS,
    CRYPTO_LONG_PATTERNS,
    SHADOW_CONFIG,
)

CRYPTO_1D = ("BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "ADA/USD", "DOT/USD", "LTC/USD", "BNB/USD", "XLM/USD", "SEI/USD", "ENS/USD", "HBAR/USD", "ARB/USD", "CRV/USD", "LDO/USD", "PAXG/USD", "ALGO/USD")


def test_les_4_cryptos_utilisent_le_jeu_elargi():
    for pair in CRYPTO_1D:
        assert SHADOW_CONFIG[pair]["patterns"] == CRYPTO_LONG_PATTERNS
        assert SHADOW_CONFIG[pair]["tf"] == "1d"


def test_range_bounce_up_est_la_raison_de_l_elargissement():
    assert "range_bounce_up" in CRYPTO_LONG_PATTERNS
    assert CRYPTO_LONG_PATTERNS == CORE_LONG_PATTERNS | {"range_bounce_up"}


def test_les_METAUX_ne_sont_PAS_touches():
    """L'élargissement vise Kraken. XAU/XAG gardent leur jeu d'origine."""
    for pair in ("XAU/USD", "XAG/USD"):
        assert SHADOW_CONFIG[pair]["patterns"] == CORE_LONG_PATTERNS
        assert "range_bounce_up" not in SHADOW_CONFIG[pair]["patterns"]


def test_le_jeu_reste_LONG_ONLY():
    """Aucun motif baissier : ce système n'ouvre jamais de vente."""
    baissiers = {"momentum_down", "engulfing_bearish", "breakout_down",
                 "pin_bar_up", "range_bounce_down", "mean_reversion_down"}
    assert not (CRYPTO_LONG_PATTERNS & baissiers)


def test_le_4h_n_est_PAS_ouvert_au_crypto():
    """Mesuré le 2026-08-08 : sur un stop 4h de 0,76 %, les frais Kraken
    atteignent 129 % de l'edge, contre 12 % en journalier à 7,59 %. Seul le
    journalier est économiquement viable sur cette route."""
    for pair in CRYPTO_1D:
        assert SHADOW_CONFIG[pair]["tf"] != "4h", (
            f"{pair} passe en 4h : les frais Kraken y consomment plus que l'edge"
        )


def test_ada_ajoutee_sur_mesure_pas_par_analogie():
    """ADA est l'un des 3 seuls instruments de tout Kraken Futures a passer
    liquidite ET porte de cout (screening des 274 contrats le 2026-08-08 :
    7 liquides, 3 passants). Elle n'est pas la par analogie."""
    assert "ADA/USD" in SHADOW_CONFIG
    assert SHADOW_CONFIG["ADA/USD"]["tf"] == "1d"
    assert SHADOW_CONFIG["ADA/USD"]["patterns"] == CRYPTO_LONG_PATTERNS


def test_HYPE_n_est_PAS_ajoutee():
    """HYPE passait la porte de cout (21,0 %, 12 M$) mais Twelve Data ne
    connait pas le symbole : aucune bougie, donc aucun setup, jamais.
    Un instrument sans source de prix ne se configure pas."""
    assert "HYPE/USD" not in SHADOW_CONFIG, (
        "HYPE ajoutee sans source de prix — elle ne produira aucun setup et "
        "son absence de signal serait indiscernable d'un marche calme"
    )
