"""Verser les setups d'une source tierce dans le journal fantome — SANS trader.

Demande de Xavier le 2026-10-02 : brancher un diffuseur MQL5 sur l'outil, et
<< c'est plus un branchement INFORMATIF qu'un branchement qui va produire des
trades >>.

🔑 **L'appareil existait deja**, et personne ne l'avait alimente. `shadow_setups`
compte 43 400 lignes et 26 673 issues resolues depuis le 18/05 : un setup y est
enregistre, la reconciliation rejoue les bougies de 5 min en avant, et inscrit
TP1 / SL / TIMEOUT avec MFE et MAE. **Aucun ordre ne part jamais.**

Deux proprietes du schema rendent ce module petit, et elles ont ete verifiees
avant d'ecrire une ligne :

  1. La reconciliation est **agnostique du systeme** — `WHERE outcome IS NULL`,
     sans filtre de provenance. Toute ligne versee ici obtient son issue
     gratuitement, par le job qui tourne deja.
  2. `UNIQUE (system_id, bar_timestamp)` — l'idempotence est native, a condition
     que le `system_id` encode la paire ET le sens, comme le fait V1.

⛔ CE QUI EST REUTILISE, JAMAIS REECRIT
Les formules derivees de `shadow_v1` (`risk_pct = risque / entree`,
`rr = recompense / risque`, `sizing_max_loss = capital x risque`) et ses
constantes `DEFAULT_CAPITAL_EUR` / `DEFAULT_RISK_PCT`. Un second jeu de chiffres
rendrait la source incomparable avec nos propres cellules — ce qui est tout
l'objet de la mesure.

⛔ CE MODULE N'EXECUTE RIEN, et un test le prouve par le COMPORTEMENT, pas en
relisant le source : `send_setup` est remplace par une fonction qui fait echouer
le test si elle est appelee.
"""
from __future__ import annotations

import sqlite3

import pytest

from backend.services import observation_externe as obs


def _charge(**kw):
    """Une observation complete et valide ; les tests en retirent un champ."""
    base = {
        "source": "algo_trading",
        "pair": "XAU/USD",
        "direction": "sell",
        "timeframe": "5min",
        "bar_timestamp": "2026-10-02T08:15:00+00:00",
        "entry_price": 4150.0,
        "stop_loss": 4175.0,
        "take_profit": 4105.0,
    }
    base.update(kw)
    return base


@pytest.fixture
def base(tmp_path, monkeypatch):
    chemin = str(tmp_path / "trades.db")
    monkeypatch.setattr(obs, "_db_path", lambda: chemin)
    with sqlite3.connect(chemin) as c:
        c.execute("""
            CREATE TABLE shadow_setups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                cycle_at TIMESTAMP NOT NULL,
                bar_timestamp TIMESTAMP NOT NULL,
                system_id TEXT NOT NULL,
                pair TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                direction TEXT NOT NULL,
                pattern TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit_1 REAL NOT NULL,
                take_profit_2 REAL,
                risk_pct REAL NOT NULL,
                rr REAL NOT NULL,
                sizing_capital_eur REAL NOT NULL DEFAULT 10000,
                sizing_risk_pct REAL NOT NULL DEFAULT 0.005,
                sizing_position_eur REAL NOT NULL,
                sizing_max_loss_eur REAL NOT NULL,
                outcome TEXT,
                UNIQUE (system_id, bar_timestamp)
            )""")
    return chemin


def _lignes(chemin):
    with sqlite3.connect(chemin) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute("SELECT * FROM shadow_setups")]


# --- Le versement nominal -----------------------------------------------

def test_une_observation_valide_est_versee(base):
    ok, cause, _ = obs.verser(_charge())
    assert ok is True and cause == obs.OK
    lignes = _lignes(base)
    assert len(lignes) == 1
    assert lignes[0]["outcome"] is None, "l'issue doit rester a resoudre"


def test_le_system_id_encode_la_source_la_paire_et_le_sens(base):
    """⛔ `UNIQUE (system_id, bar_timestamp)` : sans la paire ET le sens dans la
    cle, deux trades d'une meme source au meme horodatage se mangeraient."""
    obs.verser(_charge())
    assert _lignes(base)[0]["system_id"] == "OBS_ALGO_TRADING_XAUUSD_sell"


def test_deux_paires_au_MEME_horodatage_coexistent(base):
    """La consequence directe : une source multi-paires n'ecrase rien."""
    assert obs.verser(_charge())[0] is True
    assert obs.verser(_charge(pair="EUR/USD", entry_price=1.17,
                              stop_loss=1.175, take_profit=1.16))[0] is True
    assert len(_lignes(base)) == 2


def test_les_champs_derives_reprennent_les_formules_de_V1(base):
    """⛔ Memes formules et memes constantes, sinon la source est
    incomparable avec nos propres cellules — tout l'objet de la mesure."""
    from backend.services.shadow_v1 import (DEFAULT_CAPITAL_EUR,
                                            DEFAULT_RISK_PCT)
    obs.verser(_charge())
    l = _lignes(base)[0]
    assert l["risk_pct"] == pytest.approx(25.0 / 4150.0)
    assert l["rr"] == pytest.approx(45.0 / 25.0)
    assert l["sizing_capital_eur"] == pytest.approx(DEFAULT_CAPITAL_EUR)
    assert l["sizing_risk_pct"] == pytest.approx(DEFAULT_RISK_PCT)
    assert l["sizing_max_loss_eur"] == pytest.approx(
        DEFAULT_CAPITAL_EUR * DEFAULT_RISK_PCT)


# --- L'idempotence -------------------------------------------------------

def test_le_meme_trade_verse_deux_fois_ne_cree_qu_une_ligne(base):
    assert obs.verser(_charge())[1] == obs.OK
    ok, cause, _ = obs.verser(_charge())
    assert cause == obs.CAUSE_DOUBLON
    assert ok is True, "un rejeu n'est pas un echec — sinon la source reessaie"
    assert len(_lignes(base)) == 1


# --- Les refus, tous NOMMES ---------------------------------------------

@pytest.mark.parametrize("manquant", [
    "source", "pair", "direction", "timeframe", "bar_timestamp",
    "entry_price", "stop_loss", "take_profit",
])
def test_un_champ_manquant_est_refuse_et_NOMME(base, manquant):
    charge = _charge()
    del charge[manquant]
    ok, cause, detail = obs.verser(charge)
    assert ok is False and cause == obs.CAUSE_FORME
    assert manquant in detail, detail
    assert _lignes(base) == []


def test_la_cible_n_est_JAMAIS_derivee(base):
    """⛔ Le refus qui compte le plus.

    `take_profit_1` est NOT NULL et la reconciliation en a besoin pour conclure
    TP1. Mais deriver une cible — un 1,8 R par exemple — fabriquerait
    exactement ce qu'on veut mesurer : **la cible de la source**. Une source
    qui ne publie pas sa cible n'est pas observable, et on le DIT.
    """
    ok, cause, detail = obs.verser(_charge(take_profit=None))
    assert ok is False and cause == obs.CAUSE_FORME
    assert "take_profit" in detail
    assert _lignes(base) == []


def test_un_sens_inconnu_est_refuse(base):
    ok, cause, _ = obs.verser(_charge(direction="long"))
    assert ok is False and cause == obs.CAUSE_FORME


def test_un_nombre_illisible_est_refuse(base):
    ok, cause, _ = obs.verser(_charge(entry_price="quatre mille"))
    assert ok is False and cause == obs.CAUSE_FORME


def test_un_stop_du_mauvais_cote_est_refuse(base):
    """Une vente dont le stop est SOUS l'entree n'est pas une vente."""
    ok, cause, detail = obs.verser(_charge(direction="sell", stop_loss=4100.0))
    assert ok is False and cause == obs.CAUSE_FORME
    assert "stop" in detail.lower()


def test_un_risque_nul_est_refuse(base):
    ok, cause, _ = obs.verser(_charge(stop_loss=4150.0))
    assert ok is False and cause == obs.CAUSE_FORME


# --- La garantie qui compte : RIEN ne s'execute --------------------------

def test_verser_n_appelle_JAMAIS_le_pont(base, monkeypatch):
    """⛔ Prouve par le COMPORTEMENT, pas en relisant le source.

    Le chemin d'ingestion existant (`external_signals`) dispatche vers le
    demo : il EXECUTE. Celui-ci ne doit toucher ni `send_setup` ni la
    resolution de destinations — c'est la difference entre un branchement
    informatif et un branchement qui produit des trades.
    """
    def _interdit(*a, **kw):
        pytest.fail("verser() a appele le pont — ce module n'execute rien")

    monkeypatch.setattr("backend.services.mt5_bridge.send_setup", _interdit)
    monkeypatch.setattr(
        "backend.services.bridge_destinations.resolve_destinations", _interdit)
    assert obs.verser(_charge())[0] is True
