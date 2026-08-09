"""Les 253 couples crypto mesurés sur Kraken Futures (2026-08-09).

Le garde de corrélation ne connaissait que **6 paires crypto sur 23** : la
table du 2026-08-04, mesurée sur ``backtest.db.signals``. Pour les 17 autres,
``correlation()`` rendait ``None``, donc le garde ne comptait rien.

⚠️ **L'erreur de raisonnement corrigée.** J'avais annoncé qu'il faudrait
attendre plusieurs semaines, en confondant **notre** historique avec celui du
**marché**. La corrélation des rendements est une propriété du marché : ETHFI,
SEI ou CRV cotent chez Kraken depuis des mois. La donnée existait déjà, et
l'endpoint public des graphiques la rend — hors quota Twelve Data, sur les
perpétuels réellement tradés.

Résultat : **1 999 rendements horaires par instrument**, 253 couples, aucun
sous-échantillonné. Cf. ``scripts/mesurer_correlations_kraken.py``.

Deux contrôles de méthode plutôt qu'une confiance aveugle :

1. **Les 11 couples déjà connus se retrouvent** — même signe, même ordre,
   systématiquement plus hauts (0,67-0,81 → 0,76-0,89). L'écart est attendu :
   l'ancienne mesure échantillonnait des prix d'entrée de signaux, irréguliers,
   ce qui **atténue** une corrélation. Une mesure continue est moins bruitée.
2. **PAXG, adossé à l'or, ressort le moins corrélé de tous** (|r| max 0,346).
   Une méthode qui fabriquerait de la corrélation partout ne saurait pas
   isoler l'intrus.
"""
import json
from pathlib import Path

import pytest

from backend.services import correlation_guard as cg

FICHIER = Path(cg.__file__).parent / "correlations_kraken_1h.json"


@pytest.fixture(scope="module")
def mesure():
    return json.loads(FICHIER.read_text(encoding="utf-8"))


# ─── Le fichier de mesure ──────────────────────────────────────────────


def test_tous_les_couples_ont_le_meme_echantillon(mesure):
    """Aucun couple sous-échantillonné : sinon les valeurs ne se comparent pas."""
    n = {c["n"] for c in mesure["couples"]}
    assert len(n) == 1
    assert n.pop() >= 1500


def test_la_couverture_est_complete(mesure):
    """23 instruments ⇒ 253 couples. Un trou signifierait un instrument muet."""
    k = len(mesure["instruments"])
    assert len(mesure["couples"]) == k * (k - 1) // 2


def test_les_correlations_sont_dans_l_intervalle(mesure):
    assert all(-1.0 <= c["r"] <= 1.0 for c in mesure["couples"])


# ─── Les deux contrôles de méthode ─────────────────────────────────────


@pytest.mark.parametrize(
    "a,b,ancien",
    [("BTC/USD", "ETH/USD", 0.81), ("ETH/USD", "SOL/USD", 0.78),
     ("BTC/USD", "SOL/USD", 0.77), ("SOL/USD", "XRP/USD", 0.75),
     ("DOT/USD", "ETH/USD", 0.70), ("ADA/USD", "XRP/USD", 0.67)],
)
def test_les_couples_deja_connus_se_retrouvent(a, b, ancien):
    """Même signe, et jamais plus bas : une mesure continue atténue moins."""
    r = cg.correlation(a, b)
    assert r is not None
    assert r > 0
    assert r >= ancien - 0.05


def test_paxg_reste_l_intrus():
    """Adossé à l'or : il ne doit PAS ressortir comme un pari crypto."""
    autres = [p for p in ("BTC/USD", "ETH/USD", "SOL/USD", "LINK/USD",
                          "XRP/USD", "DOGE/USD")]
    for p in autres:
        r = cg.correlation("PAXG/USD", p)
        assert r is not None
        assert abs(r) < cg.SEUIL_CORRELATION, f"PAXG/{p} = {r}"


# ─── Le raccordement au garde ──────────────────────────────────────────


def test_les_17_paires_muettes_sont_desormais_mesurees():
    """C'était le trou : elles rendaient toutes ``None``."""
    for p in ("ETHFI/USD", "SEI/USD", "CRV/USD", "ARB/USD", "LDO/USD",
              "AAVE/USD", "ALGO/USD", "MANA/USD", "UNI/USD", "XLM/USD",
              "ENS/USD", "HBAR/USD", "BNB/USD", "LINK/USD", "PAXG/USD"):
        assert cg.correlation(p, "BTC/USD") is not None, p


def test_les_trois_positions_de_la_nuit_n_etaient_PAS_le_meme_pari():
    """⚠️ Corrige une affirmation trop rapide du matin même.

    J'avais écrit que trois positions crypto simultanées étaient « un seul pari
    pris trois fois ». La mesure dit le contraire : les trois couples sont sous
    le seuil. Le garde était muet par accident, mais son verdict aurait été le
    même — ne pas bloquer.
    """
    for a, b in (("ETHFI/USD", "SEI/USD"), ("ETHFI/USD", "CRV/USD"),
                 ("SEI/USD", "CRV/USD")):
        r = cg.correlation(a, b)
        assert r is not None
        assert abs(r) < cg.SEUIL_CORRELATION, f"{a}/{b} = {r}"


def test_le_forex_et_les_metaux_restent_servis_par_la_table_historique():
    """Kraken Futures ne cote pas ces paires : la mesure ne peut pas les couvrir.

    Les écraser en les laissant à ``None`` retirerait une protection existante.
    """
    assert cg.correlation("XAG/USD", "XAU/USD") == pytest.approx(0.82)
    assert cg.correlation("EUR/USD", "USD/CHF") == pytest.approx(-0.80)
    assert cg.correlation("EUR/JPY", "GBP/JPY") == pytest.approx(0.79)


def test_une_paire_jamais_mesuree_rend_toujours_None():
    """Le repli strict demeure : mesurer 23 instruments ne rend pas omniscient."""
    assert cg.correlation("ZZZ/USD", "BTC/USD") is None


def test_la_mesure_prime_sur_la_table_historique():
    """Même couple des deux côtés ⇒ l'échantillon le plus large gagne.

    BTC/ETH : 0,81 sur 1 468 prix d'entrée contre 0,889 sur 1 999 bougies.
    """
    assert cg.correlation("BTC/USD", "ETH/USD") == pytest.approx(0.889, abs=0.001)


def test_la_symetrie_est_conservee():
    assert cg.correlation("ETHFI/USD", "SEI/USD") == cg.correlation(
        "SEI/USD", "ETHFI/USD")
