"""Protection des pertes : resserrer le stop d'un trade durablement négatif.

Règle dictée par Xavier le 2026-10-09 :

> « Laisser le trade évoluer pendant 5 min après l'ouverture. Sur la liste de
> trades négatifs à 5 minutes, si le trade est négatif depuis la moitié de la
> fourchette des 5 min, alors updater le SL à la valeur
> `SL + distance(ouverture, cours XAU/USD) / 2`.
> Exemple : SL initial à 20 €, négatif depuis plus de 2 min 30, cours à −5 €
> ⇒ nouveau SL à `(20 + 5) / 2`. Opération toutes les 5 min. »

🔑 **LECTURE DE LA FORMULE, vérifiée sur son exemple** : `(20 + 5)/2 = 12,5`.
C'est le **point milieu entre le stop actuel et le cours actuel**. Le risque
restant passe de 20 € à 12,5 €, en laissant 7,5 € de marge sous le prix.

## ⚠️ LA CONVERGENCE, MESURÉE AVANT D'ÊTRE CODÉE

Le courtier n'impose **aucune** distance minimale sur l'or
(`trade_stops_level = 0`). Rien n'arrête donc la formule appliquée en boucle,
sur un trade qui reste à −5 € :

```
 5 min  12,50 €   marge 7,50      25 min   5,47 €   marge 0,47
15 min   6,88 €   marge 1,88      35 min   5,12 €   marge 0,12
```

⇒ Le stop **colle au prix en ~25 min**, et comme une oscillation normale de
l'or vaut ~0,25 €, le trade serait coupé par le **bruit**. Ce serait une
fermeture déguisée en stop, indistinguable d'un vrai stop dans la mesure.

**Décision de Xavier après cette mesure : plancher à 2 € de marge.** On
resserre tant qu'il reste au moins 2 € entre le stop et le prix, puis on
s'arrête.

## 🔑 POURQUOI CETTE RÈGLE A BESOIN DE LA SONDE

« Négatif depuis 2 min 30 » n'est pas lisible d'un seul coup d'œil : il faut
une **histoire**. La sonde de l'échelle, qui échantillonne aux 5 s, tient
`negatif_depuis`. Cette règle la **lit** au lieu de la deviner.

⛔ Et si la sonde ne tourne pas, `negatif_depuis` est absent ⇒ on **ne fait
rien**. « Je ne sais pas depuis quand » n'est pas « ça fait plus de 2 min 30 ».

## Périmètre : trades du RADAR seulement

Décision de Xavier. Même convention que l'échelle de gains : on ne touche pas
aux stops qu'il a posés lui-même dans le terminal.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = (Path(__file__).resolve().parents[2] / "scripts"
           / "protection_perte_or.py")

TAUX = 1.1235
MARQUE = "scalping-radar-2026-10-09"


@pytest.fixture()
def p():
    spec = importlib.util.spec_from_file_location("protection_perte_or", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pos(sens="buy", entree=4190.0, perte_eur=5.0, stop_eur=20.0,
         comment=MARQUE, ticket=1):
    """Une position d'or a `perte_eur` de perte, stop a `stop_eur` de l'entree."""
    signe = 1 if sens == "buy" else -1
    courant = entree - signe * perte_eur * TAUX
    sl = entree - signe * stop_eur * TAUX
    return {"ticket": ticket, "symbol": "XAUUSD", "type": sens,
            "price_open": entree, "price_current": courant, "sl": sl,
            "tp": 0.0, "volume": 0.01, "comment": comment}


# ─────────────────────────────────────────────────────────────────────────
# 1. L'EXEMPLE DE XAVIER, au centime
# ─────────────────────────────────────────────────────────────────────────

def test_l_exemple_de_Xavier_donne_bien_douze_euros_cinquante(p):
    """SL 20 €, perte 5 € => (20+5)/2 = 12,50 € de distance."""
    d = p.nouveau_stop_eur(stop_eur=20.0, perte_eur=5.0, marge_min_eur=2.0)

    assert d == pytest.approx(12.50)


@pytest.mark.parametrize("stop,perte,attendu", [
    (20.0, 5.0, 12.50),
    (20.0, 10.0, 15.00),
    (12.5, 5.0, 8.75),
    # ⚠️ ICI LE PLANCHER MORD, et ma premiere version du test l'avait oublie :
    # le point milieu brut vaut 6,875, mais il ne laisserait que 1,875 EUR de
    # marge — sous les 2 EUR decides par Xavier. On s'arrete donc a 7,00
    # (perte 5 + plancher 2). Le code avait raison, pas mon attente.
    (8.75, 5.0, 7.00),
])
def test_la_formule_est_le_point_MILIEU_sous_le_plancher(p, stop, perte, attendu):
    assert p.nouveau_stop_eur(stop, perte, 2.0) == pytest.approx(attendu)


def test_le_PRIX_du_stop_pour_un_BUY_descend_sous_l_entree(p):
    pos = _pos("buy", entree=4190.0, perte_eur=5.0, stop_eur=20.0)

    prix = p.stop_vise_prix(pos, TAUX, marge_min_eur=2.0)

    # 12,50 € sous l'entree, en dollars.
    assert prix == pytest.approx(4190.0 - 12.50 * TAUX, abs=0.01)
    assert prix < pos["price_open"]
    # …et il est REMONTE par rapport a l'ancien stop (resserrement).
    assert prix > pos["sl"]


def test_le_PRIX_du_stop_pour_un_SELL_est_au_dessus_de_l_entree(p):
    pos = _pos("sell", entree=4190.0, perte_eur=5.0, stop_eur=20.0)

    prix = p.stop_vise_prix(pos, TAUX, marge_min_eur=2.0)

    assert prix == pytest.approx(4190.0 + 12.50 * TAUX, abs=0.01)
    assert prix > pos["price_open"]
    # …et il est DESCENDU par rapport a l'ancien stop (resserrement).
    assert prix < pos["sl"]


# ─────────────────────────────────────────────────────────────────────────
# 2. ⛔ LE PLANCHER — décision de Xavier après la mesure
# ─────────────────────────────────────────────────────────────────────────

def test_le_plancher_empeche_le_stop_de_coller_au_prix(p):
    """⛔ Sans lui, un trade negatif depuis 25 min sort au BRUIT. Mesure :
    marge residuelle 0,47 € contre ~0,25 € d'oscillation normale.

    ⚠️ MA PREMIERE VERSION DE CE TEST SE CONTREDISAIT avec son voisin : j'y
    partais d'un stop a 5,47 € — DEJA plus serre que le plancher de 7,00 — et
    j'attendais 7,00, c'est-a-dire un DESSERREMENT. Le code refusait, et il
    avait raison.

    🔑 Le plancher doit se demontrer sur un stop qui est ENCORE au-dessus de
    lui : 8,75 € de stop, dont le point milieu brut (6,875) tomberait sous le
    plancher.
    """
    # Point milieu brut : (8,75 + 5)/2 = 6,875 => marge 1,875 €, sous les 2 €.
    d = p.nouveau_stop_eur(stop_eur=8.75, perte_eur=5.0, marge_min_eur=2.0)

    # Clampe a perte + marge_min = 7,00 : on s'arrete au plancher.
    assert d == pytest.approx(7.00)
    # …et la marge residuelle vaut bien le plancher, jamais moins.
    assert d - 5.0 == pytest.approx(2.0)


def test_un_stop_DEJA_dans_le_plancher_ne_bouge_PAS(p):
    """⛔ Et surtout il ne DESSERRE pas : rendre 7,00 quand le stop est deja a
    6,00 l'eloignerait du prix, soit l'inverse d'une protection."""
    assert p.nouveau_stop_eur(stop_eur=6.0, perte_eur=5.0, marge_min_eur=2.0) is None
    assert p.nouveau_stop_eur(stop_eur=7.0, perte_eur=5.0, marge_min_eur=2.0) is None


def test_la_suite_des_passes_CONVERGE_vers_le_plancher_et_s_arrete(p):
    """La trajectoire complete, telle qu'elle se produira en production."""
    d, vus = 20.0, []
    for _ in range(8):
        n = p.nouveau_stop_eur(d, 5.0, 2.0)
        if n is None:
            break
        d = n
        vus.append(round(d, 2))

    # ⚠️ Pas de palier intermediaire a 7,38 : depuis 8,75 le point milieu
    # brut (6,875) passe SOUS le plancher, donc on va directement a 7,00.
    assert vus == [12.5, 8.75, 7.0]
    # 🔑 Et ça S'ARRETE : 7,00 = perte 5 + plancher 2.
    assert p.nouveau_stop_eur(7.0, 5.0, 2.0) is None


# ─────────────────────────────────────────────────────────────────────────
# 3. ⛔ Les conditions d'éligibilité
# ─────────────────────────────────────────────────────────────────────────

def test_avant_CINQ_minutes_on_laisse_le_trade_evoluer(p):
    ok, motif = p.eligible(ouvert_depuis_sec=299, perte_eur=5.0,
                           negatif_depuis_sec=280)

    assert ok is False
    assert "5 min" in motif or "300" in motif


def test_negatif_depuis_MOINS_de_deux_minutes_trente_on_attend(p):
    ok, motif = p.eligible(ouvert_depuis_sec=600, perte_eur=5.0,
                           negatif_depuis_sec=149)

    assert ok is False
    assert "150" in motif or "2 min 30" in motif


def test_un_trade_en_PROFIT_ne_releve_pas_de_cette_regle(p):
    """🔑 Le profit est le domaine de l'echelle de GAINS. Deux regles sur le
    meme stop doivent avoir des domaines disjoints."""
    ok, motif = p.eligible(ouvert_depuis_sec=600, perte_eur=-1.5,
                           negatif_depuis_sec=600)

    assert ok is False
    assert "profit" in motif.lower() or "positif" in motif.lower()


def test_les_conditions_REUNIES_rendent_eligible(p):
    ok, motif = p.eligible(ouvert_depuis_sec=301, perte_eur=5.0,
                           negatif_depuis_sec=151)

    assert ok is True
    assert motif == ""


def test_negatif_depuis_INCONNU_on_ne_fait_RIEN(p):
    """⛔ FAIL-CLOSED. « Je ne sais pas depuis quand » n'est pas « ça fait plus
    de 2 min 30 ». Si la sonde ne tourne pas, on s'abstient."""
    ok, motif = p.eligible(ouvert_depuis_sec=600, perte_eur=5.0,
                           negatif_depuis_sec=None)

    assert ok is False
    assert "inconnu" in motif.lower() or "sonde" in motif.lower()


# ─────────────────────────────────────────────────────────────────────────
# 4. ⛔ Périmètre et garde-fous
# ─────────────────────────────────────────────────────────────────────────

def test_une_position_A_LA_MAIN_est_ECARTEE(p):
    """Decision de Xavier : trades du RADAR seulement. Meme convention que
    l'echelle de gains."""
    pos = _pos(comment="")

    assert p.stop_vise_prix(pos, TAUX, 2.0) is None


def test_une_paire_qui_n_est_pas_de_l_or_est_ecartee(p):
    pos = _pos()
    pos["symbol"] = "EURUSD"

    assert p.stop_vise_prix(pos, TAUX, 2.0) is None


def test_un_taux_ABSENT_n_invente_aucune_distance(p):
    """⛔ Sans le taux, les euros sont inconvertibles."""
    assert p.stop_vise_prix(_pos(), 0, 2.0) is None
    assert p.stop_vise_prix(_pos(), None, 2.0) is None


def test_une_position_SANS_STOP_n_est_pas_touchee(p):
    """⚠️ Pas de stop = rien a resserrer, et surtout : la regle ne doit pas en
    INVENTER un. Proteger une position nue est le travail du garde-fou SL/TP,
    qui a ses propres regles."""
    pos = _pos()
    pos["sl"] = 0.0

    assert p.stop_vise_prix(pos, TAUX, 2.0) is None


def test_un_stop_DEJA_du_cote_du_profit_n_est_pas_touche(p):
    """⛔ LE PIEGE : cette regle ne doit JAMAIS entrer dans le domaine du
    profit, qui appartient a l'echelle de GAINS. Deux regles avec deux
    formules sur le meme stop finiraient par se contredire.

    ⚠️ MON PREMIER TEST N'ISOLAIT PAS CE GARDE. Je l'avais ecrit avec une
    perte de 5 € : dans ce cas le garde du PLANCHER (`stop <= perte + marge`)
    repondait deja `None`, et retirer `stop_eur <= 0` ne faisait tomber aucun
    test. Trouve en reinjectant le defaut.

    🔑 Pour isoler ce garde il faut une position EN PROFIT dont le stop est
    DEJA cote profit — le seul cas que le plancher ne couvre pas.
    """
    # +5 € de profit, stop remonte a +0,75 € par l'echelle de gains.
    pos = _pos("buy", entree=4190.0, perte_eur=-5.0, stop_eur=20.0)
    pos["sl"] = 4190.0 + 0.75 * TAUX

    assert p.stop_vise_prix(pos, TAUX, 2.0) is None, (
        "la regle de PERTE a touche un stop deja dans le PROFIT : elle empiete "
        "sur l'echelle de gains")


def test_le_PLANCHER_et_le_CLIQUET_se_recouvrent_a_dessein(p):
    """⚠️ Constat honnete, pose apres reinjection : retirer le garde du
    plancher (`stop <= perte + marge`) ne change AUCUN comportement, parce que
    le cliquet final (`vise >= stop`) rend `None` dans les memes cas.

    Les deux gardes expriment le meme invariant par deux chemins. On les garde
    tous les deux — un seul suffirait, mais celui du plancher dit l'INTENTION
    (on ne descend pas sous la marge minimale) la ou le cliquet dit seulement
    la MECANIQUE (on ne desserre jamais). Ce test epingle l'invariant, pas le
    chemin.
    """
    for stop in (5.0, 6.0, 6.99, 7.0):
        assert p.nouveau_stop_eur(stop, 5.0, 2.0) is None, stop
    # …et juste au-dessus, ca resserre bien.
    assert p.nouveau_stop_eur(7.01, 5.0, 2.0) == pytest.approx(7.0)


# ═══════════════════════════════════════════════════════════════════════
# ADOPTION DES TRADES A LA MAIN — 2026-10-10
# ═══════════════════════════════════════════════════════════════════════
#
# 🔑 Mesure du 09/10 : les trois pires trades que Xavier a ouverts dans le
# terminal MT5 (258 min, 296 min, 19 min) font **-41,72 EUR** a eux seuls, et
# sans eux sa main finissait a +19,34 EUR. C'est exactement le profil que cette
# protection attrape — mais elle ne les voyait pas.

def test_un_trade_A_LA_MAIN_est_protege_QUAND_C_EST_ARME(p, monkeypatch):
    """⛔ Sans cette adoption, leur equiper un stop initial ne servirait qu'a
    moitie : il ne se resserrerait jamais."""
    monkeypatch.setenv("EQUIPER_TRADES_MAIN", "1")

    prix = p.stop_vise_prix(_pos(comment=""), TAUX)

    assert prix is not None, "la protection ignore encore les trades a la main"


def test_un_trade_A_LA_MAIN_est_IGNORE_sans_armement(p, monkeypatch):
    """⚠️ Le pendant : desarme, le comportement d'avant est EXACTEMENT
    conserve."""
    monkeypatch.delenv("EQUIPER_TRADES_MAIN", raising=False)

    assert p.stop_vise_prix(_pos(comment=""), TAUX) is None


def test_un_trade_DU_RADAR_reste_protege_dans_les_deux_cas(p, monkeypatch):
    """⚠️ L'adoption ELARGIT, elle ne remplace pas : ce qui etait protege doit
    le rester."""
    for arme in ("1", None):
        if arme:
            monkeypatch.setenv("EQUIPER_TRADES_MAIN", arme)
        else:
            monkeypatch.delenv("EQUIPER_TRADES_MAIN", raising=False)
        assert p.stop_vise_prix(_pos(), TAUX) is not None, arme
