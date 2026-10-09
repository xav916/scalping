"""Le bilan Telegram de la règle d'arrêt de l'or doit DIRE les trois jambes.

## ⛔ CE QUE CE TEST ÉPINGLE (2026-10-09)

L'adoption des positions du courtier (`ac2823b`) a fait entrer dans
`personal_trades` les trades que Xavier ouvre **dans le terminal MT5**. Séparés
par la seule `close_reason`, ceux fermés par leur stop tombaient dans la jambe
**AUTOMATIQUE** — celle qui borne l'expérience du radar :

    jambe "auto"  RADAR     n=48    −6,96 €
    jambe "auto"  TERMINAL  n= 7   −45,42 €   ← ses propres stops

**87 % de la « perte de l'automatique » étaient ses stops à lui**, et la règle a
franchi ses deux bornes le jour même du déploiement, par artefact.

🔑 `releve()` les sépare désormais par **qui a OUVERT**. Mais les sortir de la
borne ne doit pas les sortir du **message** : 45,42 € de stops réels effacés du
compte-rendu seraient une perte invisible. Le bilan porte donc trois lignes.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture()
def V():
    mod = importlib.import_module("scripts.veilleur_arret_or")
    return importlib.reload(mod)


def _m(**kw):
    base = {"ordres": 48, "pnl_auto": -6.96, "ordres_auto": 41,
            "pnl_main": 42.35, "ordres_main": 7,
            "pnl_terminal": -22.38, "ordres_terminal": 43,
            "sans_pnl": 0, "couverture": 1.0}
    base.update(kw)
    return base


def test_le_bilan_DIT_la_jambe_du_terminal(V):
    """⛔ Le défaut du 09/10 : ces 43 trades et leurs −22,38 € disparaissaient
    du bilan dès qu'on les sortait de la borne."""
    corps = V._corps_bilan(_m(), {"buy": "AUTO_EXEC"})

    assert "terminal" in corps.lower(), corps
    assert "-22.38" in corps or "−22,38" in corps, corps
    assert "43" in corps, corps


def test_le_bilan_dit_que_le_terminal_ne_BORNE_rien(V):
    """⚠️ Trois jambes dans un message, c'est trois lectures possibles. Celle
    qui compte doit être écrite : une seule borne l'expérience."""
    corps = V._corps_bilan(_m(), {})

    assert "hors borne" in corps.lower() or "ne borne" in corps.lower(), corps


def test_la_jambe_du_terminal_est_TUE_quand_elle_est_VIDE(V):
    """Pas de ligne à zéro : un bilan qui parle de ce qui n'existe pas se lit
    moins bien. Avant l'adoption, il n'y avait aucun trade du terminal."""
    corps = V._corps_bilan(_m(pnl_terminal=0.0, ordres_terminal=0), {})

    assert "terminal" not in corps.lower(), corps


def test_le_bilan_survit_a_un_releve_SANS_les_nouvelles_cles(V):
    """⚠️ Le `.py` est recopié par `docker cp` à chaque passage du cron : le
    veilleur et la règle peuvent être désynchronisés une fois. Un `KeyError`
    rendrait le bilan MUET, ce qui est pire qu'un bilan incomplet."""
    vieux = {"ordres": 10, "pnl_auto": -1.0, "ordres_auto": 5,
             "pnl_main": 2.0, "ordres_main": 3, "sans_pnl": 0,
             "couverture": 1.0}

    corps = V._corps_bilan(vieux, {})

    assert "Ordres" in corps
    assert "terminal" not in corps.lower()


def test_un_releve_absent_ne_conclut_sur_RIEN(V):
    """Trois états, jamais deux : « je n'ai pas pu regarder » n'est pas « rien
    à signaler »."""
    assert "indisponible" in V._corps_bilan(None, {}).lower()
