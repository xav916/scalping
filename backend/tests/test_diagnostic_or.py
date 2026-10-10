"""Le diagnostic « pourquoi l'or ne part pas », et `/trade` dans le webhook.

Demandé par Xavier le 2026-10-10. Il a posé **trois fois** la question
*« pourquoi je n'ai plus de trades lancés »*.

## ⛔ LE DÉFAUT QUI A COÛTÉ TROIS TENTATIVES

Première version : un écouteur `getUpdates` dans le moniteur d'infra.

1. **Mauvais bot.** Câblé sur `TRADES_TELEGRAM_BOT_TOKEN`, qui s'appelle
   « KRAKEN Trades ». L'or du réel vit sur « IC MARKETS Trades », soit
   `SALES_*`. `canaux_telegram.py` le documentait déjà.
2. **Markdown cassé.** Les codes de refus sont en snake_case et Telegram lit
   un `_` comme une italique ouverte → `400 Can't find end of the entity`,
   message jamais livré.
3. **Et surtout : `getUpdates` était IMPOSSIBLE.** Le bot IC MARKETS porte
   **déjà un webhook** (`/api/telegram/sales-webhook`) et Telegram répond
   `409 Conflict: can't use getUpdates while webhook is active`.

⇒ Les messages de Xavier arrivaient **dans le radar**, par ce webhook. Le
diagnostic vit donc là, et `/trade` est traité dans la route qui gère déjà
`recap`, `risque` et `gele`/`continue`.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.services import diagnostic_or as D


# ─────────────────────────────────────────────────────────────────────────
# 1. Le texte : fonction pure
# ─────────────────────────────────────────────────────────────────────────

def test_il_dit_D_ABORD_si_le_marche_est_FERME():
    """⛔ Sans ces lignes, il remontait `verdict_blocker` un samedi, alors que
    la seule chose à savoir était « le marché est fermé »."""
    t = D.formater({"total": 0, "radar": 0, "main": 0},
                   [("verdict_blocker", 122)], None,
                   {"marche": False, "fenetre": False})

    lignes = t.splitlines()
    assert "FERME" in lignes[0]
    assert "FERMEE" in lignes[1]


def test_il_dit_si_l_EXECUTION_est_desarmee():
    """🔑 REM-002 désarmé, aucun ordre ne part — et ça s'est produit 6 h sans
    que personne ne le lise, le 2026-10-08."""
    t = D.formater({"total": 0}, [], None,
                   {"marche": True, "fenetre": True, "execution": False})

    assert "DESARMEE" in t


def test_AUCUNE_emphase_Markdown_dans_le_texte():
    """⛔ LE DÉFAUT N°2. `_` ouvre une italique chez Telegram : l'envoi rendait
    400 et rien n'arrivait. Les codes doivent rester lisibles TELS QUELS."""
    t = D.formater({"total": 3, "radar": 2, "main": 1},
                   [("max_positions_per_pair_indecidable", 593),
                    ("verdict_blocker", 122)], 12.0,
                   {"marche": False, "fenetre": False, "execution": True})

    assert "*" not in t, t
    assert "max_positions_per_pair_indecidable" in t


def test_les_positions_RADAR_et_MAIN_sont_separees():
    """🔑 Les mélanger masquerait le signal : sa main gagne, le radar perd."""
    t = D.formater({"total": 3, "radar": 2, "main": 1}, [], 5.0)

    assert "radar 2" in t and "main 1" in t


def test_un_courtier_ILLISIBLE_se_DIT_au_lieu_de_valoir_zero():
    """⛔ `max_positions_per_pair_indecidable` a refusé 593 signaux le 09/10
    parce qu'on ne POUVAIT PAS compter. Afficher « 0 » ferait croire que la
    place est libre."""
    t = D.formater({}, [], None)

    assert "illisibles" in t.lower()
    assert "en vie : 0" not in t


def test_le_blocage_dominant_est_TRADUIT():
    t = D.formater({"total": 0}, [("heure_spread_defavorable", 2377)], None)

    assert "heure_spread_defavorable" in t
    assert "hors des heures" in t
    assert "2377" in t


def test_un_motif_INCONNU_ne_fait_pas_LEVER():
    """⚠️ Un code ajouté demain ne doit pas rendre le diagnostic muet."""
    t = D.formater({"total": 0}, [("un_motif_tout_neuf", 7)], None)

    assert "un_motif_tout_neuf" in t and "non traduit" in t


def test_des_portes_ILLISIBLES_se_TAISENT_au_lieu_d_inventer():
    """⚠️ Affirmer « ouvert » quand on ne sait pas est pire que se taire."""
    t = D.formater({"total": 0}, [], None, {})

    assert "Marche de l'or" not in t and "fenetre hebdo" not in t


def test_aucun_refus_est_une_information_aussi():
    assert "aucun refus" in D.formater({"total": 1}, [], 3.0).lower()


# ─────────────────────────────────────────────────────────────────────────
# 2. La lecture de la base
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def base(tmp_path):
    p = tmp_path / "t.db"
    with sqlite3.connect(p) as c:
        c.execute("""CREATE TABLE personal_trades (
            id INTEGER PRIMARY KEY, pair TEXT, closed_at TEXT, created_at TEXT,
            destination_id TEXT, notes TEXT)""")
        c.execute("""CREATE TABLE signal_rejections (
            id INTEGER PRIMARY KEY, pair TEXT, reason_code TEXT,
            created_at TEXT)""")
    return str(p)


def _maintenant(minutes=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def test_elle_compte_les_positions_OUVERTES_par_origine(base):
    with sqlite3.connect(base) as c:
        c.execute("INSERT INTO personal_trades VALUES "
                  "(1,'XAU/USD',NULL,?,'admin_live','scalping-radar-x')",
                  (_maintenant(5),))
        c.execute("INSERT INTO personal_trades VALUES "
                  "(2,'XAU/USD',NULL,?,'admin_live','MANUEL-TERM')",
                  (_maintenant(5),))
        # ⛔ fermee : ne doit PAS compter
        c.execute("INSERT INTO personal_trades VALUES "
                  "(3,'XAU/USD',?,?,'admin_live','scalping-radar-x')",
                  (_maintenant(1), _maintenant(9)))

    live, _b, _m = D.lire(base)

    assert live == {"radar": 1, "main": 1, "total": 2}


def test_elle_ne_regarde_que_les_refus_RECENTS(base):
    """⛔ LA BORNE EST CALCULEE EN PYTHON. `created_at` est de l'ISO AVEC
    fuseau : le comparer a datetime('now') ne filtrerait RIEN, et le
    diagnostic remonterait des refus de la semaine derniere."""
    with sqlite3.connect(base) as c:
        c.execute("INSERT INTO signal_rejections VALUES "
                  "(1,'XAU/USD','verdict_blocker',?)", (_maintenant(5),))
        c.execute("INSERT INTO signal_rejections VALUES "
                  "(2,'XAU/USD','market_closed',?)", (_maintenant(500),))

    _l, blocages, _m = D.lire(base)

    assert blocages == [("verdict_blocker", 1)], blocages


def test_elle_ignore_les_AUTRES_paires(base):
    with sqlite3.connect(base) as c:
        c.execute("INSERT INTO signal_rejections VALUES "
                  "(1,'EUR/USD','verdict_blocker',?)", (_maintenant(5),))

    _l, blocages, _m = D.lire(base)

    assert blocages == []


def test_le_dernier_ordre_exclut_les_trades_A_LA_MAIN(base):
    """🔑 << dernier ordre DU RADAR >> : un trade ouvert a la main ne doit pas
    faire croire que le radar vient de tirer."""
    with sqlite3.connect(base) as c:
        c.execute("INSERT INTO personal_trades VALUES "
                  "(1,'XAU/USD',NULL,?,'admin_live','MANUEL-TERM')",
                  (_maintenant(2),))
        c.execute("INSERT INTO personal_trades VALUES "
                  "(2,'XAU/USD',NULL,?,'admin_live','scalping-radar-x')",
                  (_maintenant(90),))

    _l, _b, minutes = D.lire(base)

    assert minutes is not None and 85 < minutes < 95, minutes


def test_une_base_ABSENTE_ne_fait_pas_LEVER(tmp_path):
    """⚠️ Appele depuis un webhook : une exception y rendrait 500 a Telegram,
    qui REESSAIERAIT le message."""
    live, blocages, minutes = D.lire(str(tmp_path / "nexiste_pas.db"))

    assert live == {} and blocages == [] and minutes is None


# ─────────────────────────────────────────────────────────────────────────
# 3. ⛔ `/trade` est BRANCHÉ dans le webhook, pas dans un getUpdates
# ─────────────────────────────────────────────────────────────────────────

def test_trade_est_traite_dans_le_WEBHOOK_sales():
    """⛔ LE DÉFAUT N°3, ET LE PLUS COÛTEUX. Le bot IC MARKETS porte DEJA un
    webhook, et Telegram refuse `getUpdates` tant qu'il est actif :

        409 Conflict: can't use getUpdates method while webhook is active

    Mon ecouteur ne pouvait RIEN recevoir. Les messages arrivent dans le
    radar, par ce webhook : `/trade` doit donc y etre traite.
    """
    src = (Path(__file__).resolve().parents[1] / "app.py").read_text(
        encoding="utf-8")
    debut = src.index('@app.post("/api/telegram/sales-webhook")')
    fin = src.index("\n@app.", debut + 10)
    bloc = src[debut:fin]

    assert "/trade" in bloc, "la commande n'est pas branchee dans le webhook"
    assert "declencheur_manuel" in bloc or "declencher" in bloc, bloc[:200]
    assert "diagnostic_or" in bloc, "le webhook ne rend pas le diagnostic"


def test_le_moniteur_ne_POLL_plus_le_bot_sales():
    """⛔ Deux chemins pour la meme commande, dont un IMPOSSIBLE (409). Le
    `getUpdates` sur un bot a webhook journalisait une erreur toutes les 5 s."""
    src = (Path(__file__).resolve().parents[2] / "mt5-bridge-monitor"
           / "bridge_monitor.py").read_text(encoding="utf-8")

    assert "trades_listener_thread" not in src or \
           "SALES_TELEGRAM_BOT_TOKEN" not in src, (
        "le moniteur poll encore le bot qui porte un webhook")
