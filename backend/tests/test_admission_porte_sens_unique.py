"""La porte d'admission ne doit pas être à sens unique.

Constaté le 2026-08-06 : le garde-fou `PAC_MIN_REAL_TRADES` (30 trades RÉELS
avant toute décision automatique) rendait la promotion **insatisfaisable par
construction**. Seule une paire en `AUTO_EXEC` produit des trades réels ; une
paire `OBSERVED` ou `TELEGRAM` n'en produit aucun. Exiger cette preuve avant
d'accorder l'exécution garantissait qu'aucune paire ne serait plus jamais
promue — l'univers tradable ne pouvait que rétrécir (11 couples le 04/08, 8 le
05/08).

⚠️ Le garde-fou reste indispensable là où il protège : **ne jamais rétrograder**
une paire en argent réel sur un échantillon complété par du simulé. C'est le
chemin exact de l'incident du 04/08 (jusqu'à −251 % de capital sur un artefact
de déduplication).

La distinction verrouillée ici :
  « on ne sait pas »            (INDETERMINATE) → la paire peut monter
  « on sait que c'est mauvais » (OBSERVED réel) → la paire ne monte pas
"""
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import pair_admission_controller as pac


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(pac, "_DB_PATH", tmp_path / "trades.db", raising=False)
    pac._ensure_schema()
    return tmp_path


def _score(eligible, sample=40, n_real=0, pnl_pct=1.0):
    return {
        "eligible_for": eligible, "sample": sample, "n_real": n_real,
        "sum_pnl": 10.0, "pnl_pct": pnl_pct, "wr": 50.0, "pf": 1.5,
        "max_dd_pct": -1.0, "reason": "test", "pnl_source": "test",
    }


def _evaluer(monkeypatch, pair, direction, etat, score, depuis_jours=0,
             promotions_recentes=0):
    """`promotions_recentes` est neutralisé par défaut : sans ça les tests
    hériteraient du compteur de la base ambiante et deviendraient
    dépendants de l'historique local."""
    monkeypatch.setattr(pac, "_promotions_recentes_vers_auto_exec",
                        lambda *a, **k: promotions_recentes)
    monkeypatch.setattr(pac, "get_current_state", lambda *a, **k: etat)
    monkeypatch.setattr(pac, "compute_promotion_score", lambda *a, **k: score)
    since = (datetime.now(timezone.utc) - timedelta(days=depuis_jours)).isoformat()
    monkeypatch.setattr(pac, "get_full_state", lambda *a, **k: {"state_since": since})
    poses = []
    monkeypatch.setattr(pac, "set_state",
                        lambda *a, **k: poses.append((a, k)) or 1)
    res = pac.evaluate_pair(pair, direction=direction)
    return res, poses


# ── Premier étage : OBSERVED → TELEGRAM ───────────────────────────────

def test_indetermine_ne_bloque_plus_la_sortie_d_observed(monkeypatch):
    """LE blocage constaté. `TELEGRAM` n'engage aucun argent : le garde-fou
    n'y protège rien et n'y produisait que de la paralysie."""
    res, _ = _evaluer(monkeypatch, "ADA/USD", "buy", pac.STATE_OBSERVED,
                      _score(pac.STATE_INDETERMINATE, n_real=0))
    assert res["action"] == "transition"
    assert res["to_state"] == pac.STATE_TELEGRAM


def test_l_indetermine_ne_saute_jamais_directement_a_l_argent_reel(monkeypatch):
    """Garde-fou du correctif : l'indécidable monte d'UN cran, pas deux."""
    res, _ = _evaluer(monkeypatch, "ADA/USD", "buy", pac.STATE_OBSERVED,
                      _score(pac.STATE_INDETERMINATE))
    assert res["to_state"] != pac.STATE_AUTO_EXEC


def test_une_paire_jugee_mauvaise_sur_du_reel_ne_monte_pas(monkeypatch):
    """`OBSERVED` comme éligibilité veut dire « évaluée et insuffisante ».
    Elle ne doit pas bénéficier du correctif."""
    res, _ = _evaluer(monkeypatch, "ADA/USD", "buy", pac.STATE_OBSERVED,
                      _score(pac.STATE_OBSERVED, n_real=50))
    assert res["action"] == "keep"


# ── Second étage : TELEGRAM → AUTO_EXEC ───────────────────────────────

def test_indetermine_franchit_le_palier_vers_l_argent_reel(monkeypatch):
    """Corriger le seul premier étage aurait déplacé l'impasse d'un cran :
    TELEGRAM n'exécute pas non plus, donc n'accumule aucun trade réel."""
    res, _ = _evaluer(monkeypatch, "ADA/USD", "buy", pac.STATE_TELEGRAM,
                      _score(pac.STATE_INDETERMINATE), depuis_jours=30)
    assert res["action"] == "transition"
    assert res["to_state"] == pac.STATE_AUTO_EXEC


def test_le_palier_temporel_reste_obligatoire(monkeypatch):
    """Le correctif ne supprime pas la prudence : il supprime l'impossibilité.
    Une paire fraîchement arrivée en TELEGRAM attend toujours."""
    res, _ = _evaluer(monkeypatch, "ADA/USD", "buy", pac.STATE_TELEGRAM,
                      _score(pac.STATE_INDETERMINATE), depuis_jours=1)
    assert res["action"] == "keep"


def test_une_paire_jugee_mauvaise_ne_franchit_pas_le_palier(monkeypatch):
    res, _ = _evaluer(monkeypatch, "ADA/USD", "buy", pac.STATE_TELEGRAM,
                      _score(pac.STATE_OBSERVED, n_real=50), depuis_jours=30)
    assert res["to_state"] != pac.STATE_AUTO_EXEC


def test_le_drapeau_permet_de_retablir_l_ancien_comportement(monkeypatch):
    import config.settings
    monkeypatch.setattr(config.settings, "PAC_ALLOW_INDETERMINATE_PROMOTION", False)
    res, _ = _evaluer(monkeypatch, "ADA/USD", "buy", pac.STATE_TELEGRAM,
                      _score(pac.STATE_INDETERMINATE), depuis_jours=30)
    assert res["action"] == "keep"


# ── Ce que le correctif ne doit PAS toucher ───────────────────────────

def test_une_paire_en_argent_reel_n_est_jamais_retrogradee_sur_du_simule(monkeypatch):
    """L'incident du 04/08 : −251 % de capital, entièrement dû à un artefact
    de déduplication côté données simulées. Ce garde-fou reste intact."""
    res, _ = _evaluer(monkeypatch, "XAU/USD", "sell", pac.STATE_AUTO_EXEC,
                      _score(pac.STATE_INDETERMINATE, pnl_pct=-251.0))
    assert res["action"] == "keep"


def test_une_saignee_mesuree_sur_du_reel_pause_toujours(monkeypatch):
    """La rétrogradation sur perte RÉELLE doit continuer de fonctionner."""
    res, _ = _evaluer(monkeypatch, "XAU/USD", "sell", pac.STATE_AUTO_EXEC,
                      _score(pac.STATE_TELEGRAM, n_real=50, pnl_pct=-9.0))
    assert res["action"] == "transition"
    assert res["to_state"] == pac.STATE_PAUSED


# ── Le débit maximal vers l'argent réel ───────────────────────────────

def test_le_budget_hebdomadaire_met_en_file_d_attente(monkeypatch):
    """37 couples étaient bloqués en OBSERVED au moment du correctif. Sans
    débit, ils arriveraient tous à maturité le même jour : 11 → 47 couples en
    argent réel d'un coup. Réparer une porte ne doit pas revenir à l'arracher."""
    res, _ = _evaluer(monkeypatch, "ADA/USD", "buy", pac.STATE_TELEGRAM,
                      _score(pac.STATE_INDETERMINATE), depuis_jours=30,
                      promotions_recentes=2)
    assert res["action"] == "keep"
    assert "file d'attente" in res["reason"]


def test_sous_le_budget_la_promotion_passe(monkeypatch):
    res, _ = _evaluer(monkeypatch, "ADA/USD", "buy", pac.STATE_TELEGRAM,
                      _score(pac.STATE_INDETERMINATE), depuis_jours=30,
                      promotions_recentes=1)
    assert res["action"] == "transition"
    assert res["to_state"] == pac.STATE_AUTO_EXEC


def test_le_message_distingue_pas_mur_et_en_file(monkeypatch):
    """Une paire non mûre ne doit pas être annoncée comme « en file d'attente » :
    le diagnostic serait faux et enverrait chercher au mauvais endroit."""
    res, _ = _evaluer(monkeypatch, "ADA/USD", "buy", pac.STATE_TELEGRAM,
                      _score(pac.STATE_INDETERMINATE), depuis_jours=1,
                      promotions_recentes=99)
    assert res["action"] == "keep"
    assert "file d'attente" not in res["reason"]


def test_compteur_illisible_bloque_la_promotion(monkeypatch, tmp_path):
    """Fail-closed : sans compteur fiable on ne promeut pas. Une promotion de
    trop engage de l'argent ; une promotion retardée ne coûte rien."""
    monkeypatch.setattr(pac, "_DB_PATH", tmp_path, raising=False)  # un répertoire
    assert pac._promotions_recentes_vers_auto_exec() > 1000
