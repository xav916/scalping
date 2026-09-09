"""Une position d'argent réel ouverte SANS stop doit le dire SUR SON FIL.

⛔ Le 2026-09-09, mesure sur le compte réel : **6 positions ouvertes sans
stop** (5,2 % des poussées où le champ existe), dont 3 sur l'or. Le bridge le
disait honnêtement — `protected:false`, `sl_error:"Invalid request"` — et le
code émettait bien une alerte.

**Zéro alerte reçue en 7 jours.**

Deux causes empilées, toutes deux déjà connues de ce dépôt :

1. L'alerte partait sur **`infra`**, où un événement qui engage de l'argent
   réel se noie. Motif identique au récap du moteur de promotion
   ([[project_or_eteint_sur_le_reel_2026_09_08]]) et au backup cassé
   ([[project_backup_casse_5_nuits_2026_09_04]]) : *l'alerte arrivait, elle
   s'est noyée dans le bruit.*
2. Les notifications Python étaient **muettes** jusqu'au 2026-09-08 (jeton en
   en-tête ⇒ 403 avalé) — corrigé par `canaux_telegram.notifier`, le seul
   endroit qui sait appeler l'endpoint.

⇒ Une alerte qui engage l'argent d'un compte part sur le FIL DE CE COMPTE.
C'est la règle déjà posée pour les rétrogradations ; elle n'avait pas été
propagée ici. *Un correctif ne se propage pas seul aux routes jumelles.*
"""
from unittest.mock import patch

import pytest

from backend.services import mt5_bridge


REPONSE_NUE = {
    "ok": True,
    "ticket": 1357451117,
    "protected": False,
    "sl_applied": False,
    "sl_error": "Invalid request",
    "fill_source": "requested",
}


@pytest.fixture
def envois():
    """Capture ce qui part, et sur quel canal.

    🔑 Une SEULE porte : `canaux_telegram.notifier`. C'est la seule qui sait
    appeler l'endpoint (jeton en paramètre d'URL, pas en en-tête — le 403 avalé
    du 2026-09-08), et `canal_pour` retombe déjà sur `infra` quand la
    destination n'a pas de fil. Deux portes, ce serait deux façons d'échouer.
    """
    envoyes: list[dict] = []

    def _notifier(canal, titre, corps, **kw):
        envoyes.append({"canal": canal, "titre": titre, "corps": corps})
        return True

    with patch("backend.services.canaux_telegram.notifier", _notifier):
        yield envoyes


def test_l_alerte_part_sur_le_fil_du_compte_reel(envois):
    """⛔ Le cœur : `admin_live` a son fil, l'alerte doit y aller."""
    mt5_bridge._alerter_position_sans_stop(
        "admin_live", "XAU/USD", "sell", REPONSE_NUE)

    assert envois, "aucune alerte émise pour une position réelle sans stop"
    assert envois[0]["canal"] == "ic_markets", (
        f"l'alerte est repartie ailleurs que sur le fil du compte : {envois}"
    )


def test_l_alerte_nomme_le_ticket_et_la_cause(envois):
    """Une alerte qu'on ne peut pas agir est une alerte perdue."""
    mt5_bridge._alerter_position_sans_stop(
        "admin_live", "XAU/USD", "sell", REPONSE_NUE)

    corps = envois[0]["corps"]
    assert "1357451117" in corps
    assert "Invalid request" in corps


def test_une_position_PROTEGEE_n_alerte_pas(envois):
    """⚠️ Le cas nominal est 95 % du flux : il doit rester silencieux."""
    mt5_bridge._alerter_position_sans_stop(
        "admin_live", "XAU/USD", "sell", {**REPONSE_NUE, "protected": True})

    assert envois == []


def test_un_bridge_SANS_le_champ_n_alerte_pas(envois):
    """⛔ `protected` n'existe que depuis le 2026-08-06. Son ABSENCE ne
    distingue pas « non protégé » de « bridge pas encore patché » — on ne
    suppose donc rien, exactement comme le code d'origine (`is False`)."""
    mt5_bridge._alerter_position_sans_stop(
        "admin_live", "XAU/USD", "sell", {"ok": True, "ticket": 42})

    assert envois == []


def test_une_destination_HORS_trading_retombe_sur_infra(envois):
    """Tout compte n'a pas de fil. Ne rien envoyer serait pire que `infra`."""
    mt5_bridge._alerter_position_sans_stop(
        "admin_inconnu", "XAU/USD", "sell", REPONSE_NUE)

    assert envois, "une destination sans fil ne doit pas faire disparaître l'alerte"
    assert envois[0]["canal"] == "infra"
