"""La zone d'accumulation — NOTRE formalisation, declaree avant d'etre codee.

⛔ **Lire d'abord** : l'etape 2 des cinq de Vivien est « trouver une zone
d'accumulation ». **Aucun seuil n'a ete publie.** Les quatre nombres testes ici
sont les notres (`720fcd3`, commit sans aucun `.py`). Les presenter comme sa
definition fabriquerait « un robot inspire de Vivien ».

## Les deux conditions, et pourquoi il en faut DEUX

- **compression** : le prix se resserre par rapport a ce qu'il faisait avant ;
- **retour** : il revient d'ou il etait parti.

La compression seule laisse passer une **tendance lineaire** : ses dix
dernieres bougies couvrent la moitie de l'amplitude des vingt precedentes,
soit 0,50 — sous le seuil de 0,60. Le retour la rejette : elle avance, elle ne
revient pas.

## ⛔ La regle declaree etait INATTEIGNABLE, et c'est un test qui l'a montre

J'avais declare « concentration = largeur(zone de valeur) / amplitude, <= 0,50 ».
Dix bougies identiques — la forme la PLUS accumulee qui soit — donnent un
profil **plat**, dont la zone de valeur vaut 0,70 x l'amplitude **par
construction** (`PART_ZONE_VALEUR`). Le seuil etait donc hors d'atteinte pour
la figure meme qu'il devait reconnaitre.

🔑 Et le profil de volume n'appartenait pas la : l'etape 2 **trouve** la zone,
l'etape 3 la **profile**. Les confondre etait mon glissement, pas le sien. Le
profil est desormais JOINT au resultat, jamais une condition d'existence.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.models.schemas import Candle
from backend.services import market_profile as mp


def _b(specs, volumes=None):
    t0 = datetime(2026, 9, 14, tzinfo=timezone.utc)
    return [Candle(timestamp=t0 + timedelta(minutes=5 * i),
                   open=o, high=h, low=bb, close=c,
                   volume=(volumes[i] if volumes else 1000.0))
            for i, (o, h, bb, c) in enumerate(specs)]


def _tendance(n, depart=100.0, pas=1.0):
    return [(depart + i * pas, depart + i * pas + 0.5,
             depart + i * pas - 0.5, depart + i * pas) for i in range(n)]


def _serre(n, prix=120.0, demi=0.10):
    return [(prix, prix + demi, prix - demi, prix)] * n


def test_une_accumulation_est_RECONNUE():
    """20 bougies qui montent, puis 10 bougies serrees sur un meme prix."""
    b = _b(_tendance(20) + _serre(10, prix=120.0))
    zone = mp.zone_accumulation(b, source=mp.VOLUME)
    assert zone is not None, "une consolidation nette doit etre reconnue"
    assert zone["bas"] <= 120.0 <= zone["haut"]
    assert zone["compression"] <= mp.ACCU_COMPRESSION
    assert zone["retour"] <= mp.ACCU_RETOUR
    # l'etape 3 : la zone est PROFILEE, en ticks
    assert zone["poc"] is not None and zone["source"] == mp.VOLUME


def test_une_TENDANCE_qui_continue_n_est_PAS_une_accumulation():
    b = _b(_tendance(30))
    assert mp.zone_accumulation(b, source=mp.VOLUME) is None


def test_une_DERIVE_LENTE_echoue_sur_le_RETOUR():
    """⛔ Le cas qui justifie la seconde condition : l'amplitude se resserre,
    mais le prix AVANCE au lieu de revenir."""
    b = _b(_tendance(20) + _tendance(10, depart=120.0, pas=0.12))
    zone = mp.zone_accumulation(b, source=mp.VOLUME)
    if zone is not None:                       # si la compression passe...
        pytest.fail("une derive lente ne doit pas etre une accumulation")


def test_SANS_VOLUME_la_zone_TIENT_mais_son_profil_est_VIDE():
    """⛔ La distinction qui compte : l'etape 2 ne depend pas du volume,
    l'etape 3 si. Sans volume, la zone existe toujours — mais son POC vaut
    None, et surtout **pas** un POC calcule sur le temps sous un autre nom."""
    b = _b(_tendance(20) + _serre(10), volumes=[0.0] * 30)
    zone = mp.zone_accumulation(b, source=mp.VOLUME)
    assert zone is not None, "la zone ne depend pas du volume"
    assert zone["poc"] is None
    assert zone["zone_valeur"] is None
    # ... alors qu'en TPO le meme profil se calcule
    assert mp.zone_accumulation(b, source=mp.TPO)["poc"] is not None


def test_le_predicat_du_LABORATOIRE_est_branche_et_fail_closed():
    from backend.services import laboratoire_or as labo
    assert "dans_accumulation" in labo._PREDICATS
    # Le predicat lit des DICTS de bougies (format du pont), pas des Candle.
    # ⚠️ Un marche PARFAITEMENT plat n'est pas une accumulation : il n'y a
    # rien eu a accumuler. compression = 1,0, donc NON.
    plates = [{"t": "2026-09-14T00:%02d:00+00:00" % i, "o": 100, "h": 100.1,
               "l": 99.9, "c": 100, "tv": 500} for i in range(40)]
    assert labo._PREDICATS["dans_accumulation"](plates, 39) is False

    # ... et la vraie forme, elle, est reconnue par le MEME predicat.
    monte = [{"t": "2026-09-14T00:%02d:00+00:00" % i, "o": 100 + i,
              "h": 100.5 + i, "l": 99.5 + i, "c": 100 + i, "tv": 500}
             for i in range(20)]
    serre = [{"t": "2026-09-14T01:%02d:00+00:00" % i, "o": 120, "h": 120.1,
              "l": 119.9, "c": 120, "tv": 500} for i in range(10)]
    bougies = monte + serre
    assert labo._PREDICATS["dans_accumulation"](bougies, len(bougies)) is True


def test_les_deux_chaines_declarees_existent_et_sont_APPARIEES():
    """🔑 L'inclusion stricte est ce qui rend la comparaison lisible : la
    chaine ne peut se declencher que la ou le balayage se declenche deja."""
    from backend.services import laboratoire_or as labo
    noms = {c["nom"]: c for c in labo.CHAINES}
    for sens in ("haussier", "baissier"):
        c = noms[f"prise_en_accumulation_{sens}"]
        assert c["predicats"] == ("dans_accumulation",)
        assert c["fenetre"] == 0, "le contexte est SIMULTANE au balayage"
        assert len(c["motifs"]) == 1, (
            "un seul motif : la chaine doit etre un SOUS-ENSEMBLE strict du "
            "balayage, sinon la comparaison n'est plus appariee")
        assert c["declencheur"] == c["motifs"][0]
        assert "liquidity_sweep" in c["declencheur"]
