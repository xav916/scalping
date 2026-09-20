"""Le blackout des news lit-il une source qu'il sait PARSER ? (2026-09-20)

⛔ POURQUOI CE FICHIER EXISTE, et c'est la lecon la plus chere de la journee.
`test_edges.py` contient six tests verts sur ce garde-fou depuis des mois. Ils
fabriquent leurs events avec `time=when.isoformat()`. Le producteur reel,
`forexfactory_service`, emet `dt.strftime("%H:%M")` — « 14:30 », sans date.
Resultat : six tests passent, et `signal_rejections` ne contient AUCUNE ligne
`event_blackout` depuis l'existence du code. Le garde-fou n'a jamais bloque un
ordre.

🔑 Une fixture plus capable que le producteur ne prouve rien. Ces tests-ci
pinnent donc le FORMAT REEL et le CHEMIN REEL, pas un format commode.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.services import event_blackout as eb

MAINTENANT = datetime(2026, 9, 24, 12, 30, tzinfo=timezone.utc)


# ─── 1. Le format du producteur, pinne a la source ──────────────────


def test_le_producteur_emet_une_heure_SANS_date():
    """⛔ Le defaut d'origine, pinne pour qu'il ne redevienne pas invisible.

    Si ce test casse un jour, c'est une BONNE nouvelle : cela voudra dire que
    `forexfactory_service` emet enfin un timestamp complet. Il faudra alors
    revenir ici et relire `_depuis_le_calendrier` — pas supprimer le test.
    """
    src = (Path(__file__).resolve().parents[1] / "services"
           / "forexfactory_service.py").read_text(encoding="utf-8")
    assert 'strftime("%H:%M")' in src, (
        "le producteur a change de format : relire event_blackout")
    assert eb._parse_event_time("14:30") is None, (
        "une heure sans date n'est pas rattrapable : « 14:30 » ne dit pas "
        "quel jour, et fromisoformat leve")


# ─── 2. Le chemin REEL : le calendrier en base ──────────────────────


def _calendrier(monkeypatch, retour):
    from backend.services import economic_calendar_service as ecs

    def _faux(within_minutes=30, min_impact="High", now=None):
        if isinstance(retour, Exception):
            raise retour
        return retour
    monkeypatch.setattr(ecs, "get_upcoming_events", _faux, raising=True)


def test_le_blackout_lit_le_calendrier_quand_rien_ne_lui_est_passe(monkeypatch):
    _calendrier(monkeypatch, [{"currency": "USD", "event_name": "FOMC Statement",
                               "impact": "High", "minutes_delta": 7}])
    etat = eb.is_blackout_for("XAU/USD", now=MAINTENANT)
    assert etat["active"] is True
    assert "FOMC" in etat["reason"] and "dans 7min" in etat["reason"]


def test_une_devise_etrangere_a_la_paire_ne_bloque_pas(monkeypatch):
    _calendrier(monkeypatch, [{"currency": "JPY", "event_name": "BOJ",
                               "impact": "High", "minutes_delta": 2}])
    assert eb.is_blackout_for("XAU/USD", now=MAINTENANT)["active"] is False
    # ... mais la meme annonce bloque une paire qui porte le JPY
    assert eb.is_blackout_for("GBP/JPY", now=MAINTENANT)["active"] is True


def test_calendrier_VIDE_et_calendrier_INJOIGNABLE_ne_sont_pas_la_meme_chose(
        monkeypatch, caplog):
    """⛔ Trois etats, jamais deux. « Aucune annonce » est une reponse ;
    « je n'ai pas pu regarder » est une panne, et elle doit CRIER."""
    _calendrier(monkeypatch, [])
    with caplog.at_level(logging.WARNING):
        assert eb.is_blackout_for("XAU/USD", now=MAINTENANT)["active"] is False
    assert not caplog.records, "un calendrier vide n'est pas un incident"

    caplog.clear()
    _calendrier(monkeypatch, RuntimeError("base verrouillee"))
    with caplog.at_level(logging.WARNING):
        assert eb.is_blackout_for("XAU/USD", now=MAINTENANT)["active"] is False
    assert any("injoignable" in r.message for r in caplog.records), (
        "un calendrier injoignable doit laisser une trace : sinon l'absence "
        "de protection est indistinguable de l'absence d'annonce")


# ─── 3. Le silence d'origine est devenu audible ─────────────────────


def test_des_events_ILLISIBLES_declenchent_un_avertissement(caplog):
    """Le chemin `events=` explicite reste, mais il ne se tait plus."""
    from types import SimpleNamespace
    events = [SimpleNamespace(currency="USD", impact=SimpleNamespace(value="high"),
                              time="14:30", event_name="CPI")]
    with caplog.at_level(logging.WARNING):
        etat = eb.is_blackout_for("XAU/USD", events=events, now=MAINTENANT)
    assert etat["active"] is False
    assert any("ILLISIBLE" in r.message for r in caplog.records), (
        "c'est exactement le cas qui a rendu le garde-fou inerte dix semaines")


def test_un_event_ISO_complet_passe_toujours_par_le_chemin_explicite():
    """Non-regression : les six tests de `test_edges.py` restent valides."""
    from types import SimpleNamespace
    quand = MAINTENANT.replace(minute=35)
    events = [SimpleNamespace(currency="USD", impact=SimpleNamespace(value="high"),
                              time=quand.isoformat(), event_name="CPI")]
    assert eb.is_blackout_for("XAU/USD", events=events, now=MAINTENANT)["active"] is True


# ─── 4. L'interrupteur d'arret ──────────────────────────────────────


def test_l_interrupteur_coupe_tout(monkeypatch):
    """⚠️ Ce garde-fou passe de « jamais declenche » a « actif », et il agit
    AVANT les verdict_blockers — donc sur toutes les destinations. Il doit
    pouvoir etre coupe sans redeployer une logique."""
    _calendrier(monkeypatch, [{"currency": "USD", "event_name": "NFP",
                               "impact": "High", "minutes_delta": 0}])
    monkeypatch.setattr(eb, "ACTIF", False, raising=True)
    assert eb.is_blackout_for("XAU/USD", now=MAINTENANT)["active"] is False
    monkeypatch.setattr(eb, "ACTIF", True, raising=True)
    assert eb.is_blackout_for("XAU/USD", now=MAINTENANT)["active"] is True


@pytest.mark.parametrize("paire,attendu", [
    ("XAU/USD", True), ("SPX", True), ("WTI/USD", True), ("EUR/GBP", False),
])
def test_quelles_paires_un_event_USD_concerne(monkeypatch, paire, attendu):
    _calendrier(monkeypatch, [{"currency": "USD", "event_name": "CPI",
                               "impact": "High", "minutes_delta": -3}])
    assert eb.is_blackout_for(paire, now=MAINTENANT)["active"] is attendu
