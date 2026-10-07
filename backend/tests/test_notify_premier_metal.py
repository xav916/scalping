"""Le premier ordre métal qui PART — et, à défaut, qui l'arrête (2026-08-28).

La poche des métaux a été ouverte à 14 % de l'equity le 28/08. Le budget
existe ; **rien ne prouve qu'un ordre en sorte**. Ce jour-là, côté bridge la
poche a cessé de refuser (zéro `bridge_plafond_risque` après le déploiement),
mais côté radar l'or restait arrêté plus haut : 10 `fees_exceed_edge`, 6
`correlated_exposure`, 1 `pattern_not_allowed` — et **126 des 128 refus du
jour portaient sur du 5 minutes**.

> **Une porte qu'on ouvre ne prouve pas qu'un ordre passe.** Le silence qui
> suit ressemble trait pour trait au silence d'avant.

Ce que ces tests verrouillent — les façons dont cette sonde pourrait mentir :

1. ⛔ **`filled` et rien d'autre.** Un `blocked` ou un `paper` décrit une
   intention ; les compter annoncerait un départ qui n'a pas eu lieu, ce qui
   est pire que se taire ;
2. ⛔ **le curseur n'avance que sur un envoi CONFIRMÉ** — ni en `DRY_RUN`, ni
   quand Telegram a refusé. Un événement dont l'annonce a échoué doit être
   rejoué, pas perdu ;
3. ⛔ **au premier passage, on n'annonce rien** : sans ça la sonde
   déclarerait « premier ordre métal ! » sur une ligne de mai ;
4. le corps est passé dans `html.escape` par l'endpoint ⇒ **texte simple**,
   toute balise s'y afficherait telle quelle.
"""
from __future__ import annotations

import importlib.util
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

_SCRIPT = (pathlib.Path(__file__).resolve().parents[2]
           / "scripts" / "notify_premier_metal.py")


@pytest.fixture()
def s():
    spec = importlib.util.spec_from_file_location("premier_metal", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ligne(id=10, symbol="XAUUSD", status="filled", direction="buy",
           lots=0.01, entry=4598.0, sl=4580.0, ticket=999):
    return {"id": id, "symbol": symbol, "status": status,
            "direction": direction, "lots": lots, "entry": entry, "sl": sl,
            "ticket": ticket, "created_at": "2026-08-28T14:00:00+00:00"}


# ── Reconnaître un métal ───────────────────────────────────────────────────

def test_or_et_argent_sont_des_metaux(s):
    for sym in ("XAUUSD", "GOLD", "XAGUSD", "SILVER"):
        assert s.est_metal(sym) is True


def test_le_platine_n_est_PAS_du_ressort_de_cette_sonde(s):
    """Nommés un par un, comme la poche : « métal » embarquerait XPT/XPD."""
    for sym in ("XPTUSD", "XPDUSD", "EURUSD", "", None):
        assert s.est_metal(sym) is False


# ── Un ordre PARTI, pas un ordre voulu ────────────────────────────────────

def test_seul_filled_compte_comme_un_depart(s):
    """⛔ LE test central. `blocked` et `paper` décrivent une intention."""
    lignes = [
        _ligne(1, status="filled"),
        _ligne(2, status="blocked"),
        _ligne(3, status="rejected"),
        _ligne(4, status="paper"),
    ]
    partis = s.metaux_partis(lignes)
    assert [p["id"] for p in partis] == [1]


def test_un_forex_parti_n_est_pas_un_metal(s):
    assert s.metaux_partis([_ligne(1, symbol="EURUSD")]) == []


def test_une_page_vide_ne_rend_aucun_depart(s):
    assert s.metaux_partis([]) == []
    assert s.metaux_partis(None) == []


def test_une_ligne_malformee_est_ignoree_sans_lever(s):
    assert s.metaux_partis([None, "bruit", {"id": 1}]) == []


# ── Le curseur ─────────────────────────────────────────────────────────────

def test_une_page_vide_rend_None_JAMAIS_zero(s):
    """⛔ Zéro ferait repartir le curseur au début de l'histoire, donc
    réannoncerait un ordre de mai comme un premier départ."""
    assert s.id_max([]) is None
    assert s.id_max([{"id": "bruit"}]) is None


def test_id_max_prend_le_plus_grand(s):
    assert s.id_max([_ligne(3), _ligne(41), _ligne(12)]) == 41


# ── Le digest de silence ───────────────────────────────────────────────────

def test_jamais_dit_donc_on_le_dit(s):
    assert s.doit_parler_du_silence(None, datetime.now(timezone.utc), 86400)


def test_deja_dit_il_y_a_une_heure_on_se_tait(s):
    maintenant = datetime.now(timezone.utc)
    hier = (maintenant - timedelta(hours=1)).isoformat()
    assert s.doit_parler_du_silence(hier, maintenant, 86400) is False


def test_dit_il_y_a_plus_de_24h_on_le_redit(s):
    maintenant = datetime.now(timezone.utc)
    avant = (maintenant - timedelta(hours=25)).isoformat()
    assert s.doit_parler_du_silence(avant, maintenant, 86400) is True


def test_un_horodatage_illisible_ne_fait_pas_taire(s):
    """Se taire sur une date qu'on ne sait pas lire, c'est se taire sans
    savoir pourquoi."""
    assert s.doit_parler_du_silence("n'importe quoi",
                                    datetime.now(timezone.utc), 86400)


# ── Les messages ───────────────────────────────────────────────────────────

def test_le_corps_est_du_TEXTE_SIMPLE(s):
    """⚠️ L'endpoint passe le corps dans `html.escape` : une balise `<b>` s'y
    afficherait littéralement, telle quelle, dans Telegram."""
    _, depart = s.message_depart("admin_live", [_ligne()])
    _, silence = s.message_silence([("fees_exceed_edge", 10)], 24,
                                   {"5min": 126})
    for corps in (depart, silence):
        assert "<" not in corps and ">" not in corps, corps


def test_le_message_de_depart_porte_le_ticket_et_le_stop(s):
    titre, corps = s.message_depart("admin_live", [_ligne(ticket=4242)])
    assert "admin_live" in titre
    assert "4242" in corps and "4580" in corps


def test_le_digest_nomme_les_motifs_ET_les_horizons(s):
    """Sans les horizons on chercherait la cause du mauvais côté : le 28/08,
    126 refus sur 128 portaient sur du 5 minutes."""
    _, corps = s.message_silence([("fees_exceed_edge", 10),
                                  ("correlated_exposure", 6)], 24,
                                 {"5min": 126, "4h": 2})
    assert "fees_exceed_edge" in corps and "correlated_exposure" in corps
    assert "5min 126" in corps


def test_aucun_refus_du_tout_se_dit_autrement(s):
    """« Rien ne part parce que tout est refusé » et « rien ne part parce que
    rien n'arrive » n'appellent pas la même décision."""
    _, corps = s.message_silence([], 24, {})
    assert "aucun signal metal" in corps.lower()


def test_le_digest_rappelle_que_la_poche_n_est_PAS_en_cause(s):
    _, corps = s.message_silence([("fees_exceed_edge", 10)], 24, {})
    assert "plafond de risque" in corps


# ── Branchement : le curseur n'avance que sur un envoi confirmé ────────────

def _armer(s, monkeypatch, etat, lignes, envoi_reussi):
    """Isole `main()` du réseau et du disque, garde sa logique de curseur."""
    ecrits = {}
    monkeypatch.setattr(s, "_charger_etat", lambda: dict(etat))
    monkeypatch.setattr(s, "_ecrire_etat", lambda e: ecrits.update(e))
    monkeypatch.setattr(s, "_lignes_audit",
                        lambda dest, depuis: (list(lignes), True))
    monkeypatch.setattr(
        s, "_notifier",
        lambda t, c, dedup, destination_id=None: envoi_reussi)
    monkeypatch.setattr(s, "_refus_metaux", lambda h: ([], {}))
    return ecrits


def test_envoi_CONFIRME_le_curseur_avance(s, monkeypatch):
    etat = {"curseur:admin_legacy": 5, "curseur:admin_live": 5}
    ecrits = _armer(s, monkeypatch, etat, [_ligne(id=9)], envoi_reussi=True)
    assert s.main() == 0
    assert ecrits["curseur:admin_legacy"] == 9
    assert ecrits["curseur:admin_live"] == 9


def test_envoi_RATE_le_curseur_NE_bouge_PAS(s, monkeypatch):
    """⛔ Un événement dont l'annonce a échoué doit être rejoué au passage
    suivant. Avancer le curseur le perdrait en silence."""
    etat = {"curseur:admin_legacy": 5, "curseur:admin_live": 5}
    ecrits = _armer(s, monkeypatch, etat, [_ligne(id=9)], envoi_reussi=False)
    assert s.main() == 0
    assert ecrits["curseur:admin_legacy"] == 5
    assert ecrits["curseur:admin_live"] == 5


def test_sans_depart_le_curseur_avance_quand_meme(s, monkeypatch):
    """Sinon la sonde relirait éternellement les mêmes pages de forex."""
    etat = {"curseur:admin_legacy": 5, "curseur:admin_live": 5}
    ecrits = _armer(s, monkeypatch, etat,
                    [_ligne(id=9, symbol="EURUSD")], envoi_reussi=True)
    assert s.main() == 0
    assert ecrits["curseur:admin_legacy"] == 9


def test_DRY_RUN_n_ecrit_RIEN(s, monkeypatch):
    """⛔ La leçon de la sonde de capture : une observation ne doit déplacer
    aucun état."""
    monkeypatch.setenv("DRY_RUN", "1")
    etat = {"curseur:admin_legacy": 5, "curseur:admin_live": 5}
    ecrits = _armer(s, monkeypatch, etat, [_ligne(id=9)], envoi_reussi=True)
    assert s.main() == 0
    assert ecrits == {}


def test_PREMIER_passage_pose_le_curseur_sans_rien_annoncer(s, monkeypatch):
    """⛔ Sans ça, la sonde annoncerait « premier ordre métal ! » sur une
    ligne de mai."""
    annonces = []
    monkeypatch.setattr(s, "_charger_etat", dict)
    ecrits = {}
    monkeypatch.setattr(s, "_ecrire_etat", lambda e: ecrits.update(e))
    monkeypatch.setattr(s, "_lignes_audit",
                        lambda dest, depuis: ([_ligne(id=9)], True))
    monkeypatch.setattr(s, "_refus_metaux", lambda h: ([], {}))

    def _espion(titre, corps, dedup, destination_id=None):
        annonces.append(titre)
        return True

    monkeypatch.setattr(s, "_notifier", _espion)
    assert s.main() == 0
    assert ecrits["curseur:admin_legacy"] == 9
    assert not any("PARTI" in a for a in annonces), annonces


def test_un_audit_ILLISIBLE_ne_pose_ni_n_avance_le_curseur(s, monkeypatch):
    """Un bridge muet ne vaut pas « rien n'est parti »."""
    monkeypatch.setattr(s, "_charger_etat",
                        lambda: {"curseur:admin_legacy": 5,
                                 "curseur:admin_live": 5})
    ecrits = {}
    monkeypatch.setattr(s, "_ecrire_etat", lambda e: ecrits.update(e))
    monkeypatch.setattr(s, "_lignes_audit", lambda dest, depuis: (None, False))
    monkeypatch.setattr(s, "_refus_metaux", lambda h: ([], {}))
    monkeypatch.setattr(s, "_notifier",
                        lambda t, c, dedup, destination_id=None: True)
    assert s.main() == 0
    assert ecrits["curseur:admin_legacy"] == 5


def test_le_digest_ne_NIE_pas_ce_que_sa_propre_liste_montre(s):
    """⛔ Le premier essai à blanc affichait « aucun de ces motifs n'est le
    plafond de risque » **trois lignes sous** un `bridge_plafond_risque : 20`.
    Une conclusion que la liste dément juste au-dessus vaut moins que pas de
    conclusion du tout."""
    _, avec = s.message_silence([("bridge_plafond_risque", 20),
                                 ("fees_exceed_edge", 3)], 24, {})
    assert "20 refus par le plafond de risque" in avec
    assert "Aucun de ces refus n'est le plafond" not in avec

    _, sans = s.message_silence([("fees_exceed_edge", 3)], 24, {})
    assert "Aucun de ces refus n'est le plafond" in sans


# ── Kraken : le journal, c'est `/fills` (2026-09-06) ──────────────────────
#
# ⛔ Kraken était hors périmètre faute d'`/audit` : son bridge n'a pas cet
# endpoint. Le brancher dessus aurait rendu « illisible » à chaque passage —
# un silence qu'on lirait comme « aucun ordre métal », c'est-à-dire l'inverse
# de ce que la sonde cherche.
#
# 🔑 Sur un exchange, un FILL EST un ordre parti : le `status="filled"` que
# l'audit MT5 porte y est acquis par construction.


def _fill(symbole="PF_XAUUSD", quand="2026-09-06T14:03:12.500Z",
          genre="taker", oid="abc-123"):
    return {"fill_id": "f-1", "order_id": oid, "symbol": symbole,
            "side": "buy", "size": 0.01, "price": 4450.0,
            "fill_time": quand, "fill_type": genre}


def test_kraken_est_desormais_surveille(s):
    assert "admin_kraken" in s.DESTINATIONS_SURVEILLEES


def test_un_fill_metal_devient_un_ordre_PARTI(s):
    l = s.fills_en_lignes_audit([_fill()])
    assert len(l) == 1 and l[0]["status"] == "filled"
    assert s.metaux_partis(l) == l


def test_un_fill_NON_metal_est_ignore(s):
    l = s.fills_en_lignes_audit([_fill(symbole="PF_XBTUSD")])
    assert s.metaux_partis(l) == []


def test_une_LIQUIDATION_n_est_PAS_un_ordre_que_nous_avons_envoye(s):
    """⛔ C'est la même distinction que `filled` et rien d'autre côté MT5 :
    décrire un événement subi comme un ordre parti serait un contresens."""
    assert s.fills_en_lignes_audit([_fill(genre="liquidation")]) == []


def test_un_type_de_fill_INCONNU_passe_et_se_voit(s):
    """⚠️ On nomme ce qui est EXCLU, pas ce qui est admis : lister les types
    admis rendrait la sonde muette le jour où Kraken renomme un libellé — et
    un détecteur ne se teste pas sur son silence."""
    assert len(s.fills_en_lignes_audit([_fill(genre="un_nouveau_type")])) == 1


def test_l_id_est_chronologique(s):
    """Le curseur ne fonctionne que si l'ordre est préservé."""
    l = s.fills_en_lignes_audit([
        _fill(quand="2026-09-06T14:05:00.000Z"),
        _fill(quand="2026-09-06T14:03:00.000Z")])
    assert [x["id"] for x in l] == sorted(x["id"] for x in l)
    assert s.id_max(l) == l[-1]["id"]


def test_un_horodatage_ILLISIBLE_ne_devient_pas_zero(s):
    """⛔ Un `id` à 0 ferait relire toute l'histoire et re-annoncer des ordres
    de mai comme s'ils partaient à l'instant."""
    assert s.fills_en_lignes_audit([_fill(quand="pas une date")]) == []
    assert s.fills_en_lignes_audit([_fill(quand=None)]) == []


def test_le_stop_est_None_PAS_zero(s):
    """⚠️ Chez Kraken le stop est un ORDRE SÉPARÉ : le fill ne le porte pas.
    Un `0.0` se lirait « position nue »."""
    assert s.fills_en_lignes_audit([_fill()])[0]["sl"] is None


def test_le_message_DIT_que_le_stop_est_inconnu(s):
    """⛔ Afficher « stop None » se lirait comme une position sans protection."""
    l = s.fills_en_lignes_audit([_fill()])
    _, corps = s.message_depart("admin_kraken", l)
    assert "None" not in corps
    assert "inconnu" in corps


def test_le_dispatcher_envoie_KRAKEN_sur_les_fills(s, monkeypatch):
    """⛔ Le brancher sur `/audit` rendrait « illisible » à chaque passage."""
    vus = []
    monkeypatch.setattr(s, "_appel",
                        lambda dest, chemin: (vus.append(chemin) or
                                              {"ok": True, "fills": [_fill()]}, True))

    class _Dest:
        bridge_type = "kraken"

    lignes, ok = s._lignes_du_journal(_Dest(), 0)
    assert vus == ["/fills"] and ok is True and len(lignes) == 1


def test_le_dispatcher_laisse_MT5_sur_l_audit(s, monkeypatch):
    vus = []
    monkeypatch.setattr(s, "_appel",
                        lambda dest, chemin: (vus.append(chemin) or
                                              {"orders": []}, True))

    class _Dest:
        bridge_type = "mt5"

    s._lignes_du_journal(_Dest(), 7)
    assert vus and vus[0].startswith("/audit"), vus


def test_le_curseur_filtre_ce_qui_est_DEJA_vu(s, monkeypatch):
    monkeypatch.setattr(s, "_appel", lambda dest, chemin: (
        {"ok": True, "fills": [_fill(quand="2026-09-06T14:03:00.000Z"),
                               _fill(quand="2026-09-06T14:07:00.000Z")]}, True))

    class _Dest:
        bridge_type = "kraken"

    tout, _ = s._lignes_du_journal(_Dest(), 0)
    apres, _ = s._lignes_du_journal(_Dest(), tout[0]["id"])
    assert len(tout) == 2 and len(apres) == 1


def test_une_lecture_RATEE_n_est_pas_une_absence_d_ordre(s, monkeypatch):
    """⛔ `(None, False)` et `([], True)` mènent à des conclusions opposées."""
    monkeypatch.setattr(s, "_appel", lambda dest, chemin: (None, False))

    class _Dest:
        bridge_type = "kraken"

    lignes, ok = s._lignes_du_journal(_Dest(), 0)
    assert lignes is None and ok is False


def test_un_ok_FALSE_du_bridge_est_aussi_une_lecture_ratee(s, monkeypatch):
    monkeypatch.setattr(s, "_appel",
                        lambda dest, chemin: ({"ok": False, "error": "x"}, True))

    class _Dest:
        bridge_type = "kraken"

    assert s._lignes_du_journal(_Dest(), 0) == (None, False)


# ── Le 3e état : « je n'ai pas eu de réponse » ─────────────────────────────
#
# ⛔ LE BUG DU 2026-10-07. Xavier a reçu **8 fois** le même message pour le
# même ordre (ticket 1360596228, parti à 14h00). Journal, à chaque passage de
# cron, toutes les 15 min :
#
#     ALERTE : 4 ordre(s) metal parti(s)
#     ENVOI ECHOUE (TimeoutError: The read operation timed out)
#     curseur NON avance — l'evenement sera rejoue
#
# Trois défauts qui se renforcent :
#   1. la sonde attendait la réponse 10 s, et le relais attend Telegram 10 s
#      lui aussi, DNS + TLS + nginx en plus ⇒ patience ÉGALE. ⚠️ Le relais
#      n'est pas lent en soi (mesuré 0,17 s le soir même) : ce fut un épisode
#      de lenteur Telegram. Mais à patience égale, le moindre épisode fait
#      lâcher le client avant le serveur ;
#   2. elle envoyait `dedup_key` SANS `cooldown_seconds`, donc la garde du
#      relais (`if dedup_key and cooldown_seconds > 0`) était INERTE ;
#   3. un délai de lecture était compté comme un échec d'envoi, et rejoué —
#      alors que le message partait vraiment.
#
# 🔑 « Je n'ai pas eu la réponse » n'est ni un succès ni un échec.

def _armer3(s, monkeypatch, etat, lignes, issue):
    """Comme `_armer`, mais `_notifier` peut rendre les TROIS états."""
    ecrits = {}
    monkeypatch.setattr(s, "_charger_etat", lambda: dict(etat))
    monkeypatch.setattr(s, "_ecrire_etat", lambda e: ecrits.update(e))
    monkeypatch.setattr(s, "_lignes_audit",
                        lambda dest, depuis: (list(lignes), True))
    monkeypatch.setattr(
        s, "_notifier",
        lambda t, c, dedup, destination_id=None: issue)
    monkeypatch.setattr(s, "_refus_metaux", lambda h: ([], {}))
    return ecrits


def test_le_cooldown_part_AVEC_la_cle_sinon_la_garde_est_inerte(s, monkeypatch):
    """🔑 Le défaut n° 2 : `app.py` exige `cooldown_seconds > 0`."""
    envoye = {}

    class _R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"sent": true}'

    def _faux_urlopen(rq, timeout=None):
        envoye["corps"] = json.loads(rq.data.decode())
        envoye["timeout"] = timeout
        return _R()

    import json
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", _faux_urlopen)
    monkeypatch.delenv("DRY_RUN", raising=False)

    assert s._notifier("T", "b", dedup="metal_parti:admin_live:4930") is True
    assert envoye["corps"]["dedup_key"] == "metal_parti:admin_live:4930"
    assert envoye["corps"]["cooldown_seconds"] > 0, (
        "sans duree, le relais ne tait RIEN et chaque rejeu repart vraiment")


def test_la_sonde_est_PLUS_patiente_que_le_relais(s):
    """🔑 Le défaut n° 1 — une patience ÉGALE est une patience trop courte.

    Le relais attend Telegram 10 s (`app.py`), plus le DNS, le TLS et nginx.
    ⚠️ Il n'est pas lent en soi : 0,17 s mesuré le soir du 07/10. Mais à
    patience égale, le moindre épisode de lenteur fait prendre au client un
    succès lent pour un échec — et il le rejoue sans fin.
    """
    assert s.DELAI_NOTIF > s.DELAI
    assert s.DELAI_NOTIF >= 20, (
        "10 s cote relais + reseau : il faut une marge franche")


def test_sans_reponse_on_rejoue_mais_PAS_indefiniment(s, monkeypatch):
    """🔑 Le défaut n° 3, et le cœur du correctif.

    Les premiers passages rejouent — le message a peut-être échoué. Mais au
    bout de `MAX_ESSAIS_SANS_REPONSE`, on considère l'annonce faite : à ce
    stade, un rejeu de plus n'apporte rien qu'un doublon de plus.
    """
    etat = {"curseur:admin_legacy": 5, "curseur:admin_live": 5}
    ecrits = _armer3(s, monkeypatch, etat, [_ligne(id=9)], issue=None)
    assert s.main() == 0
    # 1er essai sans réponse : on ne bouge pas, on compte
    assert ecrits["curseur:admin_live"] == 5
    assert ecrits["essais_sans_reponse:metal_parti:admin_live:9"] == 1

    # ... au dernier essai, on tranche et on avance
    etat2 = dict(etat)
    etat2["essais_sans_reponse:metal_parti:admin_live:9"] = \
        s.MAX_ESSAIS_SANS_REPONSE - 1
    ecrits2 = _armer3(s, monkeypatch, etat2, [_ligne(id=9)], issue=None)
    assert s.main() == 0
    assert ecrits2["curseur:admin_live"] == 9
    assert "essais_sans_reponse:metal_parti:admin_live:9" not in ecrits2


def test_un_VRAI_refus_rejoue_sans_jamais_s_epuiser(s, monkeypatch):
    """⛔ Un refus du relais est une réponse : il dit que rien n'est parti.

    Celui-là doit être rejoué, et le compteur d'essais-sans-réponse ne doit
    PAS le faire abandonner — sinon un jeton mort perdrait l'alerte en
    silence, ce que cette sonde existe précisément pour empêcher.
    """
    etat = {"curseur:admin_legacy": 5, "curseur:admin_live": 5,
            "essais_sans_reponse:metal_parti:admin_live:9": 99}
    ecrits = _armer3(s, monkeypatch, etat, [_ligne(id=9)], issue=False)
    assert s.main() == 0
    assert ecrits["curseur:admin_live"] == 5
    assert "essais_sans_reponse:metal_parti:admin_live:9" not in ecrits


def test_un_succes_efface_le_compteur_d_essais(s, monkeypatch):
    etat = {"curseur:admin_legacy": 5, "curseur:admin_live": 5,
            "essais_sans_reponse:metal_parti:admin_live:9": 2}
    ecrits = _armer3(s, monkeypatch, etat, [_ligne(id=9)], issue=True)
    assert s.main() == 0
    assert ecrits["curseur:admin_live"] == 9
    assert "essais_sans_reponse:metal_parti:admin_live:9" not in ecrits


def test_un_delai_de_lecture_rend_None_et_PAS_False(s, monkeypatch):
    """⛔ Le mapping exact qui a produit les 8 doublons.

    `urllib` lève `TimeoutError` quand la réponse n'arrive pas. L'ancienne
    sonde l'attrapait dans le même `except` que les erreurs réseau et rendait
    `False` — « rien n'est parti ». C'était faux : le message partait.
    """
    import urllib.request

    def _trop_lent(rq, timeout=None):
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(urllib.request, "urlopen", _trop_lent)
    monkeypatch.delenv("DRY_RUN", raising=False)

    assert s._notifier("T", "b", dedup="k") is None


def test_une_URLError_enveloppant_un_timeout_rend_aussi_None(s, monkeypatch):
    """`urllib` emballe parfois le délai dans `URLError.reason`."""
    import urllib.error
    import urllib.request

    def _trop_lent(rq, timeout=None):
        raise urllib.error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr(urllib.request, "urlopen", _trop_lent)
    monkeypatch.delenv("DRY_RUN", raising=False)

    assert s._notifier("T", "b", dedup="k") is None


def test_une_VRAIE_panne_reseau_rend_bien_False(s, monkeypatch):
    """⚠️ Ne pas tout transformer en « je ne sais pas » : une connexion
    refusée est une réponse, et elle veut dire que rien n'est parti."""
    import urllib.error
    import urllib.request

    def _refuse(rq, timeout=None):
        raise urllib.error.URLError(ConnectionRefusedError("refuse"))

    monkeypatch.setattr(urllib.request, "urlopen", _refuse)
    monkeypatch.delenv("DRY_RUN", raising=False)

    assert s._notifier("T", "b", dedup="k") is False


# ── Le digest ne doit pas AFFIRMER plus large que ce qu'il mesure ──────────
#
# ⛔ LE 4e DÉFAUT DU 2026-10-07, révélé le soir même. À 19h30 UTC la sonde a
# envoyé « Aucun ordre or ni argent n'est parti depuis 24 h » — alors que
# QUATRE étaient partis l'après-midi (ids 4922, 4926, 4928, 4929).
#
# Elle affirmait un fait sur 24 HEURES en ne testant qu'une condition de CE
# PASSAGE : `quelque_chose_est_parti` ne vaut que pour les lignes neuves lues
# à l'instant. Les 8 rejeux le masquaient — ils gardaient le drapeau à vrai à
# chaque passage. Avancer le curseur à la main a levé le masque.

def test_un_depart_ANNONCE_est_retenu_dans_l_etat(s, monkeypatch):
    etat = {"curseur:admin_legacy": 5, "curseur:admin_live": 5}
    ecrits = _armer3(s, monkeypatch, etat, [_ligne(id=9)], issue=True)
    assert s.main() == 0
    assert "dernier_depart_metal" in ecrits, (
        "sans cette date, le digest ne sait que ce que CE passage a vu")


def test_le_digest_SE_TAIT_si_un_metal_est_parti_dans_la_fenetre(s,
                                                                 monkeypatch):
    """🔑 L'INVARIANT : ne pas dire « rien depuis 24 h » quand il y a eu
    quelque chose dans ces 24 h, même si CE passage ne voit rien de neuf."""
    recent = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    etat = {"curseur:admin_legacy": 5, "curseur:admin_live": 5,
            "dernier_depart_metal": recent,
            # il y a plus de 24 h qu'on n'a pas fait de digest : l'ancienne
            # version aurait donc parle
            "dernier_silence": (datetime.now(timezone.utc)
                                - timedelta(hours=30)).isoformat()}
    envois = []
    ecrits = _armer3(s, monkeypatch, etat, [], issue=True)
    monkeypatch.setattr(
        s, "_notifier",
        lambda t, c, dedup, destination_id=None: envois.append(t) or True)
    assert s.main() == 0
    assert envois == [], f"le digest a parle alors qu'un metal est parti : {envois}"
    # ⚠️ `nouveau` est une COPIE de l'etat : la cle est REPORTEE, pas reecrite.
    # Exiger son absence testait le mauvais invariant — ce qui compte est
    # qu'elle n'ait pas AVANCE.
    assert ecrits["dernier_silence"] == etat["dernier_silence"]


def test_le_digest_PARLE_si_vraiment_rien_depuis_la_fenetre(s, monkeypatch):
    """⚠️ Ne pas rendre la sonde muette : son silence doit rester un signal."""
    vieux = (datetime.now(timezone.utc) - timedelta(hours=40)).isoformat()
    etat = {"curseur:admin_legacy": 5, "curseur:admin_live": 5,
            "dernier_depart_metal": vieux,
            "dernier_silence": (datetime.now(timezone.utc)
                                - timedelta(hours=30)).isoformat()}
    envois = []
    ecrits = _armer3(s, monkeypatch, etat, [], issue=True)
    monkeypatch.setattr(
        s, "_notifier",
        lambda t, c, dedup, destination_id=None: envois.append(t) or True)
    assert s.main() == 0
    assert len(envois) == 1 and "aucun ordre metal" in envois[0].lower()
    assert ecrits["dernier_silence"] != etat["dernier_silence"], (
        "le digest a parle sans noter qu'il l'avait fait : il se repetera")


def test_jamais_vu_de_depart_le_digest_parle_quand_meme(s, monkeypatch):
    """Au tout debut, aucun depart connu : le silence est legitime."""
    etat = {"curseur:admin_legacy": 5, "curseur:admin_live": 5}
    envois = []
    _armer3(s, monkeypatch, etat, [], issue=True)
    monkeypatch.setattr(
        s, "_notifier",
        lambda t, c, dedup, destination_id=None: envois.append(t) or True)
    assert s.main() == 0
    assert len(envois) == 1
