"""Chemin d'ordre Kraken : aucun fill ne doit rester sans trace (2026-08-04).

L'incident : ``kraken_bridge_client`` appelait ``record_push``, une fonction
inexistante, **dans la branche succès, après le fill**. L'``AttributeError``
était avalée par le ``except Exception`` du client et ressortait en
``kraken_bridge_exception``. Sur un compte réel :

- l'ordre partait chez Kraken,
- aucune ligne ``mt5_pushes`` n'était écrite,
- donc ni notification, ni suivi SL/TP, ni trace,
- et sans réservation, le setup se rejouait au cycle suivant.

Ces tests appellent la vraie fonction de push avec un transport HTTP simulé
et vérifient l'état réel de la base. Ils échouent si l'on revient à un
enregistrement postérieur à l'envoi.
"""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace as NS

import httpx
import pytest

from backend.services import kraken_bridge_client as kbc
from backend.services import mt5_pushes_service
from backend.services.bridge_push_ledger import PushLedger


# --- socle ----------------------------------------------------------------

@pytest.fixture
def base(tmp_path, monkeypatch):
    """Base isolée : chaque test lit l'état réel de ``mt5_pushes``."""
    db = tmp_path / "trades.db"
    monkeypatch.setattr(mt5_pushes_service, "_db_path", lambda: str(db))
    monkeypatch.setattr(
        "backend.services.rejection_service.record_rejection",
        lambda **kw: rejets.append(kw),
    )
    rejets: list[dict] = []
    mt5_pushes_service._ensure_schema()
    return NS(path=str(db), rejets=rejets)


def _setup(pair="BTC/USD", entry=60000.0):
    return NS(pair=pair, direction=NS(value="buy"), entry_price=entry,
              stop_loss=entry * 0.997, take_profit_1=entry * 1.005,
              confidence_score=72.0, verdict_action="TAKE")


def _dest():
    return NS(destination_id="admin_kraken", user_id=None,
              bridge_url="http://bridge.test", bridge_api_key="k",
              bridge_type="kraken")


def _sz(risk=1.03):
    return {"risk_money": risk}


def _lignes(base) -> list[sqlite3.Row]:
    with sqlite3.connect(base.path) as c:
        c.row_factory = sqlite3.Row
        return c.execute("SELECT * FROM mt5_pushes").fetchall()


def _transport(monkeypatch, reponse):
    """Remplace l'aller-retour HTTP. ``reponse`` peut être une exception."""
    envois: list[dict] = []

    async def _post(self, url, json=None, headers=None):
        envois.append({"url": url, "json": json})
        if isinstance(reponse, Exception):
            raise reponse
        code, body = reponse
        return httpx.Response(code, json=body,
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", _post)
    return envois


# --- LE test : un fill non confirmé laisse quand même une trace -----------

@pytest.mark.asyncio
async def test_une_exception_apres_envoi_laisse_la_ligne(base, monkeypatch):
    """C'est exactement le bug du 2026-08-04.

    L'exception survient après que la requête est partie : l'ordre a pu être
    rempli. Une ligne doit exister, sinon la position est invisible.
    """
    _transport(monkeypatch, RuntimeError("boom apres le fill"))
    await kbc.push_to_kraken(_setup(), _sz(), _dest())

    lignes = _lignes(base)
    assert len(lignes) == 1, "un fill possible sans aucune trace en base"
    assert lignes[0]["destination_id"] == "admin_kraken"
    assert lignes[0]["ok"] == 0
    assert "boom" in (lignes[0]["bridge_response"] or "")


@pytest.mark.asyncio
async def test_un_timeout_laisse_la_ligne(base, monkeypatch):
    """Timeout ⇒ issue inconnue : l'ordre a pu passer côté Kraken."""
    _transport(monkeypatch, httpx.TimeoutException("lent"))
    await kbc.push_to_kraken(_setup(), _sz(), _dest())

    lignes = _lignes(base)
    assert len(lignes) == 1
    assert lignes[0]["ok"] == 0


@pytest.mark.asyncio
async def test_apres_une_issue_inconnue_le_setup_ne_repart_pas(base, monkeypatch):
    """Sans réservation, le même setup se rejouait tous les cycles.

    Sur un compte réel, un doublon coûte plus cher qu'un trade manqué.
    """
    _transport(monkeypatch, RuntimeError("boom"))
    await kbc.push_to_kraken(_setup(), _sz(), _dest())

    envois = _transport(monkeypatch, (200, {"ok": True, "market_order_id": "x"}))
    await kbc.push_to_kraken(_setup(), _sz(), _dest())

    assert envois == [], "second envoi pour un setup deja tente"
    assert len(_lignes(base)) == 1


# --- le cas nominal --------------------------------------------------------

@pytest.mark.asyncio
async def test_un_ordre_accepte_est_enregistre(base, monkeypatch):
    _transport(monkeypatch, (200, {"ok": True, "market_order_id": "abc",
                                   "avg_price": 60010.0}))
    await kbc.push_to_kraken(_setup(), _sz(), _dest())

    lignes = _lignes(base)
    assert len(lignes) == 1
    assert lignes[0]["ok"] == 1
    assert "abc" in lignes[0]["bridge_response"]


@pytest.mark.asyncio
async def test_la_reservation_precede_l_envoi(base, monkeypatch):
    """La ligne doit exister au moment où le bridge répond, pas après.

    On inspecte la base depuis le transport lui-même : c'est la seule façon
    de distinguer « réservé avant » de « écrit après ».
    """
    vu: list[int] = []

    async def _post(self, url, json=None, headers=None):
        vu.append(len(_lignes(base)))
        return httpx.Response(200, json={"ok": True},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", _post)
    await kbc.push_to_kraken(_setup(), _sz(), _dest())

    assert vu == [1], "la cle n'etait pas reservee au moment de l'envoi"


# --- ce qui doit au contraire pouvoir retenter -----------------------------

@pytest.mark.asyncio
async def test_bridge_injoignable_autorise_un_retry(base, monkeypatch):
    """Connexion refusée : rien n'a atteint Kraken, le retry est légitime."""
    _transport(monkeypatch, httpx.ConnectError("refused"))
    await kbc.push_to_kraken(_setup(), _sz(), _dest())
    assert _lignes(base) == [], "reservation conservee alors que rien n'est parti"

    envois = _transport(monkeypatch, (200, {"ok": True}))
    await kbc.push_to_kraken(_setup(), _sz(), _dest())
    assert len(envois) == 1
    assert _lignes(base)[0]["ok"] == 1


@pytest.mark.asyncio
async def test_kill_switch_du_bridge_autorise_un_retry(base, monkeypatch):
    """429 blocked : contrainte temporaire (max positions, drawdown)."""
    _transport(monkeypatch, (429, {"ok": False, "blocked": True,
                                   "reason": "max positions"}))
    await kbc.push_to_kraken(_setup(), _sz(), _dest())
    assert _lignes(base) == []
    assert base.rejets[-1]["reason_code"] == "kraken_bridge_blocked"


@pytest.mark.asyncio
async def test_un_rejet_de_l_exchange_ne_martele_pas(base, monkeypatch):
    """`invalidSize` se reproduirait à l'identique tous les cycles.

    Le 2026-08-04, cinq ordres identiques sont partis en douze minutes.
    """
    _transport(monkeypatch, (500, {"ok": False, "error": "invalidSize"}))
    await kbc.push_to_kraken(_setup(), _sz(), _dest())

    envois = _transport(monkeypatch, (500, {"ok": False, "error": "invalidSize"}))
    await kbc.push_to_kraken(_setup(), _sz(), _dest())
    assert envois == [], "l'ordre rejete est reparti au cycle suivant"


# --- distinction des clés --------------------------------------------------

@pytest.mark.asyncio
async def test_deux_paires_ne_se_bloquent_pas(base, monkeypatch):
    envois = _transport(monkeypatch, (200, {"ok": True}))
    await kbc.push_to_kraken(_setup("BTC/USD", 60000.0), _sz(), _dest())
    await kbc.push_to_kraken(_setup("ETH/USD", 1868.0), _sz(), _dest())
    assert len(envois) == 2
    assert len(_lignes(base)) == 2


@pytest.mark.asyncio
async def test_un_prix_d_entree_different_est_un_autre_setup(base, monkeypatch):
    envois = _transport(monkeypatch, (200, {"ok": True}))
    await kbc.push_to_kraken(_setup("BTC/USD", 60000.0), _sz(), _dest())
    await kbc.push_to_kraken(_setup("BTC/USD", 60150.0), _sz(), _dest())
    assert len(envois) == 2


# --- l'API du registre elle-même ------------------------------------------

def _appels_sur(source: str, module: str) -> set[str]:
    """Attributs de ``module`` réellement appelés, d'après l'AST.

    Un scan textuel se ferait piéger par les docstrings — celles de ce dépôt
    citent justement le nom fautif pour expliquer l'incident.
    """
    import ast
    trouves: set[str] = set()
    for n in ast.walk(ast.parse(source)):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id == module):
            trouves.add(n.func.attr)
    return trouves


def test_le_registre_n_appelle_que_des_fonctions_existantes():
    """`record_push` n'existait pas : le bug tenait à cela seul.

    Une faute de nom sur un module ne lève qu'à l'exécution — ici, après le
    fill. Ce test la fait lever avant le déploiement.
    """
    import inspect
    from backend.services import bridge_push_ledger as bpl

    appels = _appels_sur(inspect.getsource(bpl), "mt5_pushes_service")
    assert appels, "aucun appel detecte : le test ne teste rien"
    inexistantes = sorted(a for a in appels if not hasattr(mt5_pushes_service, a))
    assert inexistantes == [], f"fonctions inexistantes appelees : {inexistantes}"


def test_aucun_service_n_appelle_une_fonction_de_push_inexistante():
    """Garde-fou étendu à tous les services, pour les futures plateformes."""
    import pathlib
    racine = pathlib.Path(__file__).resolve().parents[1] / "services"
    fautifs: dict[str, list[str]] = {}
    for p in racine.glob("*.py"):
        appels = _appels_sur(p.read_text(encoding="utf-8"), "mt5_pushes_service")
        manquantes = sorted(a for a in appels
                            if not hasattr(mt5_pushes_service, a))
        if manquantes:
            fautifs[p.name] = manquantes
    assert fautifs == {}, f"appels vers des fonctions inexistantes : {fautifs}"


def test_la_cle_est_celle_de_la_contrainte_unique(base):
    """Si les deux divergent, la déduplication ne dédoublonne rien."""
    l = PushLedger.for_setup(_dest(), _setup(), "buy")
    assert l.reserve() is True
    assert l.reserve() is False, "la meme cle a ete reservee deux fois"
