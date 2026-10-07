"""Le solde d'ouverture doit SURVIVRE a un redemarrage du pont.

⛔ **Mesure du 2026-10-07, 12h00 UTC.** Juste avant un redeploiement, le pont
du compte REEL refusait les ordres sur son propre plafond :

    "Daily drawdown reached: loss=19.77 >= limit=17.87 (3.0% of 595.81)"

Apres le redemarrage, le meme `/health` publiait :

    daily_loss 1.49   daily_loss_limit 17.31   (3.0% of 576.95)

**Les 19,77 EUR perdus dans la journee avaient disparu de sa vue.**
`_start_of_day_balance` ne vivait qu'en memoire : au demarrage,
`_start_of_day_date != today` et le pont prenait le solde du MOMENT comme solde
d'ouverture. Le plafond journalier du compte reel etait donc desarme jusqu'a
minuit — et il l'etait a CHAQUE redemarrage, silencieusement, depuis toujours.

> Un garde-fou qu'un redemarrage remet a zero n'est pas un garde-fou
> journalier : c'est un garde-fou depuis le dernier redemarrage.

🔑 Le fichier est relu **seulement si sa date est celle du jour** : un solde de
la veille ne doit jamais ressusciter. Et la lecture comme l'ecriture sont
best-effort — un fichier illisible rend le comportement d'avant, jamais une
exception sur le chemin d'un ordre reel.
"""
from __future__ import annotations

import json
import types
from datetime import date, timedelta
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "mt5-bridge" / "bridge.py"


class _Info:
    def __init__(self, balance):
        self.balance = balance
        self.equity = balance


def _module(tmp_path, balance=576.95, fichier="solde.json"):
    """`_refresh_start_of_day()` et ses deux aides, extraites du source reel."""
    src = _SRC.read_text(encoding="utf-8")
    mod = types.ModuleType("bridge_solde")
    mod.__dict__.update({
        "os": __import__("os"), "json": json, "date": date,
        "__file__": str(tmp_path / "bridge.py"),
        "logger": types.SimpleNamespace(info=lambda *a, **k: None,
                                        warning=lambda *a, **k: None),
        "mt5": types.SimpleNamespace(account_info=lambda: _Info(balance)),
        "_start_of_day_balance": None,
        "_start_of_day_date": None,
    })
    bout = src[src.index("def _lire_solde_du_jour("):src.index("def _flottant_exclu(")]
    exec(compile(bout, str(_SRC), "exec"), mod.__dict__)
    mod.__dict__["_FICHIER_SOLDE_JOUR"] = str(tmp_path / fichier)
    return mod


def test_le_premier_calcul_du_jour_ECRIT_le_solde(tmp_path):
    m = _module(tmp_path, balance=595.81)
    m._refresh_start_of_day()
    assert m._start_of_day_balance == 595.81
    ecrit = json.loads((tmp_path / "solde.json").read_text())
    assert ecrit == {"date": date.today().isoformat(), "balance": 595.81}


def test_un_REDEMARRAGE_le_meme_jour_retrouve_le_solde_d_ouverture(tmp_path):
    """⛔ Le defaut du 07/10 : le pont reprenait 576,95 au lieu de 595,81,
    effacant 19,77 EUR de perte."""
    (tmp_path / "solde.json").write_text(json.dumps(
        {"date": date.today().isoformat(), "balance": 595.81}))

    m = _module(tmp_path, balance=576.95)   # process NEUF, solde deja entame
    m._refresh_start_of_day()

    assert m._start_of_day_balance == 595.81
    # la perte du jour reste donc visible : 595,81 - 576,95 = 18,86
    assert round(m._start_of_day_balance - 576.95, 2) == 18.86


def test_un_solde_de_la_VEILLE_ne_ressuscite_pas(tmp_path):
    hier = (date.today() - timedelta(days=1)).isoformat()
    (tmp_path / "solde.json").write_text(json.dumps(
        {"date": hier, "balance": 1000.0}))

    m = _module(tmp_path, balance=576.95)
    m._refresh_start_of_day()

    assert m._start_of_day_balance == 576.95
    assert json.loads((tmp_path / "solde.json").read_text())["date"] == \
        date.today().isoformat()


def test_un_fichier_ILLISIBLE_rend_le_comportement_d_avant(tmp_path):
    (tmp_path / "solde.json").write_text("{ ceci n'est pas du json")
    m = _module(tmp_path, balance=576.95)
    m._refresh_start_of_day()
    assert m._start_of_day_balance == 576.95


def test_une_ECRITURE_impossible_ne_leve_PAS(tmp_path):
    """⚠️ Ce chemin est celui d'un ordre sur l'argent reel."""
    m = _module(tmp_path, balance=576.95,
                fichier="dossier_absent/encore/solde.json")
    m._refresh_start_of_day()          # ne doit pas lever
    assert m._start_of_day_balance == 576.95


def test_le_resync_anti_derive_est_PERSISTE(tmp_path):
    """Un retrait ou un depot entre deux redemarrages : la nouvelle reference
    doit survivre au suivant, sinon le filet anti-derive se rejoue a vide."""
    m = _module(tmp_path, balance=100.0)
    m.__dict__["_start_of_day_date"] = date.today()
    m.__dict__["_start_of_day_balance"] = 1000.0   # ratio 10 -> resync

    m._refresh_start_of_day()

    assert m._start_of_day_balance == 100.0
    assert json.loads((tmp_path / "solde.json").read_text())["balance"] == 100.0


def test_sans_compte_lisible_rien_n_est_ecrit(tmp_path):
    m = _module(tmp_path)
    m.__dict__["mt5"] = types.SimpleNamespace(account_info=lambda: None)
    m._refresh_start_of_day()
    assert m._start_of_day_balance is None
    assert not (tmp_path / "solde.json").exists()
