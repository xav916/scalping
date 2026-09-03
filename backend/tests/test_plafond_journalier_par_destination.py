"""Le plafond journalier juge chaque compte sur SES pertes et SON capital.

Le 2026-09-02 à 11h35 UTC, un stop sur `XAU/USD` porte le cumul réalisé du
compte réel à −28,45 € — au-delà des −19,50 € du plafond (3 % de 650 €).
`silent_mode_active_any_user()` bascule et `kill_switch.is_active()` gèle
**toutes** les destinations : 3 490 signaux refusés en `kill_switch` de 11h à
minuit, sur le réel, sur la démo **et** sur Kraken. Ni la démo ni Kraken
n'avaient perdu quoi que ce soit ce jour-là.

Deux défauts distincts, verrouillés ici :

  1. **La portée** — un compte qui saigne condamnait les autres. C'est le même
     défaut que `pair_pnl_regulator` avait le 29/08, corrigé alors seulement
     pour les pauses par paire. Le plafond journalier, lui, était resté global.

  2. **Le capital** — le seuil se calculait sur `TRADING_CAPITAL`, une
     constante à 650 € pendant que le compte réel en portait 719,18. Le
     « 3 % » en valait 2,7, et se resserrait à chaque euro gagné.

⚠️ Le piège que ces tests gardent en priorité : rendre le gel chirurgical
OUVRE une porte dérobée. Le miroir démo→réel ne rejoue pas les portes de
décision — si la démo continue de trader pendant que le réel est gelé, ses
fills sont copiés vers le réel et le plafond ne sert plus à rien. C'est
`test_le_miroir_ne_copie_pas_vers_un_compte_gele` qui tient cette porte.
"""
from __future__ import annotations

import sqlite3
from datetime import date

import pytest


# ── Harnais ────────────────────────────────────────────────────────────────

@pytest.fixture()
def base(tmp_path, monkeypatch):
    """Base réelle, schéma réel — pas une reconstitution."""
    import backend.services.trade_log_service as t

    chemin = tmp_path / "trades.db"
    monkeypatch.setattr(t, "_DB_PATH", chemin, raising=False)
    t._init_schema()

    c = sqlite3.connect(chemin)
    c.execute("""CREATE TABLE IF NOT EXISTS mt5_pushes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, destination_id TEXT,
        bridge_response TEXT)""")
    c.commit()
    c.close()
    monkeypatch.setattr(t, "TRADING_CAPITAL", 650.0, raising=False)
    monkeypatch.setattr(t, "DAILY_LOSS_LIMIT_PCT", 3.0, raising=False)
    return t, chemin


def _ajouter(chemin, pnl, ticket, destination=None, user="admin"):
    """Un trade fermé aujourd'hui, et le push qui le rattache à un compte."""
    c = sqlite3.connect(chemin)
    cols = [r[1] for r in c.execute("PRAGMA table_info(personal_trades)")]
    vals = {"user": user, "pair": "XAU/USD", "direction": "buy",
            "entry_price": 4450.0, "stop_loss": 4420.0, "take_profit": 4504.0,
            "size_lot": 0.01, "status": "CLOSED", "pnl": pnl,
            "mt5_ticket": ticket,
            "created_at": date.today().isoformat() + "T10:00:00"}
    utiles = {k: v for k, v in vals.items() if k in cols}
    c.execute(
        f"INSERT INTO personal_trades ({','.join(utiles)}) "
        f"VALUES ({','.join('?' * len(utiles))})", tuple(utiles.values()))
    if destination:
        c.execute(
            "INSERT INTO mt5_pushes (destination_id, bridge_response) "
            "VALUES (?, ?)",
            (destination, '{"ticket": %s, "ok": true}' % ticket))
    c.commit()
    c.close()


def _capital_cache(monkeypatch, **soldes):
    """Force le cache de soldes réels que le plafond interroge.

    Un cache NEUF plutôt qu'un ajout au cache du module : muter le vrai
    dictionnaire laisserait les soldes fuiter d'un test à l'autre.
    """
    import time

    import backend.services.sizing as sizing

    frais = {d: (s, time.monotonic() + 3600) for d, s in soldes.items()}
    # `_SOLDE_CONNU` et non `_BALANCE_CACHE` : c'est le cache LONG que le
    # plafond interroge, celui du sizing périmant en 5 min.
    monkeypatch.setattr(sizing, "_SOLDE_CONNU", frais, raising=False)


# ── 1. La portée : un compte ne condamne plus les autres ───────────────────

def test_une_perte_sur_le_reel_ne_gele_plus_kraken(base):
    """Le cas du 02/09 : −28,45 € sur le réel, rien sur Kraken."""
    t, chemin = base
    _ajouter(chemin, -28.45, 1001, "admin_live")

    assert t.silent_mode_active_for_destination("admin_live") is True
    assert t.silent_mode_active_for_destination("admin_kraken") is False, (
        "Kraken n'a rien perdu ce jour-là — le geler est une erreur de portée")


def test_chaque_compte_est_juge_sur_SES_pertes(base):
    """Deux comptes réels, un seul au-delà du seuil."""
    t, chemin = base
    _ajouter(chemin, -25.00, 1002, "admin_live")
    _ajouter(chemin, -3.00, 1003, "admin_kraken")

    assert t.silent_mode_active_for_destination("admin_live") is True
    assert t.silent_mode_active_for_destination("admin_kraken") is False


def test_deux_comptes_sous_le_seuil_ne_s_additionnent_plus(base):
    """−12 € et −12 € font −24 € : au-delà du seuil en cumul, en deçà chacun.

    C'est exactement ce que l'ancienne somme par `user` produisait — un gel
    déclenché par un total que AUCUN compte n'avait atteint.
    """
    t, chemin = base
    _ajouter(chemin, -12.00, 1004, "admin_live")
    _ajouter(chemin, -12.00, 1005, "admin_kraken")

    assert t.silent_mode_active_for_destination("admin_live") is False
    assert t.silent_mode_active_for_destination("admin_kraken") is False


def test_le_demo_n_est_jamais_gele_par_un_plafond_d_argent_reel(base):
    """La démo perd de l'argent qui n'existe pas — le plafond ne la vise pas.

    Prolonge le correctif du 2026-08-20 : une perte démo ne coupait plus le
    réel, mais elle continuait à se couper elle-même via le switch global.
    """
    t, chemin = base
    _ajouter(chemin, -500.00, 1006, "admin_legacy")

    assert t.silent_mode_active_for_destination("admin_legacy") is False


def test_une_perte_reelle_ne_gele_pas_le_demo(base):
    """Le réel saigne, la démo continue de mesurer. C'est le but du miroir."""
    t, chemin = base
    _ajouter(chemin, -28.45, 1007, "admin_live")

    assert t.silent_mode_active_for_destination("admin_live") is True
    assert t.silent_mode_active_for_destination("admin_legacy") is False


# ── 2. Le capital : le seuil suit le compte, pas une constante ─────────────

def test_le_seuil_suit_le_solde_REEL_de_la_destination(base, monkeypatch):
    """719,18 € au courtier ⇒ seuil −21,58 €, pas −19,50 €.

    Une perte de −20,50 € est au-delà des 3 % de la constante (650 €) mais en
    deçà des 3 % du compte. Geler ici, c'est appliquer 2,8 % en croyant en
    appliquer 3.
    """
    t, chemin = base
    _capital_cache(monkeypatch, admin_live=719.18)
    _ajouter(chemin, -20.50, 1008, "admin_live")

    assert t.silent_mode_active_for_destination("admin_live") is False


def test_le_seuil_mord_quand_le_solde_reel_est_franchi(base, monkeypatch):
    t, chemin = base
    _capital_cache(monkeypatch, admin_live=719.18)
    _ajouter(chemin, -22.00, 1009, "admin_live")

    assert t.silent_mode_active_for_destination("admin_live") is True


def test_cache_froid_retombe_sur_le_capital_CONFIGURE(base, monkeypatch):
    """Solde inconnu ⇒ on reprend 650 €, le seuil le plus SERRÉ.

    Le repli doit aller dans le sens prudent : ne pas savoir combien porte le
    compte ne doit jamais élargir le plafond.
    """
    import backend.services.sizing as sizing
    t, chemin = base
    monkeypatch.setattr(sizing, "_SOLDE_CONNU", {}, raising=False)
    _ajouter(chemin, -20.50, 1010, "admin_live")

    assert t.silent_mode_active_for_destination("admin_live") is True


# ── 3. Fail-closed : le doute protège ──────────────────────────────────────

def test_une_destination_NON_RESOLUE_compte_pour_chaque_compte_reel(base):
    """Un trade qu'on ne sait rattacher à personne pèse sur tous les réels.

    Reprend le principe déjà posé le 2026-08-20 : quand on ne sait pas, on
    protège. L'inverse laisserait un trade inconnu échapper au garde-fou.
    """
    t, chemin = base
    _ajouter(chemin, -28.45, 1011, None)

    assert t.silent_mode_active_for_destination("admin_live") is True
    assert t.silent_mode_active_for_destination("admin_kraken") is True


def test_une_destination_non_resolue_ne_gele_pas_le_demo(base):
    """Fail-closed sur l'argent réel seulement : la démo reste hors sujet."""
    t, chemin = base
    _ajouter(chemin, -500.00, 1012, None)

    assert t.silent_mode_active_for_destination("admin_legacy") is False


def test_registre_illisible_gele_par_prudence(base, monkeypatch):
    """Sans registre, on ne sait plus qui est réel : on gèle."""
    t, chemin = base
    monkeypatch.setattr(t, "_destinations_reelles", frozenset, raising=False)
    _ajouter(chemin, -28.45, 1013, "admin_legacy")

    assert t.silent_mode_active_for_destination("admin_live") is True


def test_destination_inconnue_du_registre_est_traitee_comme_reelle(base):
    """Une destination qu'on ne connaît pas n'est pas une destination sûre."""
    t, chemin = base
    _ajouter(chemin, -28.45, 1014, "admin_live")

    assert t.silent_mode_active_for_destination("destination_jamais_vue") is True


# ── 4. Compatibilité : sans destination, rien ne change ────────────────────

def test_sans_destination_le_comportement_global_est_conserve(base):
    """`kill_switch.is_active()` sans destination garde l'ancienne portée.

    `binance_drawdown_breaker` et `promotion_engine` l'appellent ainsi : leur
    question est « le système est-il gelé », pas « ce compte l'est-il ».
    """
    t, chemin = base
    _ajouter(chemin, -28.45, 1015, "admin_live")

    assert t.silent_mode_active_any_user() is True


# ── 5. Le kill switch relaie la portée ─────────────────────────────────────

def test_kill_switch_is_active_est_par_destination(base, monkeypatch):
    from backend.services import kill_switch as ks

    t, chemin = base
    monkeypatch.setattr(ks, "_load_state", lambda: {}, raising=False)
    monkeypatch.setattr(ks, "is_global_rafale_paused", lambda: (False, {}),
                        raising=False)
    monkeypatch.setattr(ks, "is_pair_rafale_paused", lambda p: (False, {}),
                        raising=False)
    _ajouter(chemin, -28.45, 1016, "admin_live")

    assert ks.is_active(destination_id="admin_live") is True
    assert ks.is_active(destination_id="admin_kraken") is False


def test_le_switch_MANUEL_reste_global(base, monkeypatch):
    """Une coupure décidée à la main ne se négocie pas par compte."""
    from backend.services import kill_switch as ks

    monkeypatch.setattr(ks, "_load_state", lambda: {"manual_enabled": True},
                        raising=False)
    monkeypatch.setattr(ks, "is_global_rafale_paused", lambda: (False, {}),
                        raising=False)

    assert ks.is_active(destination_id="admin_kraken") is True
    assert ks.is_active(destination_id="admin_legacy") is True


def test_la_pause_rafale_GLOBALE_reste_globale(base, monkeypatch):
    from backend.services import kill_switch as ks

    monkeypatch.setattr(ks, "_load_state", lambda: {}, raising=False)
    monkeypatch.setattr(ks, "is_global_rafale_paused",
                        lambda: (True, {"reason": "rafale"}), raising=False)

    assert ks.is_active(destination_id="admin_kraken") is True
