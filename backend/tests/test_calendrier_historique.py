"""Le calendrier economique ACCUMULE son historique. Il ne purge plus.

⛔ **CE QUI ETAIT EFFACE, ET POURQUOI C EST GRAVE.** `refresh_calendar()`
portait :

    # Purge les événements passés de >7j pour garder la table légère
    conn.execute("DELETE FROM economic_events WHERE ts_utc < ?", (cutoff,))

Sept jours glissants. Un evenement du 15 septembre n existait plus le 23.

🔑 Et c est l ETIQUETTE qu on perdait, pas les prix. Les bougies restent
disponibles chez le courtier a la demande — M5 jusqu au 2025-05-07, D1 jusqu en
avril 2021. Ce qui disparaissait, c est << ce jour-la a 12h30, publication de
l emploi americain, consensus 9,0K, reel -41,7K >>.

Sans l etiquette, une hypothese evenementielle est INEPROUVABLE
retroactivement : on a le prix du 15 septembre, mais plus le moyen de savoir ce
qui s y est passe. Xavier l a formule exactement : << si le pattern a eu lieu
il y a 3 semaines, comment on fait ? >>

## ⚠️ Ce que la purge economisait, mesure

    220 lignes = 45 056 octets, soit 205 octets par ligne
    4 000 evenements par an = 800 Ko/an
    la base entiere pese 88 Ko

On detruisait un historique irremplacable pour economiser moins qu une photo.
Le motif << garder la table legere >> etait sincere — le projet a connu un
disque a 97 % et un `backtest.db` qui grossit de 0,6 Go par jour — mais il ne
s applique PAS ici, et personne n avait fait la division.

⛔ Ce test existe pour qu une purge ne revienne jamais << pour alleger >>.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import economic_calendar_service as ec


@pytest.fixture
def base(tmp_path, monkeypatch):
    """Une base neuve, isolee, avec le schema reel."""
    chemin = tmp_path / "cal.db"
    monkeypatch.setattr(ec, "_DB_PATH", chemin, raising=False)
    monkeypatch.setattr(ec, "_get_db", lambda: sqlite3.connect(chemin))
    with sqlite3.connect(chemin) as c:
        c.execute("""CREATE TABLE economic_events (
            id TEXT PRIMARY KEY, ts_utc TEXT, currency TEXT,
            event_name TEXT, impact TEXT, actual TEXT, forecast TEXT,
            previous TEXT, fetched_at TEXT)""")
    return chemin


def _ancien(c, jours: int, nom: str = "Vieil evenement"):
    d = (datetime.now(timezone.utc) - timedelta(days=jours)).isoformat()
    c.execute("INSERT INTO economic_events VALUES (?,?,?,?,?,?,?,?,?)",
              (f"{d}_USD_{nom}", d, "USD", nom, "High", "1.0", "0.5", "0.4",
               d))


def test_un_rafraichissement_n_EFFACE_PAS_le_passe(base, monkeypatch):
    """⛔ LE TEST QUI COMPTE. Un evenement de trois semaines doit survivre a
    une synchro — sinon aucune hypothese evenementielle n est eprouvable."""
    with sqlite3.connect(base) as c:
        _ancien(c, 21, "Emploi americain")
        _ancien(c, 60, "Decision BCE")
        _ancien(c, 400, "Tres vieux")

    maintenant = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(ec, "_fetch_json", lambda: [{"x": 1}])
    monkeypatch.setattr(ec, "_parse_ff_json", lambda raw: [{
        "id": "neuf", "ts_utc": maintenant, "currency": "EUR",
        "event_name": "Neuf", "impact": "High", "actual": None,
        "forecast": None, "previous": None}])

    n = ec.refresh_calendar()
    assert n == 1

    with sqlite3.connect(base) as c:
        noms = {r[0] for r in c.execute("SELECT event_name FROM economic_events")}
    assert "Emploi americain" in noms, "l evenement de 3 semaines a ete EFFACE"
    assert "Decision BCE" in noms, "l evenement de 2 mois a ete EFFACE"
    assert "Tres vieux" in noms, "l evenement de 400 jours a ete EFFACE"
    assert "Neuf" in noms


def test_le_code_ne_contient_AUCUNE_purge(base):
    """⛔ Verrou de forme, assume. Un test de comportement ne peut pas
    distinguer << je ne purge pas >> de << je purge au-dela de ma fenetre de
    test >>. Celui-ci lit la source et refuse tout DELETE sur la table.

    ⚠️ Un test qui lit du code est faible — la memoire du projet le dit, et ce
    test vient d en faire la demonstration : sa 1re version echouait sur le
    COMMENTAIRE qui cite la purge retiree. D ou le depouillement ci-dessous, et
    d ou le fait qu il arrive EN PLUS du test de comportement, jamais a sa
    place.
    """
    import inspect
    src = inspect.getsource(ec.refresh_calendar)
    code = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
    assert "delete" not in code.lower(), (
        "une purge est revenue dans refresh_calendar : 800 Ko/an ne justifient "
        "pas de detruire un historique irremplacable")


def test_plusieurs_synchros_ACCUMULENT(base, monkeypatch):
    """Trois passages, trois evenements differents : les trois restent."""
    monkeypatch.setattr(ec, "_fetch_json", lambda: [{"x": 1}])
    for i in range(3):
        d = (datetime.now(timezone.utc) - timedelta(days=30 * i)).isoformat()
        monkeypatch.setattr(ec, "_parse_ff_json", lambda raw, _d=d, _i=i: [{
            "id": f"ev{_i}", "ts_utc": _d, "currency": "USD",
            "event_name": f"Evenement {_i}", "impact": "High",
            "actual": None, "forecast": None, "previous": None}])
        ec.refresh_calendar()

    with sqlite3.connect(base) as c:
        n = c.execute("SELECT COUNT(*) FROM economic_events").fetchone()[0]
    assert n == 3, f"{n} lignes au lieu de 3 — l accumulation ne tient pas"


def test_un_meme_evenement_RELU_ne_se_duplique_pas(base, monkeypatch):
    """⚠️ Accumuler n est pas doubler. `INSERT OR REPLACE` sur l `id` garantit
    qu une resynchro met a JOUR — ce qui importe : le champ `actual` arrive
    apres la publication, et doit remplacer le `None` initial."""
    monkeypatch.setattr(ec, "_fetch_json", lambda: [{"x": 1}])
    d = datetime.now(timezone.utc).isoformat()

    for actual in (None, "9.0K"):
        monkeypatch.setattr(ec, "_parse_ff_json", lambda raw, _a=actual: [{
            "id": "meme", "ts_utc": d, "currency": "CAD",
            "event_name": "Employment Change", "impact": "High",
            "actual": _a, "forecast": "9.0K", "previous": "-41.7K"}])
        ec.refresh_calendar()

    with sqlite3.connect(base) as c:
        lignes = list(c.execute(
            "SELECT actual FROM economic_events WHERE id = 'meme'"))
    assert len(lignes) == 1, "l evenement s est duplique"
    assert lignes[0][0] == "9.0K", "le `actual` publie n a pas remplace le None"
