"""Le regime de marche par l'exposant de Hurst — predicat, pas motif.

Declare dans `06ba706` AVANT ce code, releve dans le canal MQL5 @mql5fr.

🔑 **Pourquoi Hurst et pas un autre concept du canal.** Sur 35 messages lus,
les deux tiers sont des oscillateurs — valeurs continues, pas des declencheurs :
en faire un motif exigerait d'inventer le seuil ET la regle. Hurst echappe a ce
piege parce qu'il **arrive avec son seuil** : `H = 0,5` est la marche aleatoire
par construction, pas un choix au doigt.

## Ce que mesure l'etendue redimensionnee (R/S)

Sur les rendements logarithmiques : on retranche la moyenne, on cumule les
ecarts, `R` est l'amplitude de ce cumul et `S` son ecart-type. On repete en
coupant la fenetre en deux, puis en quatre ; `H` est la pente de `log(R/S)`
contre `log(taille)`.

    H > 0,5   le marche PROLONGE ses mouvements
    H < 0,5   le marche REVIENT sur lui-meme

⛔ **Aucun reglage neuf.** La fenetre est `BIAIS_FENETRE`, reutilisee telle
quelle comme le fait `_sur_niveau_majeur`. Les tailles de sous-fenetres se
deduisent par division par deux — c'est la construction standard du R/S, pas
une liste choisie.

⚠️ C'est une REUTILISATION, pas une derivation : rien ne prouve que la bonne
fenetre pour un regime soit celle d'un biais de structure. Posee une fois,
jamais ajustee.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import laboratoire_or as labo


def _serie(closes):
    """Bougies au format du pont — `{t,o,h,l,c,tv}`."""
    t0 = datetime(2026, 10, 2, 0, 0, tzinfo=timezone.utc)
    out = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c
        out.append({"t": (t0 + timedelta(minutes=5 * i)).isoformat(),
                    "o": o, "h": max(o, c) * 1.0008, "l": min(o, c) * 0.9992,
                    "c": c, "tv": 100})
    return out


def _tendance(n, depart=4000.0, phi=0.9):
    """Serie qui PROLONGE : rendements positivement autocorreles, AR(1).

    ⛔ MON PREMIER MONTAGE ETAIT FAUX, et l'erreur vaut d'etre gardee : une
    rampe lineaire bruitee rend **H = 0,37**, donc ANTI-persistante. Hurst
    mesure la memoire des RENDEMENTS, pas la direction du prix — les
    rendements d'une rampe oscillent autour d'une constante, c'est-a-dire
    qu'ils reviennent a leur moyenne.

    Un AR(1) a phi eleve est la construction qui produit vraiment de la
    memoire longue : mesure a **H = 0,84** pour phi = 0,9.

    ⚠️ Le bruit doit etre un VRAI alea, rendu reproductible par une graine.
    Ma deuxieme version employait une sinusoide << deterministe >> : elle est
    PERIODIQUE, donc lue comme un retour a la moyenne, et le meme phi = 0,9
    rendait alors H = 0,31. Un montage qui se croit neutre et ne l'est pas
    mesure autre chose que ce qu'il annonce.
    """
    import random
    tirage = random.Random(42)
    closes, p, r = [], depart, 0.0
    for _ in range(n):
        r = phi * r + tirage.gauss(0, 0.0008)
        p *= 1 + r
        closes.append(p)
    return closes


def _retour_moyenne(n, centre=4000.0, amplitude=8.0):
    """Serie qui REVIENT : elle oscille autour d'un centre fixe."""
    return [centre + amplitude * ((-1) ** i) + 0.9 * math.sin(i / 2.0)
            for i in range(n)]


N = labo.BIAIS_FENETRE + 5


# --- L'exposant lui-meme -------------------------------------------------

def test_une_serie_qui_PROLONGE_a_un_exposant_au_dessus_de_la_moitie():
    h = labo._exposant_hurst([c for c in _tendance(labo.BIAIS_FENETRE)])
    assert h is not None and h > 0.5, h


def test_une_serie_qui_REVIENT_a_un_exposant_en_dessous():
    h = labo._exposant_hurst([c for c in _retour_moyenne(labo.BIAIS_FENETRE)])
    assert h is not None and h < 0.5, h


def test_une_serie_plate_ne_rend_PAS_d_exposant():
    """⛔ Sans variation, `S` vaut zero : on ne divise pas, on rend `None`."""
    assert labo._exposant_hurst([4000.0] * labo.BIAIS_FENETRE) is None


def test_une_serie_trop_courte_ne_rend_PAS_d_exposant():
    assert labo._exposant_hurst([4000.0 + i for i in range(8)]) is None


# --- Les deux predicats --------------------------------------------------

def test_le_predicat_persistant_reconnait_une_tendance():
    bougies = _serie(_tendance(N))
    assert labo._PREDICATS["regime_persistant"](bougies, len(bougies) - 1) is True


def test_le_predicat_retour_moyenne_reconnait_une_oscillation():
    bougies = _serie(_retour_moyenne(N))
    p = labo._PREDICATS["regime_retour_moyenne"]
    assert p(bougies, len(bougies) - 1) is True


def test_les_deux_predicats_s_EXCLUENT():
    """⛔ Un marche ne peut pas persister ET revenir en meme temps.

    Sans cette propriete, les quatre chaines declarees se declencheraient
    ensemble et la comparaison appariee ne voudrait plus rien dire.
    """
    for closes in (_tendance(N), _retour_moyenne(N)):
        bougies = _serie(closes)
        i = len(bougies) - 1
        a = labo._PREDICATS["regime_persistant"](bougies, i)
        b = labo._PREDICATS["regime_retour_moyenne"](bougies, i)
        assert not (a and b), (a, b)


# --- Les refus, et le temps ---------------------------------------------

def test_sans_assez_d_histoire_le_predicat_repond_NON():
    """⛔ Fail-closed. Repondre OUI ferait declencher la chaine partout en
    pretendant avoir mesure un regime."""
    bougies = _serie(_tendance(20))
    for nom in ("regime_persistant", "regime_retour_moyenne"):
        assert labo._PREDICATS[nom](bougies, len(bougies) - 1) is False


def test_le_predicat_ne_lit_PAS_l_avenir():
    """⛔ Le verdict a l'indice `i` ne doit pas bouger quand on ajoute la
    suite. `bougies[:i]` — ce que le detecteur a vu, pas une bougie de plus."""
    closes = _tendance(N)
    bougies = _serie(closes)
    i = len(bougies) - 1
    avant = labo._PREDICATS["regime_persistant"](bougies, i)

    # On colle un effondrement APRES l'indice mesure.
    suite = _serie(closes + [closes[-1] * 0.7] * 30)
    assert labo._PREDICATS["regime_persistant"](suite, i) is avant


def test_une_bougie_malformee_ne_valide_pas():
    bougies = _serie(_tendance(N))
    bougies[-3]["c"] = "quatre mille"
    for nom in ("regime_persistant", "regime_retour_moyenne"):
        assert labo._PREDICATS[nom](bougies, len(bougies) - 1) is False


# --- Les quatre chaines declarees ---------------------------------------

def test_les_quatre_chaines_sont_declarees_et_appariees():
    """⛔ L'appariement EST la prediction : persistance -> continuation,
    retour a la moyenne -> reversion. Un appariement inverse mesurerait
    autre chose que ce qui a ete declare dans `06ba706`."""
    par_nom = {c["nom"]: c for c in labo.CHAINES}
    attendu = {
        "momentum_en_regime_persistant_haussier":
            ("momentum_up", "regime_persistant"),
        "momentum_en_regime_persistant_baissier":
            ("momentum_down", "regime_persistant"),
        "rebond_en_regime_retour_moyenne_haussier":
            ("range_bounce_up", "regime_retour_moyenne"),
        "rebond_en_regime_retour_moyenne_baissier":
            ("range_bounce_down", "regime_retour_moyenne"),
    }
    for nom, (declencheur, predicat) in attendu.items():
        assert nom in par_nom, f"chaine {nom} non declaree"
        c = par_nom[nom]
        assert c["declencheur"] == declencheur
        assert predicat in c["predicats"]


def test_chaque_chaine_est_un_sous_ensemble_STRICT_de_son_declencheur():
    """🔑 C'est ce qui rend la comparaison APPARIEE — et le test declare est
    << la chaine bat son propre declencheur seul >>, pas << elle bat le
    hasard >>."""
    par_nom = {c["nom"]: c for c in labo.CHAINES}
    for nom in ("momentum_en_regime_persistant_haussier",
                "rebond_en_regime_retour_moyenne_baissier"):
        c = par_nom[nom]
        assert c["motifs"] == (c["declencheur"],), c["motifs"]

# --- Le ZERO de l'estimateur, mesure et inscrit -------------------------

def test_le_zero_de_l_estimateur_est_MESURE_et_connu():
    """⚠️ LA LIMITE DU CONCEPT, mesuree avant que le laboratoire ne tranche.

    `H = 0,5` est la marche aleatoire **en theorie**. Mais le R/S sur un
    echantillon court est biaise vers le haut : mesure sur 12 marches
    aleatoires de `BIAIS_FENETRE` points, **H median = 0,59** (0,44 a 0,72).

    ⇒ `regime_persistant` se declenchera sur une bonne part de bruit pur, et
    `regime_retour_moyenne` sera rare. C'est une FAIBLESSE du dispositif, et
    elle est inscrite ici plutot que corrigee en deplacant le seuil :
    deplacer le seuil reviendrait a inventer le reglage que Hurst etait
    precisement cense epargner.

    Ce test ne juge pas le biais, il le VERROUILLE : si une version future le
    reduit, il echouera et on saura que l'estimateur a change.
    """
    import random
    random.seed(7)
    hs = []
    for _ in range(12):
        p, serie = 4000.0, []
        for _ in range(labo.BIAIS_FENETRE):
            p *= 1 + random.gauss(0, 0.0008)
            serie.append(p)
        h = labo._exposant_hurst(serie)
        if h is not None:
            hs.append(h)
    assert len(hs) >= 10
    median = sorted(hs)[len(hs) // 2]
    assert 0.52 < median < 0.68, (
        "le zero de l'estimateur a bouge : %.4f (mesure a 0,59 le 02/10)" % median)
