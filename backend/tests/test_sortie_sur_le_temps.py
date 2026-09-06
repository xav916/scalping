"""Sortie sur le temps — livrée désarmée, et limitée au démo (2026-09-06).

⛔ Deux mesures pointent en sens opposés, et la plus lourde dit NON :

```
porte de durée 16 h, contrefactuel du 13/08   n=5690   Δ=−0,151 R   t=−6,83
sorties manuelles rejouées, 06/09             n=  21   Δ=+0,660 R   t=+2,27
```

⚠️ Et la mesure du 06/09 dit elle-même que le temps n'est pas le bon critère :
les trades qui auraient fini au stop ont été coupés à 2,6 h de médiane, ceux qui
auraient fini à l'objectif à 10,2 h. **La main a coupé les perdants plus tôt que
les gagnants — un couperet à N heures ne distingue pas.**

Ce que ces tests verrouillent :
  - désarmé par défaut, et `[RÉEL · IC_MARKETS]` hors périmètre par défaut ;
  - une ouverture indatable n'est JAMAIS coupée ;
  - le mode observation ne ferme rien, il journalise ;
  - une fermeture qui échoue ne se compte pas comme faite.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.services import sortie_sur_le_temps as st

MAINTENANT = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)


def _pos(heures, symbol="EURUSD", ticket=1):
    return {"symbol": symbol, "ticket": ticket,
            "fill_time": (MAINTENANT - timedelta(hours=heures)).isoformat()}


def _cfg(actif=True, observer=False, heures=16.0, dests=("admin_legacy",)):
    return {"actif": actif, "observer": observer, "heures": heures,
            "destinations": frozenset(dests)}


# ── ⛔ Les défauts, qui sont le cœur du sujet ─────────────────────────

def test_DESARME_par_defaut(monkeypatch):
    monkeypatch.delenv("SORTIE_TEMPS_ENABLED", raising=False)
    assert st.reglages()["actif"] is False


def test_le_REEL_n_est_PAS_dans_le_perimetre_par_defaut(monkeypatch):
    """⛔ Stratégie du 06/09 : stops manuels sur l'argent réel tant que
    l'automatique n'est pas gagnant sur le démo."""
    monkeypatch.delenv("SORTIE_TEMPS_DESTINATIONS", raising=False)
    d = st.reglages()["destinations"]
    assert "admin_legacy" in d
    assert "admin_live" not in d
    assert "admin_kraken" not in d


def test_OBSERVATION_par_defaut(monkeypatch):
    monkeypatch.delenv("SORTIE_TEMPS_OBSERVER", raising=False)
    assert st.reglages()["observer"] is True


def test_desarme_rien_n_est_eligible():
    ok, motif = st.eligible(_pos(99), "admin_legacy", _cfg(actif=False), MAINTENANT)
    assert ok is False and "désarmée" in motif


def test_destination_hors_perimetre_refuse():
    ok, motif = st.eligible(_pos(99), "admin_live", _cfg(), MAINTENANT)
    assert ok is False and "périmètre" in motif


# ── L'âge ────────────────────────────────────────────────────────────

def test_au_dela_du_seuil_est_eligible():
    ok, _ = st.eligible(_pos(20), "admin_legacy", _cfg(heures=16), MAINTENANT)
    assert ok is True


def test_sous_le_seuil_ne_l_est_pas():
    ok, motif = st.eligible(_pos(10), "admin_legacy", _cfg(heures=16), MAINTENANT)
    assert ok is False and "seuil" in motif


def test_PILE_au_seuil_est_eligible():
    ok, _ = st.eligible(_pos(16), "admin_legacy", _cfg(heures=16), MAINTENANT)
    assert ok is True


def test_ouverture_INDATABLE_n_est_jamais_coupee():
    """⛔ Le sens sur lequel se tromper : côté MT5, un décalage d'heure serveur
    faisait passer des positions pour plus vieilles qu'elles n'étaient."""
    for mauvais in ({"symbol": "X"},
                    {"symbol": "X", "fill_time": None},
                    {"symbol": "X", "fill_time": "pas une date"}):
        ok, motif = st.eligible(mauvais, "admin_legacy", _cfg(), MAINTENANT)
        assert ok is False, mauvais
        assert "indatable" in motif


def test_l_epoque_unix_est_datable_donc_ELIGIBLE():
    """⚠️ Nuance assumée : `1970-01-01` EST une date, et très ancienne. C'est
    au lecteur des positions de ne pas la servir — le bridge Kraken la
    remplaçait par `None` le 05/09 pour cette raison même. Ici on ne devine
    pas : une date lisible est traitée comme telle."""
    ok, _ = st.eligible({"symbol": "X", "fill_time": "1970-01-01T00:00:00Z"},
                        "admin_legacy", _cfg(), MAINTENANT)
    assert ok is True


def test_age_indatable_rend_None():
    assert st._age_heures(None) is None
    assert st._age_heures("n importe quoi") is None


# ── Le passage ───────────────────────────────────────────────────────

def test_observation_ne_ferme_RIEN():
    ferme = []
    r = st.passer([_pos(20), _pos(30, "GBPUSD", 2)], "admin_legacy",
                  fermer=lambda p: ferme.append(p), cfg=_cfg(observer=True),
                  maintenant=MAINTENANT)
    assert ferme == [], "le mode observation ne doit rien fermer"
    assert len(r["observees"]) == 2
    assert r["fermees"] == []
    assert r["mode"] == "observation"


def test_mode_actif_ferme():
    ferme = []
    r = st.passer([_pos(20)], "admin_legacy",
                  fermer=lambda p: ferme.append(p) or {"ok": True},
                  cfg=_cfg(observer=False), maintenant=MAINTENANT)
    assert len(ferme) == 1
    assert len(r["fermees"]) == 1
    assert r["mode"] == "ACTIF"


def test_sans_fonction_de_fermeture_on_OBSERVE():
    """Un appelant qui ne fournit pas de quoi fermer ne doit pas croire qu'il
    a ferme."""
    r = st.passer([_pos(20)], "admin_legacy", fermer=None,
                  cfg=_cfg(observer=False), maintenant=MAINTENANT)
    assert r["fermees"] == [] and len(r["observees"]) == 1


def test_une_fermeture_qui_ECHOUE_est_signalee():
    """⛔ Elle ne se compte pas comme faite : la position reste ouverte."""
    def _casse(p):
        raise RuntimeError("courtier injoignable")

    r = st.passer([_pos(20)], "admin_legacy", fermer=_casse,
                  cfg=_cfg(observer=False), maintenant=MAINTENANT)
    assert len(r["fermees"]) == 1
    assert "erreur" in r["fermees"][0]


def test_les_positions_JEUNES_sont_comptees_a_part():
    r = st.passer([_pos(2), _pos(20)], "admin_legacy", fermer=lambda p: None,
                  cfg=_cfg(observer=True), maintenant=MAINTENANT)
    assert r["ignorees"] == 1
    assert len(r["observees"]) == 1


def test_une_liste_vide_ne_plante_pas():
    r = st.passer([], "admin_legacy", cfg=_cfg(), maintenant=MAINTENANT)
    assert r["observees"] == [] and r["ignorees"] == 0


# ── Le rejeu apparié ─────────────────────────────────────────────────
#
# 🔑 L'intérêt d'observer plutôt que de couper, sur le démo : chaque trade
# fournit LES DEUX résultats — celui obtenu et celui qu'il aurait eu. La
# comparaison est appariée, la variance entre trades s'annule, et le verdict
# arrive avec bien moins d'observations que deux périodes séparées.

import sqlite3


def _base(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "_DB", tmp_path / "t.db")
    st.init_schema()
    return tmp_path / "t.db"


def test_r_au_prix_achat_et_vente():
    assert st.r_au_prix(100, 105, 95, achat=True) == pytest.approx(1.0)
    assert st.r_au_prix(100, 95, 105, achat=False) == pytest.approx(1.0)


def test_r_au_prix_risque_nul_rend_None():
    assert st.r_au_prix(100, 105, 100, achat=True) is None


def test_une_position_n_est_observee_QU_UNE_FOIS(tmp_path, monkeypatch):
    """⛔ La règle repasse toutes les 30 min. Sans unicité par ticket, une
    position tenue trois jours pèserait 144 fois dans la mesure."""
    _base(tmp_path, monkeypatch)
    p = {"ticket": 42, "symbol": "EURUSD", "type": "buy",
         "price_open": 1.0, "price_current": 1.005, "sl": 0.99}
    assert st.enregistrer_observation(p, "admin_legacy", _cfg(), 20.0) is True
    assert st.enregistrer_observation(p, "admin_legacy", _cfg(), 25.0) is False
    c = sqlite3.connect(str(tmp_path / "t.db"))
    assert c.execute("SELECT COUNT(*) FROM observations_sortie_temps").fetchone()[0] == 1
    c.close()


def test_l_observation_fige_le_R_du_MOMENT(tmp_path, monkeypatch):
    _base(tmp_path, monkeypatch)
    st.enregistrer_observation(
        {"ticket": 7, "symbol": "X", "type": "buy",
         "price_open": 100.0, "price_current": 102.0, "sl": 95.0},
        "admin_legacy", _cfg(), 20.0)
    c = sqlite3.connect(str(tmp_path / "t.db"))
    r = c.execute("SELECT r_si_coupe FROM observations_sortie_temps").fetchone()[0]
    c.close()
    assert r == pytest.approx(2.0 / 5.0)      # +0,4 R


def test_une_position_ENCORE_OUVERTE_n_est_pas_resolue(tmp_path, monkeypatch):
    _base(tmp_path, monkeypatch)
    st.enregistrer_observation(
        {"ticket": 7, "symbol": "X", "type": "buy", "price_open": 100.0,
         "price_current": 102.0, "sl": 95.0}, "admin_legacy", _cfg(), 20.0)
    assert st.resoudre_observations(trades_fermes={}) == 0


def test_la_resolution_calcule_le_R_REEL(tmp_path, monkeypatch):
    _base(tmp_path, monkeypatch)
    st.enregistrer_observation(
        {"ticket": 7, "symbol": "X", "type": "buy", "price_open": 100.0,
         "price_current": 102.0, "sl": 95.0}, "admin_legacy", _cfg(), 20.0)
    # finalement fermee a 95 : le stop, soit -1 R
    assert st.resoudre_observations(trades_fermes={7: (95.0,)}) == 1
    b = st.bilan_apparie("admin_legacy")
    assert b["n"] == 1
    assert b["r_si_coupe_moyen"] == pytest.approx(0.4)
    assert b["r_reel_moyen"] == pytest.approx(-1.0)
    assert b["ecart_moyen"] == pytest.approx(1.4)


def test_aucune_observation_resolue_le_DIT(tmp_path, monkeypatch):
    """⛔ « Pas encore de verdict » n'est pas « pas d'écart »."""
    _base(tmp_path, monkeypatch)
    assert "ouverte" in st.bilan_apparie("admin_legacy")["verdict"]


def test_le_verdict_reste_PRUDENT_sous_le_seuil(tmp_path, monkeypatch):
    """Un écart non significatif se dit « indistinguable », jamais « ça marche »."""
    _base(tmp_path, monkeypatch)
    c = sqlite3.connect(str(tmp_path / "t.db"), isolation_level=None)
    for i, (a, b) in enumerate([(0.4, 0.3), (0.1, 0.5), (0.6, 0.2), (-0.2, 0.4)]):
        c.execute("""INSERT INTO observations_sortie_temps
            (ticket,destination_id,symbol,observe_a,seuil_h,r_si_coupe,r_reel)
            VALUES (?,?,?,?,?,?,?)""", (i, "admin_legacy", "X", "t", 16.0, a, b))
    c.close()
    v = st.bilan_apparie("admin_legacy")["verdict"]
    assert v == "indistinguable du hasard"


# ── La sonde de santé ────────────────────────────────────────────────
#
# ⛔ Une sonde ne se teste pas sur « est-ce que ça tourne » : il faut nommer les
# façons dont la mesure meurt SANS BRUIT. Trois ici — la règle ne passe plus,
# les observations ne se résolvent jamais, la portée a dérivé vers le réel.

def test_sonde_saine_quand_tout_va(tmp_path, monkeypatch):
    _base(tmp_path, monkeypatch)
    monkeypatch.setenv("SORTIE_TEMPS_ENABLED", "true")
    monkeypatch.setenv("SORTIE_TEMPS_OBSERVER", "true")
    monkeypatch.setenv("SORTIE_TEMPS_DESTINATIONS", "admin_legacy")
    s = st.sante(positions_ouvertes=[])
    assert s["ok"] is True and s["alertes"] == []


def test_ALERTE_si_un_compte_REEL_entre_dans_le_perimetre(tmp_path, monkeypatch):
    """⛔ Le seul point qui justifie de crier : la règle fermerait de l'argent
    réel."""
    _base(tmp_path, monkeypatch)
    monkeypatch.setenv("SORTIE_TEMPS_DESTINATIONS", "admin_legacy,admin_live")
    s = st.sante(positions_ouvertes=[])
    assert s["ok"] is False
    assert any("PERIMETRE" in a for a in s["alertes"])


def test_ALERTE_si_le_mode_observation_tombe(tmp_path, monkeypatch):
    _base(tmp_path, monkeypatch)
    monkeypatch.setenv("SORTIE_TEMPS_ENABLED", "true")
    monkeypatch.setenv("SORTIE_TEMPS_OBSERVER", "false")
    s = st.sante(positions_ouvertes=[])
    assert any("MODE" in a for a in s["alertes"])


def test_ALERTE_si_MUETTE_alors_que_des_positions_sont_eligibles(tmp_path, monkeypatch):
    """⛔ Le silence se lit « rien à observer », alors qu'il veut dire
    « personne ne regarde »."""
    _base(tmp_path, monkeypatch)
    monkeypatch.setenv("SORTIE_TEMPS_ENABLED", "true")
    monkeypatch.setenv("SORTIE_TEMPS_DESTINATIONS", "admin_legacy")
    from datetime import datetime, timedelta, timezone
    vieille = {"symbol": "X", "ticket": 1,
               "fill_time": (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat()}
    s = st.sante(positions_ouvertes=[vieille])
    assert any("MUETTE" in a for a in s["alertes"])


def test_ALERTE_si_les_observations_ne_se_resolvent_JAMAIS(tmp_path, monkeypatch):
    """La jointure a cassé le jour même : `mt5_ticket` et non `ticket`."""
    base = _base(tmp_path, monkeypatch)
    monkeypatch.setenv("SORTIE_TEMPS_DESTINATIONS", "admin_legacy")
    c = sqlite3.connect(str(base), isolation_level=None)
    for i in range(12):
        c.execute("""INSERT INTO observations_sortie_temps
            (ticket,destination_id,symbol,observe_a,seuil_h,r_si_coupe)
            VALUES (?,?,?,?,?,?)""", (i, "admin_legacy", "X", "2026-09-06", 16.0, 0.2))
    c.close()
    s = st.sante(positions_ouvertes=[])
    assert any("BLOQUEE" in a for a in s["alertes"])


def test_la_sonde_RAPPELLE_le_seuil_de_preuve(tmp_path, monkeypatch):
    """⚠️ Un verdict sans son seuil invite à conclure trop vite."""
    base = _base(tmp_path, monkeypatch)
    monkeypatch.setenv("SORTIE_TEMPS_DESTINATIONS", "admin_legacy")
    c = sqlite3.connect(str(base), isolation_level=None)
    for i, (a, b) in enumerate([(0.4, -1.0), (0.5, 1.8), (0.3, -1.0)]):
        c.execute("""INSERT INTO observations_sortie_temps
            (ticket,destination_id,symbol,observe_a,seuil_h,r_si_coupe,r_reel)
            VALUES (?,?,?,?,?,?,?)""", (i, "admin_legacy", "X", "2026-09-06", 16.0, a, b))
    c.close()
    s = st.sante(positions_ouvertes=[])
    assert any("5690" in i for i in s["infos"])
