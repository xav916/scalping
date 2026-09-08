"""Le laboratoire de l'or : mesurer, puis décider seul — sans se raconter d'histoires.

## Pourquoi ces tests sont écrits comme ça

Ce projet a déjà produit un « meilleur réglage » qui ne valait rien : DSR 0,35,
PBO 0,579, une gagnante qui tenait à **3 trades sur 233**. Un laboratoire qui
optimise sur les données qui l'ont suggéré fabrique exactement ça.

🔑 Ce qu'on teste ici n'est donc pas « trouve-t-il quelque chose ? » mais
**« refuse-t-il de trouver quand il n'y a rien ? »**.
"""
from __future__ import annotations

import io
import math
import sqlite3

import pytest

from backend.services import laboratoire_or as labo


def _bougies(n, depart=2000.0, pas=1.0):
    """Une série montante régulière, en dicts — le format du pont."""
    from datetime import datetime, timedelta, timezone
    t0 = datetime(2026, 6, 1, tzinfo=timezone.utc)
    return [{"t": t0 + timedelta(minutes=5 * i), "o": depart + i * pas,
             "h": depart + i * pas + 2, "l": depart + i * pas - 2,
             "c": depart + i * pas + 0.5} for i in range(n)]


# ── Le plafond du hasard ─────────────────────────────────────────────

def test_le_plafond_MONTE_avec_le_nombre_de_cellules():
    """🔑 C'est toute la protection : plus on regarde de combinaisons, plus il
    faut être net pour ne pas raconter du bruit."""
    valeurs = [labo.plafond_hasard(k) for k in (1, 3, 8, 24, 56, 128, 500)]
    assert valeurs == sorted(valeurs)
    assert len(set(valeurs)) == len(valeurs)


def test_le_plafond_colle_a_la_SIMULATION():
    """⛔ Pas la formule asymptotique : elle se trompe lourdement pour les
    petits k, et c'est précisément là qu'on décide."""
    for k, attendu in ((3, 1.328), (8, 1.789), (32, 2.349)):
        assert labo.plafond_hasard(k) == pytest.approx(attendu, abs=0.01)


def test_les_DEUX_formules_asymptotiques_se_trompent_a_petit_k():
    """Le contre-test qui justifie la table simulée. ⚠️ Les deux se trompent,
    mais pas dans le même sens — et je m'étais trompé sur le sens en écrivant
    ce test la première fois.

    À k=3, où l'on décide souvent :
    - la forme nue `sqrt(2 ln k)` rend **1,48** : trop STRICTE, elle ferait
      manquer de vraies trouvailles ;
    - la forme corrigée — **celle que mes propres scripts d'analyse
      utilisaient** — rend **0,60** : deux fois trop PERMISSIVE, elle
      adouberait du bruit.

    La simulation dit **1,33**.
    """
    k = 3
    nue = math.sqrt(2 * math.log(k))
    corrigee = nue - (math.log(math.log(k)) + math.log(4 * math.pi)) / (2 * nue)
    vrai = labo.plafond_hasard(k)
    assert nue > vrai + 0.1, (nue, vrai)          # trop stricte
    assert corrigee < vrai - 0.5, (corrigee, vrai)  # bien trop permissive


def test_au_dela_de_la_table_le_plafond_continue_de_monter():
    assert labo.plafond_hasard(1000) > labo.plafond_hasard(256)


# ── La statistique ───────────────────────────────────────────────────

def test_une_dispersion_QUASI_NULLE_ne_rend_pas_un_t_infini():
    """⛔ Vu à la première passe réelle : `60min mean_reversion_down` a rendu
    **t = −685** sur 8 trades, tous au stop, donc des R quasi identiques. Ce
    n'est pas un signal, c'est une division par presque rien — et avec 20
    trades au lieu de 8, ça passait pour la découverte du siècle."""
    _, t = labo._stat([-1.013] * 7 + [-1.014])
    assert t == 0.0


def test_une_VRAIE_dispersion_donne_bien_un_t():
    m, t = labo._stat([-1.0, 1.8] * 15)
    assert t != 0.0
    assert m == pytest.approx(0.4, abs=0.01)


# ── Le rejeu ─────────────────────────────────────────────────────────

def test_le_stop_est_teste_AVANT_l_objectif():
    """⛔ Dans une bougie qui contient les deux, on ne sait pas lequel est venu
    en premier. Supposer l'objectif fabriquerait de la performance."""
    from datetime import datetime, timezone
    t0 = datetime(2026, 6, 1, tzinfo=timezone.utc)
    # Une bougie qui touche le stop (98) ET l'objectif (103,6)
    b = [{"t": t0, "o": 100.0, "h": 104.0, "l": 97.0, "c": 100.0}]
    R, _ = labo._issue(b, 0, entree=100.0, risque=2.0, objectif_r=1.8,
                       sens=1, cout=0.0)
    assert R == pytest.approx(-1.0)


def test_l_objectif_seul_est_bien_paye():
    from datetime import datetime, timezone
    t0 = datetime(2026, 6, 1, tzinfo=timezone.utc)
    b = [{"t": t0, "o": 100.0, "h": 104.0, "l": 99.5, "c": 103.0}]
    R, _ = labo._issue(b, 0, 100.0, 2.0, 1.8, 1, cout=0.0)
    assert R == pytest.approx(1.8)


def test_le_spread_est_FACTURE():
    """⚠️ L'omettre flatterait les grandes échelles, qui le paient justement
    moins — on mesurerait l'avantage qu'on cherche à démontrer."""
    from datetime import datetime, timezone
    t0 = datetime(2026, 6, 1, tzinfo=timezone.utc)
    b = [{"t": t0, "o": 100.0, "h": 104.0, "l": 99.5, "c": 103.0}]
    R, _ = labo._issue(b, 0, 100.0, 2.0, 1.8, 1, cout=0.1)
    assert R == pytest.approx(1.7)


class _Enum:
    def __init__(self, v): self.value = v


class _Motif:
    def __init__(self, v): self.pattern = _Enum(v)


class _Setup:
    def __init__(self, motif, sens, entree, stop, objectif):
        self.pattern = _Motif(motif)
        self.direction = _Enum(sens)
        self.entry_price = entree
        self.stop_loss = stop
        self.take_profit_1 = objectif


def test_le_rejeu_est_SEQUENTIEL():
    """⛔ Jamais deux trades ouverts. Une fenêtre glissante compterait dix fois
    le même mouvement et gonflerait n — donc le t, donc la conclusion."""
    b = _bougies(400)
    # Un signal détectable à CHAQUE indice : sans la contrainte séquentielle on
    # obtiendrait ~350 trades.
    releve = {i: [_Setup("momentum_up", "buy", b[i]["c"], b[i]["c"] - 20,
                         b[i]["c"] + 36)]
              for i in range(labo.FENETRE, len(b))}
    trades = labo.rejouer_cellule(b, releve, "momentum_up", "buy", spread=0.2)
    assert 0 < len(trades) < 60


def test_un_stop_PLACEBO_est_ecarte():
    """⛔ 155 des 181 stops du réel étaient des placebos à 4 centimes. Un stop
    à 0,001 % du prix rend des R de plusieurs centaines."""
    b = _bougies(200)
    releve = {i: [_Setup("momentum_up", "buy", b[i]["c"], b[i]["c"] - 0.001,
                         b[i]["c"] + 0.002)]
              for i in range(labo.FENETRE, len(b))}
    assert labo.rejouer_cellule(b, releve, "momentum_up", "buy", 0.2) == []


def test_le_rejeu_ne_melange_PAS_les_motifs():
    b = _bougies(300)
    releve = {i: [_Setup("momentum_up", "buy", b[i]["c"], b[i]["c"] - 20,
                         b[i]["c"] + 36),
                  _Setup("breakout_up", "buy", b[i]["c"], b[i]["c"] - 20,
                         b[i]["c"] + 36)]
              for i in range(labo.FENETRE, len(b))}
    a = labo.rejouer_cellule(b, releve, "momentum_up", "buy", 0.2)
    c = labo.rejouer_cellule(b, releve, "breakout_up", "buy", 0.2)
    assert a and c
    # Deux cellules indépendantes : chacune a son propre parcours séquentiel.
    assert len(a) == len(c)


# ── L'agrégation ─────────────────────────────────────────────────────

def test_l_agregation_du_labo_est_ALIGNEE_comme_la_production():
    """⛔ Une règle qui divergerait de `echelle_agregee` ferait mesurer un
    instrument que le système ne trade pas."""
    from backend.services.echelle_agregee import agreger
    b = _bougies(60)
    a = labo._agreger_brut(b, 3, agreger)
    assert len(a) == 20
    assert all(x["t"].minute % 15 == 0 for x in a)
    assert a[0]["o"] == b[0]["o"]
    assert a[0]["c"] == b[2]["c"]
    assert a[0]["h"] == max(x["h"] for x in b[:3])


def test_la_bougie_EN_COURS_est_ecartee():
    from backend.services.echelle_agregee import agreger
    assert len(labo._agreger_brut(_bougies(7), 3, agreger)) == 2


# ── Les verdicts ─────────────────────────────────────────────────────

def _cellule(n=100, t=5.0, r=0.5, delta=0.4):
    return {"n": n, "t": t, "r_moyen": r, "delta_hasard": delta}


def test_trop_peu_de_trades_n_est_PAS_un_refus():
    """⛔ Confondre « pas assez de données » et « ça ne marche pas » fermerait
    des motifs qui n'ont simplement pas encore parlé."""
    assert labo._verdict(_cellule(n=5), 2.0) == labo.INSUFFISANT


def test_sous_le_plafond_on_ne_conclut_RIEN_dans_les_deux_sens():
    assert labo._verdict(_cellule(t=1.5), 2.5) == labo.INSUFFISANT
    assert labo._verdict(_cellule(t=-1.5, r=-0.5, delta=-0.4), 2.5) == labo.INSUFFISANT


def test_au_dessus_du_plafond_et_NEGATIF_c_est_un_refus():
    assert labo._verdict(_cellule(t=-3.5, r=-0.4, delta=-0.3), 2.5) == labo.REFUTE


def test_gagner_ne_suffit_PAS_il_faut_battre_le_HASARD():
    """🔑 « Aucun système ne bat le hasard » : Δ=+0,004 R sur 29 000 trades. Une
    cellule qui gagne autant que des entrées au hasard n'apporte rien."""
    assert labo._verdict(_cellule(t=3.5, r=0.4, delta=-0.05), 2.5) == labo.REFUTE
    assert labo._verdict(_cellule(t=3.5, r=0.4, delta=+0.30), 2.5) == labo.RETENU


# ── Le rendu ─────────────────────────────────────────────────────────

def test_rien_au_dessus_du_hasard_est_DIT_comme_un_resultat():
    """⛔ Un laboratoire qui ne sait pas annoncer « rien » est un générateur de
    justifications."""
    m = {"k": 56, "plafond": 2.55, "cellules": [
        dict(_cellule(t=1.0), horizon="5min", motif="momentum_up", sens="buy",
             verdict=labo.INSUFFISANT)]}
    texte = " ".join(labo.lignes(m))
    assert "Rien ne dépasse le hasard" in texte
    assert "pas une panne" in texte


def test_le_rendu_annonce_le_PLAFOND_a_franchir():
    m = {"k": 56, "plafond": 2.55, "cellules": [
        dict(_cellule(), horizon="5min", motif="momentum_up", sens="buy",
             verdict=labo.RETENU)]}
    texte = " ".join(labo.lignes(m))
    assert "2.55" in texte
    assert "56 combinaisons" in texte


def test_le_rendu_est_PUR():
    """⚠️ Il ne doit ni lire une base ni appeler un pont : le récap doit pouvoir
    le rendre sans réseau."""
    src = io.open("backend/services/laboratoire_or.py", encoding="utf-8").read()
    debut = src.index("def lignes(")
    corps = src[debut:]
    for interdit in ("sqlite3", "urllib", "requests", "os.environ["):
        assert interdit not in corps, interdit
