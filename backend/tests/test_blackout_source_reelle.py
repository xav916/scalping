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


# ─── 5. Une seule source de verite : la base avant le reseau ─────────


def test_le_feed_n_est_PLUS_appele_quand_la_base_repond(monkeypatch):
    """⛔ Le defaut mesure en production le 2026-09-20 :

        20:04:49  economic_calendar_service: refreshed 73 events   <- OK
        20:04:51  forexfactory_service: JSON feed failed: 429      <- jete

    Deux services, la MEME url, deux secondes d'ecart. Ce test pinne l'ordre
    corrige : la base d'abord, le reseau seulement si elle est vide.
    """
    import asyncio

    from backend.services import forexfactory_service as ff

    appels_reseau = []

    async def _jamais():
        appels_reseau.append(1)
        return []

    monkeypatch.setattr(ff, "_fetch_from_json_feed", _jamais, raising=True)
    monkeypatch.setattr(ff, "_fetch_from_html", _jamais, raising=True)
    monkeypatch.setattr(ff, "_cache", None, raising=False)
    monkeypatch.setattr(ff, "_depuis_le_calendrier",
                        lambda heures=36: [
                            ff.EconomicEvent(time="14:30", currency="USD",
                                             impact=ff.EventImpact.HIGH,
                                             event_name="Core PCE")],
                        raising=True)
    events = asyncio.run(ff.fetch_economic_events())
    assert len(events) == 1 and events[0].event_name == "Core PCE"
    assert appels_reseau == [], (
        "la base a repondu : aucun appel reseau ne doit partir")


def test_le_reseau_reste_le_repli_quand_la_base_est_vide(monkeypatch):
    """⚠️ Et l'inverse doit rester vrai : une base vide ne doit pas rendre le
    calendrier definitivement muet — sinon une premiere installation n'aurait
    jamais d'events."""
    import asyncio

    from backend.services import forexfactory_service as ff

    async def _feed():
        return [ff.EconomicEvent(time="12:00", currency="EUR",
                                 impact=ff.EventImpact.MEDIUM, event_name="IFO")]

    monkeypatch.setattr(ff, "_cache", None, raising=False)
    monkeypatch.setattr(ff, "_depuis_le_calendrier", lambda heures=36: [], raising=True)
    monkeypatch.setattr(ff, "_fetch_from_json_feed", _feed, raising=True)
    events = asyncio.run(ff.fetch_economic_events())
    assert len(events) == 1 and events[0].event_name == "IFO"


# ─── 6. La TRACE : savoir QUOI a ete bloque, pas seulement QUE ────────


def test_la_decision_porte_de_quoi_juger_le_garde_fou(monkeypatch):
    """🔑 Ce qu'on construit A LA PLACE d'une file d'attente.

    Le cooldown vaut 0 en production (`cooldown_symbole` : zero refus depuis
    toujours), donc un setup encore valide est deja re-emis au cycle suivant
    avec des niveaux RECALCULES. Ce qui manquait n'etait pas la reprise, c'etait
    la mesure : sans l'annonce en cause et son ecart, on saurait qu'un ordre a
    ete bloque sans pouvoir dire si c'etait un gagnant ou un perdant.
    """
    _calendrier(monkeypatch, [{"currency": "USD", "event_name": "Core PCE",
                               "impact": "High", "minutes_delta": -4,
                               "ts_utc": "2026-09-24T12:34:00+00:00"}])
    st = eb.is_blackout_for("XAU/USD", now=MAINTENANT)
    assert st["active"] is True
    # la phrase reste, pour les logs et les appelants qui la citent
    assert "Core PCE" in st["reason"] and "il y a 4min" in st["reason"]
    # ... et les champs structures, pour le contrefactuel
    assert st["event"] == "Core PCE"
    assert st["currency"] == "USD"
    assert st["minutes_delta"] == -4
    assert st["ts_utc"] == "2026-09-24T12:34:00+00:00"


def test_une_decision_NEGATIVE_ne_porte_pas_de_faux_detail(monkeypatch):
    """⚠️ Pas de champs fantomes : un dict inactif ne doit pas laisser croire
    qu'une annonce a ete trouvee."""
    _calendrier(monkeypatch, [])
    st = eb.is_blackout_for("XAU/USD", now=MAINTENANT)
    assert st["active"] is False
    assert st.get("event") is None and st.get("minutes_delta") is None
