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
