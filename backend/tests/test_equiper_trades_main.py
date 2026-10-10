"""Équiper les trades ouverts À LA MAIN d'un stop et d'un objectif.

Demandé par Xavier le 2026-10-10, après la mesure des chemins du vendredi :
*« la version qui équipe tes trades à la main »*.

## 🔑 CE QUE LA MESURE DIT, et c'est la seule raison de ce module

Sur les 43 trades qu'il a ouverts dans le terminal MT5 le 2026-10-09 :

```
40 sur 43  n'ont NI stop NI objectif enregistrés chez le courtier
```

⇒ Ni l'échelle de gains, ni la protection des pertes à 5 min, ni les sondes P0
ne les voient. Ses trois pires de la journée — **258 min, 296 min, 19 min** —
font **−41,72 €** à eux seuls ; sans eux la main finissait à **+19,34 €**.
C'est exactement le profil que la protection des pertes attrape.

⛔ **Et ce n'est PAS une question de direction.** Mesuré sur 5 jours : la
direction du radar est indiscernable du hasard (aucune p sous 0,27), et celle
de Xavier n'est mesurable que sur un jour, où elle ne bat pas un biais acheteur
constant. Ce module ne prétend donc rien sur le sens — il ne fait que **borner
le risque de ce qu'il ouvre lui-même**.

## Les quatre gardes, et la raison de chacune

1. **Inerte par défaut** (`EQUIPER_TRADES_MAIN=0`) — rien ne bouge tant qu'il
   n'arme pas.
2. **Il COMBLE, il ne REMPLACE jamais.** Un stop déjà posé n'est pas touché :
   resserrer la protection de quelqu'un d'autre sans le lui dire serait pire
   que de ne rien faire.
3. ⛔ **Jamais de sortie immédiate.** Si la borne calculée est **déjà
   franchie** — la position perd plus que le stop, ou gagne plus que
   l'objectif — on ne la pose pas : poser un stop du mauvais côté du cours
   **ferme** la position. Fermer n'est pas protéger, et ce n'est pas ce qui a
   été demandé.
4. **L'or seul, et seulement ce que le radar n'a pas ouvert.** Les positions du
   radar ont déjà leurs bornes ; les toucher ici créerait deux autorités sur le
   même stop.
"""
from __future__ import annotations

import importlib

import pytest

TAUX = 1.1198          # EUR/USD déduit des trades du 09/10
MARQUE = "scalping-radar"


@pytest.fixture()
def E(monkeypatch):
    monkeypatch.setenv("EQUIPER_TRADES_MAIN", "1")
    monkeypatch.setenv("XAU_SL_FIXE_EUR", "20")
    monkeypatch.setenv("XAU_TP_FIXE_EUR", "2")
    from backend.services import equiper_trades_main as mod
    return importlib.reload(mod)


def _pos(sens="buy", entree=4190.0, courant=None, sl=0.0, tp=0.0,
         comment="", symbol="XAUUSD", ticket=777, volume=0.01):
    signe = 1 if sens == "buy" else -1
    return {"ticket": ticket, "symbol": symbol, "type": sens,
            "price_open": entree,
            "price_current": entree if courant is None else courant,
            "sl": sl, "tp": tp, "volume": volume, "comment": comment}


# ─────────────────────────────────────────────────────────────────────────
# 1. Le cas qui motive tout : une position NUE
# ─────────────────────────────────────────────────────────────────────────

def test_une_position_NUE_recoit_un_stop_ET_un_objectif(E):
    """🔑 40 des 43 trades du 09/10 étaient dans cet état."""
    d = E.decision(_pos(), TAUX)

    assert d is not None
    assert d["ticket"] == 777
    # stop a 20 EUR sous l'entree, objectif a 2 EUR au-dessus
    assert d["sl"] == pytest.approx(4190.0 - 20 * TAUX, abs=0.01)
    assert d["tp"] == pytest.approx(4190.0 + 2 * TAUX, abs=0.01)
    assert d["motif"] == "nue"


def test_pour_une_VENTE_les_bornes_sont_de_l_autre_cote(E):
    d = E.decision(_pos(sens="sell"), TAUX)

    assert d["sl"] == pytest.approx(4190.0 + 20 * TAUX, abs=0.01)
    assert d["tp"] == pytest.approx(4190.0 - 2 * TAUX, abs=0.01)


def test_il_COMBLE_le_stop_manquant_sans_toucher_a_l_objectif_pose(E):
    """⚠️ Garde n°2 : il comble, il ne remplace pas."""
    d = E.decision(_pos(tp=4195.0), TAUX)

    assert d["sl"] == pytest.approx(4190.0 - 20 * TAUX, abs=0.01)
    assert d["tp"] is None, "il a touché un objectif déjà posé"


def test_il_COMBLE_l_objectif_manquant_sans_toucher_au_stop_pose(E):
    d = E.decision(_pos(sl=4150.0), TAUX)

    assert d["tp"] == pytest.approx(4190.0 + 2 * TAUX, abs=0.01)
    assert d["sl"] is None, "il a touché un stop déjà posé"


def test_une_position_DEJA_BORNEE_est_laissee_tranquille(E):
    assert E.decision(_pos(sl=4150.0, tp=4195.0), TAUX) is None


# ─────────────────────────────────────────────────────────────────────────
# 2. ⛔ Jamais de sortie immédiate
# ─────────────────────────────────────────────────────────────────────────

def test_un_stop_DEJA_FRANCHI_n_est_PAS_pose(E):
    """⛔ GARDE N°3. La position perd 25 € alors que le stop irait à 20 € :
    poser ce stop le placerait du mauvais côté du cours et FERMERAIT la
    position. Fermer n'est pas protéger."""
    pos = _pos(courant=4190.0 - 25 * TAUX)      # -25 EUR
    d = E.decision(pos, TAUX)

    assert d is None or d["sl"] is None, "il a posé un stop déjà franchi"
    if d is not None:
        assert d.get("alerte"), "il a franchi le stop sans le DIRE"


def test_un_objectif_DEJA_DEPASSE_n_est_PAS_pose(E):
    """⛔ Même raison dans l'autre sens : un objectif derrière le cours
    encaisse immédiatement. C'est une décision de sortie, pas une protection."""
    pos = _pos(courant=4190.0 + 5 * TAUX)       # +5 EUR, objectif a +2
    d = E.decision(pos, TAUX)

    assert d is None or d["tp"] is None, "il a posé un objectif déjà dépassé"


def test_le_cas_LIMITE_juste_avant_la_borne_est_POSE(E):
    """⚠️ Le pendant du test précédent : s'il refusait trop large, il ne
    poserait jamais rien. À −19 € le stop de 20 € est encore devant."""
    pos = _pos(courant=4190.0 - 19 * TAUX)
    d = E.decision(pos, TAUX)

    assert d is not None and d["sl"] is not None


# ─────────────────────────────────────────────────────────────────────────
# 3. La portée
# ─────────────────────────────────────────────────────────────────────────

def test_une_position_DU_RADAR_n_est_pas_touchee(E):
    """⛔ Elle a déjà ses bornes et son échelle. Deux autorités sur le même
    stop, c'est un conflit silencieux."""
    assert E.decision(_pos(comment=MARQUE + "-2026-10-10"), TAUX) is None


def test_une_AUTRE_paire_n_est_pas_touchee(E):
    assert E.decision(_pos(symbol="EURUSD"), TAUX) is None


def test_sans_taux_on_ne_pose_RIEN(E):
    """⛔ Sans le taux, les euros sont inconvertibles : poser une borne
    calculée sur un taux faux serait pire que de ne rien poser."""
    assert E.decision(_pos(), 0) is None


def test_sans_prix_d_ouverture_on_ne_pose_RIEN(E):
    assert E.decision(_pos(entree=0.0), TAUX) is None


# ─────────────────────────────────────────────────────────────────────────
# 4. L'interrupteur
# ─────────────────────────────────────────────────────────────────────────

def test_INERTE_par_defaut(monkeypatch):
    """⚠️ Garde n°1. Rien ne bouge tant que Xavier n'arme pas."""
    monkeypatch.delenv("EQUIPER_TRADES_MAIN", raising=False)
    from backend.services import equiper_trades_main as mod
    importlib.reload(mod)

    assert mod.arme() is False
    assert mod.decision(_pos(), TAUX) is None


def test_les_bornes_suivent_les_REGLAGES_du_radar(monkeypatch):
    """🔑 Le stop et l'objectif ne sont pas écrits ici : ils viennent des mêmes
    réglages que le chemin automatique. Deux sources de vérité dériveraient."""
    monkeypatch.setenv("EQUIPER_TRADES_MAIN", "1")
    monkeypatch.setenv("XAU_SL_FIXE_EUR", "12")
    monkeypatch.setenv("XAU_TP_FIXE_EUR", "3")
    from backend.services import equiper_trades_main as mod
    importlib.reload(mod)

    d = mod.decision(_pos(), TAUX)
    assert d["sl"] == pytest.approx(4190.0 - 12 * TAUX, abs=0.01)
    assert d["tp"] == pytest.approx(4190.0 + 3 * TAUX, abs=0.01)


@pytest.mark.parametrize("mauvais", ["", "zero", "-5", "0"])
def test_un_reglage_ILLISIBLE_rend_le_module_MUET(monkeypatch, mauvais):
    """⛔ Ici le repli n'est PAS une valeur par défaut : un stop calculé sur un
    réglage illisible serait posé sur de l'argent réel. On préfère ne rien
    poser et le dire."""
    monkeypatch.setenv("EQUIPER_TRADES_MAIN", "1")
    monkeypatch.setenv("XAU_SL_FIXE_EUR", mauvais)
    monkeypatch.setenv("XAU_TP_FIXE_EUR", "2")
    from backend.services import equiper_trades_main as mod
    importlib.reload(mod)

    d = mod.decision(_pos(), TAUX)
    assert d is None or d["sl"] is None


# ─────────────────────────────────────────────────────────────────────────
# 5. ⛔ L'échelle et la protection doivent ADOPTER ces positions
# ─────────────────────────────────────────────────────────────────────────

def test_l_echelle_accepte_la_main_QUAND_C_EST_ARME(monkeypatch):
    """⛔ Sans cela, équiper ne servirait qu'une fois : le stop serait posé et
    ne SUIVRAIT jamais le gain. Tout l'intérêt est que la position entre
    ensuite dans l'échelle et dans la protection des pertes."""
    monkeypatch.setenv("EQUIPER_TRADES_MAIN", "1")
    monkeypatch.setenv("ECHELLE_STOP_OR", "1")
    monkeypatch.setenv("ECHELLE_STOP_OR_PALIERS", "1.0:0.75,1.5:1.25")
    from backend.services import echelle_stop_or as mod
    importlib.reload(mod)

    signe = 1
    pos = {"ticket": 9, "symbol": "XAUUSD", "type": "buy",
           "price_open": 4190.0,
           "price_current": 4190.0 + 1.5 * TAUX,
           "sl": 4190.0 - 20 * TAUX, "tp": 4190.0 + 2 * TAUX,
           "volume": 0.01, "comment": ""}          # <- A LA MAIN
    d = mod.decision(pos, TAUX)

    assert d is not None, "l'échelle ignore encore les trades à la main"


def test_l_echelle_IGNORE_la_main_quand_ce_n_est_PAS_arme(monkeypatch):
    """⚠️ Le pendant : désarmé, le comportement d'avant est EXACTEMENT
    conservé."""
    monkeypatch.delenv("EQUIPER_TRADES_MAIN", raising=False)
    monkeypatch.setenv("ECHELLE_STOP_OR", "1")
    monkeypatch.setenv("ECHELLE_STOP_OR_PALIERS", "1.0:0.75,1.5:1.25")
    from backend.services import echelle_stop_or as mod
    importlib.reload(mod)

    pos = {"ticket": 9, "symbol": "XAUUSD", "type": "buy",
           "price_open": 4190.0,
           "price_current": 4190.0 + 1.5 * TAUX,
           "sl": 4190.0 - 20 * TAUX, "tp": 4190.0 + 2 * TAUX,
           "volume": 0.01, "comment": ""}
    assert mod.decision(pos, TAUX) is None
