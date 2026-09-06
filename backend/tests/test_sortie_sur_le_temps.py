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
