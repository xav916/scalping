"""Le prix d'exécution annoncé était celui du SIGNAL quand `price` valait 0.

⛔ MESURE DU 2026-09-12, sur un trade réel. Réponse du pont pour le ticket
1358460909 (XAG/USD, achat, compte réel) :

```
{"fill_price": 65.691, "fill_source": "position", "price": 0.0,
 "protected": true, "sl_applied": true, "ticket": 1358460909, ...}
```

Le prix poussé (signal) valait **65,969**. Le code lisait :

```python
fill_price=float(data.get("price") or setup.entry_price)
```

`price` vaut `0.0` — **falsy**. On retombe donc sur `setup.entry_price`, le
prix du signal. Telegram a annoncé « Fill : 65,969 » pour une exécution à
**65,691** : une erreur de **0,42 %** sur le prix d'entrée annoncé, alors que
la bonne valeur était dans le champ d'à côté.

## 🔑 Pourquoi ça n'est pas cosmétique

L'écart signal → exécution est la mesure qui décide si un stop est bien placé.
Mesuré le même jour :

    XAG/USD   mediane 0,091 %   p90 0,242 %   max 0,421 %   50 % au-dela de 0,1 %
    XAU/USD   mediane 0,042 %                               9 % au-dela de 0,1 %

Annoncer le signal à la place de l'exécution rend cet écart **invisible dans
le seul endroit que Xavier lit en direct**.

## ⚠️ `or` contre `is None`

`or` traite `0.0` comme « absent ». Ici `price: 0.0` veut dire « ce champ n'est
pas renseigné par ce chemin », et `fill_price` porte la vérité. La règle du
dépôt est déjà écrite ailleurs : *un `0.0` de MT5 signifie « aucun niveau »,
pas « niveau à zéro »* — même maladie que `pnl=0.0`, `entry_price=0.0` et
`close_reason=MANUAL`.

⇒ On lit `fill_price` D'ABORD, `price` ensuite, le signal en dernier recours —
et on ne retient jamais une valeur nulle ou négative.
"""
import pytest

from backend.services.mt5_bridge import _prix_execution


class _Setup:
    def __init__(self, entry): self.entry_price = entry


_SIGNAL = _Setup(65.969)


def test_LE_cas_reel_du_10_09():
    """⛔ `price: 0.0` et `fill_price: 65.691` — c'est fill_price qui gagne."""
    data = {"fill_price": 65.691, "price": 0.0, "ticket": 1358460909}
    assert _prix_execution(data, _SIGNAL) == pytest.approx(65.691)


def test_price_est_utilise_quand_fill_price_manque():
    """Les ponts non redeployes ne rendent que `price`."""
    assert _prix_execution({"price": 63.619}, _SIGNAL) == pytest.approx(63.619)


def test_fill_price_PRIME_sur_price_quand_les_deux_existent():
    """`fill_price` est resolu apres avoir attendu la position ; `price` est le
    retour immediat de l'ordre. Le premier est plus proche de la verite."""
    assert _prix_execution({"fill_price": 65.691, "price": 65.70},
                           _SIGNAL) == pytest.approx(65.691)


def test_sans_aucun_prix_on_retombe_sur_le_signal():
    """Dernier recours — mais il doit rester le DERNIER."""
    assert _prix_execution({}, _SIGNAL) == pytest.approx(65.969)
    assert _prix_execution({"fill_price": 0.0, "price": 0.0},
                           _SIGNAL) == pytest.approx(65.969)


def test_un_prix_NEGATIF_n_est_jamais_retenu():
    """Un prix negatif n'est pas une donnee, c'est une panne."""
    assert _prix_execution({"fill_price": -1.0}, _SIGNAL) == pytest.approx(65.969)


def test_une_valeur_ILLISIBLE_ne_fait_pas_tomber_la_notification():
    """⚠️ Cette fonction est appelee dans un chemin best-effort : lever ici
    ferait perdre la notification d'ouverture entiere pour un champ malforme."""
    assert _prix_execution({"fill_price": "abc"}, _SIGNAL) == pytest.approx(65.969)
    assert _prix_execution({"fill_price": None}, _SIGNAL) == pytest.approx(65.969)


def test_sans_signal_ni_prix_on_rend_zero_et_on_ne_leve_pas():
    class _Vide:
        pass
    assert _prix_execution({}, _Vide()) == 0.0
