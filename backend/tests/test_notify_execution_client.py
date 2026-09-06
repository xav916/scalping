"""Sonde sur l'EXECUTION client, pas sur la livraison (2026-08-21).

Cedric a paye pendant des semaines un service qui n'executait rien : 2 912
ordres en file, 0 execute, EA hors ligne depuis le 15/08. Rien ne l'a
signale, parce que le seul compteur qui existait comptait les ENVOIS.

⛔ **La lecon du 19-20/08, payee trois fois : un detecteur ne se teste pas sur
son silence.** Le detecteur de positions nues rendait « 0 position sans
stop » — reponse rassurante — alors qu'il plantait au premier vrai cas, sur
un attribut inexistant. Le chemin vide ne touchait jamais la ligne fautive.

⇒ Chaque cas ci-dessous met la sonde **face a ce qu'elle doit trouver**, et
les cas « tout va bien » ne viennent qu'apres, pour verrouiller l'absence de
faux positifs. `main()` est exerce de bout en bout sur une vraie base SQLite
reproduisant l'etat de Cedric : c'est le seul moyen de prouver que le chemin
qui alerte fonctionne vraiment.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

_SCRIPT = (pathlib.Path(__file__).resolve().parents[2]
           / "scripts" / "notify_execution_client.py")

MAINTENANT = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def script():
    spec = importlib.util.spec_from_file_location("execution_client", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _etat(**kw):
    base = {"dernier_appel": MAINTENANT - timedelta(minutes=5),
            "executes": 3, "echecs": 0, "jamais_recus": 2,
            "erreur_dominante": None}
    base.update(kw)
    return base


# --------------------------------------------------------------------------
# Ce que la sonde DOIT trouver
# --------------------------------------------------------------------------

def test_cas_cedric_ea_muet_et_zero_execution(script):
    """Le cas reel du 21/08 : EA eteint depuis 6 jours, file pleine, 0 exec."""
    soucis = script.diagnostiquer(_etat(
        dernier_appel=datetime(2026, 8, 15, 0, 28, tzinfo=timezone.utc),
        executes=0, echecs=264, jamais_recus=1715,
        erreur_dominante="OrderSend failed retcode=0"), MAINTENANT)
    assert len(soucis) == 2, soucis
    assert "muet depuis 156 h" in soucis[0]
    assert "15/08 00:28" in soucis[0]
    assert "0 exécution pour 264 échec(s)" in soucis[1]
    assert "OrderSend failed retcode=0" in soucis[1]


def test_ea_muet_juste_au_seuil(script):
    """Le seuil est inclusif : exactement 24 h de silence alerte deja."""
    soucis = script.diagnostiquer(
        _etat(dernier_appel=MAINTENANT - timedelta(hours=24)), MAINTENANT)
    assert any("muet" in s for s in soucis)


def test_ea_qui_appelle_mais_dont_rien_n_aboutit(script):
    """L'EA repond, donc « en ligne » — et pourtant le client n'a RIEN.

    C'est le cas qu'une sonde de presence rate entierement.
    """
    soucis = script.diagnostiquer(
        _etat(executes=0, echecs=0, jamais_recus=140), MAINTENANT)
    assert len(soucis) == 1
    assert "140 signaux jamais reçus, 0 exécuté" in soucis[0]


def test_echecs_sans_motif_remonte(script):
    """`mt5_error` vide ne doit pas faire disparaitre l'alerte."""
    soucis = script.diagnostiquer(
        _etat(executes=0, echecs=12, erreur_dominante=None), MAINTENANT)
    assert "sans motif remonté" in soucis[0]


def test_ea_n_a_jamais_appele(script):
    """Client installe qui n'a jamais branche son EA : `fetched_at` NULL."""
    soucis = script.diagnostiquer(
        _etat(dernier_appel=None, executes=0, echecs=0, jamais_recus=0),
        MAINTENANT)
    assert soucis == ["son EA n'a JAMAIS appelé le serveur"]


def test_les_deux_signaux_sont_independants(script):
    """Un EA en ligne peut echouer ; un EA muet peut avoir execute avant.

    Les deux diagnostics ne se masquent pas l'un l'autre.
    """
    muet_mais_productif = script.diagnostiquer(
        _etat(dernier_appel=MAINTENANT - timedelta(days=5), executes=8),
        MAINTENANT)
    assert len(muet_mais_productif) == 1 and "muet" in muet_mais_productif[0]

    present_mais_sterile = script.diagnostiquer(
        _etat(executes=0, echecs=4), MAINTENANT)
    assert len(present_mais_sterile) == 1
    assert "0 exécution" in present_mais_sterile[0]


# --------------------------------------------------------------------------
# Ce sur quoi la sonde doit se taire
# --------------------------------------------------------------------------

def test_client_qui_fonctionne_ne_declenche_rien(script):
    assert script.diagnostiquer(_etat(), MAINTENANT) == []


def test_echecs_tolerés_tant_qu_il_y_a_des_executions(script):
    """Un rejet de courtier de temps en temps n'est pas une panne.

    C'est l'ABSENCE TOTALE d'execution qui l'est.
    """
    assert script.diagnostiquer(
        _etat(executes=5, echecs=9), MAINTENANT) == []


def test_petite_file_sans_execution_reste_silencieuse(script):
    """Un client tout juste inscrit a une file vide et zero execution.

    Sans seuil, il declencherait une alerte des son premier signal.
    """
    assert script.diagnostiquer(
        _etat(executes=0, echecs=0, jamais_recus=3), MAINTENANT) == []


# --------------------------------------------------------------------------
# Le chemin complet, sur une vraie base
# --------------------------------------------------------------------------

def _base(tmp_path, lignes):
    chemin = tmp_path / "trades.db"
    with sqlite3.connect(chemin) as c:
        c.execute("""CREATE TABLE mt5_pending_orders (
            id INTEGER PRIMARY KEY, user_id INTEGER, api_key TEXT,
            payload TEXT, status TEXT, created_at TEXT, fetched_at TEXT,
            executed_at TEXT, mt5_ticket INTEGER, mt5_error TEXT,
            expires_at TEXT)""")
        c.executemany(
            "INSERT INTO mt5_pending_orders "
            "(user_id, status, created_at, fetched_at, mt5_error) "
            "VALUES (?,?,?,?,?)", lignes)
    return chemin


def _brancher(script, monkeypatch, tmp_path, clients, lignes):
    from backend.services import users_service
    monkeypatch.setattr(users_service, "list_premium_auto_exec_users",
                        lambda: clients)
    monkeypatch.setattr(users_service, "_DB_PATH", _base(tmp_path, lignes))
    envois = []
    monkeypatch.setattr(script, "_notifier",
                        lambda t, c, dedup: envois.append((t, c, dedup)) or True)
    return envois


def test_main_alerte_sur_l_etat_reel_de_cedric(script, monkeypatch, tmp_path):
    """Bout en bout : la sonde branchee sur des donnees vraies DOIT parler."""
    recent = datetime.now(timezone.utc) - timedelta(days=1)
    envois = _brancher(
        script, monkeypatch, tmp_path,
        [{"id": 2, "email": "cedric@example.com"}],
        [(2, "PENDING", recent.isoformat(), "2026-08-15T00:28:04", None)] * 40
        + [(2, "FAILED", recent.isoformat(), "2026-08-15T00:28:04",
            "OrderSend failed retcode=0")] * 12)

    assert script.main() == 0
    assert len(envois) == 1, "la sonde est restée muette sur le cas qu'elle vise"
    titre, corps, dedup = envois[0]
    assert "user:2" in titre and dedup == "exec-client:2"
    assert "cedric@example.com" in corps
    assert "muet depuis" in corps
    assert "0 exécution pour 12 échec(s)" in corps


def test_la_purge_horaire_n_aveugle_pas_la_sonde(script, monkeypatch, tmp_path):
    """⚠️ Deux garde-fous qui se neutralisent l'un l'autre.

    `purge-file-ea.sh` fait passer tout ordre non servi de `PENDING` a
    `EXPIRED` en moins d'une heure. Une sonde qui ne compterait que `PENDING`
    verrait donc un compteur eternellement a zero et **se tairait sur le cas
    meme qu'elle surveille**.

    Ici : que des `EXPIRED`, plus une seule ligne `PENDING`. La sonde doit
    parler quand meme.
    """
    recent = datetime.now(timezone.utc) - timedelta(days=1)
    envois = _brancher(
        script, monkeypatch, tmp_path,
        [{"id": 2, "email": "cedric@example.com"}],
        [(2, "EXPIRED", recent.isoformat(), "2026-08-15T00:28:04", None)] * 60)

    assert script.main() == 0
    assert len(envois) == 1, "la purge a rendu la sonde aveugle"
    assert "60 signaux jamais reçus" in envois[0][1]


def test_main_se_tait_sur_un_client_sain(script, monkeypatch, tmp_path):
    maintenant = datetime.now(timezone.utc)
    envois = _brancher(
        script, monkeypatch, tmp_path, [{"id": 7, "email": "ok@example.com"}],
        [(7, "EXECUTED", maintenant.isoformat(), maintenant.isoformat(), None)])
    assert script.main() == 0
    assert envois == []


def test_main_ignore_les_ordres_hors_fenetre(script, monkeypatch, tmp_path):
    """Un client actif AUJOURD'HUI ne doit pas etre juge sur un vieux passe.

    Ses 30 echecs du mois dernier sont hors fenetre ; seule sa semaine compte.
    """
    maintenant = datetime.now(timezone.utc)
    vieux = (maintenant - timedelta(days=40)).isoformat()
    envois = _brancher(
        script, monkeypatch, tmp_path, [{"id": 7, "email": "ok@example.com"}],
        [(7, "FAILED", vieux, maintenant.isoformat(), "vieux rejet")] * 30
        + [(7, "EXECUTED", maintenant.isoformat(),
            maintenant.isoformat(), None)])
    assert script.main() == 0
    assert envois == []


def test_main_ne_melange_pas_les_clients(script, monkeypatch, tmp_path):
    """Les ordres d'un client en panne ne doivent pas incriminer son voisin."""
    maintenant = datetime.now(timezone.utc)
    envois = _brancher(
        script, monkeypatch, tmp_path,
        [{"id": 7, "email": "ok@example.com"},
         {"id": 2, "email": "cedric@example.com"}],
        [(7, "EXECUTED", maintenant.isoformat(), maintenant.isoformat(), None),
         (2, "FAILED", maintenant.isoformat(), "2026-08-15T00:28:04", "boum")])
    assert script.main() == 0
    assert len(envois) == 1
    assert "user:2" in envois[0][0]


def test_main_alerte_quand_la_liste_des_clients_est_ILLISIBLE(
        script, monkeypatch, tmp_path):
    """⚠️ Muet n'est pas vide.

    Une lecture ratee rendrait « aucun client », donc « aucun probleme » —
    exactement le piege du moniteur muet pendant trois mois. L'echec doit
    faire du BRUIT, pas du silence.
    """
    from backend.services import users_service

    def _explose():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(users_service, "list_premium_auto_exec_users", _explose)
    envois = []
    monkeypatch.setattr(script, "_notifier",
                        lambda t, c, dedup: envois.append((t, c, dedup)) or True)

    assert script.main() == 1
    assert len(envois) == 1
    assert "lecture impossible" in envois[0][0]
    assert "PAS « aucun client en difficulté »" in envois[0][1]


def test_main_ne_harcele_pas_un_client_en_veille(script, monkeypatch, tmp_path):
    """Une veille est une DECISION, pas une panne.

    Cedric est en veille depuis le 21/08 : `list_premium_auto_exec_users()`
    rend `[]` et la sonde reste silencieuse. Elle se rearme d'elle-meme a la
    reprise — c'est precisement la qu'elle sert de filet.
    """
    from backend.services import users_service
    monkeypatch.setattr(users_service, "list_premium_auto_exec_users",
                        lambda: [])
    envois = []
    monkeypatch.setattr(script, "_notifier",
                        lambda t, c, dedup: envois.append((t, c, dedup)) or True)
    assert script.main() == 0
    assert envois == []


def test_le_canal_ne_vise_AUCUN_de_nos_comptes(script):
    """⚠️ Le seul message qui n'a plus de maison (2026-09-06).

    Un client sans service est un evenement COMMERCIAL. Le fil `sales` le
    portait pour cette raison — mais depuis le decoupage PAR COMPTE, le bot
    derriere `sales` s'appelle « IC MARKETS trades » : une alerte client s'y
    afficherait comme un evenement de notre compte reel.

    ⛔ On le range donc sur `infra`, faute de fil commercial. Le risque
    reconnu par l'ancien test tient toujours : noye parmi les redemarrages de
    bridges, il peut se perdre — c'est exactement ce qui est arrive a l'alerte
    de sauvegarde S3, qui criait depuis cinq nuits. A rejuger si un 5e fil
    est ouvert.
    """
    assert "channel=infra" in script.NOTIFY_URL
    assert "channel=sales" not in script.NOTIFY_URL


def test_realerte_une_fois_par_jour(script, monkeypatch):
    """Un client sans service est un probleme PERSISTANT.

    Une dedup sans expiration le ferait disparaitre apres la premiere alerte,
    et il redeviendrait invisible — le defaut qu'on repare ici.
    """
    import json as _json
    monkeypatch.delenv("DRY_RUN", raising=False)
    charges = []
    original = script.urllib.request.urlopen

    class _Rep:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _faux(rq, timeout=None):
        charges.append(_json.loads(rq.data))
        return _Rep()

    script.urllib.request.urlopen = _faux
    try:
        script._notifier("t", "c", "exec-client:2")
    finally:
        script.urllib.request.urlopen = original

    assert charges[0]["cooldown_seconds"] == 86400
    assert charges[0]["dedup_key"] == "exec-client:2"
