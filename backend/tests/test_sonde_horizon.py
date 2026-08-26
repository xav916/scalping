"""La sonde qui garde le remplissage de `horizon`.

⛔ Ce qu'elle empêche : l'essai `or-4h-2026-08-26` ne compte que les clôtures
portant `horizon = '4h'`. Si le dispatch cesse de le transmettre dans un cas non
prévu, l'essai **n'accumulera rien** — et un essai qui n'accumule rien ressemble
exactement à un marché calme. On attendrait des mois pour découvrir qu'on a
attendu pour rien.

Les tests portent sur la fonction de décision, pas sur l'envoi : c'est là que
sont les jugements, et c'est ce qui doit rester juste.
"""
from __future__ import annotations

import pytest


def _t(horizon, pair="XAU/USD"):
    return {"pair": pair, "horizon": horizon}


# ── Le régime nominal ─────────────────────────────────────────────────────

def test_aucun_trade_recent_ne_declenche_rien():
    """⚠️ Le silence n'est pas une preuve, mais il n'est pas non plus une
    panne : sans trade, il n'y a rien à juger."""
    from scripts.notify_horizon_rempli import juger

    v = juger(recents=[], essai_n_obs=0, essai_min=60,
              clotures_or_depuis_declaration=0, confirmation_deja_envoyee=False)
    assert v["action"] == "rien"


def test_le_premier_trade_rempli_declenche_la_confirmation():
    """Un détecteur ne se teste pas sur son silence : la sonde doit dire au
    moins une fois que la chaîne fonctionne."""
    from scripts.notify_horizon_rempli import juger

    v = juger(recents=[_t("4h"), _t("4h")], essai_n_obs=0, essai_min=60,
              clotures_or_depuis_declaration=0, confirmation_deja_envoyee=False)
    assert v["action"] == "confirmation"
    assert v["remplis"] == 2


def test_apres_confirmation_la_sonde_se_tait_quand_tout_va_bien():
    from scripts.notify_horizon_rempli import juger

    v = juger(recents=[_t("4h"), _t("1h")], essai_n_obs=3, essai_min=60,
              clotures_or_depuis_declaration=3, confirmation_deja_envoyee=True)
    assert v["action"] == "rien"


# ── La régression ─────────────────────────────────────────────────────────

def test_un_trade_sans_horizon_est_une_regression():
    """⛔ C'est le point de rupture le plus probable de toute la chaîne."""
    from scripts.notify_horizon_rempli import juger

    v = juger(recents=[_t("4h"), _t(None), _t(None)], essai_n_obs=1, essai_min=60,
              clotures_or_depuis_declaration=1, confirmation_deja_envoyee=True)
    assert v["action"] == "alerte"
    assert v["manquants"] == 2
    assert "horizon" in v["message"].lower()


def test_la_regression_prime_sur_la_confirmation():
    """Si la toute première fenêtre contient déjà des trous, c'est l'alerte qui
    part — pas un message rassurant suivi d'un silence."""
    from scripts.notify_horizon_rempli import juger

    v = juger(recents=[_t("4h"), _t(None)], essai_n_obs=0, essai_min=60,
              clotures_or_depuis_declaration=0, confirmation_deja_envoyee=False)
    assert v["action"] == "alerte"


# ── L'essai qui n'accumule pas ────────────────────────────────────────────

def test_de_l_or_qui_cloture_sans_rien_nourrir_alerte():
    """⛔ Le cas qui ressemble le plus à un marché calme : l'or trade, l'essai
    reste à zéro. Sans ce contrôle, personne ne le verrait avant des mois."""
    from scripts.notify_horizon_rempli import juger

    v = juger(recents=[_t("4h")], essai_n_obs=0, essai_min=60,
              clotures_or_depuis_declaration=12, confirmation_deja_envoyee=True)
    assert v["action"] == "alerte"
    assert "n'accumule" in v["message"] or "accumule" in v["message"]


def test_peu_de_clotures_or_ne_suffit_pas_a_crier():
    """En dessous du seuil, l'absence d'accumulation peut n'être que la lenteur
    normale du 4 h. Crier là-dessus rendrait la sonde inaudible."""
    from scripts.notify_horizon_rempli import juger

    v = juger(recents=[_t("4h")], essai_n_obs=0, essai_min=60,
              clotures_or_depuis_declaration=2, confirmation_deja_envoyee=True)
    assert v["action"] == "rien"


def test_un_essai_qui_avance_ne_declenche_rien():
    from scripts.notify_horizon_rempli import juger

    v = juger(recents=[_t("4h")], essai_n_obs=9, essai_min=60,
              clotures_or_depuis_declaration=12, confirmation_deja_envoyee=True)
    assert v["action"] == "rien"


# ── Le message ────────────────────────────────────────────────────────────

def test_le_message_dit_quoi_faire_pas_seulement_ce_qui_ne_va_pas():
    from scripts.notify_horizon_rempli import juger

    v = juger(recents=[_t(None)] * 4, essai_n_obs=0, essai_min=60,
              clotures_or_depuis_declaration=0, confirmation_deja_envoyee=True)
    assert v["action"] == "alerte"
    assert "mt5_pushes" in v["message"], "le message doit nommer où regarder"
