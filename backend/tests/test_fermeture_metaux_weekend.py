"""Fermer les positions avant la cloture du vendredi soir.

Demande le 2026-08-28 a 21 h 08 UTC — treize minutes APRES la cloture de l'or,
avec une position `XAUUSD sell` a +17,67 EUR qui passait le week-end faute de
moyen de la fermer. Le bridge n'avait alors que `/kill`, qui ferme TOUT.

> **Un interrupteur general n'est pas un outil de precision.**

⚠️ **PORTEE ELARGIE le 2026-09-04**, a la demande de Xavier : on ferme
desormais tout ce dont le marche ferme — forex, metaux, petrole, indices — et
plus seulement l'or et l'argent. Le gap de week-end frappe le forex comme le
metal. Le point 2 ci-dessous disait exactement l'inverse jusqu'a cette date ;
c'est un renversement assume, pas une derive.

## Ce que ces tests verrouillent

1. ⛔ **Le garde-fou du JOUR vit dans le SCRIPT**, pas seulement dans le cron.
   Un fichier de `cron.d` se copie, s'edite, se duplique en `.bak` — et
   `cron.d` charge les `.bak` (mesure : 7 sauvegardes = 240 passages/h au lieu
   de 30). Un script qui ferme des positions reelles ne peut pas dependre de
   l'endroit d'ou on l'appelle pour savoir s'il a le droit de le faire.
2. ⛔ **La CRYPTO reste ouverte** — son marche tourne le week-end, la fermer ne
   protege d'aucun gap. C'est ce qui distingue encore ce script de `/kill`, et
   ce qui l'empeche d'en redevenir un. On nomme ce qui est EXCLU, jamais ce
   qui est inclus : une liste positive laisserait un jour passer un symbole
   inconnu **le week-end**, ce qui est le mauvais cote du defaut.
3. ⛔ **Ce qui reste ouvert est NOMME dans le message.** Une exclusion
   silencieuse est une position qu'on croit fermee.
4. ⛔ **Un bridge muet ne vaut pas « rien a fermer »** — il est compte comme un
   echec, et le message le dit.
5. ⛔ **Un refus du courtier est ANNONCE**, avec son retcode. Une position qui
   passe le week-end sans qu'on le sache est le pire des deux resultats.
6. `DRY_RUN` ne ferme rien et n'envoie rien.
"""
from __future__ import annotations

import importlib.util
import pathlib
from datetime import datetime, timezone

import pytest

_SCRIPT = (pathlib.Path(__file__).resolve().parents[2]
           / "scripts" / "fermer_metaux_avant_weekend.py")


@pytest.fixture()
def s():
    spec = importlib.util.spec_from_file_location("fermeture", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pos(ticket=1, symbol="XAUUSD", type_="sell", profit=17.67, volume=0.01):
    return {"ticket": ticket, "symbol": symbol, "type": type_,
            "volume": volume, "profit": profit, "price_open": 4475.2,
            "price_current": 4454.5, "sl": 4538.64, "tp": 4361.01}


def _quand(jour: int, heure: int, minute: int) -> datetime:
    """Un instant UTC dont on choisit le jour de la semaine (0 = lundi)."""
    # 2026-08-24 est un lundi.
    return datetime(2026, 8, 24 + jour, heure, minute, tzinfo=timezone.utc)


# ── ⛔ La fenetre : le jour ET l'heure ─────────────────────────────────────

def test_vendredi_dans_la_fenetre_c_est_oui(s):
    assert s.dans_la_fenetre(_quand(4, 20, 30), 1200, 1259) is True


def test_vendredi_TROP_TOT_c_est_non(s):
    assert s.dans_la_fenetre(_quand(4, 15, 0), 1200, 1259) is False


def test_vendredi_APRES_la_cloture_c_est_non(s):
    """21 h 08 UTC : l'or a ferme depuis 8 minutes, il n'y a plus rien a
    fermer — c'est exactement l'heure ou la demande est arrivee."""
    assert s.dans_la_fenetre(_quand(4, 21, 8), 1200, 1259) is False


@pytest.mark.parametrize("jour", [0, 1, 2, 3, 5, 6])
def test_un_autre_JOUR_c_est_non_meme_a_la_bonne_heure(s, jour):
    """⛔ Le jour ET l'heure. Un script qui ferme des positions reelles ne doit
    pas pouvoir s'executer un mardi parce qu'on l'a lance a la main pour voir
    ce qu'il dit."""
    assert s.dans_la_fenetre(_quand(jour, 20, 30), 1200, 1259) is False


def test_les_bornes_sont_INCLUSIVES(s):
    assert s.dans_la_fenetre(_quand(4, 20, 0), 1200, 1259) is True
    assert s.dans_la_fenetre(_quand(4, 20, 59), 1200, 1259) is True


# ── ⛔ Tout ce dont le marche FERME (elargi le 2026-09-04) ────────────────

def test_on_ferme_TOUT_ce_dont_le_marche_ferme(s):
    """Le forex et le petrole subissent le gap du week-end comme le metal."""
    positions = [_pos(1, "XAUUSD"), _pos(2, "XAGUSD"), _pos(3, "EURUSD"),
                 _pos(4, "USDJPY"), _pos(5, "GOLD"), _pos(6, "WTIUSD"),
                 _pos(7, "GBPUSD")]
    fermer, laissees = s.a_fermer(positions)

    assert [p["ticket"] for p in fermer] == [1, 2, 3, 4, 5, 6, 7]
    assert laissees == []


def test_la_crypto_reste_OUVERTE(s):
    """⛔ Son marche tourne le week-end : la fermer ne protege d'aucun gap et
    lui coute deux jours de marche."""
    positions = [_pos(1, "EURUSD"), _pos(2, "ETHUSD"), _pos(3, "BCHUSD"),
                 _pos(4, "XAUUSD"), _pos(5, "BTCUSD")]
    fermer, laissees = s.a_fermer(positions)

    assert [p["ticket"] for p in fermer] == [1, 4]
    assert [p["ticket"] for p in laissees] == [2, 3, 5]


@pytest.mark.parametrize("symbole", ["AUDUSD", "USDCAD", "CADCHF", "AUDCAD"])
def test_une_paire_forex_n_est_JAMAIS_prise_pour_de_la_crypto(s, symbole):
    """⚠️ Le piege du `in` : « AUDUSD » contient AUD, et un jour un symbole
    contiendra par accident un ticker crypto. D'ou `startswith`."""
    assert s.traverse_le_weekend(symbole) is False


@pytest.mark.parametrize("symbole", ["ETHUSD", "ETH/USD", "BTC_USD", "adausd"])
def test_les_formes_du_symbole_crypto_sont_reconnues(s, symbole):
    assert s.traverse_le_weekend(symbole) is True


def test_aucune_position_ne_fait_pas_lever(s):
    assert s.a_fermer([]) == ([], [])
    assert s.a_fermer(None) == ([], [])


def test_une_ligne_malformee_est_ignoree(s):
    fermer, laissees = s.a_fermer([None, "bruit", {"symbol": "XAUUSD"}])
    assert fermer == [{"symbol": "XAUUSD"}]
    assert laissees == []


def test_un_symbole_ILLISIBLE_est_ferme_par_prudence(s):
    """⛔ Ne pas savoir ce que c'est n'autorise pas a le laisser passer le
    week-end : le defaut penche du cote ou l'on ferme."""
    fermer, laissees = s.a_fermer([{"symbol": None}, {"symbol": ""}])
    assert len(fermer) == 2 and laissees == []


# ── Le message ─────────────────────────────────────────────────────────────

def test_le_message_liste_ce_qui_a_ete_ferme(s):
    titre, corps = s.message([("admin_live", _pos(), {"ok": True})], [], False)
    assert "1/1" in corps
    assert "XAUUSD" in corps and "17,67 €" in corps
    assert "admin_live" in corps


def test_un_ECHEC_est_annonce_avec_son_retcode(s):
    """⛔ Une position qui passe le week-end sans qu'on le sache est le pire
    des deux resultats."""
    titre, corps = s.message(
        [], [("admin_live", _pos(), {"error": "marche ferme", "retcode": 10018})],
        False)
    assert "NON FERMEE" in corps and "10018" in corps
    assert "passe le week-end" in corps
    assert "ECHEC" in titre


def test_aucune_position_a_fermer_se_dit_aussi(s):
    _, corps = s.message([], [], False)
    assert "Aucune position a fermer" in corps


def test_une_execution_FORCEE_le_dit(s):
    """Une exception qui ne se voit pas est une regle qui n'en est plus une."""
    _, corps = s.message([], [], True)
    assert "FORCEE" in corps


def test_le_message_rappelle_ce_que_le_mecanisme_EST(s):
    """La gestion de sortie a mesure -0,329 R par trade sur l'or. Le rappeler
    la ou la fermeture est annoncee, c'est ce qui permettra de la juger."""
    _, corps = s.message([("admin_live", _pos(), {"ok": True})], [], False)
    assert "0,329 R" in corps and "pre_weekend" in corps


def test_le_corps_ne_porte_AUCUNE_balise(s):
    for fermees, echouees in (([], []),
                              ([("d", _pos(), {})], []),
                              ([], [("d", _pos(), {"retcode": 10018})])):
        titre, corps = s.message(fermees, echouees, False)
        assert "<" not in corps and ">" not in corps
        assert "<" not in titre and ">" not in titre


# ── Branchement ────────────────────────────────────────────────────────────

def _armer(s, monkeypatch, positions, fermeture_ok=True):
    """Isole `main()` du reseau. Rend le journal des appels."""
    appels = {"fermetures": [], "notifs": []}

    def _faux_appel(dest, chemin, charge=None):
        if chemin == "/positions":
            if positions is None:
                return {"error": "muet"}, False
            return {"positions": positions}, True
        appels["fermetures"].append(charge)
        if fermeture_ok:
            return {"ok": True, "ticket": charge["ticket"]}, True
        return {"ok": False, "error": "marche ferme", "retcode": 10018}, False

    monkeypatch.setattr(s, "_appel", _faux_appel)
    monkeypatch.setattr(s, "_notifier",
                        lambda t, c: appels["notifs"].append((t, c)) or True)
    return appels


def test_hors_fenetre_RIEN_n_est_ferme(s, monkeypatch):
    """⛔ Le garde-fou vit dans le script : lancer le fichier a la main un
    mardi ne doit rien fermer."""
    monkeypatch.delenv("FORCER", raising=False)
    monkeypatch.setattr(s, "dans_la_fenetre", lambda *a: False)
    appels = _armer(s, monkeypatch, [_pos()])
    assert s.main() == 0
    assert appels["fermetures"] == []
    assert appels["notifs"] == []


def test_dans_la_fenetre_metal_ET_forex_sont_fermes(s, monkeypatch):
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.setattr(s, "dans_la_fenetre", lambda *a: True)
    monkeypatch.setattr(s, "DESTINATIONS_SURVEILLEES", ("admin_live",))
    appels = _armer(s, monkeypatch, [_pos(ticket=1357145568), _pos(9, "EURUSD")])
    assert s.main() == 0
    assert [c["ticket"] for c in appels["fermetures"]] == [1357145568, 9]
    assert appels["fermetures"][0]["raison"] == "pre_weekend"


def test_le_FOREX_est_desormais_ferme_LUI_AUSSI(s, monkeypatch):
    """⚠️ RENVERSEMENT ASSUME du 2026-09-04.

    Ce test garantissait l'inverse — « le forex ouvert reste ouvert » — parce
    que le mecanisme ne visait que l'or et l'argent, et que toute sa raison
    d'etre etait de ne PAS se comporter comme `/kill`. Xavier a demande le
    04/09 de fermer les trades du vendredi soir : le gap de week-end frappe le
    forex comme le metal.

    ⛔ Il reste une difference de fond avec `/kill` : celui-ci ferme TOUT, y
    compris la crypto dont le marche ne ferme pas. Ici la crypto reste
    ouverte, et le message la nomme. C'est `test_la_crypto_reste_OUVERTE` qui
    tient cette ligne, et c'est elle qui empeche ce script de redevenir un
    interrupteur general.
    """
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.setattr(s, "dans_la_fenetre", lambda *a: True)
    monkeypatch.setattr(s, "DESTINATIONS_SURVEILLEES", ("admin_live",))
    appels = _armer(s, monkeypatch,
                    [_pos(1, "EURUSD"), _pos(2, "USDJPY"), _pos(3, "ETHUSD")])
    assert s.main() == 0
    assert [c["ticket"] for c in appels["fermetures"]] == [1, 2], (
        "le forex se ferme, la crypto non")


def test_un_bridge_MUET_est_compte_comme_un_ECHEC(s, monkeypatch):
    """⛔ « On ne sait pas » n'est pas « rien a fermer »."""
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.setattr(s, "dans_la_fenetre", lambda *a: True)
    monkeypatch.setattr(s, "DESTINATIONS_SURVEILLEES", ("admin_live",))
    appels = _armer(s, monkeypatch, None)
    assert s.main() == 1, "un bridge muet doit rendre un code d'echec"
    assert appels["notifs"], "le silence du bridge doit etre DIT"
    assert "illisibles" in appels["notifs"][0][1]


def test_un_refus_du_courtier_rend_un_code_d_echec(s, monkeypatch):
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.setattr(s, "dans_la_fenetre", lambda *a: True)
    monkeypatch.setattr(s, "DESTINATIONS_SURVEILLEES", ("admin_live",))
    appels = _armer(s, monkeypatch, [_pos()], fermeture_ok=False)
    assert s.main() == 1
    assert "NON FERMEE" in appels["notifs"][0][1]


def test_DRY_RUN_ne_ferme_RIEN(s, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr(s, "dans_la_fenetre", lambda *a: True)
    monkeypatch.setattr(s, "DESTINATIONS_SURVEILLEES", ("admin_live",))
    appels = _armer(s, monkeypatch, [_pos()])
    assert s.main() == 0
    assert appels["fermetures"] == [], "DRY_RUN a envoye un ordre de fermeture"
