"""L'aspiration des canaux : incrementale, tolerante, et en LECTURE SEULE.

⛔ Ce module agit avec le COMPTE de Xavier, pas avec un bot. Le fichier de
session vaut son compte Telegram. Deux proprietes doivent donc etre tenues par
le comportement, pas par une relecture du fichier :

  1. **lecture seule** — le test fournit un client qui LEVE sur toute methode
     autre que `iter_messages` : envoyer, transferer, rejoindre, supprimer ;
  2. **un canal en echec n'emporte pas les autres** — c'est le defaut du
     backfill d'admission du 02/10, ou un refus sur la 6e paire abandonnait les
     42 suivantes.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.services import ingestion_telegram as ing
from backend.services import veille_canaux as vc


class _Msg:
    def __init__(self, mid, texte, quand=None):
        self.id = mid
        self.message = texte
        self.date = quand or datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


class ClientLectureSeule:
    """⛔ Il LEVE sur tout ce qui n'est pas de la lecture. C'est le test.

    Une doublure permissive laisserait passer un envoi ou un transfert sans que
    rien ne le dise — exactement le piege des doublures sans la forme de la
    production, paye trois fois le 2026-10-03.
    """

    def __init__(self, par_canal: dict[str, list]):
        self.par_canal = par_canal
        self.lectures: list[tuple] = []

    def iter_messages(self, canal, limit=None, min_id=0):
        self.lectures.append((canal, limit, min_id))
        for m in sorted(self.par_canal.get(canal, []),
                        key=lambda x: x.id, reverse=True)[:limit]:
            if m.id > (min_id or 0):
                yield m

    def __getattr__(self, nom):
        raise AssertionError(
            f"⛔ `{nom}` appele : ce module doit etre en LECTURE SEULE")


@pytest.fixture
def base(tmp_path, monkeypatch):
    """Une base neuve, isolee, pour le curseur ET le stockage."""
    chemin = tmp_path / "trades.db"
    monkeypatch.setattr(ing, "_db", lambda: str(chemin))
    monkeypatch.setattr(vc, "_db_path", lambda: str(chemin))
    return chemin


# ─── LECTURE SEULE ───────────────────────────────────────────────────────

def test_seule_la_LECTURE_est_appelee(base):
    """Si le module envoyait, transferait ou rejoignait quoi que ce soit, la
    doublure leverait et ce test echouerait."""
    cl = ClientLectureSeule({"@a": [_Msg(1, "pin bar en 5min sur l'or")]})
    r = ing.aspirer(client=cl, canaux=("@a",))
    assert r["actif"] is True
    assert r["lus"] == 1
    assert cl.lectures and cl.lectures[0][0] == "@a"


# ─── INCREMENTAL ─────────────────────────────────────────────────────────

def test_une_SECONDE_passe_ne_relit_pas_l_historique(base):
    msgs = [_Msg(i, f"pin bar en 5min, message {i}") for i in (1, 2, 3)]
    cl = ClientLectureSeule({"@a": msgs})

    r1 = ing.aspirer(client=cl, canaux=("@a",))
    assert r1["lus"] == 3 and r1["ranges"] == 3
    assert ing.curseur("@a") == 3

    r2 = ing.aspirer(client=cl, canaux=("@a",))
    assert r2["lus"] == 0, "rien de neuf ne doit etre relu"
    assert cl.lectures[-1][2] == 3, "le min_id doit porter le curseur"


def test_seuls_les_messages_NEUFS_sont_rapportes(base):
    cl = ClientLectureSeule({"@a": [_Msg(1, "pin bar 5min"), _Msg(2, "fvg 15min")]})
    ing.aspirer(client=cl, canaux=("@a",))
    cl.par_canal["@a"].append(_Msg(3, "order block en 30min sur l'or"))
    r = ing.aspirer(client=cl, canaux=("@a",))
    assert r["lus"] == 1


def test_le_curseur_ne_RECULE_jamais(base):
    """⚠️ Sinon un passage en retard ferait relire — et doubler — l'historique."""
    cl = ClientLectureSeule({"@a": [_Msg(10, "pin bar 5min")]})
    ing.aspirer(client=cl, canaux=("@a",))
    assert ing.curseur("@a") == 10
    ing._poser_curseur("@a", 4, 0)
    assert ing.curseur("@a") == 10


def test_chaque_canal_a_son_PROPRE_curseur(base):
    cl = ClientLectureSeule({
        "@a": [_Msg(5, "pin bar 5min")],
        "@b": [_Msg(99, "fvg en 15min sur l'or")]})
    ing.aspirer(client=cl, canaux=("@a", "@b"))
    assert ing.curseur("@a") == 5
    assert ing.curseur("@b") == 99


# ─── TOLERANCE ───────────────────────────────────────────────────────────

def test_un_canal_en_ECHEC_n_emporte_pas_les_autres(base):
    """⚠️ Le defaut du backfill d'admission du 02/10 : un refus sur la 6e paire
    abandonnait les 42 suivantes."""
    class _Capricieux(ClientLectureSeule):
        def iter_messages(self, canal, limit=None, min_id=0):
            if canal == "@casse":
                raise RuntimeError("canal introuvable")
            return super().iter_messages(canal, limit, min_id)

    cl = _Capricieux({"@a": [_Msg(1, "pin bar 5min")],
                      "@c": [_Msg(2, "fvg en 15min")]})
    r = ing.aspirer(client=cl, canaux=("@a", "@casse", "@c"))
    assert "erreur" in r["par_canal"]["@casse"]
    assert r["par_canal"]["@a"]["lus"] == 1
    assert r["par_canal"]["@c"]["lus"] == 1, "les suivants doivent continuer"


def test_un_media_SANS_legende_est_ignore_mais_fait_avancer_le_curseur(base):
    """Rien a analyser dans une image nue — mais la relire indefiniment serait
    une boucle."""
    cl = ClientLectureSeule({"@a": [_Msg(1, ""), _Msg(2, "   "),
                                    _Msg(3, "pin bar en 5min")]})
    r = ing.aspirer(client=cl, canaux=("@a",))
    assert r["lus"] == 1
    assert ing.curseur("@a") == 3, "le curseur doit depasser les medias nus"


def test_le_PLAFOND_par_passage_est_respecte(base, monkeypatch):
    """⚠️ Un premier passage sur un canal ancien rapatrierait sinon des
    dizaines de milliers de messages d'un coup."""
    monkeypatch.setattr(ing, "PAR_PASSAGE", 2)
    cl = ClientLectureSeule({"@a": [_Msg(i, f"pin bar 5min {i}")
                                    for i in range(1, 11)]})
    r = ing.aspirer(client=cl, canaux=("@a",))
    assert r["lus"] == 2
    assert cl.lectures[0][1] == 2


# ─── LE CLASSEMENT est delegue, pas refait ───────────────────────────────

def test_les_messages_ranges_sont_CLASSES_par_veille_canaux(base):
    import sqlite3
    cl = ClientLectureSeule({"@a": [
        _Msg(1, "Regime de marche par l exposant de Hurst, seuil de 0,5, en 15min sur l or"),
        _Msg(2, "Nouvel indicateur RSI lisse sur 14 periodes"),
    ]})
    ing.aspirer(client=cl, canaux=("@a",))
    with sqlite3.connect(str(base)) as c:
        lignes = {r[0]: r[1] for r in c.execute(
            "SELECT message_id, famille FROM messages_canaux")}
    assert lignes["1"] == vc.PREDICAT
    assert lignes["2"] == vc.OSCILLATEUR


# ─── SANS REGLAGE, rien ──────────────────────────────────────────────────

def test_sans_canal_declare_le_module_est_INACTIF_et_le_dit(monkeypatch):
    monkeypatch.setattr(ing, "CANAUX", ())
    r = ing.aspirer()
    assert r["actif"] is False
    assert "VEILLE_CANAUX" in r["motif"]


def test_sans_identifiants_le_module_est_INACTIF_et_le_dit(monkeypatch):
    monkeypatch.setattr(ing, "CANAUX", ("@a",))
    monkeypatch.setattr(ing, "API_ID", "")
    ok, motif = ing.configure()
    assert ok is False and "API_ID" in motif


def test_configure_dit_quand_telethon_manque(monkeypatch):
    monkeypatch.setattr(ing, "CANAUX", ("@a",))
    monkeypatch.setattr(ing, "API_ID", "1")
    monkeypatch.setattr(ing, "API_HASH", "x")
    import builtins
    vrai_import = builtins.__import__

    def _sans_telethon(nom, *a, **k):
        if nom == "telethon":
            raise ImportError("absent")
        return vrai_import(nom, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _sans_telethon)
    ok, motif = ing.configure()
    assert ok is False and "telethon" in motif


def test_la_session_vit_dans_le_volume_MONTE():
    """⛔ Pas dans l'image : un deploiement l'effacerait, et il faudrait
    refaire le login par SMS. C'est la lecon du gel du banc, le meme jour."""
    # ⚠️ `as_posix()` : la production est Linux, mais ce test tourne aussi sous
    # Windows ou `Path` rend des antislashs. Comparer `str()` echouerait sur la
    # plateforme de developpement pour une raison qui n a rien a voir.
    assert ing.SESSION.as_posix().startswith("/app/data/"), ing.SESSION
