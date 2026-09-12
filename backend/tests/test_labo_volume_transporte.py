"""Le volume arrivait au pont et mourait à la frontière du laboratoire.

⛔ `laboratoire_or.detections()` construisait ses bougies avec `volume=0.0`
**en dur**. C'était juste tant que la seule source était Twelve Data, qui rend
zéro partout (vérifié en production le 12/09 : 0 bougie à volume > 0 sur
XAU/USD, XAG/USD et EUR/USD).

Mais le laboratoire ne lit PAS Twelve Data : `_bougies_et_spread` interroge
`/rates` du pont MT5, parce que le pont sert l'historique gratuitement là où
le quota Twelve Data a déjà saturé (954 refus 429). Et `/rates` transporte
désormais `tv` et `rv`.

⇒ Sans ce câblage, le volume traverserait le réseau pour être écrasé par un
zéro littéral au moment de construire l'objet `Candle`.

## 🔑 Pourquoi ce câblage ne change AUCUNE mesure existante

Vérifié avant d'écrire une ligne : **aucun détecteur ne lit `volume`**. Les 30
motifs mesurés chaque nuit restent donc comparables d'une nuit à l'autre, y
compris à cheval sur ce changement. Sans cette vérification, on aurait pu
déplacer tous les verdicts du laboratoire en croyant n'ajouter qu'un champ.

## ⚠️ `tv`, pas `rv`

`tv` (tick volume) compte les changements de prix ; `rv` (real volume) compte
les contrats, et vaut zéro chez les courtiers CFD. C'est `tv` qui alimente le
profil, et il doit être nommé pour ce qu'il est — un compte de ticks.
"""
from datetime import datetime, timezone

import pytest

from backend.services import laboratoire_or as labo


def _brut(i: int, tv=None, rv=None):
    """Une bougie telle que `/rates` la rend."""
    b = {"t": datetime(2026, 9, 12, 0, i % 60, tzinfo=timezone.utc).isoformat(),
         "o": 4300.0 + i, "h": 4302.0 + i, "l": 4298.0 + i, "c": 4301.0 + i,
         "s": 24}
    if tv is not None:
        b["tv"] = tv
    if rv is not None:
        b["rv"] = rv
    return b


def _candles_construites(bougies, monkeypatch):
    """Récupère les `Candle` que `detections` fabrique, sans rien détecter."""
    vues = []

    def _faux_detect(fenetre, pair):
        vues.extend(fenetre)
        return []

    monkeypatch.setattr("backend.services.pattern_detector.detect_patterns",
                        _faux_detect)
    labo.detections(bougies, "XAU/USD")
    return vues


def test_le_tick_volume_ARRIVE_jusqu_au_detecteur(monkeypatch):
    """⛔ LE câblage : sans lui, `tv` traverse le réseau pour être écrasé."""
    bougies = [_brut(i, tv=100 + i) for i in range(labo.FENETRE + 3)]
    vues = _candles_construites(bougies, monkeypatch)
    assert vues, "aucune bougie construite"
    assert any(c.volume > 0 for c in vues), "le volume est reste a zero"
    assert {c.volume for c in vues} != {0.0}


def test_une_bougie_SANS_volume_ne_fait_pas_tomber_la_nuit(monkeypatch):
    """⚠️ Les ponts non redeployes rendront des bougies sans `tv`. Le labo doit
    continuer a mesurer les prix — une nuit perdue coute plus qu'un champ."""
    bougies = [_brut(i) for i in range(labo.FENETRE + 3)]
    vues = _candles_construites(bougies, monkeypatch)
    assert vues
    assert all(c.volume == 0.0 for c in vues)


def test_c_est_TV_qui_alimente_le_profil_pas_RV(monkeypatch):
    """🔑 `rv` vaut zero chez les courtiers CFD. Prendre `rv` rendrait un
    profil vide en croyant mesurer le marche."""
    bougies = [_brut(i, tv=500, rv=0) for i in range(labo.FENETRE + 3)]
    vues = _candles_construites(bougies, monkeypatch)
    assert all(c.volume == 500 for c in vues), "c'est rv qui a ete pris"


def test_les_PRIX_ne_bougent_pas(monkeypatch):
    """Le refactor ne doit toucher qu'au volume."""
    bougies = [_brut(i, tv=7) for i in range(labo.FENETRE + 3)]
    vues = _candles_construites(bougies, monkeypatch)
    c = vues[0]
    assert c.open == pytest.approx(4300.0)
    assert c.high == pytest.approx(4302.0)
    assert c.low == pytest.approx(4298.0)
    assert c.close == pytest.approx(4301.0)
