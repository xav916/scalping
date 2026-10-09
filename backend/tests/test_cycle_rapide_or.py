"""Le cycle RAPIDE sur l'or : 5 s, parce que l'or seul coûte 0,7 s.

Demande de Xavier le 2026-10-09 : « je veux cycle d'analyse tourne aux 5 sec ».

## 🔑 CE QUE LA MESURE AUTORISE, ET CE QU'ELLE INTERDIT

Le cycle **complet** analyse **54 paires** et dure **23 à 25 s** (cinq
échantillons relevés en production : 24,9 · 23,5 · 25,0 · 22,9 · 23,2). Le
mettre à 5 s le ferait se chevaucher **cinq fois** lui-même : impossible.

Le cycle **restreint** à l'or, lui, dure **0,47 à 0,93 s** (quatre
échantillons, relances du lanceur sur fermeture) :

```
13:23:21,185 -> 13:23:21,656   0,47 s
13:27:21,225 -> 13:27:21,940   0,72 s
13:31:11,193 -> 13:31:12,127   0,93 s
13:45:31,229 -> 13:45:31,852   0,62 s
```

⇒ 0,7 s toutes les 5 s = **14 % de charge**, soit *exactement* la charge
actuelle du cycle complet (24 s / 180 s = 13 %). La demande est donc tenable —
**sur l'or seul**, qui est de toute façon la seule paire ouverte au réel.

## ⛔ LE PIÈGE MORTEL QUE CES TESTS GARDENT

`run_analysis_cycle(univers_force=[])` : une liste **vide** est FAUSSE en
Python, donc `restreint = bool(univers_force)` vaut `False` et le cycle devient
**COMPLET**. Un univers vide ferait tourner les 54 paires **toutes les 5
secondes** — 24 s de travail dans une fenêtre de 5 s, l'empilement garanti,
sur la machine déjà tombée une fois cette semaine faute de mémoire.

## ⛔ ET LA LEÇON SUR LE HARNAIS, PAYÉE DANS LA MÊME HEURE

Ma première version de ce fichier appelait le **vrai** `start_scheduler()` pour
lire les jobs déclarés. Il a écrit dans `data/scalping.db`, basculé
`EUR/USD buy` en non-éligible, et fait tomber **30 tests** dans d'autres
fichiers. Le code de production n'y était pour rien : **le harnais était
invasif**.

> 🔑 Pour vérifier une décision de CONFIGURATION, on n'exécute pas le démarrage
> complet d'un ordonnanceur. On isole la décision — d'où
> `config_cycle_rapide()`, et ces tests qui ne touchent plus rien.

Le reste (que l'appelant passe bien `args` et garde `max_instances=1`) se
vérifie sur le SOURCE, sans rien exécuter.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.services import scheduler as sched

_SRC = Path(__file__).resolve().parents[1] / "services" / "scheduler.py"


@pytest.fixture(autouse=True)
def _env_propre(monkeypatch):
    """Aucune variable heritee du poste : chaque test pose la sienne."""
    for k in ("CYCLE_RAPIDE_SEC", "CYCLE_RAPIDE_PAIRS",
              "MT5_BRIDGE_LIVE_WHITELIST_PAIRS"):
        monkeypatch.delenv(k, raising=False)


# ─────────────────────────────────────────────────────────────────────────
# La décision de configuration, isolée
# ─────────────────────────────────────────────────────────────────────────

def test_cinq_secondes_sur_l_or(monkeypatch):
    monkeypatch.setenv("CYCLE_RAPIDE_SEC", "5")
    monkeypatch.setenv("CYCLE_RAPIDE_PAIRS", "XAU/USD")

    assert sched.config_cycle_rapide() == (5, ["XAU/USD"])


def test_l_univers_SUIT_la_liste_blanche_du_reel(monkeypatch):
    """🔑 Pas de constante en dur : le jour où Xavier change la liste blanche,
    le cycle rapide suit au lieu de dériver en silence."""
    monkeypatch.setenv("MT5_BRIDGE_LIVE_WHITELIST_PAIRS", "XAU/USD,XAG/USD")

    assert sched.config_cycle_rapide() == (5, ["XAU/USD", "XAG/USD"])


def test_CYCLE_RAPIDE_PAIRS_a_la_priorite_sur_la_liste_blanche(monkeypatch):
    monkeypatch.setenv("MT5_BRIDGE_LIVE_WHITELIST_PAIRS", "XAU/USD,XAG/USD")
    monkeypatch.setenv("CYCLE_RAPIDE_PAIRS", "XAU/USD")

    assert sched.config_cycle_rapide() == (5, ["XAU/USD"])


def test_SANS_AUCUNE_PAIRE_la_liste_est_vide(monkeypatch):
    """⛔ LE PIÈGE MORTEL : l'appelant doit refuser de s'enregistrer. La
    fonction rend une liste vide, elle ne retombe PAS sur un univers complet."""
    monkeypatch.setenv("CYCLE_RAPIDE_SEC", "5")
    monkeypatch.setenv("CYCLE_RAPIDE_PAIRS", "")

    assert sched.config_cycle_rapide() == (5, [])


def test_a_zero_seconde_il_est_DESARME(monkeypatch):
    monkeypatch.setenv("CYCLE_RAPIDE_SEC", "0")
    monkeypatch.setenv("CYCLE_RAPIDE_PAIRS", "XAU/USD")

    assert sched.config_cycle_rapide() == (0, ["XAU/USD"])


def test_une_valeur_ILLISIBLE_desarme_au_lieu_de_prendre_le_defaut(monkeypatch):
    """⚠️ `CYCLE_RAPIDE_SEC=cinq` ne doit pas armer un rythme que personne n'a
    demande. C'est la lecon du `.env` tronque du 02/10, ou un `int()` qui leve
    avait ferme trois echelles pendant dix minutes."""
    monkeypatch.setenv("CYCLE_RAPIDE_SEC", "cinq")
    monkeypatch.setenv("CYCLE_RAPIDE_PAIRS", "XAU/USD")

    assert sched.config_cycle_rapide() == (0, [])


def test_les_espaces_autour_des_paires_sont_manges(monkeypatch):
    monkeypatch.setenv("CYCLE_RAPIDE_PAIRS", " XAU/USD , XAG/USD ,, ")

    assert sched.config_cycle_rapide()[1] == ["XAU/USD", "XAG/USD"]


# ─────────────────────────────────────────────────────────────────────────
# L'enregistrement, vérifié sur le SOURCE — sans rien exécuter
# ─────────────────────────────────────────────────────────────────────────

def _bloc_cycle_rapide() -> str:
    """La tranche du source qui enregistre le job.

    ⚠️ Bornée explicitement : une ancre vague avait déjà produit une tranche
    VIDE dans ce dépôt, donc un test qui passe sur rien.
    """
    src = _SRC.read_text(encoding="utf-8")
    debut = src.index("_cycle_rapide_sec, _cycle_rapide_paires = config_cycle_rapide()")
    fin = src.index("# ─── Echelle de stop de l'or", debut)
    bloc = src[debut:fin]
    assert len(bloc) > 200, "tranche trop courte : l'ancre a bouge"
    return bloc


def test_les_DEUX_valeurs_sont_testees_avant_d_enregistrer():
    """⛔ Le garde qui empêche le cycle COMPLET aux 5 s. Tester seulement les
    secondes laisserait passer une liste vide."""
    bloc = _bloc_cycle_rapide()

    assert re.search(r"if\s+_cycle_rapide_sec\s*>\s*0\s+and\s+_cycle_rapide_paires\s*:",
                     bloc), "la liste de paires n'est pas testee avant l'enregistrement"


def test_l_univers_est_PASSE_au_job():
    """Sans `args`, `run_analysis_cycle` tournerait en mode COMPLET."""
    assert "args=[_cycle_rapide_paires]" in _bloc_cycle_rapide()


def test_le_job_ne_peut_pas_s_empiler():
    """⛔ `max_instances=1` et `coalesce=True`. Sans eux, un retard transitoire
    ferait démarrer plusieurs cycles, que le verrou ferait tous sortir en
    journalisant — le journal noyé au lieu du travail fait."""
    bloc = _bloc_cycle_rapide()

    assert "max_instances=1" in bloc
    assert "coalesce=True" in bloc


def test_le_desarmement_se_DIT():
    """Un cycle rapide absent sans un mot serait indiscernable d'un cycle
    rapide en panne."""
    bloc = _bloc_cycle_rapide()

    assert "DESARME" in bloc
    assert "ARME" in bloc


def test_le_cycle_COMPLET_reste_declare_SANS_univers_force():
    """⚠️ Le cycle rapide s'AJOUTE, il ne remplace pas. Le complet sert les 53
    autres paires, l'interface, et surtout le **battement** que
    `bridge_monitor` surveille pour détecter un radar mort."""
    src = _SRC.read_text(encoding="utf-8")
    debut = src.index('id="analysis_cycle"')
    bloc = src[max(0, debut - 300):debut + 120]

    assert "run_analysis_cycle" in bloc
    assert "seconds=MATAF_POLL_INTERVAL" in bloc
    assert "args=" not in bloc, ("le cycle complet a reçu un univers forcé : il "
                                 "ne serait plus complet")
