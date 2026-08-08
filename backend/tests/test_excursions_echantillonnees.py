"""Excursions échantillonnées sur le flux principal (Phase 1 ML, 2026-08-08).

La cible retenue par la spec est l'excursion favorable maximale. Elle
n'existait à volume **nulle part** : 23 lignes dans `shadow_setups`, et
l'historique n'est pas recalculable — aucun dépôt de bougies, et Twelve Data
ne rend que ~5 jours d'historique en 5 minutes. Or `backtest.db.trades` porte
**107 988 trades clôturés**.

`check_open_trades` interroge le prix courant toutes les ~3 minutes sans
rejouer aucun chemin. On accumule donc un **maximum courant** à chaque sonde.

⚠️ Ce que ces tests verrouillent :
  - le sens (sur une vente, la baisse est FAVORABLE) ;
  - le caractère monotone : une excursion ne redescend jamais ;
  - la distinction d'avec `shadow_setups.mfe_pct`, qui est exacte parce que
    calculée sur les bougies — les deux ne doivent jamais être mélangées.
"""
import pytest

from backend.services.backtest_service import excursions_echantillonnees as ex


# ── Sens ──────────────────────────────────────────────────────────────

def test_achat_le_haut_est_favorable():
    mfe, mae = ex("buy", 100.0, 103.0, None, None)
    assert mfe == pytest.approx(3.0)
    assert mae == pytest.approx(0.0)


def test_vente_le_BAS_est_favorable():
    """Le piège de signe : sur une vente, la baisse profite."""
    mfe, mae = ex("sell", 100.0, 94.0, None, None)
    assert mfe == pytest.approx(6.0)
    assert mae == pytest.approx(0.0)


def test_achat_defavorable_alimente_l_adverse():
    mfe, mae = ex("buy", 100.0, 96.0, None, None)
    assert mfe == pytest.approx(0.0), "jamais de favorable négative"
    assert mae == pytest.approx(4.0)


# ── Monotonie : c'est un MAXIMUM courant ──────────────────────────────

def test_une_excursion_ne_redescend_jamais():
    """Le prix revient à l'entrée : le maximum déjà atteint est conservé."""
    mfe, mae = ex("buy", 100.0, 105.0, None, None)
    assert mfe == pytest.approx(5.0)
    mfe, mae = ex("buy", 100.0, 100.0, mfe, mae)
    assert mfe == pytest.approx(5.0), "le pic atteint doit survivre au retour"


def test_les_deux_cotes_s_accumulent_independamment():
    """Un aller-retour doit laisser une trace des deux côtés."""
    mfe, mae = ex("buy", 100.0, 104.0, None, None)   # monte
    mfe, mae = ex("buy", 100.0, 97.0, mfe, mae)      # redescend
    assert mfe == pytest.approx(4.0)
    assert mae == pytest.approx(3.0)


def test_une_sonde_moins_bonne_ne_degrade_rien():
    mfe, mae = ex("sell", 100.0, 90.0, 12.0, 2.0)
    assert mfe == pytest.approx(12.0), "12 % déjà atteint > 10 % de cette sonde"
    assert mae == pytest.approx(2.0)


# ── Robustesse ────────────────────────────────────────────────────────

def test_entree_nulle_ne_plante_pas():
    assert ex("buy", 0.0, 100.0, None, None) == (0.0, 0.0)
    assert ex("buy", 0.0, 100.0, 3.0, 1.0) == (3.0, 1.0)


def test_premiere_sonde_sans_historique():
    mfe, mae = ex("buy", 100.0, 100.0, None, None)
    assert mfe == 0.0 and mae == 0.0


# ── Ce que cette mesure N'EST PAS ─────────────────────────────────────

def test_elle_sous_estime_une_pointe_entre_deux_sondes():
    """Documente le biais : une pointe non sondée est invisible.

    Le prix monte à 110 entre deux sondes, mais n'est vu qu'à 102 et 101.
    L'excursion rendue est 2 %, pas 10 %. **Le biais est systématique et dans
    un seul sens** — c'est ce qui la rend utilisable comme cible, à condition
    de ne jamais la présenter comme exacte.
    """
    mfe, _ = ex("buy", 100.0, 102.0, None, None)
    mfe, _ = ex("buy", 100.0, 101.0, mfe, None)
    assert mfe == pytest.approx(2.0)
    assert mfe < 10.0, "la pointe non sondée est perdue, par construction"


def test_ne_pas_confondre_avec_l_excursion_exacte_du_shadow():
    """Les deux fonctions coexistent et ne mesurent pas la même chose.

    `backtest_engine.excursions_pct` lit les hauts et bas des bougies : elle
    est exacte. Celle-ci échantillonne. Mélanger les deux dans un même jeu
    d'entraînement introduirait un biais dépendant de la source.
    """
    from backend.services.backtest_engine import excursions_pct
    assert excursions_pct is not ex
    assert ex.__module__ != excursions_pct.__module__
