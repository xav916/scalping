"""Un message doit atterrir dans le fil de SON compte (2026-09-06).

⛔ Le défaut réparé : `channel=trades` visait le bot « KRAKEN Trades » et
`channel=sales` le bot « IC MARKETS trades ». `app.py` postait les clôtures sur
`trades` — si bien que « Position fermée — compte réel 13137475 » (login IC
Markets) s'affichait dans le fil Kraken — pendant que `notify-kraken-trade.sh`
postait sur `sales`, donc chez IC Markets. Les deux fils portaient l'inverse de
leur nom.

🔑 Ces tests verrouillent la seule chose qui compte : **le compte détermine le
fil**, et les anciens noms continuent de router à l'identique.
"""
from __future__ import annotations

import pytest

from backend.services import canaux_telegram as ct


# ── Le compte décide du fil ──────────────────────────────────────────

@pytest.mark.parametrize("destination_id,attendu", [
    ("admin_live", "ic_markets"),
    ("admin_kraken", "kraken"),
    ("admin_kraken_spot", "kraken"),
    ("admin_legacy", "demo"),
])
def test_chaque_compte_a_SON_fil(destination_id, attendu):
    assert ct.canal_pour(destination_id) == attendu


def test_les_quatre_fils_visent_QUATRE_bots_distincts():
    """⛔ Deux canaux partageant un jeton fusionneraient deux comptes sans
    qu'aucun test ne s'en aperçoive."""
    jetons = [v[0] for v in ct.CANAUX.values()]
    assert len(set(jetons)) == 4, jetons


def test_IBKR_ne_va_PAS_sur_un_fil_de_trading():
    """IBKR est éteint — son edge mesuré négatif. Poster son état parmi les
    trades laisserait croire qu'il en passe."""
    assert ct.canal_pour("admin_ibkr") == "infra"


def test_un_compte_INCONNU_part_sur_infra_jamais_sur_un_fil_de_trading():
    """⛔ Le repli doit être le fil le moins trompeur. Router un compte inconnu
    vers `ic_markets` lui attribuerait des trades qu'il n'a pas faits."""
    assert ct.canal_pour("admin_martien") == "infra"
    assert ct.canal_pour(None) == "infra"
    assert ct.canal_pour("") == "infra"


def test_la_destination_est_insensible_a_la_casse_et_aux_espaces():
    assert ct.canal_pour("  ADMIN_Kraken ") == "kraken"


# ── Les anciens noms ─────────────────────────────────────────────────

def test_les_alias_routent_EXACTEMENT_comme_avant():
    """⚠️ `sales` visait le bot IC Markets et `trades` le bot Kraken. Les
    intervertir « pour que ce soit logique » déplacerait 25 appelants en
    silence."""
    assert ct.normaliser("sales") == ("ic_markets", True)
    assert ct.normaliser("trades") == ("kraken", True)


def test_un_alias_se_SIGNALE():
    """Un appelant resté en arrière doit être distinguable d'un appelant
    correct — sinon on ne saura jamais la bascule terminée."""
    _, alias = ct.normaliser("trades")
    assert alias is True
    _, alias = ct.normaliser("kraken")
    assert alias is False


def test_le_canal_par_defaut_reste_infra():
    """⛔ Omettre `channel` route vers infra : documenté, et on n'y touche pas —
    le changer redirigerait silencieusement des appelants existants."""
    assert ct.normaliser(None) == ("infra", False)


def test_un_canal_inconnu_LEVE_au_lieu_de_se_replier():
    """Un nom mal orthographié doit faire une erreur 400 visible, pas un
    message rangé ailleurs."""
    with pytest.raises(KeyError):
        ct.normaliser("kraaken")


# ── Le démo était INATTEIGNABLE ──────────────────────────────────────

def test_le_fil_DEMO_est_desormais_routable():
    """⛔ `TELEGRAM_BOT_TOKEN` (bot « DEMO Trades ») n'était atteignable par
    aucun canal de l'endpoint : le fil n'était alimenté que depuis l'intérieur
    de l'app. D'où 39 non-lus et une mise en sourdine."""
    assert ct.CANAUX["demo"][0] == "TELEGRAM_BOT_TOKEN"
    assert ct.canal_pour("admin_legacy") == "demo"


def test_le_libelle_est_le_prefixe_de_compte():
    assert ct.libelle("ic_markets") == "[RÉEL · IC_MARKETS]"
    assert ct.libelle("demo") == "[DÉMO · PEPPERSTONE]"


# ── Le veto géopolitique (2026-09-06) ─────────────────────────────────────
#
# ⛔ QUATRIÈME site de routage qui contournait ce module. `send_veto_alert`
# partait sur le bot démo, via `_destinataires()` — la liste de diffusion
# CLIENTS — pour un événement qui ne concerne pas le démo.
#
# 🔑 Le veto agit dans le MOTEUR D'ANALYSE, en amont des destinations : il
# concerne tous les comptes à la fois, donc le fil d'aucun.

def _code_seul(fonction) -> str:
    """La source SANS les lignes de commentaire.

    ⛔ Une recherche naive trouve mes propres commentaires d'explication —
    qui citent forcement le defaut repare — et le test crie sur du code juste.
    Distinguer le code de la prose est exactement la lecon des trois tables de
    canaux : chercher la chaine litterale ne suffit pas.
    """
    import inspect
    lignes = [l for l in inspect.getsource(fonction).splitlines()
              if not l.lstrip().startswith("#")]
    return chr(10).join(lignes)


def test_l_alerte_de_veto_ne_diffuse_PAS_aux_clients():
    """⚠️ `_destinataires()` boucle sur `TELEGRAM_CHATS` pour servir les
    clients. Y envoyer nos vetos les leur ferait parvenir le jour où ils y
    seraient inscrits — et la liste étant vide aujourd'hui, rien ne le
    révélerait avant qu'il ne soit trop tard."""
    from backend.services import telegram_service as ts
    src = _code_seul(ts.send_veto_alert)
    assert "_destinataires()" not in src, (
        "le veto est reparti sur la liste de diffusion clients")
    assert 'jeton_et_chat("infra")' in src


def test_le_titre_du_veto_ne_dit_plus_TRADES_SUSPENDUS():
    """⛔ Lu dans le fil « DEMO Trades », « Trades suspendus » se comprend
    comme « le compte démo est suspendu » — ce qui est FAUX. Le veto porte sur
    UNE paire, et il est rare : 11 refus sur 7 jours, 0,02 % du total."""
    from backend.services import telegram_service as ts
    src = _code_seul(ts.send_veto_alert)
    assert "Trades suspendus" not in src
    assert "bloquée temporairement" in src
    assert "Cette paire SEULEMENT" in src
