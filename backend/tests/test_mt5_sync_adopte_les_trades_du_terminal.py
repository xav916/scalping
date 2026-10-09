"""Une position ouverte DANS LE TERMINAL MT5 doit entrer dans les comptes.

## ⛔ LE TROU, mesuré sur de l'argent réel le 2026-10-09

Six fermetures d'or entre 05h36 et 05h55 UTC, toutes faites à la main dans le
terminal MT5 : **−157,35 €**. Aucun garde-fou ne les a vues, et
`personal_trades` en comptait **zéro ligne**.

```
plafond journalier du courtier  ⛔ non   (il a mordu APRÈS, sur l'équité)
plafond de positions            ⛔ non
fenêtre horaire du spread       ⛔ non
règle d'arrêt de l'or           ⛔ non
interrupteur REM-002            ⛔ non
personal_trades                 ⛔ 0 ligne
```

🔑 **LA CAUSE, lue dans le code et non supposée.** Deux chemins alimentent
`personal_trades`, et aucun ne part du courtier :

- `_sync_one` lit `/audit` — le journal de ce que **le pont** a fait. Un ordre
  passé dans le terminal ne traverse pas le pont, donc n'y figure jamais ;
- `_reconcile_open_trades` compare `/positions` aux tickets **déjà en base**
  (`_select_open_auto_tickets`, `is_auto=1`). Un ticket absent de la base est
  hors de la comparaison : il ne peut pas être « réconcilié », il est
  **ignoré**.

⇒ Tout ce qui a été construit protège le chemin AUTOMATIQUE, pas la main.

🔑 **CE QUI REND LE CORRECTIF PETIT** : `_reconcile_open_trades` tient déjà la
charge utile complète de `/positions`, pour tous les ponts. Le courtier y
déclare **toutes** ses positions, les manuelles comprises. Il manquait de les
ADOPTER au lieu de ne regarder que l'intersection avec la base.

## Ce que ces tests épinglent, et pourquoi chacun

1. une position inconnue du courtier crée une ligne — le trou lui-même ;
2. elle n'est pas dupliquée au cycle suivant (sondage toutes les **10 s** en
   production : sans dédup, 6 lignes par minute) ;
3. sa fermeture est réconciliée — sinon la ligne reste `OPEN` pour toujours et
   le P&L n'entre jamais dans le plafond ;
4. ⛔ le lanceur de l'expérience TP 2 € n'est **PAS** déclenché par une
   fermeture à la main. `_relancer_apres_fermeture` n'a aucun garde sur
   `is_auto` : brancher les lignes adoptées sur le chemin de clôture ordinaire
   aurait fait relancer l'expérience sur un geste de Xavier, et déplacé en
   silence le comportement d'une mesure en cours sur de l'argent réel ;
5. un pont muet n'adopte RIEN — `[]` et « je ne sais pas » ne sont pas la même
   chose ([[feedback_detection_par_absence]]) ;
6. un symbole non cartographié garde son symbole BRUT et le DIT, au lieu
   d'inventer une paire.

⚠️ **Limite assumée** : une position ouverte ET fermée entre deux sondages
(< 10 s) reste invisible. Fermer ce reste demanderait une route
`/deals` par FENÊTRE côté pont, donc un déploiement VPS. Les six fermetures du
09/10 étaient espacées de 2 à 10 minutes.
"""
from __future__ import annotations

import sqlite3
from unittest.mock import patch

import httpx
import pytest

from backend.services import mt5_sync


# ⛔ LE SCHEMA DE LA PRODUCTION, COPIE VERBATIM — et c'est une correction.
#
# Ma premiere version de ce fichier declarait un schema PERMISSIF
# (`stop_loss REAL, take_profit REAL`, tous deux nullables). La production, elle,
# les porte en **NOT NULL**. Les 19 tests passaient, et le correctif deploye
# n'a adopte QU'UNE position sur deux : les deux autres n'avaient pas
# d'objectif (`tp: 0.0` chez MT5), mon code ecrivait `None`, et SQLite levait
# `IntegrityError`.
#
# 🔑 Un harnais plus permissif que la production ne teste pas la production.
# C'est la meme maladie que le harnais qui FOURNIT un nom absent du source
# (cf. `test_bridge_rates_tranches.py`, `timedelta` injecte le 2026-10-08) :
# dans les deux cas les tests affirment sur un objet qui n'existe pas.
#
# Les colonnes NOT NULL sont donc reproduites a l'identique. Ne pas les
# assouplir « pour simplifier le test » : c'est exactement ce qui a coute ce
# defaut.
_SCHEMA_PRODUCTION = """
    CREATE TABLE personal_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user TEXT NOT NULL DEFAULT 'anonymous',
        pair TEXT NOT NULL,
        direction TEXT NOT NULL,
        entry_price REAL NOT NULL,
        stop_loss REAL NOT NULL,
        take_profit REAL NOT NULL,
        size_lot REAL NOT NULL,
        signal_pattern TEXT,
        signal_confidence REAL,
        checklist_passed INTEGER DEFAULT 0,
        notes TEXT,
        status TEXT DEFAULT 'OPEN',
        exit_price REAL,
        pnl REAL DEFAULT 0,
        created_at TEXT NOT NULL,
        closed_at TEXT,
        post_entry_sl INTEGER DEFAULT 0,
        post_entry_tp INTEGER DEFAULT 0,
        post_entry_size INTEGER DEFAULT 0,
        post_entry_alarm INTEGER DEFAULT 0,
        mt5_ticket INTEGER,
        is_auto INTEGER DEFAULT 0,
        context_macro TEXT,
        signal_id INTEGER,
        fill_price REAL,
        slippage_pips REAL,
        close_reason TEXT,
        user_id INTEGER,
        destination_id TEXT,
        sl_at_close REAL,
        tp_at_close REAL,
        niveaux_source TEXT,
        horizon TEXT,
        source TEXT,
        motif_interne TEXT,
        motif_interne_detail TEXT
    )
"""

# ⚠️ Et l'index UNIQUE de la production, qui porte sur (ticket, sens).
_INDEX_PRODUCTION = (
    "CREATE UNIQUE INDEX idx_pt_ticket_dir "
    "ON personal_trades(mt5_ticket, direction)"
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """DB SQLite temporaire au schéma EXACT de la production."""
    db_file = tmp_path / "trades.db"
    conn = sqlite3.connect(db_file)
    conn.execute(_SCHEMA_PRODUCTION)
    conn.execute(_INDEX_PRODUCTION)
    conn.commit()
    conn.close()
    monkeypatch.setattr(mt5_sync, "_db_path", lambda: str(db_file))
    return str(db_file)


# La charge utile EXACTE d'un `/positions` du pont, telle que la route la
# produit (`mt5-bridge/bridge.py`, route `/positions`).
POSITION_OR = {
    "ticket": 1360999001,
    "symbol": "XAUUSD",
    "type": "sell",
    "volume": 0.01,
    "price_open": 4203.70,
    "price_current": 4200.10,
    "sl": 4223.70,
    "tp": 4201.46,
    "profit": 3.60,
    "time": "2026-10-09T05:30:00+00:00",
    "comment": "",
}


def _lignes(db_path: str) -> list[sqlite3.Row]:
    with sqlite3.connect(db_path) as c:
        c.row_factory = sqlite3.Row
        return c.execute(
            "SELECT * FROM personal_trades ORDER BY id"
        ).fetchall()


def test_une_position_INCONNUE_du_courtier_est_adoptee(temp_db):
    """Le trou du 09/10 : six positions du terminal, zéro ligne en base."""
    n = mt5_sync._adopter_positions_du_courtier(
        [POSITION_OR], destination_id="admin_live",
    )

    assert n == 1
    lignes = _lignes(temp_db)
    assert len(lignes) == 1
    ligne = lignes[0]
    assert ligne["mt5_ticket"] == 1360999001
    assert ligne["pair"] == "XAU/USD"
    assert ligne["direction"] == "sell"
    assert ligne["entry_price"] == pytest.approx(4203.70)
    assert ligne["size_lot"] == pytest.approx(0.01)
    assert ligne["status"] == "OPEN"
    assert ligne["destination_id"] == "admin_live"
    # 🔑 `is_auto=0` : ce trade n'a passé AUCUNE des portes du radar. Le
    # compter comme automatique fausserait toute la mesure.
    assert ligne["is_auto"] == 0


# ─────────────────────────────────────────────────────────────────────────
# Dédup et repli du symbole
# ─────────────────────────────────────────────────────────────────────────

def test_une_position_DEJA_connue_n_est_pas_dupliquee(temp_db):
    """⚠️ Le sondage tourne toutes les **10 s** en production. Sans dédup, une
    position tenue une minute produirait six lignes — et le plafond journalier
    somme les lignes."""
    mt5_sync._adopter_positions_du_courtier([POSITION_OR], "admin_live")
    n = mt5_sync._adopter_positions_du_courtier([POSITION_OR], "admin_live")

    assert n == 0
    assert len(_lignes(temp_db)) == 1


def test_une_position_DEJA_FERMEE_n_est_pas_readoptee(temp_db):
    """🔑 La dédup ne regarde NI le statut NI `is_auto` : une position fermée
    reste connue. Filtrer sur `status='OPEN'` l'aurait fait ré-adopter à
    chaque cycle, donc compter sa perte en boucle dans le plafond."""
    mt5_sync._adopter_positions_du_courtier([POSITION_OR], "admin_live")
    with sqlite3.connect(temp_db) as c:
        c.execute("UPDATE personal_trades SET status='CLOSED', pnl=-26.2")

    n = mt5_sync._adopter_positions_du_courtier([POSITION_OR], "admin_live")

    assert n == 0
    assert len(_lignes(temp_db)) == 1


def test_un_symbole_INCONNU_garde_le_symbole_brut(temp_db, caplog):
    """⛔ On n'invente pas une paire. Un faux rattachement ferait porter la
    perte à une paire qui n'a rien fait — et déclencherait SON régulateur."""
    position = {**POSITION_OR, "ticket": 777, "symbol": "TRUCMUCHE7"}

    with caplog.at_level("WARNING"):
        mt5_sync._adopter_positions_du_courtier([position], "admin_live")

    assert _lignes(temp_db)[0]["pair"] == "TRUCMUCHE7"
    assert "non cartographie" in caplog.text


def test_un_sens_illisible_n_est_PAS_adopte(temp_db, caplog):
    """Même règle que `_upsert_open_trade` : sans le SENS, ce n'est pas un
    ordre. Et l'écarter se DIT — sinon on saurait que les comptes sont faux
    sans jamais savoir pourquoi."""
    position = {**POSITION_OR, "ticket": 888, "type": ""}

    with caplog.at_level("WARNING"):
        n = mt5_sync._adopter_positions_du_courtier([position], "admin_live")

    assert n == 0
    assert _lignes(temp_db) == []
    assert "sens illisible" in caplog.text


@pytest.mark.parametrize("symbole,attendu", [
    ("XAUUSD", "XAU/USD"),
    ("GOLD", "XAU/USD"),
    ("EURUSD", "EUR/USD"),
    ("USDCHF", "USD/CHF"),
    ("XTIUSD", "WTI/USD"),
])
def test_les_symboles_du_courtier_se_traduisent(symbole, attendu):
    paire, cartographiee = mt5_sync._paire_depuis_symbole(symbole)
    assert (paire, cartographiee) == (attendu, True)


# ─────────────────────────────────────────────────────────────────────────
# Le cycle complet : adopter, puis réconcilier la fermeture
# ─────────────────────────────────────────────────────────────────────────

class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Mock d'`httpx.AsyncClient` : réponses prédéfinies par URL."""

    def __init__(self, responses):
        self._responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None, params=None):
        key = url
        if params and "ticket" in params:
            key = f"{url}?ticket={params['ticket']}"
        if key not in self._responses:
            raise httpx.ConnectError(f"aucun mock pour {key}")
        resp = self._responses[key]
        if isinstance(resp, Exception):
            raise resp
        return resp


@pytest.fixture
def pont_configure(monkeypatch):
    monkeypatch.setattr(mt5_sync, "MT5_SYNC_ENABLED", True)
    monkeypatch.setattr(mt5_sync, "MT5_BRIDGE_URL", "http://bridge.test")
    monkeypatch.setattr(mt5_sync, "MT5_BRIDGE_API_KEY", "key")
    # Le pont réel est lu dans l'environnement : le neutraliser, sinon un
    # `.env` present sur le poste ferait interroger une URL non simulée.
    monkeypatch.delenv("MT5_BRIDGE_LIVE_URL", raising=False)
    monkeypatch.delenv("MT5_BRIDGE_LIVE_API_KEY", raising=False)


@pytest.mark.asyncio
async def test_le_cycle_ADOPTE_une_position_inconnue(temp_db, pont_configure):
    """Le trou, bout en bout : le courtier porte une position que la base
    ignore, et un cycle de réconciliation la fait entrer dans les comptes."""
    responses = {
        "http://bridge.test/positions": _FakeResponse(
            200, {"positions": [POSITION_OR]}),
    }
    with patch("backend.services.mt5_sync.httpx.AsyncClient",
               lambda *a, **kw: _FakeAsyncClient(responses)):
        await mt5_sync._reconcile_open_trades()

    lignes = _lignes(temp_db)
    assert len(lignes) == 1
    assert lignes[0]["mt5_ticket"] == 1360999001
    assert lignes[0]["pair"] == "XAU/USD"
    assert lignes[0]["status"] == "OPEN"


@pytest.mark.asyncio
async def test_la_fermeture_d_une_position_ADOPTEE_est_reconciliee(
    temp_db, pont_configure
):
    """🔑 Sans ceci, la ligne adoptée resterait `OPEN` pour toujours : son P&L
    n'entrerait JAMAIS dans le plafond journalier, qui ne somme que les
    `status='CLOSED'`. Adopter sans réconcilier ne boucherait rien."""
    mt5_sync._adopter_positions_du_courtier([POSITION_OR], "admin_live")

    responses = {
        "http://bridge.test/positions": _FakeResponse(200, {"positions": []}),
        "http://bridge.test/deals?ticket=1360999001": _FakeResponse(200, {
            "ticket": 1360999001, "closed": True,
            "exit_price": 4193.13, "pnl": -26.20,
            "reason": "MANUAL", "reason_code": 0,
            "closed_at": "2026-10-09T08:55:38+00:00",
        }),
    }
    with patch("backend.services.mt5_sync.httpx.AsyncClient",
               lambda *a, **kw: _FakeAsyncClient(responses)):
        await mt5_sync._reconcile_open_trades()

    ligne = _lignes(temp_db)[0]
    assert ligne["status"] == "CLOSED"
    assert ligne["pnl"] == pytest.approx(-26.20)
    assert ligne["exit_price"] == pytest.approx(4193.13)
    assert ligne["close_reason"] == "MANUAL"


@pytest.mark.asyncio
async def test_le_LANCEUR_de_l_experience_n_est_pas_declenche(
    temp_db, pont_configure
):
    """⛔ LE DÉGÂT COLLATÉRAL À ÉVITER. `_relancer_apres_fermeture` n'a aucun
    garde sur `is_auto` : brancher les lignes adoptées sur le chemin de
    clôture ordinaire aurait fait relancer l'expérience TP 2 € sur un geste de
    Xavier. Déplacer en silence le comportement d'une mesure en cours sur de
    l'argent réel est exactement ce que ce dépôt a déjà payé plusieurs fois.
    """
    mt5_sync._adopter_positions_du_courtier([POSITION_OR], "admin_live")

    appels: list[int] = []

    async def _espion(ticket):
        appels.append(ticket)

    responses = {
        "http://bridge.test/positions": _FakeResponse(200, {"positions": []}),
        "http://bridge.test/deals?ticket=1360999001": _FakeResponse(200, {
            "ticket": 1360999001, "closed": True,
            "exit_price": 4193.13, "pnl": -26.20, "reason": "MANUAL",
            "closed_at": "2026-10-09T08:55:38+00:00",
        }),
    }
    with patch("backend.services.mt5_sync.httpx.AsyncClient",
               lambda *a, **kw: _FakeAsyncClient(responses)), \
         patch.object(mt5_sync, "_relancer_apres_fermeture", _espion), \
         patch.object(mt5_sync, "_notify_close_telegram", _espion):
        await mt5_sync._reconcile_open_trades()

    # La clôture est bien enregistrée…
    assert _lignes(temp_db)[0]["status"] == "CLOSED"
    # …et aucun effet de bord n'est parti.
    assert appels == []


@pytest.mark.asyncio
async def test_un_pont_MUET_n_adopte_RIEN(temp_db, pont_configure):
    """⛔ `[]` et « je ne sais pas » ne sont pas la même chose. Un pont
    injoignable qui ferait adopter zéro position serait inoffensif ici, mais
    c'est le même silence qui, dans l'autre sens, a déjà déclaré fermées des
    positions vivantes."""
    responses = {
        "http://bridge.test/positions": httpx.ConnectError("pont eteint"),
    }
    with patch("backend.services.mt5_sync.httpx.AsyncClient",
               lambda *a, **kw: _FakeAsyncClient(responses)):
        await mt5_sync._reconcile_open_trades()

    assert _lignes(temp_db) == []


@pytest.mark.asyncio
async def test_une_position_AUTO_n_est_pas_adoptee_en_double(
    temp_db, pont_configure
):
    """⚠️ La régression la plus coûteuse possible : adopter un ticket que le
    radar a lui-même ouvert créerait une ligne `is_auto=0` À CÔTÉ de la ligne
    auto. Le plafond journalier compterait son P&L DEUX FOIS."""
    with sqlite3.connect(temp_db) as c:
        c.execute(
            "INSERT INTO personal_trades (user, pair, direction, entry_price,"
            " stop_loss, take_profit, size_lot, status, created_at,"
            " mt5_ticket, is_auto) "
            "VALUES ('u','XAU/USD','sell',4203.7,4223.7,4201.46,0.01,'OPEN',"
            "'2026-10-09T05:30:00+00:00',1360999001,1)"
        )

    responses = {
        "http://bridge.test/positions": _FakeResponse(
            200, {"positions": [POSITION_OR]}),
    }
    with patch("backend.services.mt5_sync.httpx.AsyncClient",
               lambda *a, **kw: _FakeAsyncClient(responses)):
        await mt5_sync._reconcile_open_trades()

    lignes = _lignes(temp_db)
    assert len(lignes) == 1
    assert lignes[0]["is_auto"] == 1


# ─────────────────────────────────────────────────────────────────────────
# ⛔ UN PONT MUET NE DOIT PAS AVEUGLER LES AUTRES (mesuré en production)
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture
def deux_ponts(monkeypatch):
    """Le démo ET le réel configurés, comme en production."""
    monkeypatch.setattr(mt5_sync, "MT5_SYNC_ENABLED", True)
    monkeypatch.setattr(mt5_sync, "MT5_BRIDGE_URL", "http://demo.test")
    monkeypatch.setattr(mt5_sync, "MT5_BRIDGE_API_KEY", "key")
    monkeypatch.setenv("MT5_BRIDGE_LIVE_URL", "http://live.test")
    monkeypatch.setenv("MT5_BRIDGE_LIVE_API_KEY", "livekey")


@pytest.mark.asyncio
async def test_le_pont_DEMO_muet_n_empeche_pas_d_adopter_sur_le_REEL(
    temp_db, deux_ponts
):
    """⛔ LE DÉFAUT MESURÉ EN PRODUCTION LE 2026-10-09, après déploiement.

    Le pont démo répond **503 « MT5 not connected »** — son terminal est gelé
    depuis le 07/10. La boucle faisait `return` sur le premier pont muet, donc
    le pont RÉEL n'était **jamais interrogé** :

    ```
    legacy -> 503 {"error":"MT5 not connected"}
    live   -> 200 {"count":3, ...}      <- jamais lu
    ```

    ⇒ `_reconcile_open_trades` était **entièrement aveugle au compte réel**
    depuis que le démo est gelé, et mon adoption en héritait : déployée,
    vérifiée, et **inerte**. Zéro ligne adoptée sur trois positions vivantes.

    🔑 LA DISTINCTION QUI MANQUAIT, et c'est elle qui tranche :

    | | a besoin de | un pont muet |
    |---|---|---|
    | **adopter** | la PRÉSENCE d'une position | ne prouve rien contre |
    | **déclarer fermé** | l'ABSENCE d'un ticket | interdit de conclure |

    Adopter est **additif** : on enregistre ce qu'un courtier DÉCLARE porter.
    Aucune inférence par absence, donc aucune raison de se taire parce qu'un
    AUTRE courtier ne répond pas. Déclarer fermé est **soustractif** : là,
    l'exigence reste entière.
    """
    responses = {
        "http://demo.test/positions": _FakeResponse(
            503, {"error": "MT5 not connected"}),
        "http://live.test/positions": _FakeResponse(
            200, {"positions": [POSITION_OR]}),
    }
    with patch("backend.services.mt5_sync.httpx.AsyncClient",
               lambda *a, **kw: _FakeAsyncClient(responses)):
        await mt5_sync._reconcile_open_trades()

    lignes = _lignes(temp_db)
    assert len(lignes) == 1, (
        "la position du pont REEL n'a pas ete adoptee : un pont muet aveugle "
        "encore les autres")
    assert lignes[0]["mt5_ticket"] == 1360999001
    assert lignes[0]["destination_id"] == "admin_live"


@pytest.mark.asyncio
async def test_un_pont_muet_INTERDIT_TOUJOURS_de_declarer_une_fermeture(
    temp_db, deux_ponts
):
    """🔑 L'AUTRE MOITIÉ, et elle ne bouge pas. Un ticket absent du pont réel
    pourrait être porté par le démo, qui ne répond pas. Conclure « fermé »
    serait une détection PAR ABSENCE sur un dire incomplet — le défaut du
    2026-08-13, où les 16 trades réels d'août portaient tous une durée
    d'exactement 1 minute.

    ⇒ On adopte quand même (c'est additif), mais on ne ferme RIEN.
    """
    with sqlite3.connect(temp_db) as c:
        c.execute(
            "INSERT INTO personal_trades (user, pair, direction, entry_price,"
            " stop_loss, take_profit, size_lot, status, created_at,"
            " mt5_ticket, is_auto) "
            "VALUES ('u','EUR/USD','buy',1.1,1.09,1.12,0.1,'OPEN',"
            "'2026-10-09T05:00:00+00:00',999123,1)"
        )

    responses = {
        "http://demo.test/positions": _FakeResponse(
            503, {"error": "MT5 not connected"}),
        "http://live.test/positions": _FakeResponse(
            200, {"positions": [POSITION_OR]}),
        # ⚠️ Volontairement fourni : si la fonction le demandait malgre le
        # pont muet, le test le verrait passer au lieu d'echouer.
        "http://live.test/deals?ticket=999123": _FakeResponse(200, {
            "ticket": 999123, "closed": True,
            "exit_price": 1.09, "pnl": -8.0,
            "closed_at": "2026-10-09T09:00:00+00:00",
        }),
    }
    with patch("backend.services.mt5_sync.httpx.AsyncClient",
               lambda *a, **kw: _FakeAsyncClient(responses)):
        await mt5_sync._reconcile_open_trades()

    with sqlite3.connect(temp_db) as c:
        statut = c.execute(
            "SELECT status FROM personal_trades WHERE mt5_ticket=999123"
        ).fetchone()[0]
    assert statut == "OPEN", (
        "un ticket a ete declare FERME alors qu'un pont ne repondait pas : "
        "detection par absence sur un dire incomplet")
    # …et l'adoption a quand meme eu lieu.
    assert any(r["mt5_ticket"] == 1360999001 for r in _lignes(temp_db))


@pytest.mark.asyncio
async def test_les_DEUX_ponts_muets_n_adoptent_rien(temp_db, deux_ponts):
    """Sans aucun dire, il n'y a rien à enregistrer."""
    responses = {
        "http://demo.test/positions": httpx.ConnectError("demo eteint"),
        "http://live.test/positions": httpx.ConnectError("reel eteint"),
    }
    with patch("backend.services.mt5_sync.httpx.AsyncClient",
               lambda *a, **kw: _FakeAsyncClient(responses)):
        await mt5_sync._reconcile_open_trades()

    assert _lignes(temp_db) == []


@pytest.mark.asyncio
async def test_les_deux_ponts_REPONDENT_la_fermeture_est_declaree(
    temp_db, deux_ponts
):
    """🔑 Le contrôle positif : quand TOUS les ponts parlent, la fermeture se
    déclare comme avant. Sans ce test, rendre la fonction prudente pourrait la
    rendre inerte sans que rien ne le dise."""
    with sqlite3.connect(temp_db) as c:
        c.execute(
            "INSERT INTO personal_trades (user, pair, direction, entry_price,"
            " stop_loss, take_profit, size_lot, status, created_at,"
            " mt5_ticket, is_auto) "
            "VALUES ('u','EUR/USD','buy',1.1,1.09,1.12,0.1,'OPEN',"
            "'2026-10-09T05:00:00+00:00',999123,1)"
        )

    responses = {
        "http://demo.test/positions": _FakeResponse(200, {"positions": []}),
        "http://live.test/positions": _FakeResponse(200, {"positions": []}),
        "http://demo.test/deals?ticket=999123": _FakeResponse(200, {
            "ticket": 999123, "closed": None, "message": "no deals found"}),
        "http://live.test/deals?ticket=999123": _FakeResponse(200, {
            "ticket": 999123, "closed": True,
            "exit_price": 1.09, "pnl": -8.0,
            "closed_at": "2026-10-09T09:00:00+00:00",
        }),
    }
    with patch("backend.services.mt5_sync.httpx.AsyncClient",
               lambda *a, **kw: _FakeAsyncClient(responses)):
        await mt5_sync._reconcile_open_trades()

    with sqlite3.connect(temp_db) as c:
        row = c.execute(
            "SELECT status, pnl FROM personal_trades WHERE mt5_ticket=999123"
        ).fetchone()
    assert row[0] == "CLOSED"
    assert row[1] == pytest.approx(-8.0)


# ─────────────────────────────────────────────────────────────────────────
# ⛔ UNE POSITION SANS OBJECTIF (mesure en production, 2026-10-09)
# ─────────────────────────────────────────────────────────────────────────

# Les charges utiles REELLES des deux positions que le correctif deploye a
# MANQUEES : ni l'une ni l'autre ne porte d'objectif.
SANS_OBJECTIF = {
    "ticket": 1360798623, "symbol": "XAUUSD", "type": "sell", "volume": 0.01,
    "price_open": 4179.03, "price_current": 4181.70, "sl": 4220.82,
    "tp": 0.0, "profit": -2.38, "comment": "",
    "time": "2026-10-09T11:15:02+00:00",
}


def test_une_position_SANS_OBJECTIF_est_adoptee_quand_meme(temp_db):
    """⛔ LE DEFAUT MESURE EN PRODUCTION. Sur trois positions d'or vivantes,
    le correctif deploye n'en a adopte QU'UNE : les deux autres n'avaient pas
    d'objectif.

    `tp: 0.0` est la facon dont MT5 dit « aucun objectif » — et c'est le cas
    NORMAL d'un trade a la main. Mon code traduisait ce 0,0 en `None`, mais la
    colonne est **NOT NULL** en production : `IntegrityError`.

    🔑 Et l'erreur etait AVALEE : levee dans l'adoption, elle remontait dans le
    `try` du cycle, qui classait le pont reel comme « muet ». Un defaut
    d'ecriture se faisait passer pour une panne de reseau.
    """
    n = mt5_sync._adopter_positions_du_courtier([SANS_OBJECTIF], "admin_live")

    assert n == 1, "une position sans objectif n'a pas ete adoptee"
    ligne = _lignes(temp_db)[0]
    assert ligne["mt5_ticket"] == 1360798623
    # 🔑 On garde le 0,0 du courtier : c'est SA facon de dire « absent », la
    # colonne est NOT NULL, et aucun prix de sortie ne peut l'egaler par
    # accident.
    assert ligne["take_profit"] == 0.0
    assert ligne["stop_loss"] == pytest.approx(4220.82)


def test_les_DEUX_positions_du_09_10_sont_adoptees_ensemble(temp_db):
    """🔑 Le cas exact de la production : une position AVEC objectif et une
    SANS, dans la meme charge utile. Avant le correctif, la premiere passait et
    la seconde faisait echouer tout le reste du cycle."""
    n = mt5_sync._adopter_positions_du_courtier(
        [POSITION_OR, SANS_OBJECTIF], "admin_live")

    assert n == 2
    assert len(_lignes(temp_db)) == 2


def test_une_position_ILLISIBLE_ne_fait_pas_tomber_les_AUTRES(temp_db, caplog):
    """⛔ L'erreur d'ecriture doit etre BRUYANTE et LOCALE.

    Avant, une seule position mal formee faisait lever l'adoption entiere : le
    cycle la rattrapait et declarait le pont « muet », donc (1) les positions
    suivantes etaient perdues, (2) aucune fermeture n'etait declaree, et
    (3) le diagnostic accusait le reseau. Trois degats pour une ligne.
    """
    # ⚠️ Un type que SQLite REFUSE de lier (`InterfaceError`), et non une
    # valeur juste mal ecrite : `price_open="pas un prix"` retombe proprement
    # sur 0,0 par `_valeur_reelle` — ma premiere version de ce test le croyait
    # fatal, et c'est le TEST qui avait tort. Une date rendue comme objet est
    # le cas plausible : une version du pont qui change la forme de `time`.
    illisible = {**POSITION_OR, "ticket": 999001, "time": {"pas": "une date"}}

    with caplog.at_level("WARNING"):
        n = mt5_sync._adopter_positions_du_courtier(
            [illisible, SANS_OBJECTIF], "admin_live")

    assert n == 1, "la position saine n'a pas ete adoptee"
    assert _lignes(temp_db)[0]["mt5_ticket"] == 1360798623
    assert "999001" in caplog.text


@pytest.mark.asyncio
async def test_une_ecriture_qui_ECHOUE_ne_rend_pas_le_pont_muet(
    temp_db, pont_configure
):
    """🔑 Le volet qui manquait : un echec d'ECRITURE ne doit pas se faire
    passer pour un pont injoignable, sinon la fermeture des autres tickets est
    suspendue par un defaut qui n'a rien a voir."""
    with sqlite3.connect(temp_db) as c:
        c.execute(
            "INSERT INTO personal_trades (user, pair, direction, entry_price,"
            " stop_loss, take_profit, size_lot, status, created_at,"
            " mt5_ticket, is_auto) "
            "VALUES ('u','EUR/USD','buy',1.1,1.09,1.12,0.1,'OPEN',"
            "'2026-10-09T05:00:00+00:00',999123,1)"
        )
    illisible = {**POSITION_OR, "ticket": 999002, "time": {"pas": "une date"}}

    responses = {
        "http://bridge.test/positions": _FakeResponse(
            200, {"positions": [illisible]}),
        "http://bridge.test/deals?ticket=999123": _FakeResponse(200, {
            "ticket": 999123, "closed": True, "exit_price": 1.09,
            "pnl": -8.0, "closed_at": "2026-10-09T09:00:00+00:00",
        }),
    }
    with patch("backend.services.mt5_sync.httpx.AsyncClient",
               lambda *a, **kw: _FakeAsyncClient(responses)):
        await mt5_sync._reconcile_open_trades()

    with sqlite3.connect(temp_db) as c:
        statut = c.execute(
            "SELECT status FROM personal_trades WHERE mt5_ticket=999123"
        ).fetchone()[0]
    assert statut == "CLOSED", (
        "un echec d'ecriture a suspendu la declaration des fermetures : il "
        "s'est fait passer pour un pont muet")
