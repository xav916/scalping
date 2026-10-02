"""Un refus du banc d'essai ne doit pas emporter le backfill des 42 autres paires.

⛔ **Le constat du 2026-10-02**, lu dans les journaux de production :

    [ERROR] pair_admission_controller: startup hook failed (non-fatal)
    PermissionError: banc d'essai : aucun essai passe ne couvre
                     AVAX/USD/tous sens@TOUTES destinations (donc l'argent reel)

🔑 **La porte a RAISON.** `gate_promotion` ne s'interpose que sur
`new_state == AUTO_EXEC` touchant de l'argent reel. `AVAX/USD` est une *star*
non mise en pause : le backfill la vise donc en AUTO_EXEC avec
`destination=None`, c'est-a-dire TOUTES les destinations, l'argent reel inclus.
Aucun essai ne la couvre, le banc refuse. C'est exactement ce pour quoi il a
ete construit.

⛔ **Le defaut est la BOUCLE.** `for pair in sorted(universe)` n'a aucun
`try` par paire : le refus legitime de la 6e paire sur 48 abandonne le
backfill des **42 suivantes**. Mesure en production : 6 paires sans aucune
ligne d'admission — AVAX, DASH, INJ, SUI, TAO, ZEC — toutes *stars*, toutes
derriere AVAX dans l'ordre alphabetique.

> Un refus BRUYANT ne doit pas produire une panne SILENCIEUSE ailleurs.

⚠️ Pas dangereux aujourd'hui : une paire sans ligne vaut `OBSERVED`, donc
aucune auto-execution — verifie. Mais le backfill est **durablement tronque** :
il ne peut plus jamais poser l'etat initial de quoi que ce soit situe apres
AVAX, et une paire ajoutee demain a `WATCHED_PAIRS` n'en aurait aucun, pour
une seule ligne d'ERROR au demarrage.

⛔ Ce que ce correctif ne fait PAS : promouvoir les paires refusees. Elles
restent sans ligne, le banc tient. Il les saute, il ne les blanchit pas.
"""
from __future__ import annotations

import logging

import pytest

from backend.services import pair_admission_controller as pac


QUATRE = ["AAA/USD", "BBB/USD", "CCC/USD", "DDD/USD"]


@pytest.fixture
def base(tmp_path, monkeypatch):
    """Base vierge, univers de quatre paires, toutes *stars*.

    ⛔ **Elles doivent etre STARS**, et mon premier montage l'ignorait. Une
    paire non-star est backfillee vers `OBSERVED` — qui est DEJA la valeur par
    defaut d'une paire sans ligne : `set_state` est idempotent et ne pose rien.
    Le test rendait donc `applied == 0` et ne prouvait rien.

    Les paires reellement refusees en production (AVAX, DASH, INJ, SUI, TAO,
    ZEC) sont des stars visees en AUTO_EXEC. Le montage reproduit cela.
    """
    monkeypatch.setattr(pac, "_db_path", lambda: str(tmp_path / "trades.db"))
    # ⛔ `_SCHEMA_ENSURED` est un drapeau GLOBAL : sans ce reset, le premier
    # test cree le schema dans SA base, le drapeau reste vrai, et les suivants
    # pointent sur une base neuve sans table — « no such table ». Mes quatre
    # tests passaient en isolation et echouaient en lot pour cette seule
    # raison. `test_pair_admission_controller` fait le meme reset.
    monkeypatch.setattr(pac, "_SCHEMA_ENSURED", False)
    monkeypatch.setattr("config.settings.WATCHED_PAIRS", [], raising=False)
    monkeypatch.setattr(
        "backend.services.shadow_v2_core_long.SHADOW_PAIRS", list(QUATRE),
        raising=False)
    monkeypatch.setattr("backend.services.pair_pnl_regulator.is_paused",
                        lambda pair: False)
    return tmp_path


def _refuse(pairs_refusees):
    """Double du banc : refuse les paires nommees, laisse passer les autres."""
    def _gate(pair, new_state, direction=None, destination=None,
              transitioned_by="auto"):
        if pair in pairs_refusees:
            return False, "aucun essai passé ne couvre %s" % pair
        return True, "ok"
    return _gate


def test_le_backfill_CONTINUE_apres_un_refus(base, monkeypatch):
    """⛔ Le cœur : la 2e paire est refusee, les 3 autres doivent passer."""
    monkeypatch.setattr("backend.services.research_bench.gate_promotion",
                        _refuse({"BBB/USD"}))
    res = pac.backfill_initial_states()
    posees = {t["pair"] for t in res["transitions"]}
    assert "AAA/USD" in posees
    assert "CCC/USD" in posees, "le backfill s'est arrete au refus"
    assert "DDD/USD" in posees, "le backfill s'est arrete au refus"


def test_la_paire_REFUSEE_ne_recoit_aucune_ligne(base, monkeypatch):
    """⛔ Le banc tient : sauter n'est pas blanchir."""
    monkeypatch.setattr("backend.services.research_bench.gate_promotion",
                        _refuse({"BBB/USD"}))
    pac.backfill_initial_states()
    assert pac.get_current_state("BBB/USD") == pac.STATE_OBSERVED
    import sqlite3
    with sqlite3.connect(pac._db_path()) as c:
        lignes = c.execute(
            "SELECT 1 FROM pair_admission_state WHERE pair = ?",
            ("BBB/USD",)).fetchall()
    assert lignes == [], "une ligne a ete posee pour une paire refusee"


def test_les_refus_sont_COMPTES_et_nommes(base, monkeypatch, caplog):
    """⚠️ Un refus saute doit se lire : sinon il devient invisible."""
    monkeypatch.setattr("backend.services.research_bench.gate_promotion",
                        _refuse({"BBB/USD", "CCC/USD"}))
    with caplog.at_level(logging.WARNING):
        res = pac.backfill_initial_states()
    assert res.get("refuses") == 2, res
    assert set(res.get("paires_refusees") or []) == {"BBB/USD", "CCC/USD"}
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "BBB/USD" in messages and "CCC/USD" in messages


def test_aucun_refus_laisse_le_resultat_inchange(base, monkeypatch):
    """Le chemin nominal ne gagne pas de bruit."""
    monkeypatch.setattr("backend.services.research_bench.gate_promotion",
                        _refuse(set()))
    res = pac.backfill_initial_states()
    assert res["refuses"] == 0
    assert res["paires_refusees"] == []
    assert res["applied"] > 0


def test_une_VRAIE_erreur_remonte_toujours(base, monkeypatch):
    """⛔ On n'avale que le refus du banc. Un defaut reste un defaut.

    Sans cette borne, le `except` deviendrait un tapis sous lequel n'importe
    quelle panne de base disparaitrait — en rendant un backfill qui a l'air
    d'avoir reussi.
    """
    def _explose(pair, new_state, direction=None, destination=None,
                 transitioned_by="auto"):
        raise RuntimeError("base illisible")
    monkeypatch.setattr("backend.services.research_bench.gate_promotion",
                        _explose)
    with pytest.raises(RuntimeError):
        pac.backfill_initial_states()
