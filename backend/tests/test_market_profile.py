"""Profil de marché : POC, zone de valeur, structure, liquidité (2026-09-04).

Noyau de la stratégie demandée — « repère ta structure, tes niveaux de
liquidité, ton POC ».

⛔ **Le POC est calculé en TPO, pas en volume, et ce n'est pas un pis-aller.**
Mesuré le 04/09 sur la prod : Twelve Data rend `volume = 0` sur **toutes** les
paires (WTI, XAU, EUR/USD — 0 valeur non nulle sur 30 bougies). Un « volume
profile » y serait un chiffre inventé.

Le TPO — *Time Price Opportunity*, Steidlmayer — compte le **temps passé à
chaque prix** au lieu du volume. C'est la définition ORIGINELLE du profil de
marché ; le volume profile en est la variante tardive. Il se calcule depuis
l'OHLC seul.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.models.schemas import Candle


def _c(o, h, l, cl, i=0):
    return Candle(timestamp=datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(hours=i),
                  open=o, high=h, low=l, close=cl, volume=0.0)


# ── POC ───────────────────────────────────────────────────────────────────

def test_le_poc_est_le_prix_ou_le_temps_s_accumule():
    """Dix bougies serrées autour de 100, deux qui s'en échappent.

    Le POC doit désigner 100 : c'est là que le marché a passé son temps.
    """
    from backend.services import market_profile as mp

    bougies = [_c(100, 100.2, 99.8, 100, i) for i in range(10)]
    bougies += [_c(105, 110.0, 104.0, 109, 10), _c(109, 112.0, 108.0, 111, 11)]

    poc = mp.poc(bougies)
    assert poc == pytest.approx(100, abs=0.6), f"POC={poc}"


def test_le_poc_ne_depend_PAS_du_volume():
    """Le volume vaut 0 partout en prod : s'il comptait, tout vaudrait 0.

    Ce test échouerait si quelqu'un « améliorait » le module en pondérant par
    le volume — le POC deviendrait indéfini sur des données réelles.
    """
    from backend.services import market_profile as mp

    bougies = [_c(100, 100.2, 99.8, 100, i) for i in range(12)]
    assert mp.poc(bougies) is not None


def test_pas_assez_de_bougies_rend_None():
    from backend.services import market_profile as mp
    assert mp.poc([_c(100, 101, 99, 100, 0)]) is None
    assert mp.poc([]) is None


def test_un_marche_totalement_plat_ne_plante_pas():
    """Haut = bas sur toutes les bougies : la largeur du profil est nulle."""
    from backend.services import market_profile as mp

    bougies = [_c(100, 100, 100, 100, i) for i in range(20)]
    assert mp.poc(bougies) == pytest.approx(100)


# ── Zone de valeur ────────────────────────────────────────────────────────

def test_la_zone_de_valeur_encadre_le_poc():
    from backend.services import market_profile as mp

    bougies = [_c(100, 100.5, 99.5, 100, i) for i in range(15)]
    bougies += [_c(103, 104, 102, 103, 15), _c(96, 97, 95, 96, 16)]

    bas, haut = mp.zone_valeur(bougies)
    poc = mp.poc(bougies)
    assert bas <= poc <= haut
    assert bas > 95 and haut < 104, "la zone doit exclure les extrêmes rares"


def test_la_zone_de_valeur_couvre_la_part_demandee():
    from backend.services import market_profile as mp

    bougies = [_c(100 + i * 0.1, 100.5 + i * 0.1, 99.5 + i * 0.1, 100 + i * 0.1, i)
               for i in range(30)]
    etroite = mp.zone_valeur(bougies, part=0.30)
    large = mp.zone_valeur(bougies, part=0.90)
    assert (large[1] - large[0]) > (etroite[1] - etroite[0])


# ── Structure ─────────────────────────────────────────────────────────────

def _zigzag(paires):
    """Bougies depuis une liste ``[(haut, bas), ...]``.

    ⚠️ Une montée LISSE ne produit aucune fractale : dans une fenêtre de cinq
    bougies qui montent, le sommet est la DERNIÈRE, jamais celle du milieu. Il
    faut de vrais aller-retours pour que des sommets et des creux existent —
    c'est vrai du marché comme du jeu d'essai.
    """
    return [_c((h + b) / 2, h, b, (h + b) / 2, i) for i, (h, b) in enumerate(paires)]


def test_sommets_et_creux_montants_donnent_une_structure_HAUSSIERE():
    from backend.services import market_profile as mp

    # sommets 105 → 110 → 115, creux 98 → 100,5 → 105,5
    bougies = _zigzag([
        (100, 99), (101, 100), (105, 101), (102, 100), (101, 99.5),
        (100.5, 98), (103, 99), (106, 102), (110, 105), (107, 103),
        (105, 101), (104, 100.5), (108, 103), (112, 107), (115, 110),
        (112, 108), (110, 106), (109, 105.5), (111, 107), (112, 108),
    ])
    assert mp.structure(bougies) == "haussiere"


def test_sommets_et_creux_descendants_donnent_une_structure_BAISSIERE():
    from backend.services import market_profile as mp

    # le miroir exact du cas haussier
    bougies = _zigzag([
        (115, 114), (114, 113), (115, 110), (113, 111), (114, 112),
        (117, 112.5), (112, 108), (109, 105), (105, 100), (108, 104),
        (110, 106), (111, 107), (107, 102), (104, 99), (100, 95),
        (103, 98), (105, 100), (106, 101), (104, 99), (103, 98),
    ])
    assert mp.structure(bougies) == "baissiere"


def test_un_marche_sans_direction_est_INDECIS():
    """⚠️ La porte la plus importante de la structure : savoir dire « je ne
    sais pas ». Sans elle, la stratégie prendrait position dans du bruit."""
    from backend.services import market_profile as mp

    bougies = [_c(100, 101, 99, 100, i) for i in range(30)]
    assert mp.structure(bougies) == "indecise"


# ── Niveaux de liquidité ──────────────────────────────────────────────────

def test_la_liquidite_pointe_les_extremes_recents():
    """Là où les stops s'accumulent : au-dessus des sommets, sous les creux."""
    from backend.services import market_profile as mp

    bougies = [_c(100, 101, 99, 100, i) for i in range(10)]
    bougies += [_c(100, 108, 99, 100, 10)]          # sommet marqué
    bougies += [_c(100, 101, 92, 100, 11)]          # creux marqué
    bougies += [_c(100, 101, 99, 100, i) for i in range(12, 20)]

    niveaux = mp.niveaux_liquidite(bougies)
    assert niveaux["au_dessus"] == pytest.approx(108, abs=0.5)
    assert niveaux["en_dessous"] == pytest.approx(92, abs=0.5)


def test_sans_extreme_identifiable_les_niveaux_sont_None():
    from backend.services import market_profile as mp
    n = mp.niveaux_liquidite([_c(100, 101, 99, 100, i) for i in range(3)])
    assert n["au_dessus"] is None and n["en_dessous"] is None
