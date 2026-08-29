

# ─── Le LIEU decide, pas la paire (2026-08-29) ───────────────────────────

def test_l_or_est_OUVERT_sur_Kraken_meme_le_samedi():
    """⛔ Un perpetuel `PF_XAUUSD` cote 24/7 sur Kraken Futures, alors que le
    CFD or de MT5 ferme le vendredi soir. Juger sur `asset_class_for(pair)`
    repondait « marche ferme » pour de l'or sur Kraken **tout le week-end** —
    un refus permanent, sur une place ouverte.

    Constate le 29/08 en ouvrant l'or et l'argent sur Kraken : la meme erreur
    de principe venait d'etre corrigee le jour meme dans `cote_en_continu`.
    Les deux fonctions posent la meme question ; une seule y repondait bien.
    """
    from datetime import datetime, timezone
    from backend.services.market_hours import is_market_open_for_destination

    samedi = datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc)
    for paire in ("XAU/USD", "XAG/USD", "BTC/USD"):
        assert is_market_open_for_destination(paire, "admin_kraken", samedi) is True, paire


def test_le_meme_or_reste_FERME_sur_MT5_le_samedi():
    """La correction ne deborde pas : le CFD or ferme bien le week-end."""
    from datetime import datetime, timezone
    from backend.services.market_hours import is_market_open_for_destination

    samedi = datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc)
    for dest in ("admin_live", "admin_legacy"):
        assert is_market_open_for_destination("XAU/USD", dest, samedi) is False, dest


def test_les_xStocks_gardent_leur_opt_in_explicite(monkeypatch):
    """⚠️ Leurs sous-jacents SONT adosses a une bourse : `cote_en_continu`
    repond False, et c'est bien `KRAKEN_STOCKS_ALLOW_24_7` qui tranche — un
    opt-in assume, au prix d'un spread degrade hors heures principales."""
    from datetime import datetime, timezone
    from backend.services.market_hours import is_market_open_for_destination

    samedi = datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc)
    monkeypatch.setenv("KRAKEN_STOCKS_ALLOW_24_7", "false")
    assert is_market_open_for_destination("AAPL", "admin_kraken_stocks", samedi) is False
    monkeypatch.setenv("KRAKEN_STOCKS_ALLOW_24_7", "true")
    assert is_market_open_for_destination("AAPL", "admin_kraken_stocks", samedi) is True


def test_sans_destination_le_comportement_est_INCHANGE():
    """L'appelant qui ne nomme pas de destination garde la grille de la paire."""
    from datetime import datetime, timezone
    from backend.services.market_hours import (is_market_open_for,
                                               is_market_open_for_destination)

    samedi = datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc)
    for paire in ("XAU/USD", "EUR/USD", "BTC/USD"):
        assert (is_market_open_for_destination(paire, "", samedi)
                is is_market_open_for(paire, samedi)), paire
