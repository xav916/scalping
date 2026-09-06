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
    (0.0, False),        # rien perdu
    (-10.0, False),      # sous le plafond
    (-19.49, False),     # juste sous
    (-19.50, True),      # pile dessus : franchi
    (-32.27, True),      # le cas réel du 04/09
])
def test_le_franchissement_se_lit_sans_ambiguite(cumul, attendu):
    from backend.services import plafond_arbitrage as a
    assert a.franchi(cumul, -19.50) is attendu


def test_un_seuil_absurde_ne_franchit_jamais():
    """Un seuil nul ou positif est une anomalie de calcul, pas une porte
    ouverte — mais il ne doit pas non plus inventer un franchissement."""
    from backend.services import plafond_arbitrage as a
    assert a.franchi(-100.0, 0.0) is False
    assert a.franchi(-100.0, 19.50) is False


def test_une_autorisation_couvre_UN_plafond_de_plus_pas_la_journee():
    """Accordée à −32,27 € avec un plafond de −21,54 € : tient jusqu'à
    −53,81 €, pas un euro au-delà."""
    from backend.services import plafond_arbitrage as a
    ligne = {"pnl_au_moment": -32.27, "seuil": -21.54}

    assert a.couvre(ligne, -40.00) is True
    assert a.couvre(ligne, -53.80) is True
    assert a.couvre(ligne, -53.81) is False
    assert a.couvre(ligne, -300.00) is False


def test_une_autorisation_sans_ancrage_ne_couvre_RIEN():
    """Une ligne incomplète ne peut pas valoir permis de trader."""
    from backend.services import plafond_arbitrage as a
    assert a.couvre({}, -40.0) is False
    assert a.couvre({"pnl_au_moment": -32.27, "seuil": None}, -40.0) is False


def test_une_DERIVE_du_capital_ne_ressuscite_PAS_une_autorisation(base):
    """⛔ Le défaut vu en sondant la production le 04/09.

    Au redémarrage, le capital retombe sur `TRADING_CAPITAL` (650 €) le temps
    que le solde réel (717,93 €) revienne : le plafond glisse de −21,54 à
    −19,50 €. La première version divisait la perte par ce plafond mouvant —
    la tranche se déplaçait donc toute seule, et une autorisation périmée
    pouvait se retrouver à couvrir une perte qu'elle n'avait jamais couverte.
    """
    t, a, chemin = base

    # Autorisation donnée tôt, sur une petite perte et un plafond large.
    a.ouvrir_demande("admin_live", -21.60, -21.54)
    a.repondre(a.CONTINUER)

    # La perte s'aggrave bien au-delà de ce que cette autorisation couvrait
    # (−21,60 + −21,54 = −43,14), et le plafond s'est resserré entre-temps.
    assert a.doit_bloquer("admin_live", -60.00, -19.50) is True, (
        "une autorisation ancrée à −21,60 € ne peut pas couvrir −60 €")


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

def test_un_CONTINUER_ne_vaut_QUE_pour_sa_tranche(base):
    """⛔ « continue » à −32 € n'autorise pas −300 €.

    Sans cette borne, une seule réponse dans la journée désarmerait le plafond
    pour toutes les pertes suivantes, si profondes soient-elles.
    """
    t, a, chemin = base
    _perte(chemin, -32.27, 1001)
    t.silent_mode_active_for_destination("admin_live")
    a.repondre(a.CONTINUER)
    assert t.silent_mode_active_for_destination("admin_live") is False

    # Encore −10 € : on reste DANS la tranche autorisée (−32,27 + −19,50
    # = −51,77). Reposer la question ici serait harceler pour rien.
    _perte(chemin, -10.00, 1002)
    assert t.silent_mode_active_for_destination("admin_live") is False

    # −25 € de plus : la tranche est dépassée, la question doit revenir.
    _perte(chemin, -25.00, 1003)
    assert t.silent_mode_active_for_destination("admin_live") is True, (
        "au-delà de la tranche autorisée, la question doit être reposée")
    assert a.demandes_en_attente(), "une nouvelle demande doit être ouverte"


def test_un_GELER_ne_repose_PAS_la_question_a_chaque_perte(base):
    """Xavier a tranché : on ne le redérange pas jusqu'à minuit.

    ⚠️ Sans cette règle, chaque nouvelle perte rouvrirait une tranche et
    reposerait la question — un gel accepté deviendrait une source de bruit,
    et c'est ainsi qu'une alerte cesse d'être lue.
    """
    t, a, chemin = base
    _perte(chemin, -32.27, 1001)
    t.silent_mode_active_for_destination("admin_live")
    a.repondre(a.GELER)

    _perte(chemin, -50.00, 1002)
    assert t.silent_mode_active_for_destination("admin_live") is True
    assert a.demandes_en_attente() == [], "aucune question de plus"


def test_un_second_continue_dit_que_c_est_DEJA_en_vigueur(base):
    """⛔ Le défaut vu le 04/09 : le message était juste et trompeur.

    Xavier renvoie « continue » après une réponse déjà enregistrée. L'ancienne
    version répondait « rien n'a été modifié — on ne pré-autorise pas », ce qui
    se lit comme « ça n'a pas marché » alors que son compte tradait depuis
    16:35. Un message exact sur le fond qui laisse conclure l'inverse du vrai
    est un défaut.
    """
    t, a, chemin = base
    _perte(chemin, -32.27, 1001)
    t.silent_mode_active_for_destination("admin_live")
    a.repondre(a.CONTINUER)

    texte = a.confirmation(a.repondre(a.CONTINUER))

    assert "DEJA en vigueur" in texte, texte
    assert "AUTORISE" in texte and "admin_live" in texte, texte
    assert "-51.77" in texte, "il doit dire jusqu'où ça tient"
    assert "pre-autorise" not in texte and "pré-autorise" not in texte, (
        "ce message-là ne s'applique pas ici")


def test_un_second_gele_dit_que_le_compte_est_DEJA_gele(base):
    t, a, chemin = base
    _perte(chemin, -32.27, 1001)
    t.silent_mode_active_for_destination("admin_live")
    a.repondre(a.GELER)

    texte = a.confirmation(a.repondre(a.GELER))
    assert "DEJA en vigueur" in texte and "GELE" in texte, texte


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


# ── La décision porte sur UN compte (2026-09-06) ───────────────────────────
#
# ⛔ Le défaut : `app.py` appelait `repondre(decision)` SANS destination. Un
# seul « continue » tapé sur Telegram débloquait donc toutes les demandes en
# attente — y compris des comptes dont Xavier n'avait pas lu la ligne. Le
# service savait filtrer depuis toujours ; c'est l'appelant qui ne le faisait
# pas, et aucun test ne regardait l'appelant.
#
# 🔑 « Une porte posée d'un seul côté n'est pas une porte. »


@pytest.fixture()
def deux_en_attente(base):
    t, a, chemin = base
    a.ouvrir_demande("admin_live", -21.0, -19.5, palier=1)
    a.ouvrir_demande("admin_kraken", -33.0, -19.5, palier=1)
    return t, a, chemin


def test_un_CONTINUE_nu_avec_DEUX_comptes_est_REFUSE(deux_en_attente):
    """⛔ C'est la seule décision qui remet de l'argent réel en jeu."""
    _, a, _ = deux_en_attente
    dest, refus = a.resoudre_cible(None, a.CONTINUER)
    assert dest is None and refus
    assert "admin_live" in refus and "admin_kraken" in refus


def test_le_refus_n_ecrit_RIEN(deux_en_attente):
    """⛔ Un refus qui écrirait quand même serait pire que le défaut d'origine."""
    _, a, _ = deux_en_attente
    dest, refus = a.resoudre_cible(None, a.CONTINUER)
    assert refus
    assert len(a.demandes_en_attente()) == 2, "les deux attendent toujours"


def test_un_GELE_nu_s_applique_a_TOUS(deux_en_attente):
    """⚠️ Le gel va dans le sens qui protège : le refuser pour cause
    d'ambiguïté laisserait des comptes sans décision."""
    _, a, _ = deux_en_attente
    dest, refus = a.resoudre_cible(None, a.GELER)
    assert dest is None and refus is None
    assert a.repondre(a.GELER, dest)["applique"] == 2


def test_un_CONTINUE_NOMME_ne_touche_QUE_son_compte(deux_en_attente):
    """⛔ LE test qui compte : c'est exactement ce que le défaut violait."""
    _, a, _ = deux_en_attente
    dest, refus = a.resoudre_cible("admin_live", a.CONTINUER)
    assert refus is None and dest == "admin_live"
    r = a.repondre(a.CONTINUER, dest)
    assert r["applique"] == 1 and r["destinations"] == ["admin_live"]
    restants = [d["destination_id"] for d in a.demandes_en_attente()]
    assert restants == ["admin_kraken"], "l'autre compte reste BLOQUE"


def test_un_nom_ABREGE_est_accepte(deux_en_attente):
    """⚠️ Xavier tape « continue kraken », pas « continue admin_kraken ».
    On ne cherche que parmi les comptes EN ATTENTE, jamais au hasard."""
    _, a, _ = deux_en_attente
    assert a.resoudre_cible("kraken", a.CONTINUER)[0] == "admin_kraken"
    assert a.resoudre_cible("live", a.CONTINUER)[0] == "admin_live"


def test_un_compte_qui_N_ATTEND_PAS_est_refuse(deux_en_attente):
    """⛔ Se replier sur « toutes » parce que le nom ne matche pas
    ramènerait le défaut par la fenêtre."""
    _, a, _ = deux_en_attente
    dest, refus = a.resoudre_cible("admin_legacy", a.CONTINUER)
    assert dest is None and refus and "inconnu" in refus.lower()
    assert len(a.demandes_en_attente()) == 2


def test_un_SEUL_compte_en_attente_accepte_le_mot_nu(base):
    """Pas de régression d'ergonomie : sans ambiguïté, rien à nommer."""
    _, a, _ = base
    a.ouvrir_demande("admin_live", -21.0, -19.5, palier=1)
    dest, refus = a.resoudre_cible(None, a.CONTINUER)
    assert refus is None
    assert a.repondre(a.CONTINUER, dest)["applique"] == 1


def test_la_QUESTION_dit_comment_repondre_par_compte(deux_en_attente):
    """⛔ Sans cela le refus arrive par surprise et se lit comme une panne."""
    _, a, _ = deux_en_attente
    texte = a.construire_question(a.demandes_en_attente())
    assert "continue admin_" in texte
    assert "TOUS" in texte


def test_la_question_d_UN_SEUL_compte_ne_s_alourdit_pas(base):
    _, a, _ = base
    a.ouvrir_demande("admin_live", -21.0, -19.5, palier=1)
    texte = a.construire_question(a.demandes_en_attente())
    assert "PLUSIEURS comptes" not in texte
