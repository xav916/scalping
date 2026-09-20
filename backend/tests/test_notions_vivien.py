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
    """⚠️ Depuis le 2026-09-20, les CINQ etapes sont restituees : ce qui lui
    manque n'est plus qu'une etape, ce sont les six lignes. Le test compare
    par inclusion, pas par egalite — sinon toute avancee le casserait.

    ⛔ Et c'est le moment ou le verrou se deplace : jusqu'au 20/09 la notion
    etait bloquee par DEUX conditions independantes (une etape manquante, et
    les six lignes). Il n'en reste qu'UNE. Ce test le dit explicitement pour
    que personne ne croie la porte encore doublement fermee."""
    n = nv.par_nom("cinq_etapes")
    manque = set(nv.manques(n))
    assert set(nv.CHAMPS) <= manque, (
        "une notion dont aucune regle n'est formalisee doit annoncer les SIX "
        "lignes manquantes, pas zero")
    assert not [x for x in manque if x.startswith("etape_")], (
        "le 20/09 a comble le trou de numerotation : plus aucune etape ne "
        "doit etre MANQUANTE")
    assert n["source"], "une notion sans source n'est pas tracable"

    # une notion dont RIEN n'est connu n'annonce que les six lignes
    vierge = nv.par_nom("les_raccourcis")
    assert set(nv.manques(vierge)) == set(nv.CHAMPS)


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


# ─── Les etapes d'une notion partiellement connue (2026-09-14) ──────

def test_cinq_etapes_porte_ses_CINQ_etapes_connues():
    """2026-09-20 : 4/5 -> 5/5. Le decodage transmis ce jour-la separe deux
    choses que l'indexation du 14/09 confondait sous un seul n°4 — REPERER la
    liquidite, et attendre qu'elle soit PRISE. Le test pinne cette separation :
    si un jour les deux etapes redisent la meme chose, c'est qu'on a reperdu
    la distinction qui a comble le trou."""
    n = nv.par_nom("cinq_etapes")
    assert len(n["etapes"]) == 5, "la notion en annonce cinq, pas quatre"
    connues = [e for e in n["etapes"] if e["statut"] != nv.MANQUANT]
    assert len(connues) == 5
    assert "TradingView" in n["etapes"][0]["texte"]
    assert "structure" in n["etapes"][0]["texte"].lower(), (
        "le decodage du 20/09 ajoute la lecture de structure a l'etape 1")
    assert "accumulation" in n["etapes"][1]["texte"].lower()
    assert "volume profile" in n["etapes"][2]["texte"].lower()
    assert "accumulation" in n["etapes"][2]["texte"].lower(), (
        "il dit de poser le profil SUR la zone, pas sur la seance")
    assert "reperer" in n["etapes"][3]["texte"].lower()
    assert "prise" in n["etapes"][4]["texte"].lower()


def test_le_texte_BRUT_du_14_09_est_garde_meme_apres_confirmation():
    """⛔ « ouf TradingView » et « grade de liquidite » sont ce que l'indexation
    automatique du 14/09 restituait ; « ouvre » et « grab » etaient NOS
    reconstructions. Le decodage du 20/09 rend ces deux passages en clair, donc
    les etapes passent de RECONSTRUIT a RAPPORTE.

    ⚠️ Mais le brut RESTE attache. Effacer la trace ferait disparaitre le fait
    qu'on a devine juste — et une reconstruction heureuse qu'on ne peut plus
    relire est indistinguable d'une invention. Le n°4 et le n°5 portent le
    MEME brut, parce qu'on ne sait pas auquel des deux il appartenait."""
    n = nv.par_nom("cinq_etapes")
    assert not [e for e in n["etapes"] if e["statut"] == nv.RECONSTRUIT], (
        "plus aucune etape n'est une reconstruction depuis le 20/09")
    bruts = [e for e in n["etapes"] if e.get("brut")]
    assert len(bruts) == 3, "les deux passages devines restent tracables"
    assert n["etapes"][3]["brut"] == n["etapes"][4]["brut"], (
        "l'ambiguite du 14/09 doit rester lisible sur les DEUX etapes")
    assert nv.RECONSTRUIT, "le statut reste defini : il resservira"


def test_la_CINQUIEME_etape_est_un_SETUP_et_PAS_un_declencheur():
    """🔑 Le test le plus important de ce fichier depuis le 2026-09-20.

    La cinquieme etape est arrivee — c'est le sweep. La tentation immediate est
    d'en faire le `declencheur` de la notion et d'armer la chaine. Xavier l'a
    ecrit noir sur blanc le meme jour : « ne pas automatiser sweep = ordre
    immediat », un retest et des volumes alignes suivent. Le sweep est donc un
    SETUP. Ce test empeche la promotion silencieuse du setup en trigger."""
    n = nv.par_nom("cinq_etapes")
    cinq = n["etapes"][4]
    assert cinq["statut"] != nv.MANQUANT, "l'etape 5 est restituee depuis le 20/09"
    assert "liquidit" in cinq["texte"].lower()
    assert "reintegration" in cinq["texte"].lower()
    assert "SETUP" in cinq["note"], (
        "la note doit dire que ce n'est PAS le declencheur final")
    assert not n.get("declencheur"), (
        "⛔ le sweep ne remplit pas `declencheur` : le trigger final n'est "
        "toujours pas dit, et la moitie « volumes alignes » est bloquee par "
        "l'absence de footprint bid/ask sur CFD")


def test_la_notion_reste_BLOQUEE_meme_avec_ses_CINQ_etapes():
    """🔑 La garantie que Xavier a demandee : `allow_trade = False` tant que la
    regle n'est pas formalisee. ⚠️ Elle ne tient PLUS a l'etape manquante —
    elle tient maintenant aux six lignes seules, et ce test est la pour que ce
    deplacement soit vu. Les cinq etapes decrivent une METHODE ; elles ne
    disent ni l'echelle, ni l'invalidation, ni le stop, ni la cible."""
    n = nv.par_nom("cinq_etapes")
    assert nv.avancement(n) == "5/5"
    assert set(nv.CHAMPS) <= set(nv.manques(n)), (
        "les six lignes restent la seule condition bloquante : si l'une se "
        "remplit, elle doit venir de LUI, pas de notre lecture")
    assert n not in nv.completes()
    assert all(c["nom"] != "notion:cinq_etapes" for c in nv.chaines())


def test_une_notion_dont_TOUS_les_champs_sont_remplis_reste_bloquee_si_une_etape_manque():
    """⛔ Le piege a eviter : completer les six lignes en devinant l'etape 5
    rouvrirait la porte. Les etapes sont une condition SEPAREE."""
    faux = {"nom": "x", "source": "s", "titre": "t",
            "declencheur": "liquidity_sweep_down", "maillons": (),
            "predicats": (), "invalidation": ("bos_up",), "sens": "sell",
            "echelle": "5min", "stop": "s", "cible": "c",
            "etapes": ({"n": 1, "texte": "?", "statut": nv.MANQUANT},)}
    assert nv.manques(faux), "une etape manquante doit suffire a bloquer"
    assert nv.chaines((faux,)) == ()


def test_le_rapport_dit_COMBIEN_d_etapes_sont_connues():
    lignes = nv.lignes_manquantes()
    ligne = next(x for x in lignes if "cinq_etapes" in x)
    # 2026-09-14 : 4/5 — l'indexation coupait avant la cinquieme.
    # 2026-09-20 : 5/5 — decodage transmis ; le trou etait un decalage de
    # numerotation. La notion reste incomplete : l'avancement des etapes et la
    # completude de la notion sont deux choses, et c'est voulu.
    assert "5/5" in ligne, f"le rapport doit dire l'avancement : {ligne}"
    assert "manque" in ligne, "une notion 5/5 mais incomplete doit le dire"
