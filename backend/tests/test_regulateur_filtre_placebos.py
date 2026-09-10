"""Un stop placebo n'est pas une espérance : le régulateur doit l'écarter.

⛔ **Ce qui s'est passé le 2026-09-09 à 13:48 UTC.** `XAU/USD` a été mis en pause
**quatorze jours** sur `admin_live`, motif `ev_negative`, `pnl_pct = −15,71`.

Or l'or **gagnait de l'argent** sur cette fenêtre : **+83,90 €**, 30 trades,
wr 46,7 %. Le verdict venait d'**un seul trade** :

```
05/08   entree 4085,92   stop 4086,25   ->  risque 0,29 EUR   pnl -4,32   R = -14,90
```

Un stop de **33 centimes sur l'or** — 0,008 % du prix. Ce n'est pas un stop,
c'est un placebo. Il transforme une perte de 4,32 € en −14,90 R.

```
somme des R, telle quelle       -15,708  ->  PAUSE (seuil -10)
sans les stops placebos          +2,421  ->  GAGNANTE
```

⚠️ **Trois** trades sont écartés, pas un — je n'avais vu que le premier, parce
qu'il écrase les deux autres. Tous trois datent du 04-05 août, avant la
correction du placement des stops. Ensemble : **−18,13 R** sur une fenêtre qui
en vaut **+2,42** une fois nettoyée.

## 🔑 Deux juges, deux règles sur la même donnée

Le **laboratoire** écarte déjà tout stop sous `PLACEBO_PCT = 0,1 %` du prix — il
a été écrit pour ça, et la mémoire du projet porte que **155 des 181 stops du
réel sont des placebos**. Le **régulateur**, lui, les comptait.

⇒ Ce correctif n'est pas un desserrage : c'est refuser de compter un chiffre qui
n'a pas de sens. Un stop à 33 centimes ne mesure pas une espérance, il mesure
une erreur de placement de stop.

⚠️ **Le seuil est REPRIS du laboratoire**, jamais redéfini. Deux constantes pour
la même notion divergeraient au premier réglage — c'est le défaut « deux listes
des mêmes choses de part et d'autre d'une frontière », payé cinq fois le 08/09.

⚠️ Le trade écarté n'est pas avalé : il est **dénombré** dans
`n_non_mesurables`, déjà rendu par le relevé.
"""
import pytest

from backend.services import pair_pnl_regulator as reg
from backend.services.laboratoire_or import PLACEBO_PCT


class _Ligne(dict):
    """Une ligne de trade comme `_somme_en_r` la reçoit."""


def _t(entree, stop, pnl, lot=0.01, pair="XAU/USD"):
    return _Ligne(entry_price=entree, stop_loss=stop, size_lot=lot,
                  pnl=pnl, pair_mesure=pair)


def test_le_stop_PLACEBO_du_05_08_est_ecarte():
    """⛔ LE cas : celui qui a mis l'or en pause quatorze jours."""
    somme, n = reg._somme_en_r([_t(4085.92, 4086.25, -4.32)])
    assert n == 0, "le placebo a ete compte"
    assert somme == pytest.approx(0.0)


def test_un_stop_NORMAL_est_compte():
    """Garde-fou : si le filtre écartait tout, le régulateur ne mesurerait
    plus rien et ne pourrait plus jamais poser de pause."""
    somme, n = reg._somme_en_r([_t(4398.97, 4383.45, 13.48)])
    assert n == 1
    assert somme > 0


def test_la_FENETRE_reelle_bascule_de_PAUSE_a_PLATE():
    """⛔ Le test qui prouve que le correctif change le verdict, et de combien.

    Les 30 trades reels de `XAU/USD @admin_live` au 09/09, tels que le
    regulateur les a lus. Le placebo du 05/08 pese a lui seul -14,90 R.
    """
    reels = [
        (4092.97, 4094.79, -3.46), (4085.92, 4086.25, -4.32),
        (4093.82, 4096.54, -2.45), (4238.64, 4246.88, -9.32),
        (4378.77, 4364.90, -13.64), (4536.05, 4578.16, 31.26),
        (4475.20, 4551.01, 65.74), (4438.67, 4473.61, 31.68),
        (4409.99, 4432.72, -25.54), (4440.06, 4461.14, -13.02),
        (4447.47, 4463.02, 16.03), (4421.00, 4435.83, 24.66),
        (4402.44, 4425.85, 21.54), (4370.51, 4388.84, 28.28),
        (4336.74, 4371.81, -28.81), (4358.31, 4375.89, 24.12),
        (4326.81, 4311.82, -11.67), (4321.28, 4303.72, 2.07),
        (4315.63, 4328.44, -13.32), (4480.02, 4501.51, 14.41),
        (4464.16, 4434.99, 28.90), (4506.82, 4471.11, -30.08),
        (4486.03, 4465.14, -14.22), (4402.86, 4372.04, -20.54),
        (4423.53, 4441.27, 27.05), (4411.39, 4382.09, -25.90),
        (4398.97, 4383.45, 13.48), (4409.65, 4390.67, 3.55),
        (4402.38, 4418.27, -14.68), (4417.52, 4395.54, -17.90),
    ]
    somme, n = reg._somme_en_r([_t(e, s, p) for e, s, p in reels])

    # ⚠️ TROIS trades ecartes, pas un. Je l'ai cru a un seul — c'est le seul
    # que la mesure du 09/09 avait fait ressortir, parce qu'il ecrasait les
    # deux autres. Les 30 lignes ci-dessus ont ete RELUES en production avant
    # d'ecrire ce chiffre. Les trois datent du 04 et du 05 aout, avant la
    # correction du placement des stops.
    #
    #     04/08  4092,97 -> 4094,79   largeur 0,044 %   risque 1,58 EUR   R = -2,19
    #     05/08  4085,92 -> 4086,25   largeur 0,008 %   risque 0,29 EUR   R = -14,90
    #     05/08  4093,82 -> 4096,54   largeur 0,066 %   risque 2,35 EUR   R = -1,04
    #                                                            total    -18,13 R
    assert n == 27, f"trois trades doivent etre ecartes, {30 - n} l'ont ete"
    assert somme > -10.0, (
        f"somme_r = {somme:+.3f} — toujours sous le seuil de pause de -10")
    assert somme == pytest.approx(2.42, abs=0.05), (
        f"la fenetre vaut {somme:+.3f} R — mesure a +2,42 le 10/09")


def test_le_seuil_est_CELUI_du_laboratoire():
    """⛔ Deux constantes pour la même notion divergeraient au premier réglage.
    C'est le défaut « deux listes des mêmes choses de part et d'autre d'une
    frontière », paye cinq fois le 08/09."""
    import inspect
    src = inspect.getsource(reg._somme_en_r)
    assert "PLACEBO_PCT" in src, "le seuil est redefini au lieu d'etre repris"
    assert "laboratoire_or" in src or "from backend.services.laboratoire_or" in src


def test_le_trade_ecarte_est_DENOMBRE():
    """⚠️ Un trade avale est indiscernable d'un trade qui n'existait pas.
    Il doit ressortir dans `n_non_mesurables`."""
    somme, n = reg._somme_en_r([
        _t(4085.92, 4086.25, -4.32),      # placebo
        _t(4398.97, 4383.45, 13.48),      # normal
    ])
    assert n == 1, "le compte des mesurables ne reflete pas l'exclusion"


def test_un_stop_JUSTE_au_dessus_du_seuil_passe():
    """La borne doit mordre au bon endroit, pas plus loin."""
    entree = 4000.0
    stop = entree * (1 - PLACEBO_PCT * 1.5)     # 0,15 % : au-dessus du seuil
    _, n = reg._somme_en_r([_t(entree, stop, -5.0)])
    assert n == 1


def test_un_stop_JUSTE_en_dessous_est_ecarte():
    entree = 4000.0
    stop = entree * (1 - PLACEBO_PCT * 0.5)     # 0,05 % : sous le seuil
    _, n = reg._somme_en_r([_t(entree, stop, -5.0)])
    assert n == 0


def test_une_entree_a_ZERO_ne_leve_pas():
    """⛔ `entry_price = 0` a existe sur 217 trades du reel. Diviser par zero
    ici tuerait le regulateur au lieu d'ecarter la ligne."""
    _, n = reg._somme_en_r([_t(0.0, 4086.25, -4.32)])
    assert n == 0
