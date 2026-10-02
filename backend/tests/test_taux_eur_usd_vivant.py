"""Le taux EUR/USD par defaut doit etre LU, pas fige dans le code.

⛔ Constat du 2026-10-02, en verifiant le stop fixe de l'or :

    courtier (/tick/EURUSD)   1,1250      <- la verite, a l'instant
    macro eurusd              1,12499     <- juste, frais du jour
    EUR_USD_PAR_DEFAUT        1,155       <- fige dans le code, FAUX de 2,7 %

`calculer()` prend ce litteral des que l'appelant ne passe pas de taux — ce que
fait `porte_risque_par_trade.risque_au_lot_minimum`, donc la porte qui borne
l'engagement par trade. **Tous les montants en euros du systeme etaient donc
surevalues de 2,7 %.**

⚠️ Aucun verdict ne bascule aujourd'hui (65,03 -> 63,34 EUR reste au-dessus du
plafond de 32,50 ; 31,69 -> 30,86 reste en dessous), mais un chiffre faux qui
ne change rien aujourd'hui change quelque chose le jour ou il frole une borne.

🔑 Le litteral reste comme REPLI, jamais comme defaut : un taux illisible ne
doit pas couper le calcul, et une valeur figee vaut mieux que rien. Mais elle ne
doit plus etre le premier choix.
"""
from __future__ import annotations

import pytest

from backend.services import risk_eur


def test_le_taux_par_defaut_est_LU_et_non_fige(monkeypatch):
    monkeypatch.setattr(risk_eur, "_close_macro", lambda s: 1.1250)
    assert risk_eur.taux_eur_usd() == pytest.approx(1.1250)


def test_un_taux_illisible_replie_sur_le_litteral(monkeypatch):
    monkeypatch.setattr(risk_eur, "_close_macro", lambda s: None)
    assert risk_eur.taux_eur_usd() == pytest.approx(risk_eur.EUR_USD_PAR_DEFAUT)


def test_un_taux_absurde_replie_aussi(monkeypatch):
    """Zero ou negatif diviserait par zero plus loin."""
    for absurde in (0, -1, None):
        monkeypatch.setattr(risk_eur, "_close_macro", lambda s, v=absurde: v)
        assert risk_eur.taux_eur_usd() == pytest.approx(risk_eur.EUR_USD_PAR_DEFAUT)


def test_calculer_utilise_le_taux_LU_quand_l_appelant_n_en_passe_pas(monkeypatch):
    """⛔ Le cœur : c'est ce chemin que prend la porte de risque par trade."""
    monkeypatch.setattr(risk_eur, "_close_macro", lambda s: 1.1250)
    r = risk_eur.calculer(pair="XAU/USD", entry=4150.0, sl=4150.0 - 11.25,
                          tp=4150.0 + 20.25, volume=0.01, bridge_type="mt5")
    assert r["eur_usd"] == pytest.approx(1.1250)
    assert r["risque_eur"] == pytest.approx(10.0, abs=0.02)


def test_un_taux_EXPLICITE_de_l_appelant_reste_prioritaire(monkeypatch):
    """Les appelants qui savent — rejeux, bancs — ne doivent pas etre ecrases."""
    monkeypatch.setattr(risk_eur, "_close_macro", lambda s: 1.1250)
    r = risk_eur.calculer(pair="XAU/USD", entry=4150.0, sl=4140.0, tp=4168.0,
                          volume=0.01, bridge_type="mt5", eur_usd=1.30)
    assert r["eur_usd"] == pytest.approx(1.30)
