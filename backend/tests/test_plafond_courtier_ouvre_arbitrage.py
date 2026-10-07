"""Le plafond du COURTIER doit POSER LA QUESTION, pas couper en silence.

⛔ **Ce qui s'est passé le 2026-10-07.** Le pont a refusé l'or **224 fois** en
24 h sur son propre plafond journalier :

    "Daily drawdown reached: loss=19.77 >= limit=17.87 (3.0% of 595.81)"

Et Xavier n'a rien reçu. Le dispositif d'arbitrage existe depuis le 04/09 —
il pose la question sur Telegram et bloque le compte en attendant — mais il
n'est branché que sur le plafond du RADAR, qui compte autrement :

| | mesure | perte du jour |
|---|---|---|
| radar | clôtures en base (`pnl`) | **−16,45 €** |
| **courtier** | solde d'ouverture − equity (flottant et frais inclus) | **19,77 €** |

Le courtier franchit, nous non. **On ne peut pas poser de question sur un
dépassement qu'on ne voit pas** — alors on lit SES chiffres dans SON refus.

🔑 La réutilisation est entière : `doit_bloquer()` porte déjà l'idempotence
voulue (un `GELER` du jour → rien, un `CONTINUER` qui couvre → rien, une
question en attente → rien, sinon on ouvre). 224 refus ne doivent produire
**qu'une** ligne.

⚠️ Et un refus qu'on ne sait pas lire n'ouvre RIEN : inventer une perte ferait
poser une question sur un chiffre jamais mesuré.
"""
from __future__ import annotations

import pytest

CORPS = ('{"blocked":true,"ok":false,"reason":"Daily drawdown reached: '
         'loss=19.77 >= limit=17.87 (3.0% of 595.81)"}')


@pytest.fixture()
def arbitrage(tmp_path, monkeypatch):
    """Base réelle, schéma réel — même harnais que `test_plafond_arbitrage`."""
    import backend.services.trade_log_service as t

    chemin = tmp_path / "trades.db"
    monkeypatch.setattr(t, "_DB_PATH", chemin, raising=False)
    t._init_schema()

    from backend.services import plafond_arbitrage as a
    a._init_schema()
    return a


def test_lit_la_perte_et_le_plafond_dans_le_message_du_pont():
    from backend.services import mt5_bridge as m
    assert m._perte_journaliere_du_courtier(CORPS) == (19.77, 17.87)


def test_un_message_sans_les_deux_chiffres_ne_rend_RIEN():
    from backend.services import mt5_bridge as m
    assert m._perte_journaliere_du_courtier("Max open positions") is None
    assert m._perte_journaliere_du_courtier("") is None
    assert m._perte_journaliere_du_courtier(None) is None


def test_le_refus_du_courtier_OUVRE_une_demande_sur_SES_chiffres(arbitrage):
    from backend.services import mt5_bridge as m

    assert m._arbitrer_plafond_du_courtier("admin_live", CORPS) is True

    lignes = arbitrage.lignes_du_jour("admin_live")
    assert len(lignes) == 1
    assert lignes[0]["etat"] == arbitrage.EN_ATTENTE
    assert lignes[0]["pnl_au_moment"] == -19.77
    assert lignes[0]["seuil"] == -17.87


def test_deux_cent_vingt_quatre_refus_n_ouvrent_qu_UNE_demande(arbitrage):
    from backend.services import mt5_bridge as m

    for _ in range(224):
        m._arbitrer_plafond_du_courtier("admin_live", CORPS)

    assert len(arbitrage.lignes_du_jour("admin_live")) == 1


def test_un_refus_illisible_n_ouvre_RIEN(arbitrage):
    from backend.services import mt5_bridge as m

    assert m._arbitrer_plafond_du_courtier("admin_live", "Duplicate: x") is False
    assert arbitrage.lignes_du_jour("admin_live") == []


# ── Le câblage : journaliser ET arbitrer, depuis le même point ─────────────

def _refus_journalises(chemin):
    import sqlite3
    with sqlite3.connect(chemin) as c:
        return c.execute(
            "SELECT reason_code, destination_id FROM signal_rejections").fetchall()


def _dest(destination_id, reel):
    from types import SimpleNamespace as NS
    return NS(destination_id=destination_id, user_id=None, reel=reel)


def _setup():
    from types import SimpleNamespace as NS
    return NS(pair="XAU/USD", confidence_score=71.4)


def test_le_refus_du_pont_est_a_la_fois_JOURNALISE_et_ARBITRE(arbitrage, tmp_path):
    """⚠️ Vérifie la CHAÎNE, pas la signature — c'est le câblage qui manquait.

    Le 07/10, les 224 refus étaient parfaitement journalisés sous
    `bridge_perte_journaliere` : ce n'est pas la mesure qui a manqué, c'est la
    question. Les deux doivent partir du même point, sinon l'un peut vivre
    sans l'autre pendant des semaines.
    """
    from backend.services import mt5_bridge as m

    assert m._traiter_refus_du_pont(
        _dest("admin_live", True), _setup(), "buy", 429, CORPS
    ) == "bridge_perte_journaliere"

    assert _refus_journalises(tmp_path / "trades.db") == [
        ("bridge_perte_journaliere", "admin_live")]
    assert len(arbitrage.lignes_du_jour("admin_live")) == 1


def test_la_DEMO_ne_derange_PAS_Xavier(arbitrage, tmp_path):
    """⛔ Le plafond d'un compte de démonstration ne pose aucune question.

    Prolonge le correctif du 2026-08-20 : la démo perd de l'argent qui
    n'existe pas. Son refus reste journalisé — c'est une mesure — mais il
    n'ouvre pas d'arbitrage, sinon Xavier serait réveillé pour du fictif.
    """
    from backend.services import mt5_bridge as m

    m._traiter_refus_du_pont(
        _dest("admin_legacy", False), _setup(), "buy", 429, CORPS)

    assert _refus_journalises(tmp_path / "trades.db") == [
        ("bridge_perte_journaliere", "admin_legacy")]
    assert arbitrage.lignes_du_jour("admin_legacy") == []


def test_un_autre_refus_429_n_ouvre_aucun_arbitrage(arbitrage, tmp_path):
    """Les places pleines ne sont pas une perte : rien à arbitrer."""
    from backend.services import mt5_bridge as m

    assert m._traiter_refus_du_pont(
        _dest("admin_live", True), _setup(), "buy", 429,
        '{"reason":"Max open positions reached: 10"}'
    ) == "bridge_max_positions"
    assert arbitrage.lignes_du_jour("admin_live") == []
