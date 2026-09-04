"""Une paire peut servir PLUSIEURS horizons (2026-09-04).

`SHADOW_CONFIG` n'acceptait qu'un horizon par paire (`cfg["tf"]`). Les 12
paires de la whitelist démo y étaient déclarées en **4h** — celui que le compte
réel trade activement. Les passer en 1 jour aurait donc **remplacé** leur 4h,
et cassé le flux du réel.

D'où des horizons **supplémentaires**, additifs :

    "XAU/USD": {"tf": "4h", ..., "extras": [{"tf": "1d", ...}]}

⚠️ Le choix de garder `SHADOW_CONFIG` **keyé par paire** n'est pas cosmétique :
`SHADOW_PAIRS` en dérive et il est lu par cinq modules (`app`, `mt5_bridge`,
`pair_admission_controller`, `pair_pnl_regulator`, `scheduler`). Changer la
structure des clés les aurait tous touchés pour un besoin qui ne les concerne
pas.

⛔ Le piège de ce chantier : `shadow_setups` porte un `UNIQUE (system_id,
bar_timestamp)`. Deux horizons qui partageraient un `system_id` se
recouvriraient — l'insertion du second échouerait **en silence**, et on
croirait mesurer deux séries en n'en ayant qu'une.
"""
from __future__ import annotations

import pytest


@pytest.fixture()
def sh():
    from backend.services import shadow_v2_core_long as module
    return module


# ── L'horizon principal survit ────────────────────────────────────────────

def test_une_paire_sans_extras_garde_exactement_son_horizon(sh, monkeypatch):
    monkeypatch.setattr(sh, "SHADOW_CONFIG", {
        "XAU/USD": {"tf": "4h", "patterns": set(), "system_id": "A"},
    }, raising=False)

    assert [(p, c["tf"]) for p, c in sh._configs_par_horizon()] == [("XAU/USD", "4h")]


def test_les_extras_S_AJOUTENT_ils_ne_remplacent_pas(sh, monkeypatch):
    """⛔ Le point qui protège le 4h du compte réel."""
    monkeypatch.setattr(sh, "SHADOW_CONFIG", {
        "XAU/USD": {"tf": "4h", "patterns": set(), "system_id": "A",
                    "extras": [{"tf": "1d", "system_id": "A_1D"}]},
    }, raising=False)

    horizons = [c["tf"] for _, c in sh._configs_par_horizon()]
    assert horizons == ["4h", "1d"], "le 4h doit venir EN PREMIER et survivre"


def test_l_extra_herite_de_ce_qu_il_ne_declare_pas(sh, monkeypatch):
    """Motifs et risque suivent la paire, sauf mention contraire.

    Les redéclarer dans chaque extra garantirait qu'un des deux finisse par
    diverger — la leçon de `_assembler_setup` et de `source_du_setup`.
    """
    monkeypatch.setattr(sh, "SHADOW_CONFIG", {
        "XAU/USD": {"tf": "4h", "patterns": {"momentum_up"}, "system_id": "A",
                    "risk_pct": 0.005,
                    "extras": [{"tf": "1d", "system_id": "A_1D"}]},
    }, raising=False)

    _, extra = sh._configs_par_horizon()[1]
    assert extra["patterns"] == {"momentum_up"}
    assert extra["risk_pct"] == 0.005
    assert extra["system_id"] == "A_1D", "le system_id, lui, NE s'hérite pas"


def test_un_extra_peut_surcharger_le_risque(sh, monkeypatch):
    monkeypatch.setattr(sh, "SHADOW_CONFIG", {
        "XAU/USD": {"tf": "4h", "patterns": set(), "system_id": "A",
                    "risk_pct": 0.005,
                    "extras": [{"tf": "1d", "system_id": "A_1D", "risk_pct": 0.002}]},
    }, raising=False)

    assert sh._configs_par_horizon()[1][1]["risk_pct"] == 0.002


# ── Le piège du system_id partagé ─────────────────────────────────────────

def test_deux_horizons_ne_peuvent_PAS_partager_un_system_id(sh, monkeypatch):
    """⛔ `UNIQUE (system_id, bar_timestamp)` : le second serait perdu EN SILENCE.

    On croirait mesurer deux séries en n'en ayant qu'une — le genre de défaut
    qui ne se voit qu'en comptant les lignes des mois plus tard.
    """
    monkeypatch.setattr(sh, "SHADOW_CONFIG", {
        "XAU/USD": {"tf": "4h", "patterns": set(), "system_id": "MEME",
                    "extras": [{"tf": "1d", "system_id": "MEME"}]},
    }, raising=False)

    with pytest.raises(ValueError, match="system_id"):
        sh._configs_par_horizon()


def test_un_extra_SANS_system_id_est_refuse(sh, monkeypatch):
    monkeypatch.setattr(sh, "SHADOW_CONFIG", {
        "XAU/USD": {"tf": "4h", "patterns": set(), "system_id": "A",
                    "extras": [{"tf": "1d"}]},
    }, raising=False)

    with pytest.raises(ValueError, match="system_id"):
        sh._configs_par_horizon()


def test_le_system_id_doit_etre_unique_entre_PAIRES_aussi(sh, monkeypatch):
    monkeypatch.setattr(sh, "SHADOW_CONFIG", {
        "XAU/USD": {"tf": "4h", "patterns": set(), "system_id": "COLLISION"},
        "XAG/USD": {"tf": "4h", "patterns": set(), "system_id": "COLLISION"},
    }, raising=False)

    with pytest.raises(ValueError, match="system_id"):
        sh._configs_par_horizon()


# ── La configuration réelle ───────────────────────────────────────────────

def test_la_config_de_PROD_est_coherente(sh):
    """Le garde-fou s'applique à la vraie table, pas seulement aux fixtures."""
    configs = sh._configs_par_horizon()
    ids = [c["system_id"] for _, c in configs]
    assert len(ids) == len(set(ids)), "system_id dupliqué en configuration réelle"


def test_SHADOW_PAIRS_reste_une_liste_de_PAIRES(sh):
    """⚠️ Cinq modules en dépendent — la structure des clés ne bouge pas."""
    assert all(isinstance(p, str) and "/" in p or p.isupper()
               for p in sh.SHADOW_PAIRS)
    assert len(sh.SHADOW_PAIRS) == len(set(sh.SHADOW_PAIRS))
