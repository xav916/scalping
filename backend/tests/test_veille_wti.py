"""La veille multi-paires — elle doit PARLER quand il se passe quelque chose.

⛔ Le risque de cette veille n'est pas de se tromper : c'est de rester MUETTE.
Un moniteur silencieux est indistinguable d'un marche calme — c'est deja arrive
ici (`project_moniteur_muet_jeton_mort_2026_08_20`), et le tout premier envoi du
2026-10-03 a ete refuse par un HTTP 400 sans que rien ne le signale ailleurs que
dans un log. Ces tests verrouillent donc chaque evenement qui doit declencher.

Elle surveille `VEILLE_PAIRES` sur `admin_live` — le WTI depuis le 2026-10-03,
puis BTC et ETH depuis le 2026-10-04, apres que Xavier ait fait EXEMPTER ces
deux paires de la porte des frais. Ce qui est surveille n'est donc justifie par
aucune mesure : c'est precisement pour ca qu'on regarde.

Trois choses peuvent fermer une paire sans intervention humaine, et ce sont
elles qu'on guette : le regulateur de P&L (-10 %), une retrogradation
d'admission, et REM-002 que tout redeploiement referme.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_CHEMIN = Path(__file__).resolve().parents[2] / "scripts" / "veille_wti.py"
_spec = importlib.util.spec_from_file_location("veille_wti", _CHEMIN)
veille = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(veille)


def _pair(**kw):
    base = {
        "marche_ouvert": True,
        "admission": {"buy": "AUTO_EXEC", "sell": "AUTO_EXEC"},
        "regulateur": {"action": "keep_active",
                       "motif": "sample too small (n=5 < 10)", "n": 5,
                       "euros": -20.32, "pct_r": -4.96, "pct_euros": -3.13,
                       "wr": 20.0},
        "ordres": [], "dernier_ordre_id": 0, "refus": [], "tick": None,
    }
    base.update(kw)
    return base


def _releve(paires=None, autorisee=True, motif="ARMED"):
    return {
        "a": "2026-10-05T01:00:00+00:00",
        "execution": {"autorisee": autorisee, "motif": motif,
                      "arme": "abc123", "tourne": "abc123"},
        "paires": paires if paires is not None else {
            "BTC/USD": _pair(), "ETH/USD": _pair(), "WTI/USD": _pair()},
    }


def _ordre(i, ok=1):
    return {"id": i, "pushed_at": "2026-10-05T01:05:00+00:00",
            "direction": "buy", "horizon": "5min", "pattern": "fvg_up",
            "ok": ok, "mt5_ticket": 1360099000 + i,
            "entry_price_5dp": 84704.89, "destination_id": "admin_live",
            "reponse": ""}


# ─── Elle doit PARLER ────────────────────────────────────────────────────

def test_le_premier_passage_annonce_les_paires_surveillees():
    ev = veille.evenements({}, _releve())
    assert len(ev) == 1
    for p in ("BTC/USD", "ETH/USD", "WTI/USD"):
        assert p in ev[0], ev


def test_un_ordre_sur_BTC_declenche_un_message():
    apres = _releve({"BTC/USD": _pair(dernier_ordre_id=7, ordres=[_ordre(7)]),
                     "ETH/USD": _pair(), "WTI/USD": _pair()})
    ev = veille.evenements(_releve(), apres)
    assert any("BTC/USD" in e and "1 ordre" in e for e in ev), ev


def test_un_ordre_sur_ETH_declenche_aussi():
    """⚠️ Chaque paire est suivie SEPAREMENT : une veille qui ne regarderait
    que la premiere serait muette sur les autres."""
    apres = _releve({"BTC/USD": _pair(),
                     "ETH/USD": _pair(dernier_ordre_id=3, ordres=[_ordre(3)]),
                     "WTI/USD": _pair()})
    ev = veille.evenements(_releve(), apres)
    assert any("ETH/USD" in e for e in ev), ev
    assert not any("BTC/USD" in e for e in ev), ev


def test_les_ordres_EN_ECHEC_sont_comptes_a_part():
    """Un ordre refuse par le courtier n'est pas un trade — il faut le voir."""
    avant = _releve({"BTC/USD": _pair(), "ETH/USD": _pair()})
    apres = _releve({"BTC/USD": _pair(dernier_ordre_id=9,
                                      ordres=[_ordre(8, ok=1), _ordre(9, ok=0)]),
                     "ETH/USD": _pair()})
    ev = veille.evenements(avant, apres)
    assert any("2 ordre(s)" in e and "1 OK" in e for e in ev), ev


def test_la_MISE_EN_PAUSE_par_le_regulateur_declenche_un_message():
    """⛔ L'evenement le plus important : le regulateur referme la paire a
    -10 %, et c'est le SEUL garde automatique qui reste."""
    apres = _releve({"BTC/USD": _pair(regulateur={
        **_pair()["regulateur"], "action": "pause",
        "motif": "pnl_pct -10.4 < -10"}), "ETH/USD": _pair()})
    ev = veille.evenements(_releve({"BTC/USD": _pair(), "ETH/USD": _pair()}),
                           apres)
    assert any("pause" in e and "BTC/USD" in e for e in ev), ev


def test_une_RETROGRADATION_d_admission_declenche_un_message():
    apres = _releve({"ETH/USD": _pair(
        admission={"buy": "OBSERVED", "sell": "AUTO_EXEC"})})
    ev = veille.evenements(_releve({"ETH/USD": _pair()}), apres)
    assert any("ETH/USD" in e and "admission buy" in e for e in ev), ev


def test_l_EXECUTION_FERMEE_declenche_un_message():
    """⚠️ Tout redeploiement ferme REM-002. Sans rearmement, rien ne trade —
    et sans ce message, personne ne le saurait."""
    ev = veille.evenements(_releve(),
                           _releve(autorisee=False, motif="NEW_DEPLOYMENT"))
    assert any("FERMÉE" in e for e in ev), ev
    assert any("NEW_DEPLOYMENT" in e for e in ev), ev


def test_une_paire_AJOUTEE_au_reglage_se_signale():
    """⚠️ Sinon on croirait qu'elle est surveillee depuis toujours."""
    avant = _releve({"WTI/USD": _pair()})
    apres = _releve({"WTI/USD": _pair(), "BTC/USD": _pair()})
    ev = veille.evenements(avant, apres)
    assert any("BTC/USD" in e and "ajoutée" in e for e in ev), ev


def test_un_releve_ILLISIBLE_sur_une_paire_se_signale():
    """⛔ Une paire dont le releve echoue ne doit pas disparaitre en silence."""
    apres = _releve({"BTC/USD": {"erreur": "TimeoutError: pont muet"},
                     "ETH/USD": _pair()})
    ev = veille.evenements(_releve({"BTC/USD": _pair(), "ETH/USD": _pair()}),
                           apres)
    assert any("BTC/USD" in e and "illisible" in e for e in ev), ev


def test_l_OUVERTURE_du_marche_declenche_un_message():
    avant = _releve({"WTI/USD": _pair(marche_ouvert=False)})
    apres = _releve({"WTI/USD": _pair(marche_ouvert=True)})
    assert any("OUVERT" in e for e in veille.evenements(avant, apres))


# ─── Elle doit se TAIRE ──────────────────────────────────────────────────

def test_rien_de_neuf_ne_dit_RIEN():
    """⚠️ Une veille qui parle a chaque passage est ignoree en un jour."""
    assert veille.evenements(_releve(), _releve()) == []


def test_un_refus_de_PLUS_ne_declenche_rien():
    """Les refus se comptent par centaines : ils figurent dans le resume, ils
    ne declenchent pas d'alerte."""
    avant = _releve({"BTC/USD": _pair(refus=[("fees_exceed_edge", 10)])})
    apres = _releve({"BTC/USD": _pair(refus=[("fees_exceed_edge", 900)])})
    assert veille.evenements(avant, apres) == []


def test_la_fermeture_du_marche_le_soir_ne_declenche_rien():
    avant = _releve({"WTI/USD": _pair(marche_ouvert=True)})
    apres = _releve({"WTI/USD": _pair(marche_ouvert=False)})
    assert veille.evenements(avant, apres) == []


# ─── Le message ──────────────────────────────────────────────────────────

def test_le_message_porte_CHAQUE_paire_et_ses_chiffres():
    r = _releve({
        "BTC/USD": _pair(dernier_ordre_id=1, ordres=[_ordre(1)],
                         refus=[("below_confidence", 42)],
                         tick={"mid": 84704.89, "spread_pct": 0.0141,
                               "spread_max_pct": 0.2}),
        "ETH/USD": _pair()})
    m = veille.message(r, ["BTC/USD : 1 ordre(s)"])
    for attendu in ("BTC/USD", "ETH/USD", "1360099001", "-20.32", "-4.96",
                    "0.0141", "below_confidence", "aucun ordre",
                    "aucune règle d'arrêt", "EXEMPTÉE"):
        assert attendu in m, attendu


def test_le_motif_du_regulateur_est_ECHAPPE():
    """⛔ DEFAUT REEL du 2026-10-03 : le motif vaut litteralement
    << sample too small (n=5 < 10) >> et Telegram lit le `<` comme une balise.
    Le message ENTIER etait refuse en HTTP 400."""
    m = veille.message(_releve(), [])
    assert "n=5 &lt; 10" in m
    assert "n=5 < 10" not in m


def test_tout_texte_venu_de_la_base_est_echappe():
    r = _releve({"BTC/USD": _pair(
        admission={"buy": "OBS<ERVED", "sell": "AUTO>EXEC"},
        refus=[("motif<bizarre>", 3)],
        dernier_ordre_id=1,
        ordres=[{**_ordre(1), "pattern": "a<b>&c"}])},
        autorisee=False, motif="DENY<x>")
    m = veille.message(r, [])
    import re
    assert set(re.findall(r"</?([a-zA-Z]*)>", m)) <= {"b"}
    assert "a&lt;b&gt;&amp;c" in m


def test_le_message_n_a_pas_de_balise_cassee():
    m = veille.message(_releve(), ["veille armée"])
    assert m.count("<b>") == m.count("</b>")


def test_une_paire_illisible_est_DITE_dans_le_message():
    m = veille.message(_releve({"BTC/USD": {"erreur": "TimeoutError"}}), [])
    assert "BTC/USD" in m and "illisible" in m


# ─── LE REPLI quand Telegram refuse ──────────────────────────────────────

def _faux_telegram(monkeypatch, tmp_path, echoue_en_html):
    envois = []

    async def _envoi(texte, parse_mode="HTML"):
        envois.append((parse_mode, texte))
        return (parse_mode != "HTML") if echoue_en_html else True

    import sys as _sys
    faux = type(_sys)("backend.services.telegram_service")
    faux.send_infra_text = _envoi
    monkeypatch.setitem(_sys.modules, "backend.services.telegram_service", faux)
    monkeypatch.setattr(veille, "ETAT", tmp_path / "etat.json")
    monkeypatch.setattr(veille, "releve", lambda: _releve())
    monkeypatch.setattr(_sys, "argv", ["veille_wti.py"])
    return envois


def test_un_refus_HTML_declenche_un_repli_en_texte_brut(monkeypatch, tmp_path):
    """⛔ Le 1er envoi reel a ete refuse par un HTTP 400. Un moniteur qui
    echoue en silence est PIRE que pas de moniteur : il rassure."""
    envois = _faux_telegram(monkeypatch, tmp_path, echoue_en_html=True)
    assert veille.main() == 0
    assert len(envois) == 2 and envois[0][0] == "HTML"
    assert "repli texte brut" in envois[1][1]
    assert "<b>" not in envois[1][1]


def test_sans_refus_il_n_y_a_qu_UN_envoi(monkeypatch, tmp_path):
    envois = _faux_telegram(monkeypatch, tmp_path, echoue_en_html=False)
    assert veille.main() == 0
    assert [p for p, _ in envois] == ["HTML"]


# ─── Le reglage ──────────────────────────────────────────────────────────

def test_le_WTI_reste_surveille_par_defaut():
    """⚠️ Le defaut garde le WTI : si le reglage disparait, la veille deja
    armee ne cesse pas de surveiller."""
    assert "WTI/USD" in veille.PAIRES


def test_un_echec_sur_une_paire_n_emporte_pas_les_autres(monkeypatch):
    """⚠️ La lecon du backfill d'admission du 02/10 : un refus sur la 6e paire
    abandonnait les 42 suivantes."""
    monkeypatch.setattr(veille, "PAIRES", ("BONNE", "CASSEE", "AUTRE"))

    def _rp(pair):
        if pair == "CASSEE":
            raise RuntimeError("pont muet")
        return _pair()

    monkeypatch.setattr(veille, "releve_paire", _rp)
    monkeypatch.setattr(veille, "_execution", lambda: {
        "autorisee": True, "motif": "ARMED", "arme": "x", "tourne": "x"})
    r = veille.releve()
    assert "erreur" in r["paires"]["CASSEE"]
    assert r["paires"]["BONNE"]["admission"]["buy"] == "AUTO_EXEC"
    assert r["paires"]["AUTRE"]["admission"]["buy"] == "AUTO_EXEC"


def test_les_refus_sont_filtres_par_DESTINATION(monkeypatch, tmp_path):
    """⛔ DEFAUT REEL du 2026-10-04 : la veille comptait les refus de TOUTES
    les destinations. Elle annoncait << ETH : pair_not_whitelisted x672 >>
    alors que ces refus venaient de la DEMO, dont la liste blanche est une
    autre et n'a jamais ete ouverte. Un moniteur qui melange les comptes fait
    chercher un defaut la ou il n'y en a pas.
    """
    import sqlite3
    base = tmp_path / "t.db"
    with sqlite3.connect(base) as c:
        c.execute("CREATE TABLE signal_rejections (pair TEXT, created_at TEXT, "
                  "destination_id TEXT, reason_code TEXT)")
        for dest, motif, n in (("admin_live", "sl_too_close", 3),
                               ("admin_legacy", "pair_not_whitelisted", 50),
                               ("admin_kraken", "horizon_not_allowed", 99)):
            for _ in range(n):
                c.execute("INSERT INTO signal_rejections VALUES (?,?,?,?)",
                          ("ETH/USD", "2099-01-01T00:00:00+00:00", dest, motif))
    monkeypatch.setattr(veille, "_db", lambda: str(base))
    monkeypatch.setattr(veille, "_depuis", lambda: "2000-01-01T00:00:00+00:00")
    motifs = dict(veille._refus("ETH/USD"))
    assert motifs == {"sl_too_close": 3}, motifs
    assert "pair_not_whitelisted" not in motifs
    assert "horizon_not_allowed" not in motifs


# ─── LA SONDE DE FRAICHEUR DU CALENDRIER ────────────────────────────────
#
# ⛔ MESURE DU 2026-10-04. Le blackout evenementiel bloque massivement — 3 638
# refus depuis le 24/09, dont 121 sur BTC et 106 sur ETH. Mais :
#
#     cache : High 10 · Medium 21 · Low 114, du 29/09 au 02/10 — rien apres
#     refus : tous s arretent le 02/10 a 12:43
#
# Le cache est PERIME depuis deux jours, et les refus se sont arretes au meme
# instant. Le garde ne bloque plus parce qu il ne SAIT plus rien — pas parce
# qu il n y a plus d evenements.
#
# 🔑 C est le meme mode de panne que celui corrige le 2026-09-20, ou il etait
# reste muet des mois pour une erreur de format d heure : il se tait, et son
# silence ressemble a un calme de marche. Cette sonde existe pour que le
# silence devienne bruyant.

def _cal(heures=2.0, n=145, haut=10, erreur=None):
    if erreur:
        return {"erreur": erreur}
    return {"evenements": n, "high": haut, "age_heures": heures,
            "perime": heures > veille.CAL_AGE_MAX_H}


def test_un_calendrier_FRAIS_ne_dit_rien():
    avant = _releve(); avant["calendrier"] = _cal(heures=2)
    apres = _releve(); apres["calendrier"] = _cal(heures=3)
    assert veille.evenements(avant, apres) == []


def test_un_calendrier_qui_SE_PERIME_declenche_une_alerte():
    """⛔ L evenement qui compte : la transition frais → perime."""
    avant = _releve(); avant["calendrier"] = _cal(heures=40)
    apres = _releve(); apres["calendrier"] = _cal(heures=50)
    ev = veille.evenements(avant, apres)
    assert any("calendrier" in e.lower() and "PÉRIMÉ" in e for e in ev), ev


def test_un_calendrier_DEJA_perime_ne_re_alerte_pas():
    """⚠️ Sinon l alerte se repete toutes les 15 min et on l ignore."""
    avant = _releve(); avant["calendrier"] = _cal(heures=50)
    apres = _releve(); apres["calendrier"] = _cal(heures=60)
    assert veille.evenements(avant, apres) == []


def test_un_calendrier_qui_REDEVIENT_frais_le_dit():
    """La synchro hebdomadaire a repris : c est une bonne nouvelle a dire."""
    avant = _releve(); avant["calendrier"] = _cal(heures=50)
    apres = _releve(); apres["calendrier"] = _cal(heures=1)
    ev = veille.evenements(avant, apres)
    assert any("calendrier" in e.lower() and "à jour" in e for e in ev), ev


def test_un_calendrier_perime_DES_L_ARMEMENT_est_annonce():
    """⛔ Au premier passage il n y a pas de << avant >> : un cache deja
    perime doit quand meme se signaler, sinon on part aveugle."""
    apres = _releve(); apres["calendrier"] = _cal(heures=72)
    ev = veille.evenements({}, apres)
    assert any("PÉRIMÉ" in e for e in ev), ev


def test_un_calendrier_ILLISIBLE_se_signale():
    avant = _releve(); avant["calendrier"] = _cal(heures=2)
    apres = _releve(); apres["calendrier"] = _cal(erreur="OperationalError")
    ev = veille.evenements(avant, apres)
    assert any("calendrier" in e.lower() and "illisible" in e for e in ev), ev


def test_le_seuil_est_de_48_HEURES():
    """La synchro est HEBDOMADAIRE (dimanche 20h UTC) : 48 h laisse passer un
    retard normal, et attrape un cache mort."""
    assert veille.CAL_AGE_MAX_H == 48


def test_le_message_porte_l_age_du_calendrier():
    r = _releve(); r["calendrier"] = _cal(heures=52.5)
    m = veille.message(r, [])
    assert "52.5" in m or "52,5" in m
    assert "calendrier" in m.lower()


def test_la_fraicheur_se_mesure_sur_les_HIGH_pas_sur_tout(monkeypatch, tmp_path):
    """⛔ DEFAUT DE MA PREMIERE SONDE, attrape le 2026-10-04. Elle mesurait
    l age du dernier evenement TOUS NIVEAUX, et rendait 18,2 h — frais — alors
    que les HIGH avaient 45,7 h et les Medium 49,2 h. Les 114 lignes Low
    masquaient la donnee protectrice.

    🔑 Le blackout ne consomme QUE les HIGH : c est leur age qui compte. Une
    sonde qui mesure autre chose rassure exactement quand il faut alerter.
    """
    import sqlite3
    from datetime import datetime, timedelta, timezone
    base = tmp_path / "cal.db"
    maintenant = datetime.now(timezone.utc)
    with sqlite3.connect(base) as c:
        c.execute("CREATE TABLE economic_events (ts_utc TEXT, impact TEXT)")
        # Des Low tres frais, et des High vieux de 60 h : le cas reel.
        for h in (1, 2, 3):
            c.execute("INSERT INTO economic_events VALUES (?,?)",
                      ((maintenant - timedelta(hours=h)).isoformat(), "Low"))
        c.execute("INSERT INTO economic_events VALUES (?,?)",
                  ((maintenant - timedelta(hours=60)).isoformat(), "High"))
    monkeypatch.setattr(veille, "CAL_DB", str(base))
    r = veille._calendrier()
    assert r["perime"] is True, r
    assert 59 <= r["age_heures"] <= 61, r
    # ⚠️ L age TOUS NIVEAUX reste rendu, pour qu on voie le masquage.
    assert 0 <= r["age_tous_heures"] <= 4, r


def test_un_calendrier_SANS_AUCUN_high_est_perime(monkeypatch, tmp_path):
    """⛔ Zero evenement HIGH n est pas << pas de risque >> : c est
    << je ne sais rien >>."""
    import sqlite3
    from datetime import datetime, timezone
    base = tmp_path / "cal2.db"
    with sqlite3.connect(base) as c:
        c.execute("CREATE TABLE economic_events (ts_utc TEXT, impact TEXT)")
        c.execute("INSERT INTO economic_events VALUES (?,?)",
                  (datetime.now(timezone.utc).isoformat(), "Low"))
    monkeypatch.setattr(veille, "CAL_DB", str(base))
    r = veille._calendrier()
    assert r["perime"] is True
    assert r["high"] == 0
