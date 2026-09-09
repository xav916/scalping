"""Éprouver le LABORATOIRE lui-même, pas les motifs qu'il mesure.

⛔ **Le problème qui rend tout le reste douteux.** Le laboratoire a rendu
**224 cellules `INSUFFISANT`**. C'est le résultat attendu — sept motifs mesurés
avant septembre, aucun ne bat le hasard. Mais c'est aussi, exactement, ce que
rendrait un laboratoire **qui ne mesure rien**.

> *Un détecteur ne se teste pas sur son silence.*

Les deux verdicts sont indiscernables tant qu'on n'a pas montré que l'appareil
sait dire **oui** quand il le faut, et **non** quand il le faut.

## Les deux contrôles

**Contrôle POSITIF** — on fabrique une série où un motif est *réellement* suivi
d'un mouvement favorable. Si le laboratoire ne le voit pas, ses `INSUFFISANT`
ne valent rien : il mesurerait du bruit et rendrait toujours la même réponse.

**Contrôle NÉGATIF** — une marche aléatoire pure, sans aucune structure. Si le
laboratoire y trouve un motif gagnant, son plafond est trop bas et il
fabriquerait des découvertes.

⇒ Ensemble, ils bornent l'appareil des deux côtés. Sans eux, dix concepts
mesurés cette nuit produiront dix verdicts dont personne ne peut dire s'ils
signifient quelque chose.

⚠️ Ces contrôles n'utilisent **aucune donnée de marché** : ils sont
déterministes (graine fixe) et n'appellent pas le réseau — la leçon de
`test_phase4_e2e`, qui m'a fait accuser mon propre code deux fois.
"""
import random
from datetime import datetime, timedelta, timezone

import pytest

from backend.services.laboratoire_or import mesurer, plafond_hasard


_T0 = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _serie(n=4000, depart=4000.0, graine=42, pas=1.0):
    """Marche aléatoire en bougies de 5 min, au format que le pont rend."""
    r = random.Random(graine)
    prix = depart
    out = []
    for i in range(n):
        o = prix
        prix = o + r.gauss(0, pas)
        h = max(o, prix) + abs(r.gauss(0, pas / 3))
        b = min(o, prix) - abs(r.gauss(0, pas / 3))
        out.append({"t": _T0 + timedelta(minutes=5 * i),
                    "o": o, "h": h, "l": b, "c": prix})
    return out


def _injecter_edge(bougies, force=6.0, apres=12):
    """Après chaque forte bougie VERTE, injecte une montée qui PERSISTE.

    ⛔ Ma première version ajoutait un décalage sur `apres` bougies puis le
    laissait retomber. Mesuré : elle créait un saut de **6,00** là où la série
    d'origine est parfaitement continue (saut max 0,000). Le prix montait puis
    **retombait d'un coup** — l'edge etait annule pour tout trade encore
    ouvert, et le contrôle positif echouait.

    🔑 Le décalage est donc **cumulatif** : une fois la montée acquise, elle ne
    se rend pas. C'est ce que fait un vrai mouvement de prix.

    ⚠️ On n'injecte pas sur un motif nommé — cela reviendrait à coder deux fois
    la même règle et à vérifier qu'elles coïncident. On injecte sur une
    propriété BRUTE du prix, une grande bougie verte, que plusieurs détecteurs
    reconnaîtront chacun à leur façon.
    """
    out = [dict(b) for b in bougies]
    ecarts = [b["c"] - b["o"] for b in out]
    seuil = sorted(abs(e) for e in ecarts)[int(0.90 * len(ecarts))]

    decal = 0.0            # cumulatif : la montee acquise ne se rend pas
    rampe: list[float] = []   # ce qu'il reste a ajouter, bougie par bougie
    for i, b in enumerate(out):
        if rampe:
            decal += rampe.pop(0)
        elif ecarts[i] > seuil and i < len(out) - apres - 1:
            rampe = [force / apres] * apres
        for cle in ("o", "h", "l", "c"):
            b[cle] += decal
    return out


@pytest.fixture(scope="module")
def hasard_pur():
    return mesurer(_serie(), spread=0.02, pair="XAU/USD", echelles=(3,))


@pytest.fixture(scope="module")
def avec_edge():
    return mesurer(_injecter_edge(_serie()), spread=0.02, pair="XAU/USD",
                   echelles=(3,))


# ─── Contrôle NÉGATIF : le hasard ne doit rien produire ──────────────

def test_sur_du_HASARD_pur_aucune_cellule_ne_bat_le_plafond(hasard_pur):
    """⛔ Si le laboratoire trouve un gagnant dans une marche aléatoire, son
    plafond est trop bas et il fabriquerait des découvertes."""
    plafond = hasard_pur["plafond"]
    gagnantes = [c for c in hasard_pur["cellules"]
                 if (c.get("n") or 0) >= 30 and abs(c.get("t") or 0) > plafond]
    assert not gagnantes, (
        f"{len(gagnantes)} cellule(s) au-dessus du plafond {plafond:.2f} sur du "
        f"pur hasard : {[(c['motif'], round(c['t'], 2)) for c in gagnantes]}")


def test_le_hasard_produit_QUAND_MEME_des_cellules(hasard_pur):
    """⚠️ Garde-fou du contrôle : zéro cellule rendrait le test précédent vrai
    sans rien prouver. C'est le piège du détecteur testé sur son silence."""
    peuplees = [c for c in hasard_pur["cellules"] if (c.get("n") or 0) >= 30]
    assert len(peuplees) >= 3, (
        f"seulement {len(peuplees)} cellules peuplees — le controle negatif ne "
        "prouve rien")


# ─── Contrôle POSITIF : un vrai edge doit se voir ────────────────────

def test_un_edge_INJECTE_deplace_les_R_vers_le_haut(avec_edge, hasard_pur):
    """⛔ LE contrôle qui valide l'appareil. Si un mouvement réellement présent
    ne déplace pas les mesures, les 224 `INSUFFISANT` ne veulent rien dire."""
    def _r_moyen(res):
        peuplees = [c for c in res["cellules"] if (c.get("n") or 0) >= 20]
        return sum(c["r_moyen"] for c in peuplees) / len(peuplees), len(peuplees)

    r_edge, n_edge = _r_moyen(avec_edge)
    r_bruit, n_bruit = _r_moyen(hasard_pur)
    assert n_edge >= 3 and n_bruit >= 3, "trop peu de cellules pour comparer"
    assert r_edge > r_bruit, (
        f"l'edge injecte ne deplace RIEN : {r_edge:+.3f} avec, {r_bruit:+.3f} "
        "sans. Le laboratoire ne mesure pas ce qu'il pretend mesurer.")


def test_le_controle_ALEATOIRE_interne_reste_neutre(avec_edge):
    """⚠️ Le tirage au hasard du laboratoire ne doit PAS profiter de l'edge
    injecté : c'est lui la référence. S'il montait autant que les motifs,
    l'écart mesuré serait nul par construction et rien ne ressortirait jamais.
    """
    ref = list(avec_edge["controles"].values())
    assert ref, "aucun controle aleatoire produit"
    assert all(abs(c.get("r_moyen", 0)) < 1.0 for c in ref), (
        f"le tirage au hasard derive : {[round(c.get('r_moyen', 0), 3) for c in ref]}")


# ─── Ce que le laboratoire promet ────────────────────────────────────

def test_le_plafond_SUIT_le_nombre_de_cellules(hasard_pur):
    """La correction du test multiple doit être appliquée, pas seulement
    calculée : le plafond publié doit correspondre au `k` réel."""
    assert hasard_pur["plafond"] == pytest.approx(
        plafond_hasard(hasard_pur["k"]), abs=1e-6)


def test_mesurer_est_bien_une_fonction_PURE(hasard_pur):
    """Elle ne doit rien écrire : deux appels identiques rendent la même chose,
    et aucune décision n'est prise ici."""
    a = mesurer(_serie(n=800), spread=0.02, echelles=(3,))
    b = mesurer(_serie(n=800), spread=0.02, echelles=(3,))
    assert [c["r_moyen"] for c in a["cellules"]] == [c["r_moyen"] for c in b["cellules"]]
