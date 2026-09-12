"""Le rejeu ne savait qu'une sortie : stop a -1 R, cible fixe, expiration.

⛔ CE QUI MANQUAIT. `_issue` connaissait une entree, un stop, une cible, une
expiration et un cout. Donc rien de ce que « sortir et refermer » veut dire :
TP1/TP2/TP3, mise a zero du risque, stop suiveur, coupe discretionnaire.

## 🔑 Comparaison APPARIEE, pas un croisement de cellules

Croiser 4 politiques de sortie avec les cellules ferait passer 2 356 cellules
a ~9 400, et le plafond du hasard de 3,66 a 4,28 — on paierait en exigence
une question qu'on peut poser autrement.

La vraie question n'est pas « quelle cellule gagne avec quelle sortie », c'est
**« la gestion de sortie ajoute-t-elle quelque chose a la sortie simple ? »**.
C'est une comparaison **sur les memes trades** : memes entrees, memes stops,
seule la sortie change. Quatre politiques = quatre comparaisons, pas quatre
fois plus de cellules.

## ⛔ LE PRIOR QU'ON DOIT RESPECTER

Mesure du 2026-08-11 : la gestion de sortie a **DETRUIT** de la performance
sur l'or, **-0,329 R**. Ce banc existe pour reproduire ou refuter ce chiffre,
pas pour justifier une gestion decidee d'avance.

⚠️ Une politique qui ne se distingue pas de la sortie simple n'est pas
« neutre, donc on la prend » : c'est un degre de liberte de plus pour rien.

## Invariants

- **memes entrees** : si une politique voyait d'autres trades, la comparaison
  ne voudrait rien dire ;
- le **cout** est paye par chaque politique, y compris sur les sorties
  partielles — une moitie fermee est une moitie qui paie le spread ;
- **stop teste AVANT cible**, dans chaque politique : dans une bougie qui
  contient les deux, on ne sait pas lequel est venu en premier, et supposer la
  cible fabriquerait de la performance.
"""
import pytest

from backend.services import laboratoire_or as labo


def _b(h, l, o=None, c=None):
    return {"t": 0, "o": o if o is not None else l, "h": h, "l": l,
            "c": c if c is not None else h}


# Une entree a 100, stop a 99 (risque 1), cible a 102 (objectif 2 R).
_ENTREE, _RISQUE, _OBJ = 100.0, 1.0, 2.0


def _rejouer(politique, bougies, cout=0.0):
    return labo._issue(bougies, 0, _ENTREE, _RISQUE, _OBJ, 1, cout,
                       politique=politique)


# ─── La politique de reference ──────────────────────────────────────


def test_la_sortie_SIMPLE_reste_le_comportement_d_origine():
    """⛔ La reference ne doit pas bouger : tout le passe a ete mesure avec
    elle, et la deplacer rendrait les verdicts d'hier incomparables."""
    R, _ = _rejouer("cible_unique", [_b(102.5, 100.0)])
    assert R == pytest.approx(2.0)
    R, _ = _rejouer("cible_unique", [_b(100.0, 98.5)])
    assert R == pytest.approx(-1.0)


def test_le_stop_est_teste_AVANT_la_cible_dans_TOUTE_politique():
    """Une bougie qui contient les deux rend le STOP. Supposer la cible
    gonflerait chaque cellule gagnante."""
    les_deux = [_b(103.0, 98.0)]
    for p in labo.POLITIQUES_SORTIE:
        R, _ = _rejouer(p, les_deux)
        assert R <= 0.0, f"{p} suppose la cible dans une bougie ambigue"


# ─── Mise a zero du risque ──────────────────────────────────────────


def test_l_EQUILIBRE_transforme_un_perdant_en_neutre():
    """Le prix atteint +1 R, le stop monte a l'entree, puis le prix redescend :
    la politique simple perd 1 R, celle-ci rend 0."""
    chemin = [_b(101.2, 100.0), _b(100.2, 98.0)]
    simple, _ = _rejouer("cible_unique", chemin)
    equilibre, _ = _rejouer("equilibre_a_1R", chemin)
    assert simple == pytest.approx(-1.0)
    assert equilibre == pytest.approx(0.0)


def test_l_EQUILIBRE_ne_s_arme_pas_avant_1R():
    """⚠️ S'armer trop tot couperait des trades encore vivants — c'est
    exactement par la que la gestion de sortie detruit du rendement."""
    chemin = [_b(100.5, 100.0), _b(100.2, 98.0)]
    assert _rejouer("equilibre_a_1R", chemin)[0] == pytest.approx(-1.0)


def test_l_EQUILIBRE_laisse_courir_jusqu_a_la_cible():
    chemin = [_b(101.2, 100.0), _b(102.5, 100.5)]
    assert _rejouer("equilibre_a_1R", chemin)[0] == pytest.approx(2.0)


# ─── Sortie partielle ───────────────────────────────────────────────


def test_la_MOITIE_est_prise_a_mi_chemin():
    """La moitie sort a +1 R, le reste va a la cible : (1 + 2) / 2 = 1,5."""
    chemin = [_b(101.2, 100.0), _b(102.5, 100.5)]
    assert _rejouer("moitie_a_mi_chemin", chemin)[0] == pytest.approx(1.5)


def test_la_MOITIE_prise_limite_la_perte_si_le_prix_revient():
    """La moitie a +1 R est acquise ; le reste perd 1 R. (1 - 1) / 2 = 0."""
    chemin = [_b(101.2, 100.0), _b(100.0, 98.0)]
    assert _rejouer("moitie_a_mi_chemin", chemin)[0] == pytest.approx(0.0)


def test_sans_mi_chemin_atteint_la_MOITIE_se_comporte_comme_la_simple():
    chemin = [_b(100.4, 98.0)]
    assert _rejouer("moitie_a_mi_chemin", chemin)[0] == pytest.approx(-1.0)


# ─── Le cout ────────────────────────────────────────────────────────


def test_CHAQUE_politique_paie_le_cout():
    """⛔ Une sortie gratuite ferait gagner toutes les politiques qui coupent
    souvent. Le spread se paie a chaque fermeture, partielle comprise."""
    chemin = [_b(101.2, 100.0), _b(102.5, 100.5)]
    for p in labo.POLITIQUES_SORTIE:
        sans = _rejouer(p, chemin, cout=0.0)[0]
        avec = _rejouer(p, chemin, cout=0.05)[0]
        assert avec < sans, f"{p} ne paie pas son cout"


# ─── La comparaison appariee ────────────────────────────────────────


def test_la_comparaison_porte_sur_les_MEMES_entrees():
    """⛔ L'invariant de la comparaison. Si une politique voyait d'autres
    trades, l'ecart mesurerait une difference de population et non de
    gestion."""
    bougies = [_b(100.0 + i * 0.1, 99.0 + i * 0.1) for i in range(300)]
    releve = {}
    res = labo.comparer_sorties(bougies, releve, "peu_importe", "buy", 0.02)
    assert res == {} or all(
        v["n"] == next(iter(res.values()))["n"] for v in res.values()), (
        "les politiques ne voient pas le meme nombre de trades")


def test_toutes_les_politiques_sont_DECLAREES():
    """Pas de politique inventee au vol : la liste est fermee, et
    `cible_unique` y figure comme reference."""
    assert "cible_unique" in labo.POLITIQUES_SORTIE
    assert 2 <= len(labo.POLITIQUES_SORTIE) <= 6


def test_une_politique_INCONNUE_leve():
    """⛔ Fail-closed : retomber en silence sur la sortie simple ferait lire
    « cette gestion ne change rien » alors qu'elle n'a jamais tourne."""
    with pytest.raises(KeyError):
        _rejouer("politique_qui_nexiste_pas", [_b(102.5, 100.0)])
