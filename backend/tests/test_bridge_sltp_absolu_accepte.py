"""`sl_absolu` doit être ACCEPTÉ : la validation se contredisait elle-même.

## ⛔ LE DÉFAUT, trouvé par la question de Xavier le 2026-10-09

> « Pourquoi les SL n'ont pas évolué car les trades sont passés au-delà d'1 € »

La sonde posée pour répondre l'a prouvé en une heure — trois positions du radar
ont atteint un palier et leur stop n'a **pas** bougé :

```
1360846647 buy  max vu +1,81 €  palier 1,5   sl au max 4167,71  sl après 4167,71
1360846648 buy  max vu +1,81 €  palier 1,5   sl au max 4167,71  sl après 4167,71
1360844168 buy  max vu +1,37 €  palier 1,0   sl au max 4167,99  sl après 4167,99
```

Et le journal du pont montrait la cause : **HTTP 400 à chaque passage**.

```
charge : {'ticket': …, 'sl_absolu': 4205.28, 'deplacer': True}
=> 400 {"error":"sl_dist doit être > 0"}
```

## 🔑 LA CONTRADICTION, en quatre lignes

```python
except (TypeError, ValueError):
    if sl_absolu is None:
        return 400 "sl_dist (float > 0) ou sl_absolu requis"
    sl_dist = 0.0                            # sl_absolu fourni : on met 0
if sl_dist <= 0:
    return 400 "sl_dist doit être > 0"       # ET ON REFUSE CE 0
```

Le repli pose `sl_dist = 0` **précisément** quand `sl_absolu` est fourni, et la
ligne suivante rejette ce zéro. ⇒ **Fournir `sl_absolu` ne pouvait JAMAIS
marcher.** L'échelle de gains était donc **100 % inerte** depuis son
déploiement du matin.

⛔ **Et mon message de commit de ce matin affirmait « le pont accepte
`sl_absolu` », et « vérifié en production, les six paliers ».** J'avais vérifié
le CALCUL du prix, jamais la ROUTE. Une vérification qui ne traverse pas le
chemin réel n'est pas une vérification.

## 🔑 Pourquoi une fonction pure plutôt qu'un rustine d'une ligne

La condition manquante (`sl_absolu is None and sl_dist <= 0`) se corrige en un
caractère — mais la validation restait un enchevêtrement de `try`, de replis et
de retours anticipés où la contradiction était invisible. Elle est extraite :
`_lire_sl_demande(data)`, testable sans Flask ni MT5.
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "mt5-bridge" / "bridge.py"


@pytest.fixture()
def b():
    src = _SRC.read_text(encoding="utf-8")
    debut = src.index("def _lire_sl_demande(")
    fin = src.index("@app.route(\"/position/sltp\"")
    mod = types.ModuleType("bridge_sltp")
    exec(compile(src[debut:fin], str(_SRC), "exec"), mod.__dict__)
    return mod


# ─────────────────────────────────────────────────────────────────────────
# ⛔ LE CAS QUI ÉCHOUAIT EN PRODUCTION
# ─────────────────────────────────────────────────────────────────────────

def test_sl_absolu_SEUL_est_accepte(b):
    """⛔ LE DÉFAUT. C'est exactement la charge que l'échelle envoie, et elle
    recevait `400 sl_dist doit être > 0`."""
    dist, absolu, err = b._lire_sl_demande(
        {"ticket": 1360840476, "sl_absolu": 4205.28, "deplacer": True})

    assert err is None, f"sl_absolu seul refuse : {err}"
    assert absolu == pytest.approx(4205.28)
    assert dist == 0.0


def test_sl_dist_SEUL_reste_accepte(b):
    """⚠️ L'appelant historique (le garde-fou SL/TP) ne doit pas casser."""
    dist, absolu, err = b._lire_sl_demande({"ticket": 1, "sl_dist": 22.5})

    assert err is None
    assert dist == pytest.approx(22.5)
    assert absolu is None


def test_les_DEUX_ensemble_sont_acceptes(b):
    dist, absolu, err = b._lire_sl_demande(
        {"ticket": 1, "sl_dist": 22.5, "sl_absolu": 4205.28})

    assert err is None
    assert dist == pytest.approx(22.5)
    assert absolu == pytest.approx(4205.28)


# ─────────────────────────────────────────────────────────────────────────
# Les refus légitimes, qui ne doivent PAS disparaître
# ─────────────────────────────────────────────────────────────────────────

def test_AUCUN_des_deux_est_refuse(b):
    _, _, err = b._lire_sl_demande({"ticket": 1})

    assert err is not None
    assert "requis" in err


def test_sl_dist_NEGATIF_sans_sl_absolu_est_refuse(b):
    """⛔ Le garde d'origine, qui doit survivre : une distance nulle ou
    negative n'a pas de sens, et le repli silencieux sur zero ferait poser un
    stop AU PRIX D'ENTREE."""
    _, _, err = b._lire_sl_demande({"ticket": 1, "sl_dist": 0})
    assert err is not None and "> 0" in err

    _, _, err = b._lire_sl_demande({"ticket": 1, "sl_dist": -5})
    assert err is not None and "> 0" in err


def test_sl_dist_NEGATIF_AVEC_sl_absolu_est_ignore_sans_erreur(b):
    """🔑 C'est la nuance qui corrige le defaut : quand `sl_absolu` porte
    l'information, `sl_dist` n'a plus a etre valide — il n'est pas utilise."""
    dist, absolu, err = b._lire_sl_demande(
        {"ticket": 1, "sl_dist": 0, "sl_absolu": 4205.28})

    assert err is None
    assert absolu == pytest.approx(4205.28)


def test_sl_absolu_NEGATIF_est_refuse(b):
    _, _, err = b._lire_sl_demande({"ticket": 1, "sl_absolu": -1})
    assert err is not None and "> 0" in err

    _, _, err = b._lire_sl_demande({"ticket": 1, "sl_absolu": 0})
    assert err is not None and "> 0" in err


def test_sl_absolu_ILLISIBLE_est_refuse(b):
    _, _, err = b._lire_sl_demande({"ticket": 1, "sl_absolu": "pas un prix"})

    assert err is not None
    assert "nombre" in err


def test_sl_dist_ILLISIBLE_avec_sl_absolu_valable_passe(b):
    """⚠️ Un `sl_dist` illisible ne doit pas condamner un appel qui porte un
    prix parfaitement valable."""
    dist, absolu, err = b._lire_sl_demande(
        {"ticket": 1, "sl_dist": "bof", "sl_absolu": 4205.28})

    assert err is None
    assert absolu == pytest.approx(4205.28)


# ─────────────────────────────────────────────────────────────────────────
# ⛔ La contradiction ne doit pas pouvoir revenir
# ─────────────────────────────────────────────────────────────────────────

def test_la_route_UTILISE_la_fonction_extraite():
    """Sinon la correction vivrait a cote du chemin reel — exactement le piege
    dans lequel je suis tombe ce matin en verifiant le CALCUL et non la ROUTE.
    """
    src = _SRC.read_text(encoding="utf-8")
    debut = src.index('@app.route("/position/sltp"')
    bloc = src[debut:debut + 3000]

    assert "_lire_sl_demande(" in bloc, (
        "la route ne passe pas par la validation extraite")


def test_le_garde_contradictoire_a_DISPARU_de_la_route():
    """⛔ Epingle la ligne exacte qui cassait tout : un `if sl_dist <= 0`
    inconditionnel, juste apres un repli qui met `sl_dist = 0` quand
    `sl_absolu` est fourni."""
    src = _SRC.read_text(encoding="utf-8")
    debut = src.index('@app.route("/position/sltp"')
    bloc = src[debut:debut + 3000]

    assert "if sl_dist <= 0:" not in bloc, (
        "le garde inconditionnel sur sl_dist est revenu dans la route : "
        "sl_absolu redeviendra impossible")
