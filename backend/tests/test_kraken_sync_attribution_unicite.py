"""Attribuer un P&L quand une seule affectation est possible.

Xavier ferme des positions **à la main** sur Kraken — confirmé le 2026-08-09.
Ce n'est donc pas un accident isolé mais une pratique, et c'est exactement le
cas où ``kraken_sync`` ne savait pas attribuer le P&L : les fills de clôture
portent des ``order_id`` neufs, ni l'ouverture, ni le SL, ni le TP.

> **Le trou de mesure ne frappait pas au hasard : il frappait précisément les
> trades que Xavier clôt lui-même.** Sur une route qui produit ~1 setup par
> jour, chaque observation perdue compte double.

## Pourquoi cette règle ne contredit pas le refus du module

L'en-tête d'``attribuer_clotures`` refuse « tout rapprochement par prix ou par
horodatage ». Ces deux critères sont **approximatifs** : ils désignent le fill
*le plus probable*.

L'unicité est d'une autre nature. S'il n'existe qu'**un seul** push ouvert sur
le symbole et qu'un ou plusieurs fills de sens opposé en soldent **exactement**
la taille, il n'existe **aucune autre position** à laquelle les attribuer. Ce
n'est pas une estimation : c'est la seule affectation possible.

Trois verrous, et le moindre doute retombe sur ``pnl = None`` :

1. **un seul** push ouvert sur ce symbole ;
2. les fills soldent la taille **exactement** (tolérance 0,1 %) ;
3. ils sont **postérieurs** à l'ouverture — un fill antérieur ne peut pas
   clôturer un ordre qui n'existait pas. C'est de la **causalité**, pas un
   rapprochement par proximité temporelle.
"""
import pytest

from backend.services import kraken_sync as ks

PUSH = {
    "push_id": 1, "order_id": "OPEN-ETHFI", "pair": "ETHFI/USD",
    "direction": "buy", "entry_price": 0.3833, "volume": 14.1,
    "pushed_at": "2026-08-08T23:58:29+00:00", "symbol": "PF_ETHFIUSD",
    "sl_order_id": "SL-ETHFI", "tp_order_id": "TP-ETHFI",
}


def _fill(oid="CLOSE-1", side="sell", size=14.1, price=0.3939, pnl=0.14946,
          t="2026-08-09T15:29:42.233Z", sym="PF_ETHFIUSD"):
    return {"order_id": oid, "side": side, "size": size, "price": price,
            "realized_pnl": pnl, "fill_time": t, "symbol": sym}


def _nettage(pushes, fills, positions=None):
    return ks.clotures_par_nettage(
        pushes, fills, positions if positions is not None else {}, set())


# ─── Le cas nominal : la clôture manuelle de Xavier ────────────────────


def test_une_cloture_manuelle_est_desormais_attribuee():
    """LE test : un seul candidat possible, donc aucune ambiguïté."""
    r = _nettage([PUSH], [_fill()])

    assert len(r) == 1
    assert r[0]["pnl_usd"] == pytest.approx(0.14946)
    assert r[0]["exit_price"] == pytest.approx(0.3939)
    assert r[0]["cause"] == ks.CAUSE_EXTERNE
    assert r[0]["closed_at"] == "2026-08-09T15:29:42.233Z"


def test_une_cloture_en_plusieurs_morceaux_est_sommee():
    r = _nettage([PUSH], [
        _fill(oid="C1", size=10.0, price=0.39, pnl=0.10),
        _fill(oid="C2", size=4.1, price=0.40, pnl=0.05),
    ])
    assert r[0]["pnl_usd"] == pytest.approx(0.15)
    assert r[0]["taille"] == pytest.approx(14.1)


# ─── Les trois verrous ─────────────────────────────────────────────────


def test_deux_pushes_ouverts_sur_le_symbole_rendent_l_attribution_ambigue():
    """Verrou 1. Deux positions, un fill : impossible de savoir laquelle."""
    autre = dict(PUSH, push_id=2, order_id="OPEN-2")
    r = _nettage([PUSH, autre], [_fill()])

    assert len(r) == 2
    assert all(c["pnl_usd"] is None for c in r)


def test_une_taille_qui_ne_solde_pas_exactement_est_refusee():
    """Verrou 2. Une clôture partielle ne dit pas ce qui reste attribuable."""
    r = _nettage([PUSH], [_fill(size=7.0)])
    assert r[0]["pnl_usd"] is None


def test_un_fill_anterieur_a_l_ouverture_est_ignore():
    """Verrou 3. Causalité : il ne peut pas clôturer un ordre inexistant.

    Sans ce filtre, la clôture d'un trade ETHFI de la veille — même taille —
    serait attribuée à celui d'aujourd'hui.
    """
    r = _nettage([PUSH], [_fill(t="2026-08-07T10:00:00.000Z", pnl=99.0)])
    assert r[0]["pnl_usd"] is None


def test_un_fill_du_meme_sens_que_le_push_ne_cloture_rien():
    """Un achat ne ferme pas un achat : il l'agrandit."""
    r = _nettage([PUSH], [_fill(side="buy")])
    assert r[0]["pnl_usd"] is None


def test_un_fill_sur_un_autre_symbole_est_ignore():
    r = _nettage([PUSH], [_fill(sym="PF_SEIUSD")])
    assert r[0]["pnl_usd"] is None


def test_les_ordres_connus_du_push_ne_sont_pas_reutilises():
    """SL et TP sont déjà traités par l'attribution exacte, en amont."""
    r = _nettage([PUSH], [_fill(oid="TP-ETHFI"), _fill(oid="SL-ETHFI")])
    assert r[0]["pnl_usd"] is None


# ─── Ce qui ne bouge pas ───────────────────────────────────────────────


def test_une_exposition_restante_empeche_toute_conclusion():
    r = _nettage([PUSH], [_fill()], positions={"PF_ETHFIUSD": 14.1})
    assert r == []


def test_sans_fill_du_tout_le_montant_reste_inconnu():
    """Le comportement d'avant : la clôture est enregistrée, pas inventée."""
    r = _nettage([PUSH], [])
    assert len(r) == 1
    assert r[0]["pnl_usd"] is None
    assert r[0]["exit_price"] is None
    assert r[0]["cause"] == ks.CAUSE_EXTERNE


def test_un_push_deja_clos_est_ignore():
    r = ks.clotures_par_nettage([PUSH], [_fill()], {}, deja_closes={1})
    assert r == []
