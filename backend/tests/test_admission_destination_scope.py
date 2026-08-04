"""Portée des admissions par destination — correctif du 2026-08-04.

`VALID_DESTINATIONS` ne listait que `admin_legacy` et `admin_live`, soit 2
destinations sur 7. Toute valeur non listée était repliée en `None` — et
`None` signifie *« toutes les destinations »*.

**Le repli élargissait donc les permissions au lieu de les restreindre**, en
silence et sans erreur. Constaté en production :

    set_state('BTC/USD', AUTO_EXEC, direction='sell', destination='admin_kraken')

    is_auto_exec_eligible('BTC/USD','sell','admin_kraken')  -> True   attendu
    is_auto_exec_eligible('BTC/USD','sell','admin_live')    -> True   ⚠️
    is_auto_exec_eligible('BTC/USD','sell', None)           -> True   ⚠️

`user:2` autorisant la classe crypto, son flux s'est trouvé ouvert à une
paire sans que ce soit voulu.

Effet miroir en lecture : une row stockée avec une destination non listée
devenait inatteignable, la cascade retombant sur la row globale. La promotion
`BTC/USD buy @admin_kraken_spot` du 2026-08-03 n'a ainsi jamais rien fait.
"""
from __future__ import annotations

import pytest

from backend.services import pair_admission_controller as pac


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    from backend.services import trade_log_service
    monkeypatch.setattr(trade_log_service, "_DB_PATH", tmp_path / "trades.db")
    monkeypatch.setattr(pac, "_SCHEMA_ENSURED", False)
    return tmp_path / "trades.db"


TOUTES = [
    "admin_legacy", "admin_live", "admin_kraken",
    "admin_kraken_spot", "admin_kraken_stocks", "admin_binance",
]


# --- la liste des destinations connues -------------------------------------

@pytest.mark.parametrize("dest", TOUTES)
def test_les_destinations_admin_reelles_sont_reconnues(dest):
    """Chacune existe dans bridge_destinations : aucune ne doit être inconnue."""
    assert pac._normalize_destination(dest) == dest


@pytest.mark.parametrize("dest", ["user:1", "user:2", "user:42"])
def test_les_destinations_multi_tenant_sont_reconnues(dest):
    assert pac._normalize_destination(dest) == dest


def test_normalisation_casse_et_espaces():
    assert pac._normalize_destination("  ADMIN_Kraken ") == "admin_kraken"
    assert pac._normalize_destination("USER:7") == "user:7"


@pytest.mark.parametrize("dest", ["user:", "user:abc", "userX:2", "admin_bogus", ""])
def test_les_valeurs_invalides_restent_invalides(dest):
    assert not pac.is_valid_destination(dest)


def test_none_signifie_toutes_les_destinations():
    assert pac._normalize_destination(None) is None


# --- l'écriture refuse plutôt que d'élargir --------------------------------

def test_ecriture_sur_destination_inconnue_leve():
    """En cas de doute, restreindre. Jamais replier en portée globale."""
    with pytest.raises(ValueError, match="Destination inconnue"):
        pac.set_state("BTC/USD", pac.STATE_AUTO_EXEC, "test",
                      direction="sell", destination="admin_typo")


def test_le_message_derreur_est_actionnable():
    with pytest.raises(ValueError) as e:
        pac.set_state("BTC/USD", pac.STATE_AUTO_EXEC, "test",
                      direction="sell", destination="kraken")
    msg = str(e.value)
    assert "admin_kraken" in msg and "user:<id>" in msg


# --- la régression elle-même ----------------------------------------------

def test_une_admission_kraken_ne_fuit_pas_vers_les_autres():
    """LE test de ce correctif : l'incident du 2026-08-04, à l'identique."""
    pac.set_state("BTC/USD", pac.STATE_DEMOTED, "etat de depart", direction="sell")
    pac.set_state("BTC/USD", pac.STATE_AUTO_EXEC, "test chaine",
                  direction="sell", destination="admin_kraken")

    assert pac.is_auto_exec_eligible("BTC/USD", "sell", "admin_kraken") is True
    assert pac.is_auto_exec_eligible("BTC/USD", "sell", "admin_live") is False
    assert pac.is_auto_exec_eligible("BTC/USD", "sell", "user:2") is False
    assert pac.is_auto_exec_eligible("BTC/USD", "sell", None) is False


def test_une_row_scopee_est_relisible_pour_sa_destination():
    """L'effet miroir : la promotion @admin_kraken_spot du 03/08 était morte."""
    pac.set_state("BTC/USD", pac.STATE_DEMOTED, "global", direction="buy")
    pac.set_state("BTC/USD", pac.STATE_AUTO_EXEC, "spot only",
                  direction="buy", destination="admin_kraken_spot")

    assert pac.get_current_state("BTC/USD", "buy", "admin_kraken_spot") == pac.STATE_AUTO_EXEC
    assert pac.get_current_state("BTC/USD", "buy", "admin_live") == pac.STATE_DEMOTED


def test_la_cascade_globale_reste_honoree():
    """Sans row spécifique, une destination hérite bien du global."""
    pac.set_state("XAU/USD", pac.STATE_AUTO_EXEC, "global", direction="sell")
    for dest in TOUTES + ["user:2"]:
        assert pac.is_auto_exec_eligible("XAU/USD", "sell", dest) is True


def test_chaque_destination_est_independante():
    pac.set_state("EUR/USD", pac.STATE_DEMOTED, "global", direction="buy")
    pac.set_state("EUR/USD", pac.STATE_AUTO_EXEC, "live", direction="buy",
                  destination="admin_live")
    pac.set_state("EUR/USD", pac.STATE_TELEGRAM, "legacy", direction="buy",
                  destination="admin_legacy")

    assert pac.get_current_state("EUR/USD", "buy", "admin_live") == pac.STATE_AUTO_EXEC
    assert pac.get_current_state("EUR/USD", "buy", "admin_legacy") == pac.STATE_TELEGRAM
    assert pac.get_current_state("EUR/USD", "buy", "admin_kraken") == pac.STATE_DEMOTED


# --- la lecture reste tolérante --------------------------------------------

def test_lecture_sur_destination_inconnue_ne_leve_pas(caplog):
    """Une lecture ne doit jamais casser le dispatch — mais elle doit alerter."""
    pac.set_state("XAU/USD", pac.STATE_AUTO_EXEC, "global", direction="sell")
    import logging
    with caplog.at_level(logging.WARNING):
        assert pac.get_current_state("XAU/USD", "sell", "inconnue") == pac.STATE_AUTO_EXEC
    assert any("destination inconnue" in r.message.lower() for r in caplog.records)
