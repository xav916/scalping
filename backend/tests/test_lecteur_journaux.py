"""Le lecteur de journaux calcule ses chiffres lui-meme (2026-09-04).

Tout l'interet du module tient a une separation : `releve()` calcule, la
narration se contente de mettre en francais. Si `releve()` se trompe, le
bulletin ment avec l'autorite d'un chiffre — et personne n'ira verifier une
ligne qui ressemble a du SQL.

D'ou des tests qui portent sur la seule couche deterministe, et un test qui
verifie que la narration coupee ne retire rien aux faits.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import lecteur_journaux as lj


def _jour(decalage: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=decalage)).isoformat()


@pytest.fixture()
def base(tmp_path, monkeypatch):
    """trades.db temporaire avec les trois tables que le lecteur interroge."""
    import backend.services.trade_log_service as t

    chemin = tmp_path / "trades.db"
    monkeypatch.setattr(t, "_DB_PATH", chemin, raising=False)
    t._init_schema()  # personal_trades

    c = sqlite3.connect(chemin)
    c.execute(
        "CREATE TABLE signal_rejections (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "created_at TEXT NOT NULL, pair TEXT, direction TEXT, confidence REAL, "
        "reason_code TEXT NOT NULL, details TEXT)"
    )
    c.execute(
        "CREATE TABLE shadow_setups (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "detected_at TIMESTAMP, pair TEXT, outcome TEXT, "
        "geopolitical_features_json TEXT)"
    )
    c.commit()
    c.close()
    return chemin


def _rejet(chemin, code, decalage, details=None, pair="XAU/USD"):
    c = sqlite3.connect(chemin)
    c.execute(
        "INSERT INTO signal_rejections (created_at, pair, direction, reason_code, details) "
        "VALUES (?,?,?,?,?)",
        (f"{_jour(decalage)}T10:00:00+00:00", pair, "buy", code,
         json.dumps(details) if details else None),
    )
    c.commit()
    c.close()


def _shadow(chemin, decalage, would_veto=None, outcome=None, pair="BTC/USD", regles=None):
    geo = None
    if would_veto is not None:
        geo = json.dumps({
            "captured_at": f"{_jour(decalage)}T10:00:00+00:00",
            "veto_evaluated": {"would_veto": would_veto, "rules_matched": regles or []},
        })
    c = sqlite3.connect(chemin)
    c.execute(
        "INSERT INTO shadow_setups (detected_at, pair, outcome, geopolitical_features_json) "
        "VALUES (?,?,?,?)",
        (f"{_jour(decalage)} 10:00:00", pair, outcome, geo),
    )
    c.commit()
    c.close()


def _cloture(chemin, pair, decalage, n=1):
    c = sqlite3.connect(chemin)
    cols = {r[1] for r in c.execute("PRAGMA table_info(personal_trades)")}
    quand = f"{_jour(decalage)}T10:00:00+00:00"
    vals = {"user": "admin", "pair": pair, "direction": "buy", "entry_price": 1.0,
            "stop_loss": 0.9, "take_profit": 1.1, "size_lot": 0.01, "status": "CLOSED",
            "pnl": -1.0, "is_auto": 1, "created_at": quand, "closed_at": quand}
    u = {k: v for k, v in vals.items() if k in cols}
    for _ in range(n):
        c.execute(
            f"INSERT INTO personal_trades ({','.join(u)}) VALUES ({','.join('?' * len(u))})",
            tuple(u.values()),
        )
    c.commit()
    c.close()


# ─── Robustesse ──────────────────────────────────────────────────────────

def test_base_absente_ne_leve_pas(tmp_path, monkeypatch):
    """Aucune base : un releve vide, jamais une exception chez l'appelant."""
    import backend.services.trade_log_service as t
    monkeypatch.setattr(t, "_DB_PATH", tmp_path / "rien.db", raising=False)

    r = lj.releve(jours=7)
    assert r["rejets"]["total_courant"] == 0
    assert r["cadence"] == []


def test_details_illisible_ne_casse_pas_le_releve(base):
    """Un `details` non-JSON est ignore, le reste du releve tient."""
    c = sqlite3.connect(base)
    c.execute(
        "INSERT INTO signal_rejections (created_at, reason_code, details) VALUES (?,?,?)",
        (f"{_jour(0)}T10:00:00+00:00", "geopolitical_veto", "{ceci n'est pas du json"),
    )
    c.commit()
    c.close()

    r = lj.releve(jours=7)
    assert r["rejets"]["total_courant"] == 1
    assert all(x["jamais_tiree"] for x in r["regles_inertes"])


# ─── Rejets ──────────────────────────────────────────────────────────────

def test_rejets_separent_les_deux_fenetres(base):
    """Une fenetre glissante qui melangerait courant et precedent rendrait
    tout delta illisible — c'est le seul chiffre du bulletin qui parle de
    changement."""
    _rejet(base, "below_confidence", 0)
    _rejet(base, "below_confidence", -2)
    _rejet(base, "below_confidence", -8)   # fenetre precedente
    _rejet(base, "market_closed", -1)

    r = lj.releve(jours=7)
    assert r["rejets"]["total_courant"] == 3
    assert r["rejets"]["total_precedent"] == 1

    conf = next(x for x in r["rejets"]["par_code"] if x["code"] == "below_confidence")
    assert (conf["courant"], conf["precedent"], conf["delta"]) == (2, 1, 1)


# ─── Regles inertes ──────────────────────────────────────────────────────

def test_regle_qui_a_tire_est_datee_les_autres_sont_inertes(base):
    """Le cas gdelt_stress : la question n'est pas combien de fois une regle a
    tire, mais depuis quand elle ne tire plus."""
    _rejet(base, "geopolitical_veto", -3,
           details={"blockers": ["Geopolitical veto: [tariff] Tariff prob 70% a 5j"]})

    regles = {x["regle"]: x for x in lj.releve(jours=7)["regles_inertes"]}
    assert regles["tariff"]["jamais_tiree"] is False
    assert regles["tariff"]["jours_depuis"] == 3
    assert regles["gdelt_stress"]["jamais_tiree"] is True
    assert regles["gdelt_stress"]["dernier_tir"] is None


# ─── Contrefactuel ───────────────────────────────────────────────────────

def test_contrefactuel_compte_les_would_veto(base):
    """La mesure conservee le 2026-08-08 : combien de fois le veto AURAIT
    bloque. Un shadow sans snapshot ne compte pas dans le denominateur."""
    _shadow(base, -1, would_veto=True, regles=["gdelt_stress"])
    _shadow(base, -2, would_veto=False)
    _shadow(base, -3, would_veto=False)
    _shadow(base, -1, would_veto=None)  # sans snapshot : hors denominateur

    v = lj.releve(jours=7)["veto_contrefactuel"]
    assert v["disponible"] is True
    assert v["shadows_evalues"] == 3
    assert v["would_veto"] == 1
    assert v["taux"] == pytest.approx(1 / 3)
    assert v["par_regle"] == {"gdelt_stress": 1}


def test_contrefactuel_a_zero_quand_le_veto_ne_tire_jamais(base):
    """Taux nul = regle hors de portee d'une mesure. Le chiffre doit sortir
    a 0.0, pas a None : l'absence de tir est un resultat, pas une donnee
    manquante."""
    _shadow(base, -1, would_veto=False)
    _shadow(base, -2, would_veto=False)

    v = lj.releve(jours=7)["veto_contrefactuel"]
    assert v["shadows_evalues"] == 2
    assert v["taux"] == 0.0


# ─── Shadows en suspens ──────────────────────────────────────────────────

def test_shadow_non_resolu_au_dela_du_seuil_est_abandonne(base):
    _shadow(base, -20, would_veto=False, outcome=None)   # abandonne
    _shadow(base, -2, would_veto=False, outcome=None)    # encore vivant
    _shadow(base, -30, would_veto=False, outcome="TP1")  # resolu

    s = lj.releve(jours=7)["shadows_en_suspens"]
    assert s["total"] == 2
    assert s["abandonnes"] == 1


# ─── Cadence ─────────────────────────────────────────────────────────────

def test_cadence_donne_un_debit_et_un_delai(base):
    """7 clotures sur 7 jours ~ 30 par mois ; le delai restant se compte sur
    ce debit et sur le N declare dans promotion_criteria."""
    _cloture(base, "XAU/USD", -1, n=7)

    ligne = next(x for x in lj.releve(jours=7)["cadence"] if x["pair"] == "XAU/USD")
    assert ligne["clotures_fenetre"] == 7
    assert ligne["par_mois"] == pytest.approx(30.4, abs=0.1)
    assert ligne["n_requis"] == lj.N_REQUIS_EDGE
    # (700 - 7) / 30.4 ~ 22,8 mois
    assert ligne["mois_restants"] == pytest.approx(22.8, abs=0.3)


def test_cadence_sans_delai_quand_le_n_est_atteint(base, monkeypatch):
    monkeypatch.setattr(lj, "N_REQUIS_EDGE", 3, raising=False)
    _cloture(base, "WTI/USD", -1, n=5)

    ligne = next(x for x in lj.releve(jours=7)["cadence"] if x["pair"] == "WTI/USD")
    assert ligne["mois_restants"] == 0


# ─── Narration ───────────────────────────────────────────────────────────

def test_narration_coupee_ne_retire_rien_aux_faits(base, monkeypatch):
    """Le bulletin doit rester utile sans appel au modele : c'est ce qui
    garantit qu'aucun chiffre ne depend de lui."""
    monkeypatch.setattr(lj, "LECTEUR_NARRATION_ENABLED", False, raising=False)
    _rejet(base, "below_confidence", 0)

    b = asyncio.run(lj.bulletin(jours=7))
    assert b["narration"] is None
    assert b["rejets"]["total_courant"] == 1


def test_narration_sans_cle_ne_tente_pas_l_appel(base, monkeypatch):
    """Active mais sans cle : on retourne None sans lever ni appeler le reseau."""
    monkeypatch.setattr(lj, "LECTEUR_NARRATION_ENABLED", True, raising=False)
    monkeypatch.setattr(lj, "LECTEUR_NARRATION_API_KEY", "", raising=False)

    assert asyncio.run(lj.narration({"jours": 7})) is None


# ─── Bulletin ────────────────────────────────────────────────────────────

def test_bulletin_signale_les_regles_jamais_declenchees(base):
    """Le seul chiffre qui compte pour gdelt_stress est qu'il n'y en a pas."""
    texte = lj.texte_bulletin(lj.releve(jours=7))
    assert "Regles jamais declenchees" in texte
    assert "gdelt_stress" in texte


def test_bulletin_separe_la_narration_des_faits(base):
    """Le lecteur doit voir ou s'arrete ce que le modele a ecrit."""
    donnees = {**lj.releve(jours=7), "narration": "Rien de neuf cette semaine."}
    texte = lj.texte_bulletin(donnees)

    assert texte.index("Rien de neuf cette semaine.") < texte.index("— faits —")


def test_bulletin_vide_le_dit_plutot_que_de_meubler(base):
    texte = lj.texte_bulletin({"jours": 7})
    assert "Rien a signaler" in texte


def test_envoi_hebdomadaire_rend_le_resultat_de_telegram(base, monkeypatch):
    """Prouver qu'un message part ne prouve pas qu'il arrive — mais un envoi
    qui echoue doit au moins remonter False."""
    import sys
    import types

    envois = []

    faux = types.ModuleType("backend.services.telegram_service")

    async def send_infra_text(texte, parse_mode=None):
        envois.append(texte)
        return False

    faux.send_infra_text = send_infra_text
    monkeypatch.setitem(sys.modules, "backend.services.telegram_service", faux)
    # `from backend.services import telegram_service` lit l'ATTRIBUT du paquet
    # des qu'un autre module de test l'a importe : sys.modules seul ne suffit
    # pas, le vrai service repasserait devant (pollution croisee).
    import backend.services as _paquet_services
    monkeypatch.setattr(_paquet_services, "telegram_service", faux, raising=False)
    monkeypatch.setattr(lj, "LECTEUR_NARRATION_ENABLED", False, raising=False)
    _rejet(base, "below_confidence", 0)

    assert asyncio.run(lj.envoyer_bulletin_hebdomadaire(jours=7)) is False
    assert len(envois) == 1
    assert "Lecteur de journaux" in envois[0]
