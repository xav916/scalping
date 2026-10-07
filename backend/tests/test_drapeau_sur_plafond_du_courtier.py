"""Après un « continue » sur le plafond DU COURTIER, le drapeau doit partir.

Le pont lève sa porte de drawdown — et elle seule — quand l'ordre porte
`drawdown_arbitre` (2026-09-04, vérifié dans le `bridge.py` déployé). Ce
drapeau vient de `arbitrage_actif_pour()`.

⛔ **Le trou du 2026-10-07.** Cette fonction rendait `None` dès que NOTRE
plafond n'était pas franchi. Or le courtier coupe sur SA mesure (solde
d'ouverture − equity) : il franchissait à 19,77 € quand nos clôtures en base
n'en comptaient que 16,45. Résultat, après un `continue` **aucun drapeau ne
partait** et le pont refusait quand même : le bouton était décoratif.

🔑 La tranche reste la borne. Une autorisation accordée à −19,77 € avec un
plafond de −17,87 € couvre jusqu'à −37,64 € — et pas un euro au-delà. Pour le
vérifier il faut la perte que le courtier compte **maintenant**, pas celle
d'il y a une heure : c'est `perte_du_courtier()` qui la lit sur `/health`.

⛔ **Fail-closed à chaque étage.** Pont muet, chiffre absent, flottant exclu,
aucune ligne du jour, `GELER` : tout rend `None`, donc « le pont applique son
garde-fou ». C'est de l'argent réel — une panne de lecture ne vaut pas
autorisation.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest


@pytest.fixture()
def harnais(tmp_path, monkeypatch):
    """Notre plafond NON franchi (une seule clôture à −2 €), le courtier OUI."""
    import backend.services.trade_log_service as t
    from backend.services import plafond_arbitrage as a

    chemin = tmp_path / "trades.db"
    monkeypatch.setattr(t, "_DB_PATH", chemin, raising=False)
    monkeypatch.setattr(t, "TRADING_CAPITAL", 650.0, raising=False)
    monkeypatch.setattr(t, "DAILY_LOSS_LIMIT_PCT", 3.0, raising=False)
    t._init_schema()
    a._init_schema()

    monkeypatch.setattr(t, "_destinations_reelles", lambda: {"admin_live"},
                        raising=False)

    c = sqlite3.connect(chemin)
    c.execute("""CREATE TABLE IF NOT EXISTS mt5_pushes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, destination_id TEXT,
        bridge_response TEXT)""")
    cols = {r[1] for r in c.execute("PRAGMA table_info(personal_trades)")}
    champs = {"user": "admin", "pair": "XAU/USD", "direction": "buy",
              "entry_price": 4130.0, "stop_loss": 4120.0,
              "take_profit": 4150.0, "size_lot": 0.01,
              "status": "CLOSED", "pnl": -2.0,
              "destination_id": "admin_live",
              "created_at": datetime.now(timezone.utc).isoformat()}
    champs = {k: v for k, v in champs.items() if k in cols}
    c.execute(f"INSERT INTO personal_trades ({','.join(champs)}) VALUES "
              f"({','.join('?' * len(champs))})", tuple(champs.values()))
    c.commit()
    c.close()
    return t, a


def _ligne_continuer(a, perte=-19.77, seuil=-17.87):
    """Une tranche ouverte sur les chiffres DU COURTIER, puis autorisée."""
    a.ouvrir_demande("admin_live", perte, seuil)
    a.repondre(a.CONTINUER, "admin_live")


def test_notre_plafond_n_est_PAS_franchi(harnais):
    """Le point de départ, sinon le test ne prouve rien."""
    t, _ = harnais
    cumul, limite = t._cumul_et_limite("admin_live")
    assert cumul == -2.0
    assert not t_franchi(t, cumul, limite)


def t_franchi(t, cumul, limite):
    from backend.services import plafond_arbitrage as a
    return a.franchi(cumul, limite)


def test_le_drapeau_PART_quand_la_tranche_du_courtier_est_autorisee(
        harnais, monkeypatch):
    t, a = harnais
    _ligne_continuer(a)
    monkeypatch.setattr(a, "perte_du_courtier", lambda d: -21.40)

    drapeau = t.arbitrage_actif_pour("admin_live")
    assert drapeau is not None
    assert drapeau["accorde_a"] == -19.77
    assert drapeau["couvre_jusqua"] == -37.64


def test_un_GELER_ne_laisse_RIEN_passer(harnais, monkeypatch):
    t, a = harnais
    a.ouvrir_demande("admin_live", -19.77, -17.87)
    a.repondre(a.GELER, "admin_live")
    monkeypatch.setattr(a, "perte_du_courtier", lambda d: -21.40)

    assert t.arbitrage_actif_pour("admin_live") is None


def test_au_dela_de_la_tranche_le_drapeau_s_arrete(harnais, monkeypatch):
    """−37,64 est la borne. À −40, la porte du pont doit se refermer."""
    t, a = harnais
    _ligne_continuer(a)
    monkeypatch.setattr(a, "perte_du_courtier", lambda d: -40.00)

    assert t.arbitrage_actif_pour("admin_live") is None


def test_un_pont_qui_ne_dit_pas_sa_perte_ne_leve_RIEN(harnais, monkeypatch):
    """⛔ Fail-closed : ne pas savoir où en est le courtier n'autorise rien."""
    t, a = harnais
    _ligne_continuer(a)
    monkeypatch.setattr(a, "perte_du_courtier", lambda d: None)

    assert t.arbitrage_actif_pour("admin_live") is None


def test_sans_ligne_du_jour_rien_ne_change(harnais, monkeypatch):
    t, a = harnais
    monkeypatch.setattr(a, "perte_du_courtier",
                        lambda d: pytest.fail("ne doit pas etre interroge"))

    assert t.arbitrage_actif_pour("admin_live") is None
