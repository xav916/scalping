"""Le journal des envois Telegram — et les trois cadences non gardées.

> Xavier, 2026-10-11 : « faire 1 et 2 ».

## ⛔ ① LE TROU : on ne pouvait PAS compter

En faisant l'inventaire du fil IC Markets, j'ai pu dire **qui tente** d'écrire
et **à quelle cadence**. Pas combien de messages arrivent : ni table, ni log,
ni trace. Deux conséquences réelles :

- les **huit copies** du même message du 2026-10-07 ont passé sans être
  comptées ;
- la rationalisation en trois étages, armée le soir même, était
  **invérifiable**.

## ⛔ ② LES TROIS CADENCES QUI TUAIENT TOUT L'ORDONNANCEUR

`start_scheduler()` écrivait `int(os.getenv("ECHELLE_STOP_INTERVAL_SEC", "15"))`
sans garde. Une valeur illisible lève, et comme l'appel est **dans**
`start_scheduler`, **aucun travail n'est déclaré après cette ligne**. Le
2026-10-11, un `.env` dont une ligne s'était collée à la précédente a fait
disparaître l'échelle de stop **et** la boucle légère — conteneur `active`,
ordonnanceur mort.
"""
from __future__ import annotations

import datetime as dt

import pytest

from backend.services import journal_envois_telegram as J


# ─── ① Le journal : toutes les issues, jamais une exception ──────────────

def test_tracer_ecrit_et_rend_vrai(tmp_path):
    db = str(tmp_path / "j.db")
    assert J.tracer("envoye", "ic_markets", "ic_markets", "nue", "agir",
                    "Position nue", None, 120, db) is True


def test_un_journal_indisponible_rend_FAUX_et_ne_leve_PAS():
    """⛔ Un journal indisponible est un désagrément ; un message de trade
    perdu parce que son journal était plein serait une faute."""
    assert J.tracer("envoye", chemin="/chemin/inexistant/x.db") is False


@pytest.mark.parametrize("issue", list(J.ISSUES))
def test_les_CINQ_issues_sont_tracees(tmp_path, issue):
    """⛔ Ne tracer que les succès ferait lire un émetteur qui échoue mille
    fois par jour comme un émetteur MUET, et un cooldown qui étouffe une
    alerte comme une absence d'alerte."""
    db = str(tmp_path / "j.db")
    assert J.tracer(issue, "ic_markets", "ic_markets", "k", None, "t", None,
                    1, db) is True
    b = J.bilan(1, chemin=db)
    assert [x["issue"] for x in b] == [issue]


def test_une_issue_HORS_LISTE_est_tracee_quand_meme(tmp_path, caplog):
    """On ne perd pas une trace pour une faute de frappe — mais on la crie."""
    db = str(tmp_path / "j.db")
    with caplog.at_level("ERROR"):
        assert J.tracer("bizarre", "ic_markets", chemin=db) is True
    assert any("hors de" in r.message for r in caplog.records)
    assert len(J.bilan(1, chemin=db)) == 1


def test_le_titre_est_TRONQUE(tmp_path):
    """⚠️ Le journal sert à COMPTER, pas à archiver. 4 000 caractères par ligne
    feraient plusieurs gigaoctets en quelques mois — ce disque porte déjà une
    `backtest.db` de 7,2 Go."""
    db = str(tmp_path / "j.db")
    J.tracer("envoye", "ic_markets", "ic_markets", "k", None, "T" * 4000,
             "D" * 4000, 1, db)
    with J._db(db) as c:
        l = list(c.execute(f"SELECT titre, detail FROM {J.TABLE}"))[0]
    assert len(l["titre"]) == 200
    assert len(l["detail"]) == 200


# ─── ② Le bilan : par émetteur, par issue ────────────────────────────────

def test_le_bilan_groupe_par_PREFIXE(tmp_path):
    """🔑 Comme la table des étages : le préfixe est la seule partie stable
    d'une clé qui porte une identité variable."""
    db = str(tmp_path / "j.db")
    for t in range(7):
        J.tracer("envoye", "ic_markets", "ic_markets",
                 f"tiers_objectif:{t}:1.8", "digest", "Palier", None, 10, db)
    J.tracer("echec", "ic_markets", "ic_markets", "nue", "agir", "Nue",
             "telegram 502", 10, db)
    b = J.bilan(1, chemin=db)
    par = {(x["emetteur"], x["issue"]): x["n"] for x in b}
    assert par[("tiers_objectif", "envoye")] == 7, b
    assert par[("nue", "echec")] == 1


def test_le_bilan_ne_remonte_PAS_au_dela_de_la_fenetre(tmp_path):
    db = str(tmp_path / "j.db")
    vieux = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    J.tracer("envoye", "ic_markets", "ic_markets", "nue", None, "t", None, 1,
             db, maintenant=vieux)
    assert J.bilan(1, chemin=db) == []
    assert len(J.bilan(400, chemin=db)) == 1


def test_un_bilan_illisible_rend_une_liste_VIDE_sans_lever():
    assert J.bilan(1, chemin="/chemin/inexistant/x.db") == []


def test_la_purge_garde_la_fenetre_et_retire_le_reste(tmp_path):
    db = str(tmp_path / "j.db")
    vieux = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    J.tracer("envoye", "ic_markets", "ic_markets", "a", None, "t", None, 1,
             db, maintenant=vieux)
    J.tracer("envoye", "ic_markets", "ic_markets", "b", None, "t", None, 1, db)
    assert J.purger(90, db) == 1
    restant = J.bilan(400, chemin=db)
    assert [x["emetteur"] for x in restant] == ["b"]


# ─── ③ Les accroches : la ROUTE trace chaque issue ───────────────────────

VALID_TOKEN = "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
URL = f"/api/admin/notify-infra-telegram?token={VALID_TOKEN}&channel=ic_markets"


@pytest.fixture
def client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from backend.app import app

    db = str(tmp_path / "j.db")
    traces = []
    vrai = J.tracer

    def _espion(*a, **k):
        k.setdefault("chemin", db)
        traces.append((a[0] if a else k.get("issue"), a, k))
        return vrai(*a, **k)

    monkeypatch.setattr(J, "tracer", _espion)

    class _R:
        status_code = 200
        text = "{}"
        def json(self): return {"ok": True}

    class _FauxAsync:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, **kw): return _R()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _FauxAsync)
    from config import settings as _cfg
    monkeypatch.setattr(_cfg, "SALES_TELEGRAM_BOT_TOKEN", "9:FAUX", raising=False)
    monkeypatch.setattr(_cfg, "SALES_TELEGRAM_CHAT_ID", "1", raising=False)
    monkeypatch.setattr(_cfg, "INFRA_TELEGRAM_BOT_TOKEN", "8:FAUX", raising=False)
    monkeypatch.setattr(_cfg, "INFRA_TELEGRAM_CHAT_ID", "2", raising=False)
    return TestClient(app), traces


def test_la_route_trace_un_ENVOI(client):
    cli, traces = client
    r = cli.post(URL, json={"title": "Nue", "body": "x", "dedup_key": "nue"})
    assert r.status_code == 200, r.text
    assert [t[0] for t in traces] == ["envoye"], traces


def test_la_route_trace_un_COOLDOWN(client):
    """⛔ Un cooldown qui tait une alerte se lirait sinon comme une absence
    d'alerte."""
    cli, traces = client
    corps = {"title": "Nue", "body": "x", "dedup_key": "nue_cd",
             "cooldown_seconds": 600}
    assert cli.post(URL, json=corps).status_code == 200
    traces.clear()
    r2 = cli.post(URL, json=corps)
    assert r2.json().get("skipped") == "cooldown", r2.text
    assert [t[0] for t in traces] == ["cooldown"], traces


def test_la_route_trace_un_DIFFERE(monkeypatch, client):
    cli, traces = client
    monkeypatch.setenv("ETAGES_NOTIFICATION", "1")
    r = cli.post(URL, json={"title": "Palier", "body": "x",
                            "dedup_key": "tiers_objectif:1:1.8"})
    assert r.json().get("differe") == "bilan_du_jour", r.text
    assert "differe" in [t[0] for t in traces], traces


def test_la_route_trace_un_REROUTAGE(monkeypatch, client):
    cli, traces = client
    monkeypatch.setenv("ETAGES_NOTIFICATION", "1")
    r = cli.post(URL, json={"title": "IBKR", "body": "x",
                            "dedup_key": "ibkr-digest"})
    assert r.status_code == 200, r.text
    issues = [t[0] for t in traces]
    assert "reroute" in issues, traces
    assert "envoye" in issues, "le message n'est pas parti après reroutage"


# ─── ④ Les trades : ils ne passent PAS par la route ─────────────────────

def test_le_relais_de_trade_existe_et_est_appele_aux_DEUX_sites():
    """🔑 `telegram_service` parle à Telegram EN DIRECT : un journal posé
    seulement sur la route manquerait **exactement** les messages que Xavier a
    demandé de garder — et on en conclurait qu'il n'en reçoit aucun."""
    import inspect
    from backend.services import telegram_service as T
    src = inspect.getsource(T)
    assert "def _tracer_trade(" in src
    assert src.count('_tracer_trade("envoye"') == 2, "un des deux sites manque"
    assert src.count('_tracer_trade("echec"') == 4, "les échecs ne sont pas tous tracés"
    assert '"trade_ouvert"' in src and '"trade_ferme"' in src


def test_le_canal_de_trace_est_defini_avant_chaque_usage():
    """⛔ J'avais écrit `_canal_trace` sans le définir : un `NameError` qui
    n'apparaîtrait qu'à la PREMIÈRE fermeture de trade réelle."""
    import inspect
    from backend.services import telegram_service as T
    lignes = inspect.getsource(T).splitlines()
    defs = [i for i, l in enumerate(lignes) if "_canal_trace = " in l]
    uses = [i for i, l in enumerate(lignes)
            if "_canal_trace," in l or "_canal_trace)" in l]
    assert defs, "aucune définition de _canal_trace"
    for u in uses:
        avant = [d for d in defs if d < u]
        assert avant, f"ligne {u}: _canal_trace utilisé sans définition en amont"
        assert u - max(avant) < 80, f"ligne {u}: définition trop loin, portées distinctes ?"


# ─── ⑤ Les trois cadences qui tuaient l'ordonnanceur ────────────────────

def test_plus_AUCUNE_conversion_directe_dans_start_scheduler():
    """⛔ LE DÉFAUT. Une valeur illisible levait, et comme l'appel est DANS
    `start_scheduler`, aucun travail n'était déclaré après cette ligne."""
    import inspect
    import re
    from backend.services import scheduler as S
    src = inspect.getsource(S.start_scheduler)
    mines = re.findall(r'(?:int|float)\(os\.getenv\("([A-Z_0-9]+)"[^)]*\)\)', src)
    assert mines == [], f"conversions non gardées : {mines}"


def test_la_valeur_EXACTE_qui_a_casse_la_production_ne_leve_plus(monkeypatch):
    """La ligne réelle du 2026-10-11 :
    `ECHELLE_STOP_INTERVAL_SEC=1FENETRE_HEBDO_DEBUT=lun 00:00`."""
    from backend.services.scheduler import intervalle_sec
    monkeypatch.setenv("T_CAD", "1FENETRE_HEBDO_DEBUT=lun 00:00")
    assert intervalle_sec("T_CAD", 15) == 15


@pytest.mark.parametrize("brut,attendu", [
    ("", 15), ("   ", 15), ("abc", 15), ("-5", 15), ("0", 15),
    ("1", 1), ("60", 60), (" 3 ", 3),
])
def test_une_cadence_illisible_retombe_sur_son_defaut(monkeypatch, brut, attendu):
    from backend.services.scheduler import intervalle_sec
    monkeypatch.setenv("T_CAD", brut)
    assert intervalle_sec("T_CAD", 15) == attendu


def test_une_cadence_illisible_est_criee_au_niveau_ALERTE(monkeypatch, caplog):
    """⚠️ Une cadence qui n'est pas celle qu'on croit est exactement le genre
    de chose qui se lit six mois trop tard."""
    from backend.services.scheduler import intervalle_sec
    monkeypatch.setenv("T_CAD", "abc")
    with caplog.at_level("ERROR"):
        intervalle_sec("T_CAD", 15)
    assert any("illisible" in r.message for r in caplog.records)
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_une_cadence_ABSENTE_ne_crie_PAS(monkeypatch, caplog):
    """⛔ Crier sur une variable simplement non posée noierait le vrai
    avertissement : la plupart des cadences vivent sur leur défaut."""
    from backend.services.scheduler import intervalle_sec
    monkeypatch.delenv("T_CAD", raising=False)
    with caplog.at_level("ERROR"):
        assert intervalle_sec("T_CAD", 15) == 15
    assert not [r for r in caplog.records if r.levelname == "ERROR"]


# ─── ⑥ L'ÉCHEC : le trou que ma réinjection a trouvé ────────────────────

def _client_qui_echoue(monkeypatch, tmp_path, comment: str):
    """Un client dont l'envoi Telegram RATE — par réseau ou par code HTTP."""
    from fastapi.testclient import TestClient
    from backend.app import app

    db = str(tmp_path / "j.db")
    traces = []
    vrai = J.tracer

    def _espion(*a, **k):
        k.setdefault("chemin", db)
        traces.append(a[0] if a else k.get("issue"))
        return vrai(*a, **k)

    monkeypatch.setattr(J, "tracer", _espion)

    import httpx

    class _R:
        status_code = 502
        text = "bad gateway"
        def json(self): return {}

    class _FauxAsync:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, **kw):
            if comment == "reseau":
                raise httpx.ConnectError("la liaison a lache")
            return _R()

    monkeypatch.setattr(httpx, "AsyncClient", _FauxAsync)
    from config import settings as _cfg
    monkeypatch.setattr(_cfg, "SALES_TELEGRAM_BOT_TOKEN", "9:FAUX", raising=False)
    monkeypatch.setattr(_cfg, "SALES_TELEGRAM_CHAT_ID", "1", raising=False)
    return TestClient(app), traces


def test_la_route_trace_un_ECHEC_RESEAU(monkeypatch, tmp_path):
    """⛔ LE TROU TROUVÉ PAR LA RÉINJECTION. Retirer cette trace laissait mes
    31 tests verts : aucun ne faisait RATER l'envoi. Un émetteur qui échoue
    mille fois par jour se lirait alors comme un émetteur muet — exactement ce
    que le journal est censé rendre visible."""
    cli, traces = _client_qui_echoue(monkeypatch, tmp_path, "reseau")
    r = cli.post(URL, json={"title": "Nue", "body": "x", "dedup_key": "nue"})
    assert r.status_code == 502, r.text
    assert traces == ["echec"], traces


def test_la_route_trace_un_REFUS_de_telegram(monkeypatch, tmp_path):
    """L'autre branche : Telegram répond, mais pas 200."""
    cli, traces = _client_qui_echoue(monkeypatch, tmp_path, "http")
    r = cli.post(URL, json={"title": "Nue", "body": "x", "dedup_key": "nue"})
    assert r.status_code == 502, r.text
    assert traces == ["echec"], traces


def test_un_echec_ne_marque_PAS_le_cooldown(monkeypatch, tmp_path):
    """🔑 Et la propriété d'origine tient toujours : un échec ne consomme pas
    le silence. Le cooldown doit taire les DOUBLONS, jamais les ÉCHECS."""
    cli, _ = _client_qui_echoue(monkeypatch, tmp_path, "reseau")
    corps = {"title": "Nue", "body": "x", "dedup_key": "nue_echec",
             "cooldown_seconds": 600}
    assert cli.post(URL, json=corps).status_code == 502
    r2 = cli.post(URL, json=corps)
    assert r2.status_code == 502, "le 2e appel a été étouffé par le cooldown"
