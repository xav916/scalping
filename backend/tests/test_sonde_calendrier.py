"""La sonde qui repond a UNE question : ForexFactory nous donne-t-il un jour
le chiffre PUBLIE ?

## Pourquoi elle existe

Mesure du 2026-10-04 sur la base de production :

    220 evenements · 116 avec PREVISION · 150 avec PRECEDENTE · 0 avec ACTUEL

Zero. Et le flux `ff_calendar_thisweek.json` couvre une fenetre qui GLISSE vers
l'avant (04/10 -> 09/10 au moment de la mesure), avec UN seul evenement deja
passe, sans chiffre. `lastweek.json` et `nextweek.json` repondent 404.

🔑 Sans le chiffre publie, la SURPRISE (reel - prevision) est incalculable — or
c'est elle, et non la prevision, qui peut faire bouger un prix : la prevision
est le consensus public, deja dans le cours.

⚠️ Un seul evenement passe un DIMANCHE ne prouve rien. D'ou cette sonde : elle
synchronise toutes les heures et parle le jour ou un `actual` apparait. Lundi
est charge en publications ; on saura mardi.

## Ce qu'elle ne fait pas

⛔ Elle n'ecrit pas dans le calendrier autrement qu'en appelant
`refresh_calendar()`. Elle observe, elle ne fabrique pas la donnee qu'elle
mesure.
"""
from __future__ import annotations

import sqlite3

import pytest

from scripts import sonde_calendrier as sc


@pytest.fixture
def base(tmp_path):
    chemin = tmp_path / "scalping.db"
    with sqlite3.connect(chemin) as c:
        c.execute("""CREATE TABLE economic_events (
            id TEXT PRIMARY KEY, ts_utc TEXT NOT NULL, currency TEXT NOT NULL,
            event_name TEXT NOT NULL, impact TEXT NOT NULL, actual TEXT,
            forecast TEXT, previous TEXT, fetched_at TEXT NOT NULL)""")
    return chemin


def _ev(chemin, eid, nom, actual=None, forecast=None, impact="High"):
    with sqlite3.connect(chemin) as c:
        c.execute(
            "INSERT OR REPLACE INTO economic_events "
            "(id, ts_utc, currency, event_name, impact, actual, forecast, "
            " previous, fetched_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (eid, "2026-10-05T12:30:00+00:00", "USD", nom, impact,
             actual, forecast, None, "2026-10-05T13:00:00+00:00"))


# ─── Le comptage ────────────────────────────────────────────────────────────

def test_compte_separement_prevision_precedente_et_ACTUEL(base):
    _ev(base, "a", "Avec tout", actual="1.2", forecast="1.0")
    _ev(base, "b", "Sans reel", forecast="2.0")
    _ev(base, "c", "Nu")
    m = sc.mesurer(base)
    assert m["total"] == 3
    assert m["forecast"] == 2
    assert m["actual"] == 1


def test_une_base_vide_ne_fait_pas_tomber_la_sonde(base):
    m = sc.mesurer(base)
    assert m == {"total": 0, "forecast": 0, "previous": 0, "actual": 0}


def test_une_base_INJOIGNABLE_rend_None_et_ne_leve_pas(tmp_path):
    """⛔ Trois etats, jamais deux. Confondre « aucun chiffre » et « je n'ai
    pas pu regarder » est exactement le defaut que `event_blackout` a paye."""
    assert sc.mesurer(tmp_path / "inexistante.db") is None


# ─── La detection de la NOUVEAUTE ───────────────────────────────────────────

def test_signale_un_actual_qui_APPARAIT(base):
    _ev(base, "a", "Nonfarm Payrolls", forecast="50.0")
    assert sc.nouveaux_actuels(base, {"vus": []}) == []

    _ev(base, "a", "Nonfarm Payrolls", actual="-140.0", forecast="50.0")
    neufs = sc.nouveaux_actuels(base, {"vus": []})
    assert len(neufs) == 1
    assert neufs[0]["id"] == "a"
    assert neufs[0]["actual"] == "-140.0"
    assert neufs[0]["forecast"] == "50.0"


def test_ne_resignale_PAS_ce_qui_a_deja_ete_vu(base):
    """Sinon la sonde crierait toutes les heures sur le meme evenement."""
    _ev(base, "a", "Nonfarm Payrolls", actual="-140.0", forecast="50.0")
    assert sc.nouveaux_actuels(base, {"vus": ["a"]}) == []


def test_l_etat_n_oublie_jamais_un_identifiant(base):
    """⚠️ Le curseur ne doit jamais reculer : un oubli reannoncerait un vieux
    chiffre comme une decouverte."""
    etat = {"vus": ["a", "b"]}
    _ev(base, "c", "Nouveau", actual="1.0")
    neufs = sc.nouveaux_actuels(base, etat)
    suivant = sc.etat_suivant(etat, neufs)
    assert set(suivant["vus"]) == {"a", "b", "c"}


# ─── Le message ─────────────────────────────────────────────────────────────

def test_le_message_ECHAPPE_le_texte_venu_de_la_base(base):
    """⛔ Defaut reel du 2026-10-03 : un motif contenant `sample too small
    (n=5 < 10)` a fait refuser TOUT le message en HTTP 400. Un nom
    d'evenement peut contenir `<` ou `&` — ex. « M/M & Y/Y »."""
    neufs = [{"id": "x", "ts_utc": "2026-10-05T12:30:00+00:00",
              "currency": "USD", "event_name": "CPI <core> & M/M",
              "actual": "1.0", "forecast": "0.5"}]
    txt = sc.message(neufs, {"total": 1, "forecast": 1, "previous": 0,
                             "actual": 1})
    assert "&lt;core&gt;" in txt
    assert "&amp;" in txt
    assert "<core>" not in txt


def test_le_message_dit_la_SURPRISE_quand_elle_est_calculable(base):
    neufs = [{"id": "x", "ts_utc": "2026-10-05T12:30:00+00:00",
              "currency": "CAD", "event_name": "Employment Change",
              "actual": "-41.7", "forecast": "9.0"}]
    txt = sc.message(neufs, {"total": 1, "forecast": 1, "previous": 0,
                             "actual": 1})
    assert "-41.7" in txt and "9.0" in txt
    assert "-50.7" in txt, "l'ecart reel - prevision doit apparaitre"


def test_un_chiffre_ILLISIBLE_ne_fait_pas_tomber_le_message():
    """Les valeurs ForexFactory sont du TEXTE : « 9.0K », « 6.4% », « <0.1 ».
    On affiche sans calculer plutot que de lever."""
    neufs = [{"id": "x", "ts_utc": "2026-10-05T12:30:00+00:00",
              "currency": "USD", "event_name": "Un truc",
              "actual": "9.0K", "forecast": "6.4%"}]
    txt = sc.message(neufs, {"total": 1, "forecast": 1, "previous": 0,
                             "actual": 1})
    assert "9.0K" in txt and "6.4%" in txt


# ─── Le comportement d'ensemble ─────────────────────────────────────────────

def test_la_sonde_se_TAIT_quand_rien_n_apparait(base, monkeypatch):
    """Mode evenement : elle ne parle que si quelque chose a change. Sinon
    elle crierait 24 fois par jour pour rien."""
    _ev(base, "a", "Rien de neuf", forecast="1.0")
    envois = []
    monkeypatch.setattr(sc, "_synchroniser", lambda: 0)
    monkeypatch.setattr(sc, "_envoyer", lambda txt: envois.append(txt) or True)
    monkeypatch.setattr(sc, "DB", str(base))
    monkeypatch.setattr(sc, "_etat_lu", lambda: {"vus": []})
    monkeypatch.setattr(sc, "_etat_ecrit", lambda d: None)

    assert sc.main() == 0
    assert envois == [], "la sonde a parle alors que rien n'a change"


def test_la_sonde_PARLE_au_premier_chiffre_publie(base, monkeypatch):
    _ev(base, "a", "Nonfarm Payrolls", actual="-140.0", forecast="50.0")
    envois = []
    monkeypatch.setattr(sc, "_synchroniser", lambda: 1)
    monkeypatch.setattr(sc, "_envoyer", lambda txt: envois.append(txt) or True)
    monkeypatch.setattr(sc, "DB", str(base))
    monkeypatch.setattr(sc, "_etat_lu", lambda: {"vus": []})
    monkeypatch.setattr(sc, "_etat_ecrit", lambda d: None)

    assert sc.main() == 0
    assert len(envois) == 1
    assert "Nonfarm Payrolls" in envois[0]


def test_une_synchro_en_ECHEC_n_empeche_pas_la_mesure(base, monkeypatch):
    """⚠️ `refresh_calendar()` est best-effort et rend 0 si la source est
    indisponible. La sonde doit quand meme regarder la base : un chiffre a pu
    arriver au passage precedent."""
    _ev(base, "a", "Nonfarm Payrolls", actual="-140.0", forecast="50.0")
    envois = []

    def synchro_cassee():
        raise RuntimeError("source indisponible")

    monkeypatch.setattr(sc, "_synchroniser", synchro_cassee)
    monkeypatch.setattr(sc, "_envoyer", lambda txt: envois.append(txt) or True)
    monkeypatch.setattr(sc, "DB", str(base))
    monkeypatch.setattr(sc, "_etat_lu", lambda: {"vus": []})
    monkeypatch.setattr(sc, "_etat_ecrit", lambda d: None)

    assert sc.main() == 0
    assert len(envois) == 1, "la panne de synchro a emporte la mesure"


def test_la_sonde_n_ECRIT_PAS_dans_le_calendrier(base, monkeypatch):
    """⛔ Elle observe, elle ne fabrique pas la donnee qu'elle mesure. Une
    sonde qui ecrit dans ce qu'elle observe ne mesure plus rien."""
    import inspect
    src = "".join(inspect.getsource(f) for f in
                  (sc.mesurer, sc.nouveaux_actuels, sc.etat_suivant,
                   sc.message, sc.main))
    code = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
    for interdit in ("insert", "update ", "delete", "drop", "alter"):
        assert interdit not in code.lower(), (
            f"la sonde contient un `{interdit}` : elle ecrirait dans ce "
            f"qu'elle observe")
