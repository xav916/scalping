"""Le profil de VOLUME — et le refus de se calculer sans volume.

⛔ **Pourquoi il n'existait pas** (en-tete de `market_profile`, 2026-09-04) :

    WTI/USD   30 bougies, volumes non nuls   0/30
    XAU/USD   30 bougies, volumes non nuls   0/30

Twelve Data ne rend aucun volume sur ces CFD. Le profil a donc ete construit
en **TPO** — le temps passe a chaque prix — ce qui est la definition
ORIGINELLE du profil de marche, pas un pis-aller.

✅ **Ce qui a change le 2026-09-12** : le pont MT5 transporte `tv`, et le
laboratoire le cable jusqu'aux bougies. Mesure du 14/09 sur l'or : 36 bougies
sur 36 avec un volume non nul, 813 ticks sur la derniere. Le profil de volume
que l'etape 3 de Vivien demande — « tracer le Volume Profile sur cette zone »
— est devenu calculable.

## Les deux garanties tenues ici

1. ⛔ **Sans volume, le profil de volume REFUSE de se calculer.** Il ne
   retombe pas sur le TPO. Un repli silencieux ferait mesurer le temps en
   croyant mesurer le volume — et le nom du resultat mentirait.
2. ⛔ **Le TPO reste le defaut, inchange.** Tous les verdicts de `poc_return`
   depuis le 04/09 ont ete rendus en TPO ; basculer en silence les rendrait
   incomparables sans que rien ne le dise.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.models.schemas import Candle
from backend.services import market_profile as mp


def _bougies(specs, volumes=None):
    t0 = datetime(2026, 9, 14, tzinfo=timezone.utc)
    return [Candle(timestamp=t0 + timedelta(minutes=5 * i),
                   open=o, high=h, low=b, close=c,
                   volume=(volumes[i] if volumes else 0.0))
            for i, (o, h, b, c) in enumerate(specs)]


def _montee(n=20):
    """Le prix monte regulierement : chaque niveau est visite AUTANT de temps."""
    return [(100.0 + i, 100.5 + i, 99.5 + i, 100.0 + i) for i in range(n)]


def test_sans_volume_le_profil_de_volume_REFUSE_de_se_calculer():
    """⛔ La garantie centrale. Pas de repli sur le TPO : un profil de volume
    calcule sans volume mesurerait le temps sous un autre nom."""
    b = _bougies(_montee())
    assert mp.profil(b, source=mp.VOLUME) == []
    assert mp.poc(b, source=mp.VOLUME) is None
    assert mp.zone_valeur(b, source=mp.VOLUME) is None


def test_avec_du_volume_le_POC_suit_le_VOLUME_et_non_le_temps():
    """Le prix passe partout le meme temps, mais tout le volume est sur une
    seule bougie : les deux profils doivent donner des reponses DIFFERENTES."""
    specs = _montee(20)
    volumes = [1.0] * 20
    volumes[3] = 10_000.0            # tout le volume au quatrieme niveau
    b = _bougies(specs, volumes)

    poc_volume = mp.poc(b, source=mp.VOLUME)
    poc_tpo = mp.poc(b, source=mp.TPO)
    assert poc_volume is not None
    assert abs(poc_volume - 103.0) < 1.5, (
        f"le POC volume devrait etre sur la bougie chargee, il est a {poc_volume}")
    assert abs(poc_volume - poc_tpo) > 1.0, (
        "les deux profils rendent le meme POC : le volume n'est pas utilise")


def test_la_zone_de_valeur_en_volume_se_resserre_autour_du_POC_volume():
    specs = _montee(20)
    volumes = [1.0] * 20
    volumes[3] = 10_000.0
    b = _bougies(specs, volumes)
    zv = mp.zone_valeur(b, source=mp.VOLUME)
    assert zv is not None
    bas, haut = zv
    assert bas <= mp.poc(b, source=mp.VOLUME) <= haut


def test_le_TPO_reste_le_DEFAUT_et_ne_bouge_pas():
    """⛔ Les verdicts de `poc_return` depuis le 04/09 sont en TPO. Basculer en
    silence les rendrait incomparables."""
    b = _bougies(_montee(), volumes=[5.0] * 20)
    assert mp.poc(b) == mp.poc(b, source=mp.TPO)
    assert mp.profil(b) == mp.profil_tpo(b)
    assert mp.zone_valeur(b) == mp.zone_valeur(b, source=mp.TPO)


def test_le_detecteur_poc_return_n_a_PAS_change_de_profil():
    """Le test qui protege les verdicts existants : le detecteur de production
    doit toujours demander le TPO, explicitement ou par defaut."""
    import inspect

    from backend.services import pattern_detector as pd
    src = inspect.getsource(pd._detect_poc_return)
    assert "VOLUME" not in src, (
        "le detecteur bascule en volume : tous les verdicts depuis le 04/09 "
        "deviendraient incomparables sans qu'aucun test ne le dise")


def test_une_source_inconnue_LEVE():
    """Fail-closed : `source='vollume'` ne doit pas rendre un profil TPO."""
    import pytest
    b = _bougies(_montee())
    with pytest.raises(ValueError, match="source"):
        mp.profil(b, source="vollume")
