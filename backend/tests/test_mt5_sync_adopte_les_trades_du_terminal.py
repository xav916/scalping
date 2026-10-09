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


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """DB SQLite temporaire au schéma de `personal_trades`."""
    db_file = tmp_path / "trades.db"
    conn = sqlite3.connect(db_file)
    conn.execute("""
        CREATE TABLE personal_trades (
            id INTEGER PRIMARY KEY,
            user TEXT, pair TEXT, direction TEXT,
            entry_price REAL, stop_loss REAL, take_profit REAL,
            size_lot REAL, signal_pattern TEXT, signal_confidence REAL,
            checklist_passed INTEGER, notes TEXT, status TEXT,
            created_at TEXT, mt5_ticket INTEGER, is_auto INTEGER,
            post_entry_sl INTEGER, post_entry_tp INTEGER, post_entry_size INTEGER,
            context_macro TEXT, exit_price REAL, pnl REAL, closed_at TEXT,
            signal_id INTEGER, fill_price REAL, slippage_pips REAL,
            close_reason TEXT, sl_at_close REAL, tp_at_close REAL,
            niveaux_source TEXT, destination_id TEXT
        )
    """)
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
            " size_lot, status, created_at, mt5_ticket, is_auto) "
            "VALUES ('u','XAU/USD','sell',4203.7,0.01,'OPEN',"
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
