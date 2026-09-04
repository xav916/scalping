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


def _pos(ticket=1, symbol="XAUUSD", type_="sell", profit=17.67, volume=0.01,
         part=None, tp=4361.01):
    """Une position ouverte.

    ``part`` fixe la fraction du chemin DEJA parcourue vers l'objectif — c'est
    elle qui decide desormais si la position se ferme. Le prix courant en est
    deduit, pour que le jeu d'essai dise la meme chose que la regle.
    """
    entree = 4475.2
    p = {"ticket": ticket, "symbol": symbol, "type": type_,
         "volume": volume, "profit": profit, "price_open": entree,
         "price_current": 4454.5, "sl": 4538.64, "tp": tp}
    if part is not None and tp:
        vente = str(type_).lower().startswith("s")
        distance = (entree - tp) if vente else (tp - entree)
        acquis = part * distance
        p["price_current"] = entree - acquis if vente else entree + acquis
    return p


def _au_seuil(ticket=1, symbol="XAUUSD", **kw):
    """Une position qui a franchi le tiers — donc a fermer."""
    return _pos(ticket, symbol, part=0.40, **kw)


def _trop_tot(ticket=1, symbol="XAUUSD", **kw):
    """Une position sous le tiers — donc a garder."""
    return _pos(ticket, symbol, part=0.10, **kw)


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

def test_on_ferme_TOUT_ce_dont_le_marche_ferme_SI_le_seuil_est_atteint(s):
    """Le forex et le petrole subissent le gap du week-end comme le metal —
    mais seules les positions assez avancees sont fermees."""
    positions = [_au_seuil(1, "XAUUSD"), _au_seuil(2, "XAGUSD"),
                 _au_seuil(3, "EURUSD"), _au_seuil(4, "USDJPY"),
                 _au_seuil(5, "GOLD"), _au_seuil(6, "WTIUSD"),
                 _au_seuil(7, "GBPUSD")]
    fermer, laissees = s.a_fermer(positions)

    assert [p["ticket"] for p, _m in fermer] == [1, 2, 3, 4, 5, 6, 7]
    assert laissees == []


def test_la_crypto_reste_OUVERTE(s):
    """⛔ Son marche tourne le week-end : la fermer ne protege d'aucun gap et
    lui coute deux jours de marche."""
    positions = [_au_seuil(1, "EURUSD"), _au_seuil(2, "ETHUSD"),
                 _au_seuil(3, "BCHUSD"), _au_seuil(4, "XAUUSD"),
                 _au_seuil(5, "BTCUSD")]
    fermer, laissees = s.a_fermer(positions)

    assert [p["ticket"] for p, _m in fermer] == [1, 4]
    assert [p["ticket"] for p, _m in laissees] == [2, 3, 5]
    assert all("week-end" in motif for _p, motif in laissees)


# ── 🔑 La regle du TIERS (2026-09-04) ─────────────────────────────────────

def test_sous_le_TIERS_on_ATTEND(s):
    """🔑 Le coeur de la demande : « sinon attendre ».

    ⛔ La position traverse le week-end plutot que d'etre bradee a mi-chemin
    sous la contrainte d'une horloge. C'est un risque de gap assume, pas un
    oubli — et le motif le dit.
    """
    fermer, laissees = s.a_fermer([_trop_tot(1, "XAUUSD")])

    assert fermer == []
    assert len(laissees) == 1
    assert "10% du chemin" in laissees[0][1], laissees[0][1]


def test_PILE_au_tiers_ca_ferme(s):
    """⛔ Le seuil est inclusif, et doit le rester a la limite EXACTE.

    Sans l'epsilon importe de la sonde des paliers, `4475,2 - 114,19/3` puis
    la soustraction rendent 0,33333315 au lieu de 0,3333333 : une position
    pile au tiers ne declencherait pas, a cause d'une erreur de
    representation a une magnitude de 4 475.
    """
    fermer, laissees = s.a_fermer([_pos(1, "XAUUSD", part=1 / 3)])

    assert [p["ticket"] for p, _m in fermer] == [1], laissees


def test_le_seuil_est_reglable(s):
    """La regle est un reglage, pas une constante enfouie."""
    p = _pos(1, "XAUUSD", part=0.25)
    assert s.a_fermer([p], seuil=0.20)[0] != []
    assert s.a_fermer([p], seuil=0.50)[0] == []


def test_une_position_SANS_objectif_reste_ouverte_et_le_DIT(s):
    """⛔ On ne decide pas dans le noir.

    Sans objectif, « un tiers du chemin » n'a aucun sens : la regle de Xavier
    ne peut pas s'appliquer. On garde la position et on NOMME la raison —
    la confondre avec « pas assez avancee » ferait passer une donnee cassee
    pour un choix de trading.
    """
    fermer, laissees = s.a_fermer([_pos(1, "XAUUSD", tp=0)])

    assert fermer == []
    assert "non mesurable" in laissees[0][1], laissees[0][1]


def test_un_objectif_du_MAUVAIS_COTE_n_est_pas_pris_pour_un_avancement(s):
    """⚠️ Mesure d'aout : 14 % des TP stockes etaient du mauvais cote de
    l'entree reelle. Un tel TP donnerait une part negative ou absurde."""
    fermer, laissees = s.a_fermer(
        [_pos(1, "XAUUSD", type_="sell", tp=4600.0)])

    assert fermer == []
    assert "non mesurable" in laissees[0][1], laissees[0][1]


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
    fermer, laissees = s.a_fermer([None, "bruit", _au_seuil(1, "XAUUSD")])
    assert [p["ticket"] for p, _m in fermer] == [1]


def test_un_symbole_ILLISIBLE_ne_ferme_PAS_a_l_aveugle(s):
    """⛔ Un symbole qu'on ne sait pas nommer n'a pas non plus de prix
    exploitable : il ressort « non mesurable », pas ferme d'office. On garde,
    et on le dit — decider sans mesure serait le vrai danger."""
    fermer, laissees = s.a_fermer([{"symbol": None}, {"symbol": ""}])
    assert fermer == []
    assert all("non mesurable" in motif for _p, motif in laissees)


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
    appels = _armer(s, monkeypatch,
                    [_au_seuil(1357145568), _au_seuil(9, "EURUSD")])
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
                    [_au_seuil(1, "EURUSD"), _au_seuil(2, "USDJPY"),
                     _au_seuil(3, "ETHUSD")])
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
    appels = _armer(s, monkeypatch, [_au_seuil()], fermeture_ok=False)
    assert s.main() == 1
    assert "NON FERMEE" in appels["notifs"][0][1]


def test_DRY_RUN_ne_ferme_RIEN(s, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr(s, "dans_la_fenetre", lambda *a: True)
    monkeypatch.setattr(s, "DESTINATIONS_SURVEILLEES", ("admin_live",))
    appels = _armer(s, monkeypatch, [_pos()])
    assert s.main() == 0
    assert appels["fermetures"] == [], "DRY_RUN a envoye un ordre de fermeture"


# ── ⏰ Le PREAVIS d'une heure avant la cloture (2026-09-04) ────────────────
#
# Demande de Xavier : « recevoir un message telegram une heure avant la cloture
# du weekend m'indiquant tous les trades en cours et ceux fermés que le cron
# job a cloturé ». Les DEUX listes, dans le meme message — il lui reste une
# heure pour agir a la main, il lui faut l'etat complet sous les yeux.

def test_le_journal_retient_ce_que_le_cron_a_ferme(s, tmp_path):
    """⛔ Sans trace, le preavis ne saurait dire QUE ce qu'il vient de fermer.

    Le script passe toutes les 5 min ; celui de 20:00 n'a aucune memoire de
    celui de 14:35. Le journal est ce qui rend la question repondable.
    """
    base = str(tmp_path / "j.db")
    s.journaliser("admin_live", _au_seuil(42, "XAUUSD"),
                  {"part": 0.41}, chemin=base)

    lignes = s.fermetures_du_jour(chemin=base)
    assert len(lignes) == 1
    assert lignes[0]["ticket"] == "42"
    assert lignes[0]["symbole"] == "XAUUSD"
    assert round(lignes[0]["part"], 2) == 0.41


def test_le_journal_ne_compte_pas_DEUX_FOIS_le_meme_ticket(s, tmp_path):
    """Idempotent : deux passages sur le meme ticket ne font pas deux lignes."""
    base = str(tmp_path / "j.db")
    for _ in range(3):
        s.journaliser("admin_live", _au_seuil(42), {"part": 0.41}, chemin=base)
    assert len(s.fermetures_du_jour(chemin=base)) == 1


def test_un_journal_ILLISIBLE_n_empeche_pas_de_fermer(s):
    """⛔ Le journal sert a raconter, la fermeture sert a proteger.

    Confondre les deux priorites ferait rater une sortie pour cause de disque
    plein. `journaliser` avale donc son erreur, et le dit sur la sortie.
    """
    s.journaliser("admin_live", _au_seuil(42), {"part": 0.41},
                  chemin="/chemin/qui/n/existe/pas/x.db")   # ne doit PAS lever


def test_le_preavis_liste_les_DEUX_ensembles(s):
    """🔑 Le coeur de la demande : en cours ET fermes, dans un seul message."""
    deja = [{"symbole": "XAUUSD", "sens": "sell", "destination_id": "admin_live",
             "ticket": "42", "part": 0.41, "profit": 17.67,
             "ferme_le": "2026-09-04T18:20:11+00:00"}]
    laissees = [("admin_live", _trop_tot(7, "EURUSD"), "9% du chemin seulement")]

    _titre, corps = s.message([], [], False, laissees, deja)

    assert "XAUUSD" in corps and "42" in corps and "18:20" in corps
    assert "41%" in corps, "l'avancement au moment de la fermeture"
    assert "EURUSD" in corps and "9%" in corps
    assert "aujourd'hui" in corps


def test_le_preavis_parle_MEME_sans_rien_avoir_ferme(s, monkeypatch):
    """⛔ C'est le seul passage qui parle dans le silence.

    Les ~100 autres passages du vendredi se taisent — sans quoi l'alerte
    deviendrait du bruit, et le bruit ne se lit plus.
    """
    monkeypatch.setattr(s, "PREAVIS", True)
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.setattr(s, "dans_la_fenetre", lambda *a: True)
    monkeypatch.setattr(s, "DESTINATIONS_SURVEILLEES", ("admin_live",))
    monkeypatch.setattr(s, "fermetures_du_jour", lambda *a, **k: [])
    appels = _armer(s, monkeypatch, [_trop_tot(1, "EURUSD")])

    assert s.main() == 0
    assert appels["fermetures"] == [], "rien ne doit etre ferme"
    assert appels["notifs"], "le preavis doit PARLER"
    assert "EURUSD" in appels["notifs"][0][1]


def test_un_passage_ORDINAIRE_reste_MUET(s, monkeypatch):
    """Le pendant du test precedent, et la raison pour laquelle il tient."""
    monkeypatch.setattr(s, "PREAVIS", False)
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.setattr(s, "dans_la_fenetre", lambda *a: True)
    monkeypatch.setattr(s, "DESTINATIONS_SURVEILLEES", ("admin_live",))
    appels = _armer(s, monkeypatch, [_trop_tot(1, "EURUSD")])

    assert s.main() == 0
    assert appels["notifs"] == [], "un passage sans fermeture ne parle pas"


def test_le_corps_du_preavis_ne_porte_AUCUNE_balise(s):
    deja = [{"symbole": "XAUUSD", "sens": "sell", "destination_id": "admin_live",
             "ticket": "42", "part": 0.41, "profit": 17.67,
             "ferme_le": "2026-09-04T18:20:11+00:00"}]
    _titre, corps = s.message([], [], False, [], deja)
    assert "<" not in corps and ">" not in corps


def test_main_JOURNALISE_vraiment_ce_qu_il_ferme(s, monkeypatch, tmp_path):
    """⛔ Le branchement, pas la fonction.

    `journaliser` peut etre parfait et n'etre jamais appele : c'est le trou
    qu'avait le detecteur de positions nues. Sans ce test, retirer l'appel dans
    `main()` ne casse rien — verifie le 04/09, la mutation passait inapercue —
    et le preavis annoncerait « rien ferme aujourd'hui » un soir ou le cron
    aurait ferme six positions.
    """
    base = str(tmp_path / "j.db")
    monkeypatch.setattr(s, "JOURNAL", base)
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.setattr(s, "dans_la_fenetre", lambda *a: True)
    monkeypatch.setattr(s, "DESTINATIONS_SURVEILLEES", ("admin_live",))
    _armer(s, monkeypatch, [_au_seuil(4242, "XAUUSD")])

    assert s.main() == 0

    lignes = s.fermetures_du_jour(chemin=base)
    assert [l["ticket"] for l in lignes] == ["4242"], (
        "la fermeture doit avoir laisse une trace")


def test_une_fermeture_ECHOUEE_n_est_PAS_journalisee(s, monkeypatch, tmp_path):
    """Le journal dit ce qui EST ferme, pas ce qu'on esperait fermer.

    Sinon le preavis annoncerait comme close une position qui passe le
    week-end — le pire des deux resultats, deja nomme pour les echecs.
    """
    base = str(tmp_path / "j.db")
    monkeypatch.setattr(s, "JOURNAL", base)
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.setattr(s, "dans_la_fenetre", lambda *a: True)
    monkeypatch.setattr(s, "DESTINATIONS_SURVEILLEES", ("admin_live",))
    _armer(s, monkeypatch, [_au_seuil(4242, "XAUUSD")], fermeture_ok=False)

    assert s.main() == 1
    assert s.fermetures_du_jour(chemin=base) == []


def test_DRY_RUN_n_ecrit_RIEN_dans_le_journal(s, monkeypatch, tmp_path):
    """Un essai a blanc qui laisserait une trace ferait mentir le preavis."""
    base = str(tmp_path / "j.db")
    monkeypatch.setattr(s, "JOURNAL", base)
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr(s, "dans_la_fenetre", lambda *a: True)
    monkeypatch.setattr(s, "DESTINATIONS_SURVEILLEES", ("admin_live",))
    _armer(s, monkeypatch, [_au_seuil(4242, "XAUUSD")])

    s.main()
    assert s.fermetures_du_jour(chemin=base) == []
