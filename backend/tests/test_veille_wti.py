"""La veille WTI — elle doit PARLER quand quelque chose arrive, et se taire sinon.

⛔ Le risque de cette veille n'est pas de se tromper : c'est de rester MUETTE.
Un moniteur silencieux est indistinguable d'un marche calme — c'est deja arrive
ici (`project_moniteur_muet_jeton_mort_2026_08_20`). Ces tests verrouillent donc
chaque evenement qui doit declencher un message.

Elle est armee le 2026-10-03 parce que le WTI a ete rouvert en AUTO_EXEC sur
l'argent reel CONTRE la mesure du jour (banc : 0 cellule retenue sur 493), sans
regle d'arret. Les deux fermetures possibles sans intervention humaine sont le
regulateur de P&L (-10 %) et REM-002 (tout redeploiement).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_CHEMIN = Path(__file__).resolve().parents[2] / "scripts" / "veille_wti.py"
_spec = importlib.util.spec_from_file_location("veille_wti", _CHEMIN)
veille = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(veille)


def _releve(**kw):
    base = {
        "a": "2026-10-05T01:00:00+00:00",
        "marche_ouvert": True,
        "execution": {"autorisee": True, "motif": "ARMED",
                      "arme": "abc123", "tourne": "abc123"},
        "admission": {"buy": "AUTO_EXEC", "sell": "AUTO_EXEC"},
        "regulateur": {"action": "keep_active", "motif": "healthy", "n": 5,
                       "euros": -20.32, "pct_r": -4.96, "pct_euros": -3.13,
                       "wr": 20.0},
        "ordres": [], "dernier_ordre_id": 0, "refus": [], "tick": None,
    }
    base.update(kw)
    return base


# --- Elle doit PARLER ----------------------------------------------------

def test_le_premier_passage_annonce_l_armement():
    assert veille.evenements({}, _releve()) == ["veille armée"]


def test_un_ordre_POUSSE_declenche_un_message():
    avant = _releve()
    apres = _releve(dernier_ordre_id=7, ordres=[
        {"id": 7, "pushed_at": "2026-10-05T01:05:00+00:00", "direction": "buy",
         "horizon": "5min", "pattern": "momentum_up", "ok": 1,
         "mt5_ticket": 1360099001, "entry_price_5dp": 93.48,
         "destination_id": "admin_live", "reponse": ""}])
    ev = veille.evenements(avant, apres)
    assert any("ordre" in e for e in ev), ev


def test_PLUSIEURS_ordres_neufs_sont_comptes(monkeypatch):
    avant = _releve(dernier_ordre_id=7)
    ordres = [{"id": i, "pushed_at": "x", "direction": "buy", "horizon": "5min",
               "pattern": "p", "ok": 1, "mt5_ticket": i, "entry_price_5dp": 1,
               "destination_id": "admin_live", "reponse": ""}
              for i in (7, 8, 9, 10)]
    ev = veille.evenements(avant, _releve(dernier_ordre_id=10, ordres=ordres))
    assert any("3 ordre" in e for e in ev), ev


def test_la_MISE_EN_PAUSE_par_le_regulateur_declenche_un_message():
    """⛔ C'est l'evenement le plus important : le regulateur referme la paire
    a -10 %, et le WTI entre dans la semaine a -4,96 % avec 5 trades."""
    avant = _releve()
    apres = _releve(regulateur={**_releve()["regulateur"],
                                "action": "pause", "motif": "pnl_pct -10.4 < -10"})
    ev = veille.evenements(avant, apres)
    assert any("pause" in e for e in ev), ev


def test_une_RETROGRADATION_d_admission_declenche_un_message():
    avant = _releve()
    apres = _releve(admission={"buy": "OBSERVED", "sell": "AUTO_EXEC"})
    ev = veille.evenements(avant, apres)
    assert any("admission buy" in e for e in ev), ev


def test_l_EXECUTION_FERMEE_declenche_un_message():
    """⚠️ Tout redeploiement ferme REM-002. Sans rearmement, rien ne trade —
    et sans ce message, personne ne le saurait."""
    avant = _releve()
    apres = _releve(execution={"autorisee": False, "motif": "NEW_DEPLOYMENT",
                               "arme": "abc123", "tourne": "def456"})
    ev = veille.evenements(avant, apres)
    assert any("FERMÉE" in e for e in ev), ev
    assert any("NEW_DEPLOYMENT" in e for e in ev), ev


def test_l_OUVERTURE_du_marche_declenche_un_message():
    ev = veille.evenements(_releve(marche_ouvert=False), _releve(marche_ouvert=True))
    assert any("OUVERT" in e for e in ev), ev


# --- Elle doit se TAIRE --------------------------------------------------

def test_rien_de_neuf_ne_dit_RIEN():
    """⚠️ Une veille qui parle a chaque passage est ignoree au bout d'un jour."""
    assert veille.evenements(_releve(), _releve()) == []


def test_un_refus_de_PLUS_ne_declenche_rien():
    """Les refus se comptent par milliers : ils figurent dans le resume, ils ne
    declenchent pas d'alerte."""
    ev = veille.evenements(_releve(refus=[("stale_tick", 10)]),
                           _releve(refus=[("stale_tick", 9000)]))
    assert ev == []


def test_la_fermeture_du_marche_le_soir_ne_declenche_rien():
    ev = veille.evenements(_releve(marche_ouvert=True), _releve(marche_ouvert=False))
    assert ev == []


# --- Le message ----------------------------------------------------------

def test_le_message_porte_les_chiffres_qui_decident():
    r = _releve(dernier_ordre_id=1, ordres=[
        {"id": 1, "pushed_at": "2026-10-05T01:05:00+00:00", "direction": "buy",
         "horizon": "5min", "pattern": "momentum_up", "ok": 1,
         "mt5_ticket": 1360099001, "entry_price_5dp": 93.48,
         "destination_id": "admin_live", "reponse": ""}],
        refus=[("stale_tick", 42)],
        tick={"mid": 93.48, "spread_pct": 0.0216, "spread_max_pct": 0.3})
    m = veille.message(r, ["1 ordre(s) WTI poussé(s)"])
    for attendu in ("1360099001", "-20.32", "-4.96", "0.0216", "0.3",
                    "stale_tick", "aucune cellule", "-10 %"):
        assert attendu in m, attendu


def test_le_message_dit_quand_il_n_y_a_AUCUN_ordre():
    m = veille.message(_releve(), [])
    assert "aucun ordre WTI" in m


def test_le_message_n_a_pas_de_balise_cassee():
    """⚠️ Un seul chevron mal ferme et Telegram rejette tout le message."""
    m = veille.message(_releve(), ["veille armée"])
    assert m.count("<b>") == m.count("</b>")
    # L'esperluette doit etre echappee, sinon HTML la refuse.
    assert "P&amp;L" in m and "P&L" not in m.replace("P&amp;L", "")


# --- L'ECHAPPEMENT du texte venu de la BASE -----------------------------
#
# ⛔ DEFAUT REEL, attrape au 1er envoi du 2026-10-03 :
#     send_infra_text: HTTP 400 "can't parse entities: Unsupported start tag
#     \"\" at byte offset 280"
# Le motif du regulateur vaut litteralement << sample too small (n=5 < 10) >>.
# Telegram lit le `<` comme un debut de balise et REFUSE tout le message.
#
# 🔑 La veille aurait ete MUETTE toute la semaine, l echec ne vivant que dans
# un fichier de log que personne ne lit. Mes tests verifiaient l equilibre des
# <b> et l esperluette — pas le texte venu de la BASE.

def test_le_motif_du_regulateur_est_ECHAPPE():
    """Le vrai motif en production contient un `<`."""
    r = _releve(regulateur={**_releve()["regulateur"],
                            "motif": "sample too small (n=5 < 10)"})
    m = veille.message(r, [])
    assert "n=5 &lt; 10" in m, m
    assert "n=5 < 10" not in m


def test_tout_texte_venu_de_la_base_est_echappe():
    """⚠️ Motif, pattern, reponse du pont : tout peut porter < > &."""
    r = _releve(
        dernier_ordre_id=1,
        ordres=[{"id": 1, "pushed_at": "2026-10-05T01:05", "direction": "buy",
                 "horizon": "5min", "pattern": "a<b>&c", "ok": 0,
                 "mt5_ticket": 1, "entry_price_5dp": 93.48,
                 "destination_id": "admin_live", "reponse": "<erreur>"}],
        refus=[("motif<bizarre>", 3)],
        execution={"autorisee": False, "motif": "DENY<x>", "arme": "a<b",
                   "tourne": "c>d"},
        admission={"buy": "OBS<ERVED", "sell": "AUTO>EXEC"})
    m = veille.message(r, [])
    # Les SEULES balises doivent etre les miennes.
    import re
    balises = set(re.findall(r"</?([a-zA-Z]*)>", m))
    assert balises <= {"b"}, balises
    assert "a&lt;b&gt;&amp;c" in m
    assert "motif&lt;bizarre&gt;" in m


def test_les_evenements_aussi_sont_echappes():
    """Un evenement porte l etat venu de la base (<b>pause</b> est a MOI, mais
    le nom d etat vient du systeme)."""
    ev = veille.evenements(_releve(),
                           _releve(admission={"buy": "OB<SERVED", "sell": "AUTO_EXEC"}))
    m = veille.message(_releve(), ev)
    import re
    assert set(re.findall(r"</?([a-zA-Z]*)>", m)) <= {"b"}


# --- LE REPLI quand Telegram refuse -------------------------------------
#
# ⛔ Le tout premier envoi du 2026-10-03 a ete refuse par un HTTP 400 (un `<`
# venu de la base). La cause est corrigee, mais le principe reste : un moniteur
# qui echoue en silence est PIRE que pas de moniteur, parce qu il rassure. Une
# balise mal formee ne doit plus jamais couter le message ENTIER.

def test_un_refus_HTML_declenche_un_repli_en_texte_brut(monkeypatch, tmp_path):
    envois = []

    async def _faux_envoi(texte, parse_mode="HTML"):
        envois.append((parse_mode, texte))
        return parse_mode != "HTML"          # l'HTML echoue, le brut passe

    import sys as _sys
    faux = type(_sys)("backend.services.telegram_service")
    faux.send_infra_text = _faux_envoi
    monkeypatch.setitem(_sys.modules, "backend.services.telegram_service", faux)
    monkeypatch.setattr(veille, "ETAT", tmp_path / "etat.json")
    monkeypatch.setattr(veille, "releve", lambda: _releve())
    monkeypatch.setattr(_sys, "argv", ["veille_wti.py"])

    assert veille.main() == 0, "le repli doit rendre un succes"
    assert len(envois) == 2, envois
    assert envois[0][0] == "HTML"
    assert envois[1][0] != "HTML"
    assert "repli texte brut" in envois[1][1]
    assert "<b>" not in envois[1][1], "les balises doivent etre retirees"


def test_sans_refus_il_n_y_a_qu_UN_envoi(monkeypatch, tmp_path):
    envois = []

    async def _faux_envoi(texte, parse_mode="HTML"):
        envois.append(parse_mode)
        return True

    import sys as _sys
    faux = type(_sys)("backend.services.telegram_service")
    faux.send_infra_text = _faux_envoi
    monkeypatch.setitem(_sys.modules, "backend.services.telegram_service", faux)
    monkeypatch.setattr(veille, "ETAT", tmp_path / "etat.json")
    monkeypatch.setattr(veille, "releve", lambda: _releve())
    monkeypatch.setattr(_sys, "argv", ["veille_wti.py"])

    assert veille.main() == 0
    assert envois == ["HTML"]
