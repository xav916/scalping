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
    ne déplace pas les mesures, les 224 `INSUFFISANT` ne veulent rien dire.

    ⛔ **PORTÉE RESTREINTE AUX MOTIFS SIMPLES (2026-09-12).** Les chaînes de
    confluence sont entrées dans le relevé ce jour-là, et ce test a rougi :

        toutes cellules confondues   -0,041 avec edge   +0,014 sans
        motifs simples SEULS         +0,047 avec edge   +0,014 sans
        chaines seules               -0,926 avec edge   +0,004 sans

    Le laboratoire allait bien : **une seule** cellule de chaîne,
    `sweep_sur_order_block_baissier` à −0,93 R, tirait la moyenne de onze vers
    le bas. Et ce −0,93 est JUSTE — l'edge injecté est haussier, une chaîne
    baissière doit perdre. Le test moyennait donc des objets de natures
    opposées et concluait que l'appareil ne mesurait plus rien.

    🔑 L'injection vise des motifs, pas des combinaisons. Le contrôle positif
    doit donc porter sur ce que l'injection touche, sinon il mesure la
    dilution et non l'appareil.

    ⚠️ Le contrôle NÉGATIF, lui, garde les chaînes — et il passe. C'est là que
    le risque de fabrication se trouve : une chaîne qui inventerait un gagnant
    sur du pur hasard. L'exclusion ici ne doit surtout pas s'y propager.
    """
    def _r_moyen(res):
        peuplees = [c for c in res["cellules"]
                    if (c.get("n") or 0) >= 20
                    and not str(c.get("motif", "")).startswith("chaine:")]
        return sum(c["r_moyen"] for c in peuplees) / len(peuplees), len(peuplees)

    r_edge, n_edge = _r_moyen(avec_edge)
    r_bruit, n_bruit = _r_moyen(hasard_pur)
    assert n_edge >= 3 and n_bruit >= 3, "trop peu de cellules pour comparer"
    assert r_edge > r_bruit, (
        f"l'edge injecte ne deplace RIEN : {r_edge:+.3f} avec, {r_bruit:+.3f} "
        "sans. Le laboratoire ne mesure pas ce qu'il pretend mesurer.")


def test_le_controle_ALEATOIRE_n_ABSORBE_PAS_l_edge(avec_edge):
    """⚠️ Le tirage au hasard ne doit pas monter AUTANT que les motifs : c'est
    lui la référence. S'il absorbait l'edge, l'écart serait nul par
    construction et rien ne ressortirait jamais du laboratoire.

    ⛔ Réécrit le 2026-09-15. L'assertion d'avant exigeait un contrôle proche
    de zéro (`|r_moyen| < 1`). Elle n'était vraie que parce que le tirage
    prenait le sens à PILE OU FACE et moyennait les deux sens — c'est-à-dire
    à cause du défaut même qu'on vient de fermer. Un contrôle acheteur sur une
    série qui monte DOIT monter ; ce qu'il ne doit pas faire, c'est monter
    autant que le motif. C'est cela qu'on vérifie maintenant.
    """
    ref = avec_edge["controles"]
    assert ref, "aucun controle aleatoire produit"
    for cle, controle in ref.items():
        meilleures = [c["r_moyen"] for c in avec_edge["cellules"]
                      if c["sens"] == controle["sens"]
                      and c["echelle"] == controle["echelle"]
                      and c["n"] >= 30]
        if not meilleures:
            continue
        assert controle["r_moyen"] < max(meilleures), (
            f"le controle {cle} ({controle['r_moyen']:+.3f}) absorbe l'edge : "
            f"il atteint la meilleure cellule de son sens ({max(meilleures):+.3f}) "
            "— plus aucun ecart ne pourrait jamais ressortir")


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


# ─── Contrôle DIRECTIONNEL : la dérive n'est pas un avantage ─────────
#
# ⛔ LE TROU, trouvé le 2026-09-15. `controle_aleatoire` tire le sens à PILE OU
# FACE, et `mesurer` ne calculait qu'UN contrôle par échelle, partagé par les
# cellules acheteuses ET vendeuses. Sur un marché qui dérive, le contrôle
# moyenne les deux sens à zéro pendant qu'une cellule à sens unique encaisse
# la dérive entière. Son `delta_hasard` est alors gonflé de toute la tendance.
#
# Mesuré ce jour-là sur l'or : +16,6 % en 365 jours, soit ≈ +0,045 R par trade
# pour un achat — la MOITIÉ du `r_moyen` de la meilleure cellule acheteuse.
#
# 🔑 Le contrôle d'une cellule doit prendre le sens de cette cellule. Sinon on
# ne mesure pas un motif, on mesure la tendance du marché.

def _serie_avec_derive(n=4000, depart=4000.0, graine=7, pas=1.0, derive=0.08):
    """Marche aléatoire PLUS une dérive constante vers le haut.

    ⚠️ Aucun motif n'a d'avantage ici : la dérive profite à TOUT achat et
    pénalise TOUTE vente, quel que soit le déclencheur. C'est exactement la
    situation où un contrôle à pile ou face ment — et la seule série qui
    puisse le prouver.
    """
    r = random.Random(graine)
    prix = depart
    out = []
    for i in range(n):
        o = prix
        prix = o + derive + r.gauss(0, pas)
        h = max(o, prix) + abs(r.gauss(0, pas / 3))
        b = min(o, prix) - abs(r.gauss(0, pas / 3))
        out.append({"t": _T0 + timedelta(minutes=5 * i),
                    "o": o, "h": h, "l": b, "c": prix})
    return out


@pytest.fixture(scope="module")
def avec_derive():
    return mesurer(_serie_avec_derive(), spread=0.02, pair="XAU/USD",
                   echelles=(3,))


def test_le_controle_suit_le_SENS_de_la_cellule(avec_derive):
    """Sur une série qui monte, le tirage ACHETEUR doit gagner et le tirage
    VENDEUR perdre. Un contrôle unique, partagé par les deux sens, rendrait
    exactement la même valeur des deux côtés — et c'est le défaut."""
    achats = [c["r_hasard"] for c in avec_derive["cellules"]
              if c["sens"] == "buy" and c["n"] >= 30]
    ventes = [c["r_hasard"] for c in avec_derive["cellules"]
              if c["sens"] == "sell" and c["n"] >= 30]
    assert achats and ventes, "il faut des cellules des DEUX sens pour trancher"
    assert max(ventes) < min(achats), (
        f"le controle ne distingue pas les sens : achats {sorted(set(round(x, 4) for x in achats))}, "
        f"ventes {sorted(set(round(x, 4) for x in ventes))} — "
        "une valeur identique des deux cotes = un seul tirage a pile ou face")


def test_une_DERIVE_seule_ne_produit_aucun_RETENU(avec_derive):
    """⛔ La promesse. Une tendance de marché n'est pas un motif : aucune
    cellule ne doit être RETENUE sur une série sans la moindre structure,
    même quand tous les achats y gagnent."""
    retenues = [c for c in avec_derive["cellules"] if c["verdict"] == "RETENU"]
    assert not retenues, (
        f"{len(retenues)} cellule(s) RETENUE(s) sur une simple derive : "
        f"{[(c['motif'], c['sens'], round(c['r_moyen'], 3), round(c['delta_hasard'], 3)) for c in retenues]}")


def test_le_controle_MIS_EN_COMMUN_est_stable(avec_derive):
    """⛔ Une référence qui saute n'est pas une référence.

    Mesuré le 2026-09-15 sur l'or : un tirage unique de 300 trades bouge de
    ±0,10 R selon la graine — plus du double de la dérive qu'on corrige, et le
    signe achat/vente s'inversait dans 2 cas sur 6. Depuis que le verdict
    s'appuie sur l'écart au contrôle, cette dispersion entrerait droit dans les
    verdicts.

    On vérifie donc que la mise en commun tient : trois points de départ
    différents doivent rendre des contrôles qui se ressemblent.
    """
    from backend.services.laboratoire_or import controle_aleatoire, controle_poole
    import statistics as st

    serie = _serie(n=3000)
    args = (serie, 0.02, 200, 8.0, 1.8)

    seuls = [st.fmean([x["R"] for x in controle_aleatoire(*args, g, sens="buy")])
             for g in (101, 202, 303)]
    pooles = [st.fmean(controle_poole(*args, g, sens="buy")) for g in (101, 202, 303)]

    etendue_seul = max(seuls) - min(seuls)
    etendue_poole = max(pooles) - min(pooles)
    assert etendue_poole < etendue_seul, (
        f"la mise en commun n'apaise rien : seul {etendue_seul:.4f}, "
        f"mis en commun {etendue_poole:.4f}")
