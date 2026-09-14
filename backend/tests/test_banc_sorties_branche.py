"""Le banc des politiques de sortie existait — et n'avait JAMAIS tourne.

⛔ **Trouve le 2026-09-14.** `comparer_sorties` est code depuis le 12/09, avec
ses trois politiques et son invariant d'entrees appariees. Recherche dans tout
le depot : il n'est reference que par **ses propres tests**. Le cycle nocturne
ne l'appelle pas. Le banc mesurait donc zero nuit sur zero instrument.

C'est la forme exacte du defaut deja paye ici : un correctif jamais branche
([[feedback_stale_patch_dead_import]]), et `_resolve_fill_price` reste deux
mois sans que l'audit s'en serve.

## Pourquoi ca comptait CE SOIR

La fermeture partielle du pont ne se declenche jamais sur le compte reel : le
courtier impose `volume_min = volume_step = 0,01`, et 50 % de 0,01 vaut 0,005.
Sur 112 positions, 103 sont ouvertes a 0,01. Avant d'ajouter un TP3 a un
mecanisme qui ne peut pas couper, il faut savoir si couper aide — et c'est
precisement la question de ce banc.

⛔ **LE PRIOR A RESPECTER** : mesure du 2026-08-11, la gestion de sortie a
DETRUIT de la performance sur l'or, **−0,329 R**. Ce banc existe pour
reproduire ou refuter ce chiffre, pas pour justifier une gestion decidee
d'avance.

⚠️ **Il ne cree AUCUNE cellule.** Croiser les politiques avec les cellules
ferait passer 2 356 cellules a ~9 400 et le plafond du hasard de 3,66 a 4,28.
La comparaison est APPARIEE sur les memes entrees : elle se range a part.
"""
from __future__ import annotations

import sqlite3

from backend.services import laboratoire_or as labo
from backend.services import reglage_or as rg
from backend.tests.test_reglage_or import _base_neuve  # noqa: F401


# ⚠️ 600 : le cycle nocturne ignore un instrument sous 500 bougies.
# Ma premiere version en generait 400 et le banc ne tournait pas —
# le test echouait pour la bonne raison, mais pas celle que je croyais.
def _bougies_qui_bougent(n=600):
    """Des bougies qui montent et redescendent : de quoi declencher des motifs."""
    out = []
    prix = 100.0
    for i in range(n):
        prix += 1.4 if (i // 7) % 2 == 0 else -1.1
        out.append({"t": f"2026-09-{1 + i // 288:02d}T{(i // 12) % 24:02d}:{(i % 12) * 5:02d}:00+00:00",
                    "o": prix, "h": prix + 0.9, "l": prix - 0.9,
                    "c": prix + (0.4 if i % 3 else -0.4), "tv": 500})
    return out


def test_le_banc_POOLE_les_politiques_sur_tous_les_motifs():
    b = _bougies_qui_bougent()
    releve = labo.detections(b, "XAU/USD")
    res = labo.comparer_sorties_global(b, releve, spread=0.02)
    assert set(res) >= set(labo.POLITIQUES_SORTIE), (
        "les trois politiques doivent etre rendues, meme perdantes")
    ref = labo.POLITIQUES_SORTIE[0]
    assert res[ref]["delta_reference"] == 0.0, "la reference s'ecarte d'elle-meme"
    for p, d in res.items():
        assert d["n"] > 0, f"{p} n'a rejoue aucun trade"
    # ⛔ Meme population : l'ecart doit mesurer la GESTION, pas le tirage.
    assert len({d["n"] for d in res.values()}) == 1, (
        "les politiques ne voient pas le meme nombre de trades — l'ecart "
        "mesurerait une difference de population")


def test_le_banc_ne_cree_AUCUNE_cellule():
    """🔑 Le plafond du hasard ne doit pas bouger parce qu'on mesure les
    sorties : la comparaison est appariee, elle se range a part."""
    b = _bougies_qui_bougent()
    avant = labo.mesurer(b, 0.02, pair="XAU/USD")["k"]
    labo.comparer_sorties_global(b, labo.detections(b, "XAU/USD"), 0.02)
    apres = labo.mesurer(b, 0.02, pair="XAU/USD")["k"]
    assert avant == apres


def test_la_nuit_ENREGISTRE_les_politiques(monkeypatch):
    """Le test qui aurait attrape le defaut : le banc doit etre APPELE."""
    b = _bougies_qui_bougent()
    monkeypatch.setattr(rg, "instruments_servis", lambda: ["XAU/USD"])
    monkeypatch.setattr(rg, "_bougies_et_spread", lambda j, pair=None: (b, 0.02))
    monkeypatch.setattr(rg, "_notifier", lambda *a, **k: None)
    rg.cycle_nocturne()
    with sqlite3.connect(rg._db()) as c:
        lignes = c.execute(
            "SELECT pair, politique, n, r_moyen, delta_reference "
            "FROM labo_or_sorties").fetchall()
    assert lignes, "aucune politique enregistree : le banc n'a pas tourne"
    politiques = {l[1] for l in lignes}
    assert politiques == set(labo.POLITIQUES_SORTIE)


def test_le_PRIOR_de_2026_08_11_est_ecrit_dans_le_code():
    """⛔ −0,329 R. Un banc qui oublie son prior finit par le contredire sans
    s'en apercevoir."""
    import inspect
    src = inspect.getsource(labo)
    assert "-0,329" in src or "0,329" in src or "0.329" in src
