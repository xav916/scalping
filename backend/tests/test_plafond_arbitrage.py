"""Le plafond journalier arbitré par Xavier (2026-09-04).

Demande : quand le plafond de perte du jour est franchi, ne plus geler tout
seul — poser la question sur Telegram et **bloquer le compte pendant tout le
temps de la réponse**.

⛔ Ce que ces tests gardent avant tout : **le dispositif ne peut PAS échouer
en ouvert.** Un arbitrage, par nature, introduit un intervalle où personne n'a
tranché ; si cet intervalle laissait passer les ordres, on aurait remplacé un
garde-fou par une formalité. Chaque panne imaginable — scheduler mort,
Telegram muet, module absent, base illisible, réponse jamais donnée — doit se
lire « bloqué ».

⚠️ Le second piège est l'inverse du premier : une autorisation trop large. Un
« continue » à −32 € ne doit pas valoir pour −300 €, et un « continue » envoyé
alors que RIEN n'est en attente ne doit rien pré-autoriser. C'est
`test_un_continue_sans_demande_n_autorise_RIEN` qui tient cette porte — sans
elle, il suffirait d'un mot envoyé le matin pour désarmer le plafond du soir.
"""
from __future__ import annotations

import sqlite3
from datetime import date

import pytest


# ── Harnais ────────────────────────────────────────────────────────────────

@pytest.fixture()
def base(tmp_path, monkeypatch):
    """Base réelle, schéma réel — comme les tests du plafond existants."""
    import backend.services.trade_log_service as t

    chemin = tmp_path / "trades.db"
    monkeypatch.setattr(t, "_DB_PATH", chemin, raising=False)
    t._init_schema()

    c = sqlite3.connect(chemin)
    c.execute("""CREATE TABLE IF NOT EXISTS mt5_pushes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, destination_id TEXT,
        bridge_response TEXT)""")
    c.commit()
    c.close()

    monkeypatch.setattr(t, "TRADING_CAPITAL", 650.0, raising=False)
    monkeypatch.setattr(t, "DAILY_LOSS_LIMIT_PCT", 3.0, raising=False)

    from backend.services import plafond_arbitrage as a
    a._init_schema()
    return t, a, chemin


def _perte(chemin, pnl, ticket, destination="admin_live", user="admin"):
    c = sqlite3.connect(chemin)
    cols = [r[1] for r in c.execute("PRAGMA table_info(personal_trades)")]
    vals = {"user": user, "pair": "XAU/USD", "direction": "buy",
            "entry_price": 4450.0, "stop_loss": 4420.0, "take_profit": 4504.0,
            "size_lot": 0.01,
            "status": "CLOSED", "pnl": pnl, "mt5_ticket": ticket,
            "destination_id": destination,
            "created_at": date.today().isoformat() + "T10:00:00"}
    utiles = {k: v for k, v in vals.items() if k in cols}
    c.execute(f"INSERT INTO personal_trades ({','.join(utiles)}) "
              f"VALUES ({','.join('?' * len(utiles))})", tuple(utiles.values()))
    c.commit()
    c.close()


# ── 1. Le palier : une autorisation ne vaut que pour sa tranche ───────────

@pytest.mark.parametrize("cumul, attendu", [
    (0.0, 0),        # rien perdu
    (-10.0, 0),      # sous le plafond
    (-19.49, 0),     # juste sous
    (-19.50, 1),     # pile dessus : franchi
    (-32.27, 1),     # le cas réel du 04/09
    (-39.00, 2),     # deuxième plafond consommé
    (-58.51, 3),
])
def test_le_palier_compte_les_plafonds_consommes(cumul, attendu):
    from backend.services import plafond_arbitrage as a
    assert a.palier_de(cumul, -19.50) == attendu


def test_un_seuil_absurde_ne_franchit_jamais():
    """Un seuil nul ou positif est une anomalie de calcul, pas une porte
    ouverte — mais il ne doit pas non plus inventer un franchissement."""
    from backend.services import plafond_arbitrage as a
    assert a.palier_de(-100.0, 0.0) == 0
    assert a.palier_de(-100.0, 19.50) == 0


# ── 2. Fermé par défaut : l'intervalle d'arbitrage BLOQUE ─────────────────

def test_le_franchissement_bloque_AVANT_toute_question(base):
    """🔑 La propriété centrale.

    Aucun message n'est parti, le scheduler n'a pas tourné, personne n'a
    répondu — et le compte est déjà bloqué. Si ce test tombe, l'arbitrage a
    remplacé le garde-fou par une fenêtre de tir.
    """
    t, a, chemin = base
    _perte(chemin, -32.27, 1001)

    assert t.silent_mode_active_for_destination("admin_live") is True
    assert a.demandes_en_attente(), "un arbitrage doit avoir été ouvert"


def test_une_demande_en_attente_bloque_toujours(base):
    t, a, chemin = base
    _perte(chemin, -32.27, 1001)
    t.silent_mode_active_for_destination("admin_live")

    assert a.doit_bloquer("admin_live", -32.27, -19.50) is True


def test_sans_reponse_le_compte_reste_bloque(base):
    """Le silence n'est pas un accord : c'est le cas le plus probable."""
    t, a, chemin = base
    _perte(chemin, -32.27, 1001)

    for _ in range(5):
        assert t.silent_mode_active_for_destination("admin_live") is True


def test_repondre_GELER_maintient_le_blocage(base):
    t, a, chemin = base
    _perte(chemin, -32.27, 1001)
    t.silent_mode_active_for_destination("admin_live")

    a.repondre(a.GELER)
    assert t.silent_mode_active_for_destination("admin_live") is True


def test_repondre_CONTINUER_debloque(base):
    """Le seul chemin qui ouvre — et il demande un mot explicite de Xavier."""
    t, a, chemin = base
    _perte(chemin, -32.27, 1001)
    t.silent_mode_active_for_destination("admin_live")

    a.repondre(a.CONTINUER)
    assert t.silent_mode_active_for_destination("admin_live") is False


# ── 3. L'autorisation ne déborde pas de sa tranche ────────────────────────

def test_un_CONTINUER_ne_vaut_QUE_pour_son_palier(base):
    """⛔ « continue » à −32 € n'autorise pas −300 €.

    Sans cette borne, une seule réponse dans la journée désarmerait le plafond
    pour toutes les pertes suivantes, si profondes soient-elles.
    """
    t, a, chemin = base
    _perte(chemin, -32.27, 1001)
    t.silent_mode_active_for_destination("admin_live")
    a.repondre(a.CONTINUER)
    assert t.silent_mode_active_for_destination("admin_live") is False

    # La perte s'aggrave et consomme un deuxième plafond.
    _perte(chemin, -15.00, 1002)
    assert t.silent_mode_active_for_destination("admin_live") is True, (
        "au palier suivant, la question doit être reposée")

    en_attente = a.demandes_en_attente()
    assert any(d["palier"] == 2 for d in en_attente)


def test_un_continue_sans_demande_n_autorise_RIEN(base):
    """⛔ La porte la plus dangereuse du dispositif.

    Un « continue » envoyé alors que rien n'est en attente ne doit rien
    pré-autoriser : sinon un mot posé le matin désarmerait le plafond du soir
    sans que personne ne l'ait vu venir.
    """
    t, a, chemin = base

    resultat = a.repondre(a.CONTINUER)
    assert resultat["applique"] == 0

    _perte(chemin, -32.27, 1001)
    assert t.silent_mode_active_for_destination("admin_live") is True


def test_l_arbitrage_d_un_compte_ne_debloque_pas_l_autre(base):
    """La portée par destination, acquise le 03/09, doit survivre."""
    t, a, chemin = base
    _perte(chemin, -32.27, 1001, destination="admin_live")
    _perte(chemin, -30.00, 1002, destination="admin_kraken")
    t.silent_mode_active_for_destination("admin_live")
    t.silent_mode_active_for_destination("admin_kraken")

    a.repondre(a.CONTINUER, destination_id="admin_live")

    assert t.silent_mode_active_for_destination("admin_live") is False
    assert t.silent_mode_active_for_destination("admin_kraken") is True, (
        "seul le compte nommé est débloqué")


# ── 4. Ce qui n'a pas changé ──────────────────────────────────────────────

def test_sous_le_plafond_rien_ne_se_declenche(base):
    """Aucune demande parasite : la question ne se pose qu'au franchissement."""
    t, a, chemin = base
    _perte(chemin, -10.00, 1001)

    assert t.silent_mode_active_for_destination("admin_live") is False
    assert a.demandes_en_attente() == []


def test_la_demo_n_est_toujours_pas_concernee(base):
    """Elle perd de l'argent qui n'existe pas — acquis du 2026-08-20."""
    t, a, chemin = base
    _perte(chemin, -500.00, 1001, destination="admin_legacy")
    assert t.silent_mode_active_for_destination("admin_legacy") is False


def test_module_d_arbitrage_absent_rend_le_GEL_pas_le_passage(base, monkeypatch):
    """⛔ Une panne d'import ne peut pas valoir autorisation."""
    t, a, chemin = base
    _perte(chemin, -32.27, 1001)

    import builtins
    vrai_import = builtins.__import__

    def _casse(nom, *args, **kw):
        if nom.endswith("plafond_arbitrage"):
            raise ImportError("simulé")
        return vrai_import(nom, *args, **kw)

    monkeypatch.setattr(builtins, "__import__", _casse)
    assert t.silent_mode_active_for_destination("admin_live") is True


# ── 5. La question part, et une seule fois ────────────────────────────────

@pytest.mark.asyncio
async def test_la_question_est_posee_une_seule_fois(base, monkeypatch):
    """⛔ `doit_bloquer` est appelé des centaines de fois par jour (570 le
    04/09). Sans idempotence, Xavier recevrait la question à chaque signal."""
    t, a, chemin = base
    _perte(chemin, -32.27, 1001)
    for _ in range(20):
        t.silent_mode_active_for_destination("admin_live")

    envoyes = []

    async def _ok(texte, parse_mode=None):
        envoyes.append(texte)
        return True

    monkeypatch.setattr("backend.services.telegram_service.send_sales_text", _ok)
    assert await a.executer() == 1
    assert await a.executer() == 0
    assert len(envoyes) == 1


@pytest.mark.asyncio
async def test_un_envoi_ECHOUE_laisse_la_demande_ouverte(base, monkeypatch):
    """⛔ La règle des sondes : le curseur n'avance que sur un envoi confirmé.

    Marquer avant confirmation laisserait le compte bloqué sur une question
    que personne n'a reçue — c'est le moniteur muet du 20/08, mais avec un
    compte à l'arrêt au bout.
    """
    t, a, chemin = base
    _perte(chemin, -32.27, 1001)
    t.silent_mode_active_for_destination("admin_live")

    async def _echec(texte, parse_mode=None):
        return False

    monkeypatch.setattr("backend.services.telegram_service.send_sales_text",
                        _echec)
    assert await a.executer() == 0

    envoyes = []

    async def _ok(texte, parse_mode=None):
        envoyes.append(texte)
        return True

    monkeypatch.setattr("backend.services.telegram_service.send_sales_text", _ok)
    assert await a.executer() == 1, "la question doit être retentée"


@pytest.mark.asyncio
async def test_aucune_question_quand_rien_n_est_en_attente(base, monkeypatch):
    t, a, chemin = base
    envoyes = []

    async def _ok(texte, parse_mode=None):
        envoyes.append(texte)
        return True

    monkeypatch.setattr("backend.services.telegram_service.send_sales_text", _ok)
    assert await a.executer() == 0
    assert envoyes == []


def test_le_message_ne_casse_pas_le_HTML(base):
    """Le canal poste en HTML : un chevron mal formé fait refuser le message
    ENTIER par Telegram, en silence."""
    t, a, chemin = base
    _perte(chemin, -32.27, 1001)
    t.silent_mode_active_for_destination("admin_live")

    texte = a.construire_question(a.demandes_en_attente())
    assert "<" not in texte and ">" not in texte
    assert "gele" in texte and "continue" in texte
    assert "DEJA bloque" in texte, (
        "le message doit dire que le blocage est déjà en vigueur")
