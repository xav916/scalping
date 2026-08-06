"""Ajustement du volume à la marge disponible (`mt5-bridge/bridge.py`).

Contexte 2026-08-06 : le compte Demo avait **564 € libres** et un plafond métal
à **0,1 lot**, soit ~1300 € de marge exigée sur l'or. Chaque ordre repartait en
`No money` (retcode 10019) et le compte ne tradait plus du tout — alors qu'il
pouvait parfaitement financer 0,01 lot.

Un plafond statique par classe ne règle pas ça : il redevient faux dès que le
solde bouge. D'où une réduction du volume calculée sur la marge réelle.

⚠️ Le point délicat n'est pas de réduire, c'est de **ne pas bloquer à tort**.
Une marge incalculable ou inconnue doit laisser passer l'ordre : le courtier
reste l'arbitre, et une panne de calcul ne doit pas arrêter le trading.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

_CHEMIN = Path(__file__).resolve().parents[2] / "mt5-bridge" / "bridge.py"
_spec = importlib.util.spec_from_file_location("bridge_margin_fit", _CHEMIN)
bridge = importlib.util.module_from_spec(_spec)
sys.modules["bridge_margin_fit"] = bridge
_spec.loader.exec_module(bridge)

fit = bridge._fit_volume_to_free_margin


def _marge_lineaire(par_lot):
    """Courtier simple : la marge est proportionnelle au volume."""
    return lambda v: v * par_lot


# ── Le cas qui a bloqué le compte ─────────────────────────────────────

def test_le_volume_est_reduit_pour_tenir_dans_la_marge():
    """0,1 lot d'or exige ~1300 €, le compte en a 564. Au lieu de `No money`,
    on descend au volume finançable."""
    v, motif = fit(volume=0.1, marge_pour=_marge_lineaire(13000.0),
                   marge_libre=564.0, volume_min=0.01, step=0.01)
    assert v is not None
    assert v <= 0.04, "0,04 lot exigerait 520 € : au-dessus des 90 % de 564 €"
    assert v >= 0.01
    assert motif == "reduit_pour_tenir_dans_la_marge"


def test_un_volume_finançable_passe_inchange():
    v, motif = fit(volume=0.01, marge_pour=_marge_lineaire(13000.0),
                   marge_libre=564.0, volume_min=0.01, step=0.01)
    assert v == 0.01
    assert motif is None


def test_refus_explicite_quand_meme_le_lot_minimum_ne_tient_pas():
    """Mieux vaut refuser en le disant que d'envoyer un ordre condamné : le
    backend ne sait pas distinguer un `No money` d'une panne du bridge."""
    v, motif = fit(volume=0.1, marge_pour=_marge_lineaire(13000.0),
                   marge_libre=50.0, volume_min=0.01, step=0.01)
    assert v is None
    assert motif == "marge_insuffisante_meme_au_lot_minimum"


def test_reduction_jusqu_au_lot_minimum():
    """La réduction proportionnelle tombe sous le minimum, mais le minimum
    lui-même tient : on le prend plutôt que de renoncer.

    Ce cas n'existe qu'avec un courtier à **levier dégressif** — la marge y
    croît plus vite que le volume, donc l'extrapolation depuis un gros volume
    sous-estime ce qu'un petit volume peut financer. C'est courant (paliers de
    levier au-delà d'un certain notionnel), et sans ce rattrapage on refuserait
    un ordre parfaitement finançable.
    """
    marge_degressive = lambda v: (v ** 2) * 100_000.0
    v, motif = fit(volume=1.0, marge_pour=marge_degressive,
                   marge_libre=150.0, volume_min=0.01, step=0.01)
    assert v == 0.01
    assert motif == "reduit_au_lot_minimum"
    assert marge_degressive(0.01) <= 150.0 * 0.90


# ── Ne jamais bloquer à tort ──────────────────────────────────────────

def test_marge_libre_inconnue_laisse_passer():
    """Fail-open : le courtier reste l'arbitre final."""
    v, motif = fit(volume=0.1, marge_pour=_marge_lineaire(13000.0),
                   marge_libre=None, volume_min=0.01, step=0.01)
    assert v == 0.1
    assert motif is None


def test_marge_exigee_incalculable_laisse_passer():
    v, motif = fit(volume=0.1, marge_pour=lambda _v: None,
                   marge_libre=564.0, volume_min=0.01, step=0.01)
    assert v == 0.1
    assert motif is None


def test_marge_libre_nulle_refuse():
    """Zéro n'est pas « inconnu » : c'est une information positive."""
    v, motif = fit(volume=0.1, marge_pour=_marge_lineaire(13000.0),
                   marge_libre=0.0, volume_min=0.01, step=0.01)
    assert v is None
    assert motif == "marge_libre_epuisee"


def test_marge_libre_negative_refuse():
    """Situation réelle du compte Live : marge libre négative."""
    v, motif = fit(volume=0.01, marge_pour=_marge_lineaire(13000.0),
                   marge_libre=-8.07, volume_min=0.01, step=0.01)
    assert v is None


# ── Respect des contraintes du courtier ───────────────────────────────

def test_le_volume_rendu_est_un_multiple_du_pas():
    v, _ = fit(volume=1.0, marge_pour=_marge_lineaire(1000.0),
               marge_libre=337.0, volume_min=0.01, step=0.05)
    assert v is not None
    crans = round(v / 0.05, 6)
    assert abs(crans - round(crans)) < 1e-6, f"{v} n'est pas un multiple de 0,05"


def test_une_reserve_est_gardee_sur_la_marge():
    """Consommer la marge au dernier centime placerait le compte en appel de
    marge au premier tick défavorable."""
    v, _ = fit(volume=1.0, marge_pour=_marge_lineaire(100.0),
               marge_libre=100.0, volume_min=0.01, step=0.01,
               part_utilisable=0.90)
    assert v is not None
    assert v * 100.0 <= 90.0 + 1e-9, "la marge exigée doit rester sous 90 %"


def test_un_courtier_non_lineaire_est_verifie_apres_arrondi():
    """La marge par lot peut croître par paliers. L'arrondi au pas ne doit pas
    laisser passer un volume finalement trop gros — d'où la vérification."""
    def paliers(v):
        return 10_000.0 if v >= 0.03 else 100.0
    v, motif = fit(volume=0.1, marge_pour=paliers,
                   marge_libre=1000.0, volume_min=0.01, step=0.01)
    assert v is None or paliers(v) <= 900.0
