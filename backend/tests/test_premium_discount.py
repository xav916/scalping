"""Premium / discount — ou se situe le prix dans sa fourchette.

⚠️ **Provenance differente des autres concepts de ce depot.** Il ne figure pas
dans les 38 familles rapportees par Xavier le 2026-09-12 : il vient de ma
propre liste, je l'ai signale comme tel, et il a ete demande explicitement
ensuite. Marque **ICT / Smart Money**, pas « corpus Vivien ». La distinction
entre ce qui est rapporte et ce que nous ajoutons doit rester lisible.

## Aucun reglage neuf

- la fourchette est celle que les detecteurs regardent deja ;
- l'equilibre est le **milieu** — 50 % est la definition du concept, pas un
  parametre qu'on pourrait optimiser.

Un seul seuil ajoute serait un degre de liberte de plus, donc de l'edge
fabrique.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.models.schemas import Candle
from backend.services import laboratoire_or as labo
from backend.services import market_profile as mp


def _c(specs):
    t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    return [Candle(timestamp=t0 + timedelta(minutes=5 * i),
                   open=o, high=h, low=l, close=c, volume=500.0)
            for i, (o, h, l, c) in enumerate(specs)]


def _dicts(specs):
    t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    return [{"t": (t0 + timedelta(minutes=5 * i)).isoformat(),
             "o": o, "h": h, "l": l, "c": c, "tv": 500}
            for i, (o, h, l, c) in enumerate(specs)]


def _fourchette(n=60, bas=100.0, haut=110.0, fin=None):
    """Une fourchette nette, et une derniere cloture au niveau demande."""
    out = []
    for i in range(n - 1):
        prix = bas if i % 2 else haut
        out.append((prix, haut, bas, prix))
    dernier = fin if fin is not None else haut
    out.append((dernier, haut, bas, dernier))
    return out


def test_sous_l_equilibre_c_est_un_DISCOUNT():
    z = mp.zone_premium_discount(_c(_fourchette(fin=101.0)))
    assert z is not None
    assert z["position"] < 0.5
    assert z["discount"] is True and z["premium"] is False
    assert abs(z["equilibre"] - 105.0) < 1e-6


def test_au_dessus_de_l_equilibre_c_est_un_PREMIUM():
    z = mp.zone_premium_discount(_c(_fourchette(fin=109.0)))
    assert z["position"] > 0.5
    assert z["premium"] is True and z["discount"] is False


def test_l_equilibre_EXACT_compte_comme_discount():
    """⚠️ Une frontiere doit etre tranchee une fois pour toutes, sinon deux
    appels au meme prix rendent deux reponses."""
    z = mp.zone_premium_discount(_c(_fourchette(fin=105.0)))
    assert abs(z["position"] - 0.5) < 1e-9
    assert z["discount"] is True and z["premium"] is False


def test_une_fourchette_PLATE_est_indecidable():
    """Fail-closed : sans amplitude, il n'y a ni haut ni bas."""
    plat = [(100.0, 100.0, 100.0, 100.0)] * 60
    assert mp.zone_premium_discount(_c(plat)) is None


def test_les_deux_predicats_sont_branches_et_fail_closed():
    assert "en_discount" in labo._PREDICATS
    assert "en_premium" in labo._PREDICATS
    b = _dicts(_fourchette(fin=101.0))
    i = len(b)
    assert labo._PREDICATS["en_discount"](b, i) is True
    assert labo._PREDICATS["en_premium"](b, i) is False
    # trop court : on ne valide pas
    assert labo._PREDICATS["en_discount"](_dicts(_fourchette(n=5)), 5) is False


def test_le_predicat_ne_regarde_PAS_au_dela_du_signal():
    """Meme discipline que les autres : il lit `bougies[:i]`."""
    avant = _fourchette(fin=101.0)          # discount a cet instant
    apres = [(109.0, 110.0, 100.0, 109.0)] * 10   # le prix monte ENSUITE
    b = _dicts(avant + apres)
    assert labo._PREDICATS["en_discount"](b, len(avant)) is True, (
        "la montee posterieure a change le verdict : le predicat lit l'avenir")


def test_les_deux_chaines_sont_des_SOUS_ENSEMBLES_stricts():
    noms = {c["nom"]: c for c in labo.CHAINES}
    c = noms["sweep_en_discount_haussier"]
    assert c["motifs"] == ("liquidity_sweep_up",)
    assert c["predicats"] == ("en_discount",)
    c = noms["sweep_en_premium_baissier"]
    assert c["motifs"] == ("liquidity_sweep_down",)
    assert c["predicats"] == ("en_premium",)


def test_AUCUN_seuil_neuf_n_a_ete_introduit():
    """🔑 Le garde-fou du concept : l'equilibre est 50 %, point.

    ⚠️ On juge le CODE, pas la prose. Ma premiere version cherchait le mot
    « MARGE » dans le source entier — et le trouvait dans la phrase du
    docstring qui explique justement pourquoi il ne doit pas exister. Deuxieme
    fois dans la journee que je me fais avoir par un test qui lit les
    commentaires (le premier disait « TOUS les comptes »).
    """
    import ast
    import inspect

    src = inspect.getsource(mp.zone_premium_discount)
    arbre = ast.parse(src)   # fonction de module : deja en colonne 0
    # on retire le docstring, puis on relit les seules lignes de CODE
    fonction = arbre.body[0]
    if (fonction.body and isinstance(fonction.body[0], ast.Expr)
            and isinstance(fonction.body[0].value, ast.Constant)):
        fonction.body = fonction.body[1:]
    code = ast.unparse(fonction)

    assert "0.5" in code, "l'equilibre a disparu du code"
    for interdit in ("MARGE", "SEUIL", "0.55", "0.45", "0.6", "0.4"):
        assert interdit not in code, f"seuil neuf introduit : {interdit}"
