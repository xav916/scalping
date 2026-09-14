"""Cinq titres de videos, aucune regle — et la machine qui les attend.

⛔ **Le verrou.** Cinq notions sont VERIFIEES comme existantes mais leur
contenu est inconnu : « 5 etapes pour prendre des trades gagnants »,
« ma strategie en 3 etapes », « Tu achetes ou tu vends ? », « ces
raccourcis », « Que faire dans ce contexte ? ». Aucune heure de code ne les
ouvre — inventer les cinq etapes fabriquerait « un robot inspire de Vivien »
en croyant reproduire sa methode, ce que Xavier a explicitement refuse.

🔑 **Ce qui est implementable, c'est le verrou lui-meme** : un dictionnaire ou
chaque notion est DECLAREE avec les six lignes qui la rendent mesurable —
declencheur · invalidation · sens · echelle · stop · cible — et ou une notion
incomplete est nommee comme telle, avec la liste exacte de ce qui manque.

Le systeme sait alors ce qu'il ne sait pas. Et le jour ou les six lignes
arrivent, la chaine se mesure **sans une ligne de code**.

## Les trois refus que ces tests tiennent

1. une notion **incomplete ne produit AUCUNE chaine** — le laboratoire ne
   mesure jamais une regle a moitie devinee ;
2. une notion **sans source** leve — c'est ce qui separe « ce qu'il dit » de
   « ce que nous avons deduit » ;
3. un nom de motif ou de predicat **inconnu leve** — meme doctrine que
   `_PREDICATS` : un nom mal orthographie mesurerait la chaine sans sa
   condition, et le verdict serait faux sans que rien ne le dise.
"""
from __future__ import annotations

import pytest

from backend.services import laboratoire_or as labo
from backend.services import notions_vivien as nv


def test_les_SIX_notions_verrouillees_sont_DECLAREES():
    """⛔ SIX, pas cinq. Ma premiere version en declarait cinq et perdait
    « Ne trade plus sans connaitre ces elements » — trouve le 2026-09-14 quand
    Xavier a demande la citation qui prouvait ma liste. Une notion oubliee est
    une notion qu'on n'attendra jamais."""
    noms = {n["nom"] for n in nv.NOTIONS}
    assert {"cinq_etapes", "strategie_trois_etapes", "acheter_ou_vendre",
            "ne_trade_plus_sans_ces_elements", "les_raccourcis",
            "que_faire_dans_ce_contexte"} <= noms
    assert len(nv.NOTIONS) == 6


def test_aucune_source_ne_se_PRETEND_verifiee_de_premiere_main():
    """⛔ Ma premiere version ecrivait « index public Vivien_Legendary, releve
    le 2026-09-12 » — comme si nous l'avions consulte. Nous ne l'avons jamais
    ouvert : les titres et les durees viennent d'un document transmis par
    Xavier, qui dit lui-meme que le contenu « doit encore etre decode ».

    🔑 C'est le glissement exact que ce module existe pour empecher. Une source
    doit dire d'ou vient le titre ET qu'il n'a pas ete verifie."""
    for n in nv.NOTIONS:
        src = n["source"]
        assert "2026-09-12" in src, f"{n['nom']} : la provenance n'est pas datee"
        assert "jamais consulte" in src, (
            f"{n['nom']} : la source ne dit pas qu'elle est de seconde main")
        assert n.get("titre"), f"{n['nom']} : le titre rapporte manque"


def test_une_notion_verrouillee_NOMME_ce_qui_lui_manque():
    n = nv.par_nom("cinq_etapes")
    assert set(nv.manques(n)) == set(nv.CHAMPS), (
        "une notion dont on ne connait que le titre doit annoncer les SIX "
        "lignes manquantes, pas zero")
    assert n["source"], "une notion sans source n'est pas tracable"


def test_aucune_notion_n_est_complete_AUJOURD_HUI():
    """⚠️ Le jour ou ce test devient faux, c'est que les regles sont arrivees.
    Il documente l'etat, il ne le defend pas."""
    assert nv.completes() == (), (
        f"notions completes : {[n['nom'] for n in nv.completes()]} — "
        f"verifier qu'elles viennent de Xavier et non d'une invention")


def test_une_notion_incomplete_ne_produit_AUCUNE_chaine():
    assert nv.chaines() == ()


def test_le_plafond_du_hasard_ne_BOUGE_PAS_aujourd_hui():
    """🔑 Ajouter des chaines releve la barre pour tout le monde. Une machine
    qui attend ne doit rien couter tant qu'elle attend."""
    avant = len(labo.CHAINES)
    assert len(labo.CHAINES) + len(nv.chaines()) == avant


def test_une_notion_COMPLETE_devient_une_chaine_mesurable():
    complete = {
        "nom": "essai_complet",
        "source": "citation verbatim de la video",
        "declencheur": "liquidity_sweep_down",
        "maillons": ("bos_down",),
        "predicats": ("volume_fort",),
        "invalidation": ("bos_up",),
        "sens": "sell",
        "echelle": "5min",
        "stop": "au-dela de la meche du balayage",
        "cible": "liquidite opposee",
    }
    (chaine,) = nv.chaines((complete,))
    assert chaine["nom"] == "notion:essai_complet"
    assert chaine["declencheur"] == "liquidity_sweep_down"
    assert set(chaine["motifs"]) == {"liquidity_sweep_down", "bos_down"}
    assert chaine["predicats"] == ("volume_fort",)
    assert chaine["invalidants"] == ("bos_up",)
    # la chaine doit etre consommable telle quelle par le laboratoire
    releve, compte = labo.chaines_detectees({}, [], chaines=(chaine,))
    assert compte == {"notion:essai_complet": 0}


def test_un_MOTIF_inconnu_LEVE():
    faux = {"nom": "x", "source": "s", "declencheur": "motif_qui_n_existe_pas",
            "maillons": (), "predicats": (), "invalidation": (), "sens": "sell",
            "echelle": "5min", "stop": "s", "cible": "c"}
    with pytest.raises(ValueError, match="motif"):
        nv.chaines((faux,))


def test_un_PREDICAT_inconnu_LEVE():
    faux = {"nom": "x", "source": "s", "declencheur": "liquidity_sweep_down",
            "maillons": (), "predicats": ("predicat_invente",),
            "invalidation": (), "sens": "sell", "echelle": "5min",
            "stop": "s", "cible": "c"}
    with pytest.raises(ValueError, match="predicat"):
        nv.chaines((faux,))


def test_un_SENS_qui_contredit_le_declencheur_LEVE():
    """⛔ Le defaut du 14/09 : neuf motifs haussiers vendaient. Une notion qui
    declare acheter sur un declencheur vendeur doit casser, pas se taire."""
    faux = {"nom": "x", "source": "s", "declencheur": "liquidity_sweep_down",
            "maillons": (), "predicats": (), "invalidation": (), "sens": "buy",
            "echelle": "5min", "stop": "s", "cible": "c"}
    with pytest.raises(ValueError, match="sens"):
        nv.chaines((faux,))


def test_une_notion_SANS_SOURCE_LEVE():
    faux = {"nom": "x", "source": "", "declencheur": "liquidity_sweep_down",
            "maillons": (), "predicats": (), "invalidation": (), "sens": "sell",
            "echelle": "5min", "stop": "s", "cible": "c"}
    with pytest.raises(ValueError, match="source"):
        nv.chaines((faux,))


def test_le_rapport_dit_ce_qui_manque_notion_par_notion():
    lignes = nv.lignes_manquantes()
    assert len(lignes) == len(nv.incompletes())
    assert any("cinq_etapes" in x for x in lignes)
    assert any("5 etapes pour prendre des trades gagnants" in x
               for x in lignes), "le rapport doit citer le TITRE"
    for x in lignes:
        assert "declencheur" in x, "le rapport doit nommer les champs manquants"


def test_une_notion_COMPLETE_entre_dans_le_labo_SANS_UNE_LIGNE_DE_CODE(monkeypatch):
    """🔑 Le test qui donne son sens au module : declarer suffit."""
    complete = {
        "nom": "essai_branche", "source": "citation",
        "declencheur": "liquidity_sweep_down", "maillons": ("bos_down",),
        "predicats": (), "invalidation": ("bos_up",), "sens": "sell",
        "echelle": "5min", "stop": "meche", "cible": "liquidite opposee",
    }
    monkeypatch.setattr(nv, "NOTIONS", (complete,))
    _, compte = labo.chaines_detectees({}, [])       # aucune chaine explicite
    assert "notion:essai_branche" in compte, (
        "une notion declaree complete doit etre mesuree par defaut")


def test_le_message_de_la_nuit_NE_MENT_PAS_sur_la_portee(monkeypatch):
    """⛔ Le texte disait « vaut pour TOUS les comptes ». C'etait vrai avant la
    portee par destination (14/09) ; ca ne l'est plus. Un message faux sur une
    decision de trading est pire qu'un message absent : il fait croire a une
    protection qui n'existe pas.

    🔑 On juge le CORPS ENVOYE, pas le code source : ma premiere version
    interdisait la phrase jusque dans un commentaire qui l'expliquait.
    """
    import httpx

    from backend.services import reglage_or as rg

    recu = {}

    class _R:
        @staticmethod
        def raise_for_status(): return None

    def _post(url, params=None, json=None, timeout=None):
        recu.update(json or {})
        return _R()

    monkeypatch.setattr(httpx, "post", _post)
    monkeypatch.setenv("SHADOW_LOG_TOKEN", "jeton")
    cellule = {"horizon": "5min", "motif": "poc_return_up", "sens": "buy",
               "n": 90, "r_moyen": -0.4, "t": -3.5, "delta_hasard": -0.33,
               "plafond": 2.55, "verdict": labo.REFUTE}
    rg._notifier({"pair": rg.PAIRE, "cellules": [cellule], "k": 1,
                  "plafond": 2.55},
                 [{"action": rg.FERMER, "horizon": "5min",
                   "motif": "poc_return_up", "pair": rg.PAIRE, "detail": "x"}])
    corps = recu.get("body", "")
    assert rg.DESTINATION_MESUREE in corps, "le courtier concerne n'est pas nomme"
    assert "pour lui SEUL" in corps
    assert "TOUS les comptes" not in corps
    assert "🔒" in corps, "les notions en attente doivent rester visibles"
