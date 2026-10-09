"""Le veilleur de la marge de l'or : DIRE pourquoi l'or automatique dort.

## ⛔ CE QU'IL EXISTE POUR EMPÊCHER

Le 2026-10-09, Xavier a demandé pourquoi aucun ordre d'or automatique ne
partait. Rien n'était cassé : l'interrupteur était armé, les signaux
sortaient, les portes faisaient leur tri. Le compte ne pouvait simplement pas
porter une position de plus.

🔑 **Et ce n'est pas le courtier qui refusait.** Sa propre simulation
(`/order_check`) rendait `retcode 0`, commentaire « Done » : il acceptait
l'ordre. C'est **notre** plancher `MARGE_LIBRE_MIN_PCT = 30` qui le refusait,
pour garder de la distance avec la liquidation — le niveau de marge serait
tombé à 140 %.

⇒ Un refus parfaitement justifié, parfaitement invisible. Il fallait **une
mesure** à lire, pas une porte à desserrer.
→ [[feedback_ne_pas_desserrer_les_portes]]

## L'arithmétique que ce veilleur rend lisible

Une position d'or à 0,01 lot coûte **186,75 €** de marge (mesuré : 373,49 €
pour deux). Notre plancher exige `marge libre après ordre ≥ 30 % de l'équité`,
donc pour **N** positions :

```
equite - N x marge_par_position >= 0,30 x equite
       <=>  equite >= N x marge_par_position / 0,70
```

| N | équité requise | équité réelle du 09/10 (524,13 €) |
|---|---|---|
| 1 | 266,78 € | ✅ |
| 2 | **533,56 €** | ❌ il manque **9,43 €** |
| 3 | 800,35 € | ❌ il manque 276,22 € |

🔑 Le lot est **déjà au minimum** (`volume_min` et `volume_step` tous deux à
0,01) : il n'y a rien en dessous. La seule variable qui ne touche aucune porte
est l'**équité**.

## ⛔ Les quatre façons dont ce veilleur pourrait trahir

1. **Se taire quand c'est bloqué** — il ne servirait à rien.
2. **Se taire quand il n'a pas pu lire** — « je n'ai pas regardé » n'est pas
   « tout va bien ».
3. **Parler à chaque passage** — une alerte répétée n'est plus lue (les 8
   doublons du 07/10). D'où un `dedup_key` porté par l'IDENTITÉ du blocage :
   il parle quand le blocage CHANGE, pas à chaque tick.
4. ⛔ **Inventer la marge par position quand il n'y a aucune position
   ouverte.** `margin / 0` n'existe pas. Il doit le DIRE et se replier sur la
   valeur MESURÉE, étiquetée comme telle.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = (Path(__file__).resolve().parents[2] / "scripts"
           / "veilleur_marge_or.py")


@pytest.fixture()
def v():
    spec = importlib.util.spec_from_file_location("veilleur_marge", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Les chiffres EXACTS releves sur le compte reel le 2026-10-09 a 12h52 UTC.
COMPTE_DEUX = {
    "balance": 530.31, "equity": 524.13, "margin": 373.49,
    "margin_free": 150.64, "positions_count": 2, "currency": "EUR",
}
GARDES = {
    "marge_libre_min_pct": 30.0,
    "max_risque_engage_or_argent_pct": 20.0,
    "daily_loss": 180.90,
    "daily_loss_limit": 70.18,
}


def test_la_marge_par_position_est_MESUREE_pas_supposee(v):
    """On DIVISE ce que le courtier declare : 373,49 € pour deux positions
    ⇒ 186,745 € l'unité.

    ⛔ **ET LE CHIFFRE EST CHOISI POUR QUE LE TEST PUISSE ECHOUER.** Ma
    premiere version assertait sur `186.745` — exactement la valeur de
    `MARGE_PAR_POSITION_MESUREE`. Coder la constante en dur passait donc le
    test : il ne distinguait pas « divise » de « suppose ». Reinjecte comme
    defaut, il ne tombait pas.

    🔑 Un test dont l'attendu coincide avec le repli ne teste rien. Celui-ci
    utilise une marge dont la moitie DIFFERE de la constante.
    """
    # 400 / 2 = 200, et la constante vaut 186,745 : les deux sont distinguables.
    compte = {**COMPTE_DEUX, "margin": 400.0, "positions_count": 2}
    assert v.marge_par_position(compte) == pytest.approx(200.0)
    assert v.marge_par_position(compte) != pytest.approx(
        v.MARGE_PAR_POSITION_MESUREE)

    # Et sur les chiffres reels du 09/10, la division redonne bien la mesure.
    assert v.marge_par_position(COMPTE_DEUX) == pytest.approx(186.745)


def test_sans_aucune_position_la_marge_unitaire_est_un_REPLI_etiquete(v):
    """⛔ `margin / 0` n'existe pas. Le veilleur doit se replier sur la valeur
    MESUREE et DIRE que c'en est une — pas la faire passer pour une mesure du
    moment."""
    compte = {**COMPTE_DEUX, "margin": 0.0, "positions_count": 0,
              "margin_free": 524.13}

    valeur, mesuree = v.marge_par_position_et_origine(compte)

    assert valeur == pytest.approx(v.MARGE_PAR_POSITION_MESUREE)
    assert mesuree is False


def test_equite_requise_pour_N_positions(v):
    """La formule, sur les trois cas qui comptent."""
    m = 186.745
    assert v.equite_requise(1, m, 30.0) == pytest.approx(266.78, abs=0.01)
    assert v.equite_requise(2, m, 30.0) == pytest.approx(533.56, abs=0.01)
    assert v.equite_requise(3, m, 30.0) == pytest.approx(800.34, abs=0.01)


def test_avec_DEUX_positions_a_la_main_c_est_la_MARGE_qui_bloque(v):
    """Le cas de Xavier le 09/10 : il tient deux positions et demande que
    l'automatique fasse avec. Il faudrait 800 € d'equite ; le compte en a
    524."""
    d = v.diagnostic(COMPTE_DEUX, GARDES)

    assert d["verdict"] == "BLOQUE"
    assert d["blocage"] == "marge"
    assert d["positions_ouvertes"] == 2
    assert d["equite_requise"] == pytest.approx(800.34, abs=0.05)
    assert d["manque_euros"] == pytest.approx(276.21, abs=0.05)


def test_avec_UNE_position_il_ne_manque_que_neuf_euros(v):
    """🔑 Le chiffre qui change la decision : avec une seule position a la
    main, la coexistence est a **9,43 €** d'equite. C'est atteignable par son
    propre scalping (+6,54 € ce jour-la), sans desserrer quoi que ce soit."""
    compte = {**COMPTE_DEUX, "margin": 186.745, "positions_count": 1,
              "margin_free": 337.385}

    d = v.diagnostic(compte, GARDES)

    assert d["blocage"] == "marge"
    assert d["equite_requise"] == pytest.approx(533.56, abs=0.05)
    assert d["manque_euros"] == pytest.approx(9.43, abs=0.05)


def test_marge_suffisante_le_PLAFOND_JOURNALIER_prend_le_relais(v):
    """⚠️ Annoncer « ça passe » alors qu'une autre porte refuse serait une
    fausse bonne nouvelle. Le veilleur nomme le blocage SUIVANT."""
    compte = {**COMPTE_DEUX, "margin": 0.0, "positions_count": 0,
              "equity": 900.0, "margin_free": 900.0}

    d = v.diagnostic(compte, GARDES)

    assert d["verdict"] == "BLOQUE"
    assert d["blocage"] == "plafond_journalier"


def test_rien_ne_bloque_quand_les_deux_portes_passent(v):
    compte = {**COMPTE_DEUX, "margin": 0.0, "positions_count": 0,
              "equity": 900.0, "margin_free": 900.0}
    gardes = {**GARDES, "daily_loss": 5.0, "daily_loss_limit": 90.0}

    d = v.diagnostic(compte, gardes)

    assert d["verdict"] == "PASSE"
    assert d["blocage"] is None


def test_un_compte_ILLISIBLE_n_est_pas_un_compte_qui_passe(v):
    """⛔ La deuxieme façon de trahir. « Je n'ai pas pu regarder » doit rendre
    un verdict distinct de « tout va bien »."""
    d = v.diagnostic(None, GARDES)

    assert d["verdict"] == "ILLISIBLE"
    assert d["blocage"] == "mesure_absente"


def test_le_plancher_DESARME_ne_bloque_plus_sur_la_marge(v):
    """`marge_libre_min_pct <= 0` desarme la porte cote pont : le veilleur doit
    lire le MEME reglage, sinon il annoncerait un blocage qui n'existe pas."""
    gardes = {**GARDES, "marge_libre_min_pct": 0.0,
              "daily_loss": 5.0, "daily_loss_limit": 90.0}

    d = v.diagnostic(COMPTE_DEUX, gardes)

    assert d["blocage"] is None


# ─────────────────────────────────────────────────────────────────────────
# Le message, et sa discretion
# ─────────────────────────────────────────────────────────────────────────

def test_la_cle_de_dedup_porte_l_IDENTITE_du_blocage(v):
    """🔑 C'est ce qui le rend discret : il parle quand le blocage CHANGE, pas
    a chaque passage. Deux etats differents => deux cles differentes."""
    bloque_marge = v.diagnostic(COMPTE_DEUX, GARDES)
    compte_libre = {**COMPTE_DEUX, "margin": 0.0, "positions_count": 0,
                    "equity": 900.0, "margin_free": 900.0}
    bloque_plafond = v.diagnostic(compte_libre, GARDES)

    assert v.cle_dedup(bloque_marge) != v.cle_dedup(bloque_plafond)
    # …et le MEME etat rend la MEME cle, sinon le cooldown ne mordrait jamais.
    assert v.cle_dedup(bloque_marge) == v.cle_dedup(
        v.diagnostic(COMPTE_DEUX, GARDES))


def test_le_message_DIT_le_chiffre_qui_manque(v):
    """Un veilleur qui dit « bloque » sans dire de combien oblige a refaire le
    calcul a la main. C'est ce qu'on remplace."""
    corps = v.corps(v.diagnostic(COMPTE_DEUX, GARDES))

    assert "800" in corps
    assert "276" in corps
    assert "0,01" in corps or "0.01" in corps


def test_le_message_RAPPELLE_que_le_courtier_accepte(v):
    """🔑 Sans cela, Xavier lirait « marge insuffisante » et croirait son
    compte a la limite de la liquidation. C'est NOTRE plancher, pas celui du
    courtier — et la distinction change ce qu'il y a a faire."""
    corps = v.corps(v.diagnostic(COMPTE_DEUX, GARDES))

    assert "30" in corps
    assert "notre" in corps.lower() or "nôtre" in corps.lower()
