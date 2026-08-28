"""Le mot `risque` rend le risque engagé cumulé à l'instant t (2026-08-25).

Jusqu'ici le chiffre n'existait qu'une fois par heure, poussé par la sonde de
saturation, et **uniquement quand il franchissait un seuil**. Entre deux
franchissements, la question « combien ai-je d'engagé, là, maintenant ? »
n'avait aucune réponse — il fallait sommer les positions à la main.

Ce que ces tests verrouillent, ce sont les façons dont cette réponse à la
demande pourrait mentir. Toutes reviennent au même piège : **rendre un
chiffre rassurant là où il n'y a pas de mesure.**

1. ⛔ un bridge muet ne vaut PAS « 0 € engagé » ni « 0 % » — c'est le sort du
   moniteur resté muet trois mois. « Illisible » et « il reste de la place »
   ne se ressemblent que dans un message mal écrit ;
2. ⛔ une position SANS STOP rend le total indécidable, jamais nul : son
   risque n'est pas borné, donc aucune somme n'a de sens ;
3. ⛔ **le total tous comptes ne s'annonce que si TOUS les comptes ont été
   mesurés.** Sommer ce qu'on a pu lire et taire le reste produit un total
   crédible et faux — le pire des deux mondes ;
4. ⛔ **une observation ne doit RIEN déplacer** : répondre à `risque` n'écrit
   pas l'état de la sonde horaire et ne consomme aucun cooldown. C'est la
   leçon du `DRY_RUN` de la sonde de capture, qui avançait son curseur ;
5. une panne du calcul se DIT. Un `except` muet ici rejouerait le garde-fou
   qui cachait un `NameError`.

Le calcul lui-même n'est pas retesté : il est réutilisé tel quel depuis
`scripts/notify_saturation_risque.py`, déjà couvert par
`test_notify_saturation_risque.py`. Ce fichier teste le **branchement** et la
**mise en mots** — précisément ce que des tests de fonctions pures ne
diraient pas.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

CHAT = "424242"


# --------------------------------------------------------------------------
# Fabriques d'évaluations, telles que `_lire_destination` les rend
# --------------------------------------------------------------------------

def _eval_ok(total=28.75, plafond=33.54, login=13137475, positions=6,
             candidats=0, liberable=0.0, marge_min_r=1.0):
    return {
        "lisible": True, "indecidable": False,
        "risque_total": total, "plafond": plafond,
        "pct": 100.0 * total / plafond, "restant": plafond - total,
        "nues": 0, "non_mesurables": 0, "positions": positions,
        "candidats": candidats, "liberable": liberable,
        "login": login, "marge_min_r": marge_min_r, "marge_min_sigma": 0.0,
    }


def _eval_illisible(login=None):
    return {
        "lisible": False, "indecidable": True,
        "risque_total": None, "plafond": None, "pct": None, "restant": None,
        "nues": 0, "non_mesurables": 0, "positions": 0,
        "candidats": 0, "liberable": 0.0, "login": login,
    }


def _eval_nue(nues=1, login=62134158):
    return {
        "lisible": True, "indecidable": True,
        "risque_total": 12.0, "plafond": None, "pct": None, "restant": None,
        "nues": nues, "non_mesurables": 0, "positions": 3,
        "candidats": 0, "liberable": 0.0, "login": login, "marge_min_r": 1.0,
    }


def _eval_non_mesurable(n=2, login=62134158):
    return {
        "lisible": True, "indecidable": True,
        "risque_total": 8.0, "plafond": None, "pct": None, "restant": None,
        "nues": 0, "non_mesurables": n, "positions": 4,
        "candidats": 0, "liberable": 0.0, "login": login, "marge_min_r": 1.0,
    }


def _eval_desarme(login=62134158):
    e = _eval_illisible(login=login)
    e.update({"lisible": True, "indecidable": False, "pct": 0.0,
              "desarme": True})
    return e


def _mesure(did, badge, evaluation, verdict):
    return {"id": did, "badge": badge, "evaluation": evaluation,
            "verdict": verdict}


def _live(evaluation, verdict):
    return _mesure("admin_live", "💰 Live IC Markets", evaluation, verdict)


def _demo(evaluation, verdict):
    return _mesure("admin_legacy", "🧪 Demo Pepperstone", evaluation, verdict)


# --------------------------------------------------------------------------
# Mise en mots — fonction PURE
# --------------------------------------------------------------------------

def test_un_compte_lisible_montre_engage_plafond_et_marge():
    from backend.app import _formater_risque

    texte = _formater_risque([_live(_eval_ok(), "sature")])

    assert "28,75" in texte and "33,54" in texte, texte
    assert "86" in texte, texte
    # La marge restante est LE chiffre qui dit si le prochain ordre passe.
    assert "4,79" in texte, texte
    assert "13137475" in texte, texte


def test_un_bridge_muet_ne_dit_ni_zero_ni_pourcentage():
    """⛔ Le sort du moniteur muet : « rien » lu comme « tout va bien »."""
    from backend.app import _formater_risque

    texte = _formater_risque([_live(_eval_illisible(), "illisible")])

    assert "illisible" in texte.lower(), texte
    # Aucun montant ni pourcentage ne doit apparaître pour ce compte.
    assert "0,00" not in texte, texte
    assert "%" not in texte, texte
    assert "engagés" not in texte, texte


def test_une_position_sans_stop_ferme_l_admission_et_supprime_le_pourcentage():
    from backend.app import _formater_risque

    texte = _formater_risque([_demo(_eval_nue(nues=2), "indecidable")])

    assert "sans stop" in texte.lower(), texte
    assert "2" in texte, texte
    assert "%" not in texte, texte


def test_des_positions_non_mesurables_rendent_le_compte_indecidable():
    from backend.app import _formater_risque

    texte = _formater_risque([_demo(_eval_non_mesurable(n=2), "indecidable")])

    assert "non mesurable" in texte.lower(), texte
    assert "%" not in texte, texte


def test_plafond_desarme_le_dit_au_lieu_d_afficher_zero_pour_cent():
    from backend.app import _formater_risque

    texte = _formater_risque([_demo(_eval_desarme(), "ok")])

    assert "désarmé" in texte.lower(), texte


# --------------------------------------------------------------------------
# ⛔ Le total tous comptes — le piège central
# --------------------------------------------------------------------------

def test_le_total_est_annonce_quand_les_deux_comptes_sont_mesures():
    from backend.app import _formater_risque

    texte = _formater_risque([
        _live(_eval_ok(total=28.75, plafond=33.54), "sature"),
        _demo(_eval_ok(total=10.25, plafond=31.44, login=62134158), "ok"),
    ])

    assert "39,00" in texte, texte


def test_un_compte_illisible_INTERDIT_d_annoncer_un_total():
    """⛔ Sommer ce qu'on a lu et taire le reste rend un total crédible et faux.

    C'est plus dangereux qu'une absence de total : personne ne se méfie d'un
    chiffre qui s'affiche.
    """
    from backend.app import _formater_risque

    texte = _formater_risque([
        _live(_eval_ok(total=28.75, plafond=33.54), "sature"),
        _demo(_eval_illisible(), "illisible"),
    ])

    assert "total tous comptes : impossible" in texte.lower(), texte
    # Le compte lisible garde son chiffre ; c'est la SOMME qui est refusée.
    assert "28,75" in texte, texte


def test_un_compte_indecidable_INTERDIT_aussi_le_total():
    from backend.app import _formater_risque

    texte = _formater_risque([
        _live(_eval_ok(total=28.75, plafond=33.54), "sature"),
        _demo(_eval_nue(), "indecidable"),
    ])

    assert "total tous comptes : impossible" in texte.lower(), texte


def test_aucune_destination_lisible_ne_produit_pas_un_message_rassurant():
    from backend.app import _formater_risque

    texte = _formater_risque([
        _live(_eval_illisible(), "illisible"),
        _demo(_eval_illisible(), "illisible"),
    ])

    assert texte.lower().count("illisible") >= 2, texte
    assert "total tous comptes : impossible" in texte.lower(), texte
    assert "%" not in texte, texte


def test_la_soupape_sans_candidat_est_dite_explicitement():
    """« Saturé et rien à libérer » et « saturé mais 8 € récupérables »
    n'appellent pas la même décision."""
    from backend.app import _formater_risque

    sans = _formater_risque([_live(_eval_ok(candidats=0), "sature")])
    avec = _formater_risque([
        _live(_eval_ok(candidats=2, liberable=8.4), "sature")])

    assert "aucun candidat" in sans.lower(), sans
    assert "8,40" in avec, avec


# --------------------------------------------------------------------------
# Branchement — ce que des tests de fonctions pures ne diraient PAS
# --------------------------------------------------------------------------

@pytest.fixture
def envois(monkeypatch):
    """Capture ce qui part vers le fil sales."""
    vus: list[str] = []

    async def _faux_send(texte, *a, **kw):
        vus.append(texte)
        return True

    import backend.services.telegram_service as ts
    monkeypatch.setattr(ts, "send_sales_text", _faux_send)
    return vus


@pytest.fixture
def client(monkeypatch, envois):
    import config.settings as _s
    from backend.app import app

    monkeypatch.setattr(_s, "SALES_TELEGRAM_CHAT_ID", CHAT, raising=False)
    monkeypatch.setattr(_s, "TELEGRAM_SALES_WEBHOOK_SECRET", "", raising=False)
    return TestClient(app)


def _poster(client, texte, chat=CHAT):
    return client.post(
        "/api/telegram/sales-webhook",
        json={"message": {"chat": {"id": chat}, "text": texte}},
    )


@pytest.fixture
def mesure_bouchonnee(monkeypatch):
    """Remplace la lecture réseau — le branchement seul est sous test."""
    appels: list[int] = []

    def _faux():
        appels.append(1)
        return [_live(_eval_ok(), "sature"),
                _demo(_eval_ok(total=10.25, plafond=31.44, login=62134158), "ok")]

    import backend.app as _app
    monkeypatch.setattr(_app, "_mesurer_risque_destinations", _faux)
    return appels


def test_le_mot_risque_declenche_VRAIMENT_le_calcul(client, envois,
                                                    mesure_bouchonnee):
    """Sans ce test, `_formater_risque` pourrait être parfaite et jamais
    appelée — exactement le trou du détecteur de positions nues."""
    r = _poster(client, "risque")

    assert r.status_code == 200, r.text
    assert r.json()["command"] == "risque", r.json()
    assert len(mesure_bouchonnee) == 1, "le calcul n'a pas été appelé"
    assert len(envois) == 1, envois
    assert "28,75" in envois[0], envois[0]


@pytest.mark.parametrize("mot", ["risque", "/risque", "Risque", "  RISQUE  ",
                                 "risk", "/risk"])
def test_les_variantes_du_mot_sont_acceptees(client, envois, mesure_bouchonnee,
                                             mot):
    _poster(client, mot)
    assert len(envois) == 1, f"{mot!r} non reconnu"


def test_un_autre_chat_n_obtient_rien(client, envois, mesure_bouchonnee):
    r = _poster(client, "risque", chat="999")

    assert r.json().get("skipped") == "chat_id_mismatch", r.json()
    assert envois == [], envois
    assert mesure_bouchonnee == [], "le calcul a tourné pour un chat inconnu"


def test_recap_marche_toujours(client, monkeypatch, envois):
    """Ajouter une commande ne doit pas en casser une autre."""
    async def _faux_recap():
        return "RECAP"

    import backend.app as _app
    monkeypatch.setattr(_app, "_build_sales_recap_text", _faux_recap)

    r = _poster(client, "recap")
    assert r.json()["command"] == "recap", r.json()
    assert envois == ["RECAP"], envois


def test_une_panne_du_calcul_se_DIT(client, envois, monkeypatch):
    """⛔ Un `except` muet rejouerait le garde-fou qui cachait un NameError."""
    def _explose():
        raise RuntimeError("bridge injoignable")

    import backend.app as _app
    monkeypatch.setattr(_app, "_mesurer_risque_destinations", _explose)

    r = _poster(client, "risque")

    assert r.status_code == 200, r.text
    assert len(envois) == 1, "la panne est restée silencieuse"
    assert "bridge injoignable" in envois[0], envois[0]


def test_repondre_n_ecrit_RIEN(client, envois, mesure_bouchonnee, tmp_path,
                               monkeypatch):
    """⛔ Une observation ne doit rien déplacer.

    La sonde horaire décide de parler en comparant à l'état précédent. Si la
    réponse à la demande écrivait cet état, poser la question ferait taire
    l'alerte suivante — on aurait rendu le système muet en l'interrogeant.
    """
    instantane = tmp_path / "saturation_risque.json"
    monkeypatch.setenv("SATURATION_SNAPSHOT_PATH", str(instantane))

    _poster(client, "risque")

    assert not instantane.exists(), "la réponse a écrit l'état de la sonde"


# --------------------------------------------------------------------------
# Deux poches : 6 % hors or, 14 % pour l'or seul (2026-08-28)
# --------------------------------------------------------------------------


def _eval_deux_poches(autres=28.75, metaux=60.0, plafond_autres=33.12,
                      plafond_metaux=77.28, login=13137475, positions=7):
    """Ce que `_lire_destination` rend depuis que le bridge a deux budgets.

    ⛔ `risque_total` n'y décrit QUE la poche la plus tendue : c'est elle qui
    refusera le prochain ordre. L'afficher comme « l'engagement du compte »
    serait un chiffre amputé de tout ce qui vit dans l'autre poche.
    """
    poches = {
        "autres": {"risque": autres, "plafond": plafond_autres,
                   "pct": 100.0 * autres / plafond_autres,
                   "candidats": 0, "liberable": 0.0},
        "or_argent": {"risque": metaux, "plafond": plafond_metaux,
                      "pct": 100.0 * metaux / plafond_metaux,
                      "candidats": 0, "liberable": 0.0},
    }
    q = max(poches, key=lambda k: poches[k]["pct"])
    return {
        "lisible": True, "indecidable": False,
        "poche": q, "multi_poches": True, "detail_poches": poches,
        "risque_total": poches[q]["risque"], "plafond": poches[q]["plafond"],
        "pct": poches[q]["pct"],
        "restant": poches[q]["plafond"] - poches[q]["risque"],
        "nues": 0, "non_mesurables": 0, "positions": positions,
        "candidats": 0, "liberable": 0.0,
        "login": login, "marge_min_r": 1.0, "marge_min_sigma": 0.0,
    }


def test_les_DEUX_poches_sont_montrees_avec_leur_propre_plafond():
    from backend.app import _formater_risque

    texte = _formater_risque([_live(_eval_deux_poches(), "sature")])

    assert "autres" in texte and "or_argent" in texte, texte
    assert "33,12" in texte and "77,28" in texte, texte
    # 28,75 / 33,12 = 87 % contre 60 / 77,28 = 78 % : c'est le forex qui mord.
    assert "87" in texte, texte


def test_l_engagement_affiche_SOMME_les_deux_poches():
    """⛔ 28,75 € seuls seraient l'engagement de la poche la plus tendue, pas
    celui du compte. Un total amputé s'affiche sans que personne s'en méfie."""
    from backend.app import _formater_risque

    texte = _formater_risque([_live(_eval_deux_poches(), "sature")])

    assert "88,75" in texte, texte


def test_le_total_tous_comptes_additionne_bien_les_poches():
    from backend.app import _formater_risque

    texte = _formater_risque([
        _live(_eval_deux_poches(), "sature"),
        _demo(_eval_ok(total=10.0, plafond=33.0), "ok"),
    ])

    assert "98,75" in texte, texte
