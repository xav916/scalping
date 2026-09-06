"""Ce que le SL/TP aurait donné sur les trades sortis autrement (2026-09-06).

Sur `[RÉEL · IC_MARKETS]`, les sorties automatiques font −0,40 R et les autres
+0,42 R. Tentant d'en conclure que sortir tôt vaut mieux — sauf qu'on compare
les trades qu'on a **choisi** de couper à ceux qu'on a **choisi** de laisser.

⛔ Le biais est dans la sélection, pas dans les chiffres. Ce module rejoue les
mêmes trades aux mêmes prix pour rendre la comparaison possible.

Ce que ces tests verrouillent :
  - l'ordre des touches à l'intérieur d'une barre est INCONNAISSABLE ⇒
    `indetermine`, jamais un choix ;
  - un stop collé à l'entrée est EXCLU, pas corrigé — un R calculé sur une
    distance de 0,0063 % vaut +79 et déplace toute une moyenne ;
  - un objectif du mauvais côté de l'entrée ne peut pas être touché ;
  - « aucune ligne résolue » se dit, il ne se tait pas.
"""
from __future__ import annotations

import pytest

from backend.services import contrefactuel_sortie as cf


def _b(haut, bas):
    return {"high": haut, "low": bas, "timestamp": "2026-09-06T10:00:00+00:00"}


# ── L'issue lue sur les bougies ──────────────────────────────────────

def test_achat_objectif_touche():
    assert cf.issue_depuis_bougies([_b(110, 99)], sl=95, tp=108, achat=True) == "TP"


def test_achat_stop_touche():
    assert cf.issue_depuis_bougies([_b(101, 94)], sl=95, tp=108, achat=True) == "SL"


def test_vente_les_sens_sont_INVERSES():
    """Sur une vente, l'objectif est SOUS l'entrée et le stop au-dessus."""
    assert cf.issue_depuis_bougies([_b(101, 92)], sl=105, tp=95, achat=False) == "TP"
    assert cf.issue_depuis_bougies([_b(106, 99)], sl=105, tp=95, achat=False) == "SL"


def test_les_DEUX_dans_la_meme_bougie_rend_indetermine():
    """⛔ L'ordre des touches à l'intérieur d'une barre est inconnaissable.
    Choisir ferait pencher la mesure du côté qu'on espère."""
    assert cf.issue_depuis_bougies([_b(110, 94)], sl=95, tp=108, achat=True) == "indetermine"


def test_aucun_niveau_touche_rend_None():
    assert cf.issue_depuis_bougies([_b(103, 99)], sl=95, tp=108, achat=True) is None


def test_la_PREMIERE_bougie_qui_touche_decide():
    bougies = [_b(103, 99), _b(101, 94), _b(115, 99)]   # SL avant TP
    assert cf.issue_depuis_bougies(bougies, sl=95, tp=108, achat=True) == "SL"


def test_une_bougie_illisible_n_interrompt_pas_la_lecture():
    bougies = [{"high": "?", "low": None}, _b(110, 99)]
    assert cf.issue_depuis_bougies(bougies, sl=95, tp=108, achat=True) == "TP"


def test_aucune_bougie_rend_None():
    assert cf.issue_depuis_bougies([], sl=95, tp=108, achat=True) is None
    assert cf.issue_depuis_bougies(None, sl=95, tp=108, achat=True) is None


# ── Le R réalisé ─────────────────────────────────────────────────────

def test_r_realise_achat_gagnant():
    assert cf.r_realise(100, 105, 95, achat=True) == pytest.approx(1.0)


def test_r_realise_vente_gagnante():
    assert cf.r_realise(100, 95, 105, achat=False) == pytest.approx(1.0)


def test_r_realise_risque_nul_rend_None():
    """⛔ `None`, jamais 0.0 : un risque nul rend le R indéfini, pas neutre."""
    assert cf.r_realise(100, 105, 100, achat=True) is None


# ── ⛔ Le filtre anti-placebo ─────────────────────────────────────────

def test_stop_colle_a_l_entree_est_EXCLU():
    """Le USD/JPY du démo : stop à 0,0063 % ⇒ R = +79,30, moyenne du compte
    passée de +0,43 à +3,99 par un seul trade."""
    assert cf.stop_utilisable(156.0, 156.0 * (1 - 0.000063)) is False


def test_stop_normal_est_accepte():
    assert cf.stop_utilisable(100.0, 99.5) is True     # 0,5 %


def test_le_seuil_est_a_0_05_pourcent():
    assert cf.stop_utilisable(100.0, 99.95) is True    # pile 0,05 %
    assert cf.stop_utilisable(100.0, 99.96) is False   # 0,04 %


def test_entree_illisible_est_exclue():
    assert cf.stop_utilisable(0, 1) is False
    assert cf.stop_utilisable("x", 1) is False


# ── Le bilan ─────────────────────────────────────────────────────────

def test_aucune_ligne_resolue_le_DIT(tmp_path, monkeypatch):
    """⛔ « Pas encore de verdict » n'est pas « pas d'écart »."""
    monkeypatch.setattr(cf, "_DB", tmp_path / "t.db")
    r = cf.bilan("admin_live")
    assert r["n"] == 0
    assert "ouverte" in r["verdict"]


def test_le_bilan_compare_les_MEMES_trades(tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.setattr(cf, "_DB", tmp_path / "t.db")
    cf.init_schema()
    c = sqlite3.connect(str(tmp_path / "t.db"), isolation_level=None)
    for i, (rr, rc) in enumerate([(0.4, -1.0), (0.5, 1.8), (0.3, -1.0)]):
        c.execute("""INSERT INTO contrefactuels_sortie
            (trade_id,destination_id,pair,direction,entry_price,sl,tp,exit_price,
             closed_at,close_reason,r_realise,r_contrefactuel,issue)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (i, "admin_live", "EUR/USD", "buy", 1.0, 0.99, 1.02, 1.004,
                   "2026-09-01", "MANUAL", rr, rc, "SL"))
    c.close()
    r = cf.bilan("admin_live")
    assert r["n"] == 3
    assert r["r_realise_total"] == pytest.approx(1.2)
    assert r["r_contrefactuel_total"] == pytest.approx(-0.2)
    assert "sortir tôt a MIEUX fait" in r["verdict"]


# ── ⛔ Une panne de lecture n'est pas une absence d'événement ─────────
#
# Trouvé au PREMIER passage réel du 06/09 : 13 lignes déclarées « expirées »
# alors que Twelve Data refusait sur quota (429). Le verdict « ni le stop ni
# l'objectif n'ont été touchés » était en réalité « je n'ai pas pu regarder ».

import sqlite3

import pytest


def _ligne(tmp_path, monkeypatch, closed_at, sl=95.0, tp=108.0):
    monkeypatch.setattr(cf, "_DB", tmp_path / "t.db")
    cf.init_schema()
    c = sqlite3.connect(str(tmp_path / "t.db"), isolation_level=None)
    c.execute("""INSERT INTO contrefactuels_sortie
        (trade_id,destination_id,pair,direction,entry_price,sl,tp,exit_price,
         closed_at,close_reason,r_realise)
        VALUES (1,'admin_live','EUR/USD','buy',100.0,?,?,101.0,?,'MANUAL',0.2)""",
              (sl, tp, closed_at))
    c.close()


def _issue(tmp_path):
    c = sqlite3.connect(str(tmp_path / "t.db"))
    v = c.execute("SELECT issue FROM contrefactuels_sortie").fetchone()[0]
    c.close()
    return v


@pytest.mark.asyncio
async def test_bougies_ILLISIBLES_laissent_en_attente(tmp_path, monkeypatch):
    """⛔ Le défaut du 06/09 : un 429 devenait « expiré »."""
    _ligne(tmp_path, monkeypatch, "2026-01-01T00:00:00+00:00")   # tres vieux

    async def _casse(pair, interval=None, outputsize=None):
        raise RuntimeError("429 Too Many Requests")

    r = await cf.resoudre(fetch_candles=_casse)
    assert _issue(tmp_path) is None, "une panne de lecture ne tranche RIEN"
    assert r["en_attente"] == 1


@pytest.mark.asyncio
async def test_liste_VIDE_ne_vaut_pas_lecture(tmp_path, monkeypatch):
    """Le quota rend `[]` exactement comme un marché sans bougie."""
    _ligne(tmp_path, monkeypatch, "2026-01-01T00:00:00+00:00")

    async def _vide(pair, interval=None, outputsize=None):
        return ([], False)

    await cf.resoudre(fetch_candles=_vide)
    assert _issue(tmp_path) is None


@pytest.mark.asyncio
async def test_bougies_LUES_sans_touche_expirent(tmp_path, monkeypatch):
    """Le cas legitime : on a regardé, rien n'a été touché, le délai est passé."""
    _ligne(tmp_path, monkeypatch, "2026-01-01T00:00:00+00:00")

    async def _calme(pair, interval=None, outputsize=None):
        return ([{"high": 101.0, "low": 99.0,
                  "timestamp": "2026-01-02T00:00:00+00:00"}], False)

    await cf.resoudre(fetch_candles=_calme)
    assert _issue(tmp_path) == "expire"


@pytest.mark.asyncio
async def test_objectif_touche_donne_le_R_du_niveau(tmp_path, monkeypatch):
    _ligne(tmp_path, monkeypatch, "2026-01-01T00:00:00+00:00")

    async def _gagne(pair, interval=None, outputsize=None):
        return ([{"high": 109.0, "low": 99.0,
                  "timestamp": "2026-01-02T00:00:00+00:00"}], False)

    await cf.resoudre(fetch_candles=_gagne)
    c = sqlite3.connect(str(tmp_path / "t.db"))
    issue, rc = c.execute(
        "SELECT issue, r_contrefactuel FROM contrefactuels_sortie").fetchone()
    c.close()
    assert issue == "TP"
    assert rc == pytest.approx((108 - 100) / (100 - 95))    # 1,6 R


@pytest.mark.asyncio
async def test_indetermine_ne_recoit_AUCUN_R(tmp_path, monkeypatch):
    """⛔ Ne pas savoir ne s'impute pas : ni gain, ni perte."""
    _ligne(tmp_path, monkeypatch, "2026-01-01T00:00:00+00:00")

    async def _les_deux(pair, interval=None, outputsize=None):
        return ([{"high": 109.0, "low": 94.0,
                  "timestamp": "2026-01-02T00:00:00+00:00"}], False)

    await cf.resoudre(fetch_candles=_les_deux)
    c = sqlite3.connect(str(tmp_path / "t.db"))
    issue, rc = c.execute(
        "SELECT issue, r_contrefactuel FROM contrefactuels_sortie").fetchone()
    c.close()
    assert issue == "indetermine"
    assert rc is None
