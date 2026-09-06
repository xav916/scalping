"""Savoir qu'une sonde est PASSÉE, et si elle va bien (2026-09-06).

Demande : « chaque passage de sonde doit faire l'objet d'un message Telegram
expliquant le but de la sonde et si le résultat est OK ou KO ».

⛔ Mesuré le jour même : **8 507 passages de cron par jour**. Un message par
passage serait un message toutes les dix secondes — et ce dépôt documente ce
que ça produit : l'alerte de sauvegarde S3 a crié cinq nuits sans être vue,
noyée dans le bruit.

🔑 On sépare donc *enregistrer* de *dire* : chaque passage est noté avec son
but et son verdict, et le healthcheck en fait UN récap. Ce que ces tests
verrouillent, c'est que le récap ne puisse pas mentir.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import journal_sondes as j


@pytest.fixture(autouse=True)
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(j, "_DB", tmp_path / "t.db")
    sqlite3.connect(str(tmp_path / "t.db")).close()
    j.init_schema()


MAINTENANT = datetime(2026, 9, 6, 18, 0, tzinfo=timezone.utc)


def _vu_a():
    """L'instant que le journal a REELLEMENT enregistre.

    ⛔ Mes premiers tests comparaient une date figee a l'horloge du poste :
    ils passaient a 17h et echouaient a 19h. Un test qui depend de l'heure
    qu'il est ne teste pas ce qu'il pretend tester.
    """
    return datetime.fromisoformat(j.bilan()["sondes"][0]["dernier_passage"])


# ── Le verdict vient du CODE DE SORTIE ────────────────────────────────────

def test_code_zero_vaut_OK():
    assert j.enregistrer("s.sh", "vérifie X", 0)["verdict"] == j.OK


def test_code_non_nul_vaut_KO():
    assert j.enregistrer("s.sh", "vérifie X", 1)["verdict"] == j.KO


def test_un_script_qui_echoue_SANS_RIEN_DIRE_compte_comme_un_echec():
    """⛔ C'est le cas le plus dangereux : il ressemble au silence d'une
    situation saine. Le verdict vient du code, jamais d'une analyse du texte."""
    j.enregistrer("muette.sh", "vérifie X", 2, detail=None)
    assert j.bilan(MAINTENANT)["sondes"][0]["verdict"] == j.KO


# ── Le but vit avec la sonde ──────────────────────────────────────────────

def test_le_but_est_conserve_si_un_passage_ne_le_declare_pas():
    """⚠️ Un passage sans en-tête lisible ne doit pas EFFACER le but connu :
    on afficherait « (but non déclaré) » sur une sonde parfaitement décrite."""
    j.enregistrer("s.sh", "vérifie les stops", 0)
    j.enregistrer("s.sh", None, 0)
    assert j.bilan(MAINTENANT)["sondes"][0]["but"] == "vérifie les stops"


def test_une_sonde_sans_but_le_DIT():
    j.enregistrer("s.sh", None, 0)
    assert "non déclaré" in j.bilan(MAINTENANT)["sondes"][0]["but"]


# ── Les compteurs ─────────────────────────────────────────────────────────

def test_les_passages_et_les_echecs_se_cumulent():
    for code in (0, 0, 1, 0):
        j.enregistrer("s.sh", "b", code)
    s = j.bilan(MAINTENANT)["sondes"][0]
    assert s["passages"] == 4 and s["echecs"] == 1


def test_le_dernier_verdict_prime_sur_l_historique():
    """Une sonde réparée doit repasser au vert immédiatement."""
    j.enregistrer("s.sh", "b", 1)
    j.enregistrer("s.sh", "b", 0)
    assert j.bilan(MAINTENANT)["sondes"][0]["verdict"] == j.OK


# ── ⛔ MUET est un troisième état ─────────────────────────────────────────

def test_une_sonde_qui_n_est_pas_passee_est_MUETTE_pas_OK():
    """⛔ LE test qui compte. Confondre « muet » et « ok » est exactement ce
    qui a laissé la sonde des activations mentir treize jours."""
    j.enregistrer("s.sh", "b", 0, periode_min=15)
    tard = _vu_a() + timedelta(hours=5)
    assert j.bilan(tard)["sondes"][0]["verdict"] == j.MUET


def test_un_simple_RETARD_ne_declenche_pas_le_muet():
    """⚠️ Deux périodes de tolérance, pas une : un décalage de cron ou une
    machine chargée ferait du bruit là où on veut du signal."""
    j.enregistrer("s.sh", "b", 0, periode_min=60)
    assert j.bilan(_vu_a() + timedelta(minutes=90))["sondes"][0]["verdict"] == j.OK


def test_sans_periode_declaree_la_tolerance_est_de_six_heures():
    j.enregistrer("s.sh", "b", 0)
    vu = _vu_a()
    assert j.bilan(vu + timedelta(hours=11))["sondes"][0]["verdict"] == j.OK
    assert j.bilan(vu + timedelta(hours=13))["sondes"][0]["verdict"] == j.MUET


def test_un_horodatage_illisible_rend_MUET_pas_OK():
    """⛔ « On ne sait pas quand » n'est pas « c'est passé »."""
    j.enregistrer("s.sh", "b", 0)
    with sqlite3.connect(str(j._DB), isolation_level=None) as c:
        c.execute("UPDATE passages_sondes SET dernier_passage='n importe quoi'")
    assert j.bilan(MAINTENANT)["sondes"][0]["verdict"] == j.MUET


# ── Le message ────────────────────────────────────────────────────────────

def test_le_recap_parle_MEME_quand_tout_va_bien():
    """⛔ Une santé qui ne parle qu'en cas de problème rend un cron cassé
    indiscernable d'une situation saine."""
    j.enregistrer("s.sh", "vérifie X", 0)
    titre, corps = j.message(j.bilan(MAINTENANT))
    assert "1 OK" in titre and "✅" in titre
    assert "vérifie X" in corps


def test_le_recap_nomme_le_BUT_de_chaque_sonde():
    """C'est la demande explicite : savoir ce que la sonde vérifie."""
    j.enregistrer("a.sh", "vérifie les stops", 0)
    j.enregistrer("b.sh", "vérifie la marge", 1)
    _, corps = j.message(j.bilan(MAINTENANT))
    assert "vérifie les stops" in corps and "vérifie la marge" in corps


def test_ce_qui_ne_va_pas_est_annonce_EN_PREMIER():
    """⚠️ Un récap se lit en diagonale : l'échec doit être avant le reste."""
    j.enregistrer("zzz_ok.sh", "b", 0)
    j.enregistrer("aaa_ko.sh", "b", 1)
    _, corps = j.message(j.bilan(MAINTENANT))
    assert corps.index("aaa_ko.sh") < corps.index("zzz_ok.sh")


def test_le_titre_CRIE_des_qu_une_sonde_est_muette():
    j.enregistrer("s.sh", "b", 0, periode_min=15)
    titre, _ = j.message(j.bilan(_vu_a() + timedelta(hours=5)))
    assert titre.startswith("⛔") and "1 muette" in titre


def test_un_journal_VIDE_ne_dit_pas_que_tout_va_bien():
    """⛔ « Aucun passage » n'est pas « aucun problème » — c'est « on ne
    sait pas »."""
    titre, corps = j.message(j.bilan(MAINTENANT))
    assert "aucun passage" in titre.lower()
    assert "on ne sait pas" in corps


def test_le_message_ne_porte_AUCUNE_balise():
    """⚠️ L'endpoint passe le corps dans `html.escape` : une balise s'y
    afficherait telle quelle."""
    j.enregistrer("s.sh", "vérifie X", 1, detail="erreur <b>ici</b>")
    titre, corps = j.message(j.bilan(MAINTENANT))
    assert "<b>" not in titre
    # Le détail vient d'une sortie de script : on ne le nettoie pas, mais le
    # message que NOUS composons ne doit pas en ajouter.
    assert "<b>" not in corps.replace("erreur <b>ici</b>", "")


def test_le_detail_d_un_echec_est_montre():
    """Sans lui, un KO dit qu'il y a un problème sans dire lequel."""
    j.enregistrer("s.sh", "b", 1, detail="connexion refusée port 8790")
    _, corps = j.message(j.bilan(MAINTENANT))
    assert "8790" in corps


# ── Le cri immédiat, et sa retenue (2026-09-06) ───────────────────────────
#
# Demande : « remonter tout de suite si la sonde est KO », le récap passant à
# deux fois par jour. ⛔ Mais `check-live-positions-sltp.sh` passe 1 440 fois
# par jour : crier à chaque passage en échec inonderait exactement le fil
# qu'on veut rendre lisible.
#
# 🔑 On crie sur les TRANSITIONS, et on rappelle rarement.

def test_la_PREMIERE_panne_crie_tout_de_suite():
    """C'est l'événement : il ne doit pas attendre le récap de 22h."""
    r = j.enregistrer("s.sh", "b", 1)
    assert r["crier"] is True and r["motif"] == "nouvelle panne"


def test_une_panne_qui_SE_REPETE_ne_crie_pas_a_chaque_passage():
    """⛔ 1 440 passages par jour : sans cette retenue, une seule sonde cassée
    produirait un message toutes les minutes."""
    j.enregistrer("s.sh", "b", 1)
    for _ in range(20):
        r = j.enregistrer("s.sh", "b", 1)
        assert r["crier"] is False, "une panne qui dure ne crie pas en boucle"


def test_une_panne_qui_DURE_rappelle_apres_six_heures():
    """⚠️ Se taire pour toujours ferait oublier une sonde morte."""
    j.enregistrer("s.sh", "b", 1)
    ancien = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    with sqlite3.connect(str(j._DB), isolation_level=None) as c:
        c.execute("UPDATE passages_sondes SET dernier_cri=?", (ancien,))
    r = j.enregistrer("s.sh", "b", 1)
    assert r["crier"] is True and r["motif"] == "panne qui dure"


def test_la_REPARATION_se_dit():
    """⛔ Savoir que c'est rentré dans l'ordre vaut autant que d'avoir su que
    c'était cassé — sans quoi on continue de croire le système en panne."""
    j.enregistrer("s.sh", "b", 1)
    r = j.enregistrer("s.sh", "b", 0)
    assert r["crier"] is True and r["motif"] == "reparee"


def test_une_sonde_qui_va_bien_ne_dit_RIEN():
    """Le cas de 8 500 passages sur 8 530 : le silence est la norme."""
    j.enregistrer("s.sh", "b", 0)
    for _ in range(10):
        assert j.enregistrer("s.sh", "b", 0)["crier"] is False


def test_le_premier_passage_REUSSI_ne_crie_pas():
    """⚠️ Une sonde inconnue qui démarre au vert n'est pas une réparation."""
    assert j.enregistrer("neuve.sh", "b", 0)["crier"] is False


# ── Le texte de l'alerte ──────────────────────────────────────────────────

def test_l_alerte_nomme_le_BUT_et_le_code():
    titre, corps = j.alerte("s.sh", "vérifie les stops", "nouvelle panne",
                            "connexion refusée", 1)
    assert "s.sh" in titre and "ECHEC" in titre
    assert "vérifie les stops" in corps and "code de sortie 1" in corps
    assert "connexion refusée" in corps


def test_l_alerte_DIT_ce_que_l_echec_implique():
    """⛔ « La sonde est KO » ne suffit pas : ce qu'elle surveille cesse de
    l'être, et c'est ça qu'il faut lire."""
    _, corps = j.alerte("s.sh", "b", "nouvelle panne", None, 1)
    assert "n'est PAS surveillé" in corps


def test_l_alerte_de_REPARATION_est_distincte():
    titre, _ = j.alerte("s.sh", "b", "reparee", None, 0)
    assert titre.startswith("✅") and "réparée" in titre


def test_l_alerte_ne_porte_AUCUNE_balise():
    titre, corps = j.alerte("s.sh", "b", "nouvelle panne", None, 1)
    assert "<" not in titre and "<b>" not in corps
