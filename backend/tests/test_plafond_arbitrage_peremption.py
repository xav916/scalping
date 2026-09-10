"""Une question d'arbitrage doit dire QUAND elle expire, et le DIRE quand elle a expiré.

⛔ **Ce qui s'est passé le 2026-09-07.** Le plafond a été franchi à 23h18 UTC.
La question est partie à 23h19 UTC — **01h19 du matin, heure de Paris**. Xavier
dormait. Elle n'a **jamais** reçu de réponse.

Elle n'en avait plus besoin : 41 minutes plus tard, à minuit UTC, le jour a
changé, le plafond s'est remis à zéro et le compte a retradé tout seul
(`XAG/USD buy` à 01h09 UTC le 08/09). Comparaison des trois demandes de
l'historique :

```
04/09  posée 16h31 Paris  ->  CONTINUER en 4 minutes
07/09  posée 01h19 Paris  ->  JAMAIS repondu
09/09  posée 17h07 Paris  ->  en attente
```

Deux mécanismes ont scellé le silence, et aucun n'est un bug :

1. La question n'est posée **qu'une fois** (`if not d.get("demande_le")`).
   Volontaire — relancer à 1h du matin pour un plafond qui se réinitialise dans
   41 minutes serait du bruit, pas de la protection.
2. `demandes_en_attente()` filtre `WHERE jour = aujourd'hui`. Au changement de
   jour, la demande devient **invisible** — mais reste `EN_ATTENTE` en base,
   pour toujours.

⇒ **Le message MENTAIT** : il disait « sans réponse, il reste bloqué », ce qui
n'est vrai que jusqu'à minuit UTC. Et la ligne restait éternellement dans un
état qui affirme attendre une décision devenue sans objet.

*Un état qui ne dit pas la vérité sur lui-même est le défaut de la journée.*

⚠️ Aucun de ces deux correctifs ne desserre quoi que ce soit : le premier
ajoute une phrase, le second renomme un état déjà invisible à toutes les
requêtes (**toutes** filtrent sur `jour`). Vérifié avant d'écrire.
"""
from datetime import datetime, timezone

import pytest

from backend.services import plafond_arbitrage as pa


@pytest.fixture
def db(tmp_path, monkeypatch):
    f = tmp_path / "trades.db"
    monkeypatch.setattr(pa, "_db_path", lambda: str(f), raising=False)
    import backend.services.trade_log_service as tls
    monkeypatch.setattr(tls, "_DB_PATH", f)
    pa._init_schema()
    return f


def _demande(jour, etat=pa.EN_ATTENTE, dest="admin_live", demande_le="x"):
    with pa._conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO plafond_arbitrage "
            "(destination_id, jour, palier, etat, pnl_au_moment, seuil, "
            " cree_le, demande_le) VALUES (?,?,1,?,-24.6,-21.1,?,?)",
            (dest, jour, etat, f"{jour}T23:18:00+00:00", demande_le))


# ─── 1. Le message dit QUAND il expire ───────────────────────────────

def test_la_question_dit_l_heure_de_peremption(db):
    """⛔ « Sans réponse, il reste bloqué » était FAUX au-delà de minuit UTC."""
    texte = pa.construire_question(
        [{"destination_id": "admin_live", "palier": 1,
          "pnl_au_moment": -24.6, "seuil": -21.1}],
        maintenant=datetime(2026, 9, 9, 15, 7, tzinfo=timezone.utc))

    assert "02h00 Paris" in texte
    assert "8h53" in texte or "8 h 53" in texte, (
        f"le temps restant n'est pas annoncé : {texte}")


def test_la_question_dit_que_le_compte_RETRADE_sans_decision(db):
    """Le point que le message taisait : à minuit, il repart tout seul."""
    texte = pa.construire_question(
        [{"destination_id": "admin_live", "palier": 1,
          "pnl_au_moment": -24.6, "seuil": -21.1}],
        maintenant=datetime(2026, 9, 9, 15, 7, tzinfo=timezone.utc))

    # ⚠️ On normalise les espaces : le message est replié sur plusieurs
    # lignes, et la place de la coupure est un choix de mise en forme, pas un
    # comportement. Un test qui en dépend casse au premier reformatage et
    # n'aurait rien dit de plus.
    plat = " ".join(texte.lower().split())
    assert "retrade" in plat
    assert "sans que tu aies decide" in plat


def test_une_question_posee_TARD_annonce_le_peu_de_temps_restant(db):
    """Le cas du 07/09 : 41 minutes. C'est ce qu'il fallait pouvoir lire."""
    texte = pa.construire_question(
        [{"destination_id": "admin_live", "palier": 1,
          "pnl_au_moment": -27.8, "seuil": -21.4}],
        maintenant=datetime(2026, 9, 7, 23, 19, tzinfo=timezone.utc))

    assert "41min" in texte or "41 min" in texte, texte


def test_le_message_reste_SANS_chevrons(db):
    """⛔ Le canal poste en HTML : Telegram refuse le message ENTIER sur une
    balise mal formée — échec silencieux. Invariant déjà payé huit fois."""
    texte = pa.construire_question(
        [{"destination_id": "admin_live", "palier": 1,
          "pnl_au_moment": -24.6, "seuil": -21.1}],
        maintenant=datetime(2026, 9, 9, 15, 7, tzinfo=timezone.utc))
    assert "<" not in texte and ">" not in texte


def test_construire_question_marche_SANS_maintenant(db):
    """Rétrocompatible : l'appelant existant ne passe pas l'heure."""
    texte = pa.construire_question(
        [{"destination_id": "admin_live", "palier": 1,
          "pnl_au_moment": -24.6, "seuil": -21.1}])
    assert "PLAFOND DE PERTE FRANCHI" in texte


# ─── 2. Une demande périmée le DIT ───────────────────────────────────

def test_une_demande_de_la_VEILLE_est_marquee_EXPIRE(db):
    """⛔ Le cœur : `EN_ATTENTE` à vie affirme attendre une décision qui n'a
    plus d'objet."""
    _demande("2026-09-07")
    n = pa.expirer_demandes_perimees(aujourdhui="2026-09-09")

    assert n == 1
    with pa._conn() as c:
        etat = c.execute(
            "SELECT etat FROM plafond_arbitrage WHERE jour='2026-09-07'"
        ).fetchone()[0]
    assert etat == pa.EXPIRE


def test_la_demande_DU_JOUR_n_est_PAS_touchee(db):
    """⚠️ Elle attend une vraie décision : l'expirer serait la perdre."""
    _demande("2026-09-09")
    assert pa.expirer_demandes_perimees(aujourdhui="2026-09-09") == 0

    with pa._conn() as c:
        etat = c.execute(
            "SELECT etat FROM plafond_arbitrage WHERE jour='2026-09-09'"
        ).fetchone()[0]
    assert etat == pa.EN_ATTENTE


def test_une_demande_TRANCHEE_garde_sa_decision(db):
    """`CONTINUER` et `GELER` sont des décisions prises : les écraser
    effacerait la trace de ce que Xavier a répondu."""
    _demande("2026-09-04", etat=pa.CONTINUER)
    _demande("2026-09-05", etat=pa.GELER, dest="admin_kraken")
    assert pa.expirer_demandes_perimees(aujourdhui="2026-09-09") == 0

    with pa._conn() as c:
        etats = {r[0] for r in c.execute(
            "SELECT etat FROM plafond_arbitrage WHERE jour<'2026-09-09'")}
    assert etats == {pa.CONTINUER, pa.GELER}


def test_expirer_ne_change_RIEN_a_ce_qui_bloque(db):
    """⛔ L'invariant qui autorise ce correctif : toutes les requêtes filtrent
    déjà sur `jour`, donc une ligne de la veille était DÉJÀ invisible.
    Renommer son état ne peut pas rouvrir un compte."""
    # ⛔ `demandes_en_attente()` lit l'horloge REELLE : ce test, ecrit le 09/09
    # avec la date en dur, est passe au vert ce jour-la et a rougi le
    # lendemain. Un test qui ne passe que le jour ou on l'ecrit ne teste rien
    # — il date. Le jour se derive donc de l'horloge, comme le code teste.
    from datetime import date, timedelta
    aujourdhui = date.today().isoformat()
    veille = (date.today() - timedelta(days=2)).isoformat()

    _demande(veille)
    _demande(aujourdhui)

    avant = pa.demandes_en_attente()
    pa.expirer_demandes_perimees(aujourdhui=aujourdhui)
    apres = pa.demandes_en_attente()

    assert [d["jour"] for d in avant] == [d["jour"] for d in apres] == [aujourdhui]


def test_expirer_ne_LEVE_jamais(db, monkeypatch):
    """Une base illisible ne doit pas tuer le job qui pose les questions —
    c'est lui qui empêche un blocage muet."""
    monkeypatch.setattr(pa, "_conn", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert pa.expirer_demandes_perimees(aujourdhui="2026-09-09") == 0
