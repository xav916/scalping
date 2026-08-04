"""Vocabulaire d'horizon — module pur, socle du routage (2026-08-05)."""
import pytest

from backend.services.horizon import (
    HORIZONS, LONG_HORIZONS, bar_minutes, is_long, normalize,
)


@pytest.mark.parametrize("brut,attendu", [
    ("5min", "5min"),
    ("5MIN", "5min"),
    (" 5min ", "5min"),
    ("5m", "5min"),
    ("15min", "15min"),
    ("1h", "1h"),
    ("1H", "1h"),
    ("4h", "4h"),
    ("4H", "4h"),
    ("1d", "1d"),
    ("1D", "1d"),
    ("1day", "1d"),
    ("daily", "1d"),
])
def test_normalize_reconnait_les_ecritures_du_code_existant(brut, attendu):
    # "1H" vient de VolatilityData.timeframe, "1day" de l'appel Twelve Data
    # dans run_shadow_log, "4h"/"1d" de SHADOW_CONFIG. Les trois cohabitent
    # deja en base : normalize est le point ou elles se rejoignent.
    assert normalize(brut) == attendu


@pytest.mark.parametrize("brut", [None, "", "  ", "2h", "3min", "1w", "inconnu"])
def test_normalize_rend_none_sur_inconnu_jamais_une_valeur_par_defaut(brut):
    # Regle globale du projet : inconnu vaut None, jamais une valeur inventee.
    # Rendre "5min" par defaut ferait passer un setup non etiquete pour du
    # scalping et le router vers de l'argent reel.
    assert normalize(brut) is None


def test_bar_minutes():
    assert bar_minutes("5min") == 5
    assert bar_minutes("15min") == 15
    assert bar_minutes("1h") == 60
    assert bar_minutes("4h") == 240
    assert bar_minutes("1d") == 1440


def test_bar_minutes_rend_none_sur_inconnu():
    assert bar_minutes("2h") is None
    assert bar_minutes(None) is None


def test_bar_minutes_accepte_les_ecritures_non_normalisees():
    # Un appelant ne doit pas avoir a normaliser avant d'interroger.
    assert bar_minutes("4H") == 240
    assert bar_minutes("1day") == 1440


def test_is_long_separe_le_portage_du_scalping():
    # Le portage (funding, swap, gap de week-end) n'existe qu'a partir de 4h.
    assert is_long("4h") is True
    assert is_long("1d") is True
    assert is_long("1h") is False
    assert is_long("5min") is False


def test_is_long_est_faux_sur_inconnu_et_ne_leve_pas():
    # Fail-safe : un horizon inconnu n'active pas les regles de portage,
    # mais la porte de la tache 3 le bloquera de toute facon.
    assert is_long(None) is False
    assert is_long("inconnu") is False


def test_tous_les_horizons_declares_sont_mesurables():
    # Garde-fou : ajouter un horizon a HORIZONS sans lui donner sa duree
    # ferait rendre None a bar_minutes en production, silencieusement.
    for h in HORIZONS:
        assert bar_minutes(h) is not None, h
        assert normalize(h) == h, h


def test_les_horizons_longs_sont_un_sous_ensemble_des_horizons():
    assert LONG_HORIZONS <= set(HORIZONS)
