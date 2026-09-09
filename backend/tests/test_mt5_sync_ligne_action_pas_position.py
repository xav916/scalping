"""Une ligne d'ACTION du bridge n'est pas une POSITION.

Le garde-fou SL/TP du bridge (`/position/sltp`, cron toutes les minutes) pose
un stop sur une position trouvée NUE chez le courtier. Il journalise son geste
avec ``status="filled"`` — **le même statut qu'un vrai remplissage** — mais
sans ``pair``, sans ``direction`` et sans ``entry`` : ce sont des champs d'un
ordre, pas d'une modification de stop.

`_sync_one` prend toute ligne ``filled`` pour une nouvelle position. Dans
`_upsert_open_trade`, deux replis se sont alors additionnés :

- ``pair = row.get("pair") or row.get("symbol")`` → ``XAUUSD`` au lieu de
  ``XAU/USD``, donc invisible à tout filtre par paire ;
- ``direction = (row.get("direction") or "").lower()`` → ``''``.

Et ``''`` étant une valeur DISTINCTE, la clé unique ``(mt5_ticket, direction)``
ne voit aucun conflit : le doublon s'insère sans erreur. La clôture, elle,
retrouve les deux lignes par ``WHERE mt5_ticket = ?`` et leur recopie le MÊME
P&L.

Mesuré le 2026-09-09 sur le compte réel : **6 lignes fantômes**, dont 2 sur
l'or. Le plafond journalier — qui somme `personal_trades` par destination, sans
filtre de paire — a vu le 01/09 **+37,85 € de gain qui n'existaient pas**. Un
gain fantôme *desserre* une garde de perte sur de l'argent réel.

🔑 Chaque fois que le filet de sécurité sauvait le compte, il faussait les
comptes. Les deux seuls juges épargnés (rétrogradation, régulateur) ne l'ont été
que parce qu'ils filtrent sur ``pair = 'XAU/USD'``.

⇒ La règle posée ici : **une ligne d'audit ne devient une position que si elle
porte un sens réel** (``buy`` / ``sell``). Les pattes de clôture
(``close-buy`` / ``close-sell``, écrites par `/position/close` et `/kill`)
tombent sous la même règle — ce sont aussi des journaux d'action, jamais des
positions ouvertes.

Cf. [[project_analyse_clotures_main_2026_08_24]] ·
    [[feedback_ne_pas_desserrer_les_portes]]
"""
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.services import mt5_sync, trade_log_service


@pytest.fixture
def db(tmp_path: Path):
    trades_db = tmp_path / "trades.db"
    with patch.object(trade_log_service, "_DB_PATH", trades_db), patch(
        "backend.services.macro_context_service.get_macro_snapshot",
        return_value=None,
    ):
        trade_log_service._init_schema()
        yield trades_db


def _lignes(db_path: Path, ticket: int) -> list[sqlite3.Row]:
    with sqlite3.connect(db_path) as c:
        c.row_factory = sqlite3.Row
        return c.execute(
            "SELECT * FROM personal_trades WHERE mt5_ticket = ?", (ticket,)
        ).fetchall()


# Charge utile RÉELLE, relevée dans l'audit du bridge du compte réel
# (`/audit`, lignes 3927 et 3928). Ne pas la « simplifier » : un test qui
# fabrique lui-même la charge d'un système externe valide sa propre fiction.
REMPLISSAGE = {
    "id": 3927,
    "ticket": 1357451117,
    "status": "filled",
    "mode": "live",
    "pair": "XAU/USD",
    "symbol": "XAUUSD",
    "direction": "sell",
    "entry": 4447.47,
    "sl": 4463.02,
    "tp": 4418.5,
    "lots": 0.01,
    "created_at": "2026-09-01T01:14:11.755635+00:00",
}

GARDE_FOU_SLTP = {
    "id": 3928,
    "ticket": 1357451117,
    "status": "filled",
    "mode": "live",
    "pair": None,
    "symbol": "XAUUSD",
    "direction": None,
    "entry": None,
    "sl": 4491.94,
    "tp": 0.0,
    "lots": None,
    "client_comment": "sltp-guard",
    "created_at": "2026-09-01T01:15:04.408062+00:00",
}

PATTE_DE_CLOTURE = {
    "id": 4100,
    "ticket": 1357451117,
    "status": "filled",
    "mode": "live",
    "symbol": "XAUUSD",
    "direction": "close-buy",
    "lots": 0.01,
    "client_comment": "close-api",
    "created_at": "2026-09-01T05:16:55.639716+00:00",
}


def test_le_vrai_remplissage_cree_bien_la_position(db):
    """Garde-fou du garde-fou : la règle ne doit rien casser du cas normal."""
    mt5_sync._upsert_open_trade(REMPLISSAGE, "x@test", destination_id="admin_live")

    lignes = _lignes(db, 1357451117)
    assert len(lignes) == 1
    assert lignes[0]["pair"] == "XAU/USD"
    assert lignes[0]["direction"] == "sell"


def test_la_ligne_du_garde_fou_ne_cree_aucune_position(db):
    """Le cœur du défaut : 2 lignes pour 1 position, dont une invisible."""
    mt5_sync._upsert_open_trade(REMPLISSAGE, "x@test", destination_id="admin_live")
    mt5_sync._upsert_open_trade(GARDE_FOU_SLTP, "x@test", destination_id="admin_live")

    lignes = _lignes(db, 1357451117)
    assert len(lignes) == 1, (
        "la ligne du garde-fou SL/TP a créé une position fantôme : "
        f"{[dict(l) for l in lignes]}"
    )


def test_la_patte_de_cloture_ne_cree_aucune_position(db):
    """`close-buy` / `close-sell` sont des journaux d'action, pas des positions."""
    mt5_sync._upsert_open_trade(REMPLISSAGE, "x@test", destination_id="admin_live")
    mt5_sync._upsert_open_trade(PATTE_DE_CLOTURE, "x@test", destination_id="admin_live")

    lignes = _lignes(db, 1357451117)
    assert len(lignes) == 1


def test_aucune_ligne_ne_porte_le_symbole_du_courtier(db):
    """Le symbole non normalisé est le SECOND silence : il rend la ligne
    invisible à tout filtre `pair = 'XAU/USD'`. Aucune ligne écrite ne doit
    porter une paire sans séparateur."""
    for charge in (REMPLISSAGE, GARDE_FOU_SLTP, PATTE_DE_CLOTURE):
        mt5_sync._upsert_open_trade(charge, "x@test", destination_id="admin_live")

    with sqlite3.connect(db) as c:
        sans_slash = c.execute(
            "SELECT pair FROM personal_trades WHERE pair NOT LIKE '%/%'"
        ).fetchall()
    assert sans_slash == [], f"paires non normalisées écrites : {sans_slash}"


def test_le_refus_dit_ce_qu_il_refuse(db, caplog):
    """⛔ Un refus muet laisserait le défaut revivre. Mais surtout : l'alerte
    qui existait AVANT accusait le mauvais coupable.

    En production, ces lignes déclenchaient bien un WARNING — « entry ABSENT
    pour ticket=… Verifier `_prix_pour_audit` cote bridge ». Il envoyait
    chercher un bug de prix côté bridge, alors que la ligne n'était pas un
    remplissage du tout. Une alerte qui désigne la mauvaise cause coûte plus
    cher que pas d'alerte : elle a été lue, et elle a fait chercher ailleurs.

    Le refus doit donc nommer LA raison : ce n'est pas un ordre.
    """
    import logging

    with caplog.at_level(logging.WARNING):
        mt5_sync._upsert_open_trade(
            GARDE_FOU_SLTP, "x@test", destination_id="admin_live"
        )

    messages = [r.getMessage() for r in caplog.records]
    assert any("1357451117" in m for m in messages), (
        f"aucun journal ne mentionne le ticket refusé : {messages}"
    )
    assert not any("_prix_pour_audit" in m for m in messages), (
        "le refus renvoie encore vers `_prix_pour_audit` — mauvaise piste : "
        f"{messages}"
    )
