"""Le critère de promotion démo → réel (2026-09-04).

Demandé par Xavier : ouvrir un instrument sur la démo, le mesurer, et ne le
passer sur le réel que si le bénéfice est là.

⛔ **Le bénéfice par paire N'EST PAS MESURABLE, et ce module refuse de
prétendre le contraire.** Mesuré le 04/09 : la démo produit 12 trades/mois sur
`WTI/USD`, 2 sur `USD/JPY`. Distinguer un edge de +0,15 R du hasard en demande
~700. Soit 44 mois sur la meilleure paire.

C'est exactement en promouvant sur ces échantillons-là que le système a obtenu
un DSR de 0,35 et un PBO de 0,579 — la « gagnante » tenait à 3 trades sur 233.
Un critère bâti sur « est-ce rentable ? » refabriquerait la même erreur avec
plus de cérémonie.

🔑 Ce que la démo PEUT trancher en trois semaines :

  1. **Mécanique** — l'ordre part-il, le symbole est-il mappé, le stop est-il
     réellement posé chez le courtier ?
  2. **Coût** — le spread et le slippage réels laissent-ils quelque chose ?
  3. **Incidents** — aucune position nue, aucun stop non appliqué.

Ces trois-là décident. La rentabilité est CALCULÉE et RAPPORTÉE, jamais
utilisée comme porte — et elle est accompagnée du N qu'il faudrait, pour que
personne ne la lise comme un verdict.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest


@pytest.fixture()
def base(tmp_path, monkeypatch):
    import backend.services.trade_log_service as t

    chemin = tmp_path / "trades.db"
    monkeypatch.setattr(t, "_DB_PATH", chemin, raising=False)
    t._init_schema()
    c = sqlite3.connect(chemin)
    c.execute("""CREATE TABLE IF NOT EXISTS mt5_pushes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, destination_id TEXT, pair TEXT,
        direction TEXT, pushed_at TEXT, ok INTEGER, bridge_response TEXT)""")
    c.commit()
    c.close()
    return chemin


def _push(chemin, pair="WTI/USD", dest="admin_legacy", ok=1,
          sl_applied=True, tp_applied=True, sl_error=None, n=1,
          instrumente=True):
    c = sqlite3.connect(chemin)
    champs = {"ok": bool(ok), "fill_price": 65.0, "volume": 0.01,
              "sl_error": sl_error, "tp_error": None, "ticket": 1}
    if instrumente:
        # `sl_applied` n'existe dans les réponses que depuis le 2026-08-06 ;
        # `instrumente=False` reproduit une poussée antérieure.
        champs.update({"sl_applied": sl_applied, "tp_applied": tp_applied,
                       "protected": sl_applied})
    corps = json.dumps(champs)
    for _ in range(n):
        c.execute("INSERT INTO mt5_pushes (destination_id, pair, direction, "
                  "pushed_at, ok, bridge_response) VALUES (?,?,?,?,?,?)",
                  (dest, pair, "buy",
                   datetime.now(timezone.utc).isoformat(), ok, corps))
    c.commit()
    c.close()


def _trade(chemin, pair="WTI/USD", dest="admin_legacy", pnl=1.0,
           entry=65.0, sl=64.6, slippage=0.5, n=1):
    c = sqlite3.connect(chemin)
    cols = [r[1] for r in c.execute("PRAGMA table_info(personal_trades)")]
    for _ in range(n):
        vals = {"user": "admin", "pair": pair, "direction": "buy",
                "entry_price": entry, "stop_loss": sl, "take_profit": 65.8,
                "size_lot": 0.01, "status": "CLOSED", "pnl": pnl,
                "destination_id": dest, "slippage_pips": slippage,
                "fill_price": entry, "close_reason": "TP",
                "created_at": date.today().isoformat() + "T10:00:00",
                "closed_at": date.today().isoformat() + "T12:00:00"}
        u = {k: v for k, v in vals.items() if k in cols}
        c.execute(f"INSERT INTO personal_trades ({','.join(u)}) "
                  f"VALUES ({','.join('?' * len(u))})", tuple(u.values()))
    c.commit()
    c.close()


# ── La rentabilité n'est JAMAIS une porte ─────────────────────────────────

def test_une_paire_tres_rentable_mais_peu_mesuree_n_est_PAS_promue(base):
    """+8 € sur 25 trades : magnifique, et statistiquement muet.

    C'est LE test qui protège du DSR à 0,35. Si celui-ci tombe un jour parce
    qu'on a « amélioré » le critère, le système recommencera à promouvoir du
    bruit.
    """
    from backend.services import promotion_criteria as pc

    _push(base, n=25)
    _trade(base, pnl=8.0, n=25)

    r = pc.evaluer_candidat("WTI/USD", "admin_legacy")
    assert r["verdict"] != "PROMOUVOIR", "25 trades ne prouvent rien"
    assert r["rentabilite"]["decidable"] is False
    assert r["rentabilite"]["n_requis"] > 500


def test_la_rentabilite_est_RAPPORTEE_avec_le_N_qu_il_faudrait(base):
    """La calculer sans dire combien il en faudrait, c'est inviter à la croire."""
    from backend.services import promotion_criteria as pc

    _push(base, n=60)
    _trade(base, pnl=2.0, n=60)

    rent = pc.evaluer_candidat("WTI/USD", "admin_legacy")["rentabilite"]
    assert "pnl_total" in rent and "n" in rent and "n_requis" in rent
    assert rent["decidable"] is False, "60 trades restent trop peu"


def test_une_paire_PERDANTE_mais_mecaniquement_saine_n_est_pas_refusee_pour_ca(base):
    """Symétrique du premier : le critère ne juge pas non plus dans l'autre sens.

    Refuser sur une perte non significative serait la même erreur de méthode,
    et couperait des paires au hasard.
    """
    from backend.services import promotion_criteria as pc

    _push(base, n=60)
    _trade(base, pnl=-2.0, n=60)

    r = pc.evaluer_candidat("WTI/USD", "admin_legacy")
    assert "rentabilite" not in [p for p in r["portes"]], \
        "la rentabilité ne doit pas figurer parmi les portes"
    assert all(p != "ECHEC" or nom != "rentabilite"
               for nom, p in ((n, d["verdict"]) for n, d in r["portes"].items()))


# ── Porte 1 : mécanique ───────────────────────────────────────────────────

def test_en_attente_tant_que_l_echantillon_est_trop_petit(base):
    from backend.services import promotion_criteria as pc

    _push(base, n=5)
    _trade(base, n=5)
    r = pc.evaluer_candidat("WTI/USD", "admin_legacy")
    assert r["verdict"] == "EN_ATTENTE"
    assert r["portes"]["mecanique"]["verdict"] == "EN_ATTENTE"


def test_un_stop_NON_applique_chez_le_courtier_fait_echouer(base):
    """⛔ La porte la plus importante : une position nue sur le réel a déjà
    coûté −230 € le 24/08. On ne promeut pas un instrument qui en produit."""
    from backend.services import promotion_criteria as pc

    _push(base, n=24)
    _push(base, n=1, sl_applied=False)
    _trade(base, n=60)

    r = pc.evaluer_candidat("WTI/USD", "admin_legacy")
    assert r["portes"]["mecanique"]["verdict"] == "ECHEC"
    assert r["verdict"] == "REFUSER"


def test_des_ordres_refuses_par_le_courtier_font_echouer(base):
    """Symbole mal mappé, volume invalide : ça se voit au taux d'acceptation."""
    from backend.services import promotion_criteria as pc

    _push(base, n=15, ok=1)
    _push(base, n=10, ok=0)
    _trade(base, n=60)

    r = pc.evaluer_candidat("WTI/USD", "admin_legacy")
    assert r["portes"]["mecanique"]["verdict"] == "ECHEC"


# ── Porte 2 : coût ────────────────────────────────────────────────────────

def test_un_stop_trop_serre_rend_le_cout_prohibitif(base):
    """Le coût en R dépend de la DISTANCE AU STOP, pas du prix.

    Un stop à 0,02 % du prix fait exploser le coût relatif : c'est ce qui a
    tué le 5 min et les frais Kraken à 2,6× l'edge.
    """
    from backend.services import promotion_criteria as pc

    _push(base, n=60)
    _trade(base, n=60, entry=65.0, sl=64.987)  # stop à 0,02 %

    r = pc.evaluer_candidat("WTI/USD", "admin_legacy")
    assert r["portes"]["cout"]["verdict"] == "ECHEC"
    assert r["verdict"] == "REFUSER"


def test_un_stop_normal_passe_la_porte_de_cout(base):
    from backend.services import promotion_criteria as pc

    _push(base, n=60)
    _trade(base, n=60, entry=65.0, sl=64.6)  # stop à 0,62 %

    assert pc.evaluer_candidat("WTI/USD", "admin_legacy")["portes"]["cout"]["verdict"] == "OK"


# ── Le verdict d'ensemble ─────────────────────────────────────────────────

def test_toutes_les_portes_franchies_donne_PROMOUVOIR(base):
    from backend.services import promotion_criteria as pc

    _push(base, n=60)
    _trade(base, n=60, entry=65.0, sl=64.6, pnl=0.10)

    r = pc.evaluer_candidat("WTI/USD", "admin_legacy")
    assert r["verdict"] == "PROMOUVOIR", r["portes"]
    assert r["rentabilite"]["decidable"] is False, (
        "on promeut SANS avoir prouvé la rentabilité — et le rapport doit le dire")


def test_le_verdict_ne_regarde_que_la_destination_demandee(base):
    """Les trades du réel ne doivent pas valider un candidat de la démo."""
    from backend.services import promotion_criteria as pc

    _push(base, n=60, dest="admin_live")
    _trade(base, n=60, dest="admin_live")
    _push(base, n=3, dest="admin_legacy")
    _trade(base, n=3, dest="admin_legacy")

    assert pc.evaluer_candidat("WTI/USD", "admin_legacy")["verdict"] == "EN_ATTENTE"


def test_une_paire_inconnue_ne_plante_pas(base):
    from backend.services import promotion_criteria as pc

    r = pc.evaluer_candidat("INCONNUE/USD", "admin_legacy")
    assert r["verdict"] == "EN_ATTENTE"
    assert r["n_clotures"] == 0


# ── L'absence de trace n'est pas l'absence du stop ────────────────────────

def test_des_poussees_SANS_la_trace_du_stop_ne_condamnent_pas(base):
    """⛔ Le faux positif du 04/09, verrouillé.

    `sl_applied` n'existe dans les réponses du bridge que depuis le 06/08. Une
    première version lisait « champ absent » comme « stop non posé » et
    condamnait WTI/USD (0 poussée instrumentée sur 54) et XAU/USD (12 sur 63)
    — deux paires saines, dont une qui trade sur le compte RÉEL.
    """
    from backend.services import promotion_criteria as pc

    _push(base, n=40, instrumente=False)
    _trade(base, n=60)

    m = pc.evaluer_candidat("WTI/USD", "admin_legacy")["portes"]["mecanique"]
    assert m["verdict"] == "EN_ATTENTE", "non mesurable n'est pas fautif"
    assert m["poussees_instrumentees"] == 0


def test_un_stop_explicitement_FALSE_condamne_toujours(base):
    """Le correctif ne doit pas désarmer la porte qu'il assouplit."""
    from backend.services import promotion_criteria as pc

    _push(base, n=25)
    _push(base, n=1, sl_applied=False)
    _trade(base, n=60)

    m = pc.evaluer_candidat("WTI/USD", "admin_legacy")["portes"]["mecanique"]
    assert m["verdict"] == "ECHEC"
    assert m["stops_non_appliques"] == 1


def test_un_melange_ancien_recent_juge_sur_les_mesurables(base):
    """20 poussées instrumentées suffisent, même noyées dans de l'historique."""
    from backend.services import promotion_criteria as pc

    _push(base, n=30, instrumente=False)
    _push(base, n=22, instrumente=True)
    _trade(base, n=60)

    m = pc.evaluer_candidat("WTI/USD", "admin_legacy")["portes"]["mecanique"]
    assert m["verdict"] == "OK"
    assert m["poussees_instrumentees"] == 22
