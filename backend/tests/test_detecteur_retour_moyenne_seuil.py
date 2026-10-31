"""Le seuil du retour à la moyenne doit être RÉGLABLE, sans bouger de défaut.

Pré-inscription : `docs/predictions/2026-10-31_retour-moyenne-or.md`.

Le banc balaie trois seuils (1,5σ / 2,0σ / 2,5σ). Pour les mesurer, il lui
faut le détecteur **de production**, pas une copie — ce dépôt sait ce que
coûtent deux implémentations de la même règle (« les 18 chaînes n'existaient
que dans le rejeu », `chaines_production.py`).

⛔ **Le défaut doit rester 2,0σ.** `mean_reversion_*` est armé sur le démo
depuis le 04/09 (BTC, ETH, XAU en `_down`). Déplacer le défaut en rendant le
seuil réglable changerait, sous couvert de refactor, ce que la production
détecte — exactement le genre de glissement muet que ces tests existent pour
interdire.

⚠️ Ce fichier ne mesure RIEN sur l'avantage du motif. Il verrouille un
mécanisme de mesure. L'espérance, c'est le banc qui la dira, et la
pré-inscription prédit le REJET.
"""
from datetime import datetime, timedelta, timezone

import pytest

from backend.models.schemas import PatternType
from backend.services import pattern_detector as pd


def _c(o, h, l, c, i=0):
    """Une bougie, cinq minutes après la précédente."""
    from backend.services.pattern_detector import Candle
    return Candle(
        timestamp=datetime(2026, 10, 31, tzinfo=timezone.utc) + timedelta(minutes=5 * i),
        open=o, high=h, low=l, close=c, volume=0)


def _serie_ecartee(sigmas: float, sens: str = "bas", prix: float = 4000.0):
    """19 bougies de bruit régulier, puis une 20ᵉ à `sigmas` écarts-types.

    Le bruit alterne ±1,0 autour de `prix` : sur 19 clôtures l'écart-type est
    donc proche de 1,0, ce qui rend le placement de la dernière bougie direct
    et lisible. La 20ᵉ est une bougie de RETOURNEMENT, que le détecteur exige
    en plus de l'écart.
    """
    bougies = []
    for i in range(19):
        p = prix + (1.0 if i % 2 else -1.0)
        bougies.append(_c(p, p + 0.2, p - 0.2, p, i))

    # L'écart-type est calculé par le détecteur sur les 20 dernières clôtures,
    # la 20ᵉ incluse — on vise donc large et on laisse le test vérifier le
    # franchissement plutôt que de prédire le sigma au centième.
    if sens == "bas":
        cl = prix - sigmas * 1.0
        # close > open : la bougie rebondit, condition du détecteur
        bougies.append(_c(cl - 0.5, cl + 0.2, cl - 0.8, cl, 19))
    else:
        cl = prix + sigmas * 1.0
        # close < open : la bougie rejette
        bougies.append(_c(cl + 0.5, cl + 0.8, cl - 0.2, cl, 19))
    return bougies


def _motifs(candles):
    return {p.pattern for p in pd.detect_patterns(candles, "XAU/USD")}


# ─── Le défaut ne bouge pas ──────────────────────────────────────────

def test_le_defaut_vaut_bien_deux_sigmas():
    """⛔ La valeur armée en production. Un refactor ne la déplace pas."""
    assert pd.MEAN_REVERSION_SIGMA == pytest.approx(2.0)


def test_un_ecart_FRANC_declenche_au_defaut():
    assert PatternType.MEAN_REVERSION_UP in _motifs(_serie_ecartee(4.0, "bas"))


def test_un_ecart_FAIBLE_ne_declenche_pas_au_defaut():
    """1,2σ est sous le seuil : le motif doit se taire."""
    assert PatternType.MEAN_REVERSION_UP not in _motifs(_serie_ecartee(1.2, "bas"))


# ─── Le seuil est réglable, et c'est le MÊME code ────────────────────

def test_desserrer_le_seuil_fait_apparaitre_un_ecart_FAIBLE(monkeypatch):
    """Le banc a besoin de ça : mesurer 1,5σ sans recopier le z-score.

    ⛔ Si ce test échouait, le banc devrait réimplémenter la mesure d'écart —
    et les deux versions divergeraient un jour sans que rien ne le dise.
    """
    serie = _serie_ecartee(1.2, "bas")
    assert PatternType.MEAN_REVERSION_UP not in _motifs(serie)

    monkeypatch.setattr(pd, "MEAN_REVERSION_SIGMA", 0.8)
    assert PatternType.MEAN_REVERSION_UP in _motifs(serie)


def test_resserrer_le_seuil_fait_disparaitre_un_ecart_FRANC(monkeypatch):
    serie = _serie_ecartee(4.0, "bas")
    assert PatternType.MEAN_REVERSION_UP in _motifs(serie)

    monkeypatch.setattr(pd, "MEAN_REVERSION_SIGMA", 9.0)
    assert PatternType.MEAN_REVERSION_UP not in _motifs(serie)


def test_le_sens_VENTE_suit_le_meme_seuil(monkeypatch):
    """`mean_reversion_down` est le seul sens armé sur l'or : il doit répondre
    au réglage comme l'autre, sans quoi le banc mesurerait deux règles."""
    serie = _serie_ecartee(1.2, "haut")
    assert PatternType.MEAN_REVERSION_DOWN not in _motifs(serie)

    monkeypatch.setattr(pd, "MEAN_REVERSION_SIGMA", 0.8)
    assert PatternType.MEAN_REVERSION_DOWN in _motifs(serie)


# ─── La bougie de confirmation reste exigée ──────────────────────────

def test_sans_bougie_de_RETOURNEMENT_rien_ne_sort(monkeypatch):
    """⛔ Le seuil n'est pas la seule condition.

    Prédiction 3 de la pré-inscription suppose que desserrer le seuil
    multiplie le nombre de signaux. Si la bougie de confirmation était la
    vraie contrainte, desserrer ne changerait presque rien — ce test fixe donc
    que les deux conditions sont bien distinctes et toutes deux actives.
    """
    prix = 4000.0
    bougies = [_c(prix + (1.0 if i % 2 else -1.0),
                  prix + 1.2, prix - 1.2,
                  prix + (1.0 if i % 2 else -1.0), i) for i in range(19)]
    cl = prix - 4.0
    # close < open : le prix s'écarte ENCORE, il ne revient pas
    bougies.append(_c(cl + 0.5, cl + 0.6, cl - 0.8, cl, 19))

    monkeypatch.setattr(pd, "MEAN_REVERSION_SIGMA", 0.5)
    assert PatternType.MEAN_REVERSION_UP not in _motifs(bougies)
