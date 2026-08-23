"""La porte de credibilite portait sur le MAUVAIS nombre (2026-08-23).

Le rapport hebdomadaire du 22/08 a crie `veto_would_help` en affichant
`n_total = 879` et « CREDIBLE — analyse statistique fiable ». La comparaison
ne reposait pourtant que sur les setups que le veto aurait **bloques** : ils
etaient **27**, sous le seuil de 30 que ce meme fichier definit deja.

> **Un groupe temoin de 879 ne rend pas credible un groupe traite de 27.**
> C'est le PLUS PETIT des deux qui borne ce qu'on peut conclure.

Contrôle aleatoire passe le 23/08 : ecart observe +1,297 %, **p = 0,087** —
un tirage de 27 setups au hasard fait aussi bien une fois sur onze. En
retirant quatre paires gagnant 100 % du temps (dans un systeme qui en gagne
48 %), l'ecart tombe a +0,338 %, p = 0,328.

⚠️ Le rapport et l'endpoint HTTP portaient CHACUN leur copie du verdict. Un
test par chemin ne suffit donc pas : on verifie ici qu'ils rendent le meme.
"""
from __future__ import annotations

import pytest

from scripts.research.track_a_veto_counterfactual import (
    N_MIN_DECISION,
    _sample_verdict,
    build_report,
    paires_invraisemblables,
    verdict_directionnel,
)


def _st(n, mean):
    return {"n": n, "mean_pnl_pct": mean, "n_tp": 0, "n_sl": 0,
            "n_timeout": 0, "win_rate": None, "pf": None, "total_pnl_pct": 0.0}


# --------------------------------------------------------------------------
# Le cas reel du 22/08
# --------------------------------------------------------------------------

def test_le_cas_du_22_08_ne_doit_PLUS_trancher():
    """27 bloques contre 852 temoins : aucun verdict directionnel."""
    code, phrase = verdict_directionnel(_st(27, -0.13), _st(852, 0.82))
    assert code == "insufficient", f"a tranche sur 27 observations : {phrase}"
    assert "27" in phrase and "INSUFFISANT" in phrase


def test_un_temoin_ENORME_ne_rachete_pas_un_groupe_traite_minuscule():
    """⛔ Le coeur de la faute. Un million de temoins n'y change rien."""
    code, _ = verdict_directionnel(_st(5, -3.0), _st(1_000_000, 2.0))
    assert code == "insufficient"


def test_la_confiance_se_lit_sur_le_groupe_decisif():
    assert "INSUFFISANT" in _sample_verdict(27)
    assert "CRÉDIBLE" in _sample_verdict(879)


# --------------------------------------------------------------------------
# La porte laisse passer ce qu'elle doit laisser passer
# --------------------------------------------------------------------------

def test_au_seuil_le_verdict_est_rendu():
    """Le seuil est inclusif : exactement 30 suffit."""
    code, _ = verdict_directionnel(_st(N_MIN_DECISION, -1.0), _st(500, 1.0))
    assert code == "veto_would_help"


def test_les_deux_directions_restent_possibles():
    aide, _ = verdict_directionnel(_st(50, -1.0), _st(500, 1.0))
    nuit, _ = verdict_directionnel(_st(50, 2.0), _st(500, 0.5))
    assert aide == "veto_would_help"
    assert nuit == "veto_would_hurt"


def test_ecart_negligeable_rend_neutre():
    code, _ = verdict_directionnel(_st(50, 1.00), _st(500, 1.02))
    assert code == "neutral"


def test_groupes_vides():
    assert verdict_directionnel(_st(0, None), _st(100, 1.0))[0] == "insufficient"
    assert verdict_directionnel(_st(100, 1.0), _st(0, None))[0] == "insufficient"


# --------------------------------------------------------------------------
# Les paires invraisemblables sont SIGNALEES, jamais retirees
# --------------------------------------------------------------------------

def _setup(pair, pnl):
    return {"pair": pair, "pnl_pct_net": pnl, "would_veto": False,
            "rules_matched": [], "outcome": "TP1" if pnl > 0 else "SL"}


def test_une_paire_qui_gagne_TOUJOURS_est_signalee():
    setups = ([_setup("LINK/USD", 14.5) for _ in range(18)]
              + [_setup("EUR/USD", 0.1) for _ in range(10)]
              + [_setup("EUR/USD", -0.1) for _ in range(10)])
    louches = paires_invraisemblables(setups)
    assert [p for p, _, _ in louches] == ["LINK/USD"]


def test_une_paire_normale_n_est_PAS_signalee():
    setups = ([_setup("EUR/USD", 1.0)] * 10) + ([_setup("EUR/USD", -1.0)] * 10)
    assert paires_invraisemblables(setups) == []


def test_trop_peu_de_setups_pour_conclure_a_l_artefact():
    """3 gagnants d'affilee n'ont rien d'anormal."""
    assert paires_invraisemblables([_setup("BTC/USD", 1.0)] * 3) == []


def test_le_rapport_AFFICHE_l_avertissement_sans_retirer_les_donnees(monkeypatch):
    """⚠️ Ecarter des donnees revient a l'humain, pas au script.

    Le rapport doit donc citer la paire douteuse ET continuer a la compter.
    """
    from datetime import datetime, timezone
    setups = ([_setup("LINK/USD", 14.5) for _ in range(18)]
              + [_setup("EUR/USD", -0.1) for _ in range(40)])
    for s in setups[:5]:
        s["would_veto"] = True
    md = build_report(setups, datetime(2026, 8, 23, tzinfo=timezone.utc))
    assert "invraisemblable" in md.lower()
    assert "LINK/USD" in md
    assert "conservées" in md, "le rapport doit dire qu'il n'a RIEN retire"
    assert "58 setups réconciliés" in md, "les donnees douteuses restent comptees"


def test_le_rapport_du_22_08_n_affiche_plus_LE_VETO_AURAIT_AIDE():
    """Bout en bout : la phrase qui a declenche l'alerte doit disparaitre."""
    from datetime import datetime, timezone
    setups = ([_setup("XAU/USD", -0.13) for _ in range(27)]
              + [_setup("EUR/USD", 0.82) for _ in range(852)])
    for s in setups[:27]:
        s["would_veto"] = True
    md = build_report(setups, datetime(2026, 8, 23, tzinfo=timezone.utc))
    assert "LE VETO AURAIT AIDÉ" not in md
    assert "INSUFFISANT POUR TRANCHER" in md
    assert "CRÉDIBLE" not in md, "la confiance se lit sur les 27, pas sur 879"
