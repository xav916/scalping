"""Aspire les messages de plusieurs canaux Telegram. Lecture SEULE.

Demande de Xavier le 2026-10-03 : « je veux automatiser maintenant ». Les
messages partent ensuite dans `veille_canaux.verser()`, qui les classe, puis
dans l'analyse.

## ⛔ Pourquoi une session UTILISATEUR, et ce que ca engage

Un bot Telegram ne peut pas lire un canal dont il n'est pas administrateur, et
il n'existe aucun transfert automatique entre deux canaux quelconques. Lire
<< tous les canaux >> automatiquement exige donc un client agissant comme le
COMPTE de Xavier (MTProto), pas comme un bot.

⚠️ **Le fichier de session vaut le compte Telegram.** Quiconque l'obtient lit
toutes ses conversations. Consequences tenues par ce module :

  - il vit dans le volume monte (`/app/data/`), **jamais** dans l'image, jamais
    dans git — et un deploiement ne l'efface donc pas (lecon du gel du banc, le
    meme jour) ;
  - il est cree avec des droits `0600` ;
  - ni `api_hash` ni le contenu de la session ne sont journalises. Les traces
    ne portent que des noms de canaux et des comptes.

## ⛔ LECTURE SEULE, et c'est structurel

Aucune methode d'envoi, de transfert, d'adhesion ou de suppression n'est
appelee ici. Le client ne sert qu'a `iter_messages`. Un test l'exige par le
comportement : il fournit un client qui **leve** sur toute autre methode.

🔑 Ce que ce module ne fait pas non plus : interpreter. Il range du texte brut.
Le classement est dans `veille_canaux`, deterministe et teste ; l'analyse est
ailleurs. Un module qui aspirerait ET jugerait serait impossible a eprouver.

## Incremental par construction

Le dernier `message_id` vu est retenu PAR CANAL dans `veille_canaux_curseur`.
Une seconde passe ne relit donc pas l'historique — et `UNIQUE (canal,
message_id)` cote stockage rend l'idempotence native de toute facon. Les deux,
parce qu'un curseur perdu ne doit pas doubler les messages.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# ⚠️ VIDE par defaut : sans reglage, ce module ne lit RIEN et ne se plaint pas.
CANAUX: tuple[str, ...] = tuple(
    c.strip() for c in os.getenv("VEILLE_CANAUX", "").split(",") if c.strip())

SESSION = Path(os.getenv("VEILLE_TG_SESSION", "/app/data/veille_telegram"))
API_ID = os.getenv("VEILLE_TG_API_ID", "")
API_HASH = os.getenv("VEILLE_TG_API_HASH", "")

# Plafond par canal et par passage. ⚠️ Un premier passage sur un canal ancien
# pourrait sinon rapatrier des dizaines de milliers de messages d'un coup.
PAR_PASSAGE = int(os.getenv("VEILLE_TG_PAR_PASSAGE", "200"))


def configure() -> tuple[bool, str]:
    """Peut-on lire ? Rend aussi POURQUOI non, pour que ce soit lisible."""
    if not CANAUX:
        return False, "VEILLE_CANAUX vide — aucun canal declare"
    if not API_ID or not API_HASH:
        return False, "VEILLE_TG_API_ID / VEILLE_TG_API_HASH absents"
    try:
        import telethon  # noqa: F401
    except ImportError:
        return False, "telethon absent de l'image"
    return True, f"{len(CANAUX)} canal/canaux declare(s)"


# ─── Le curseur, par canal ───────────────────────────────────────────────

def _db() -> str:
    from backend.services.pair_admission_controller import _db_path
    return _db_path()


def _schema(c: sqlite3.Connection) -> None:
    c.execute("""CREATE TABLE IF NOT EXISTS veille_canaux_curseur (
        canal           TEXT PRIMARY KEY,
        dernier_id      INTEGER NOT NULL,
        maj_a           TEXT NOT NULL,
        messages_lus    INTEGER NOT NULL DEFAULT 0)""")


def curseur(canal: str) -> int:
    with sqlite3.connect(_db()) as c:
        _schema(c)
        r = c.execute("SELECT dernier_id FROM veille_canaux_curseur "
                      "WHERE canal = ?", (canal,)).fetchone()
    return int(r[0]) if r else 0


def _poser_curseur(canal: str, dernier_id: int, lus: int) -> None:
    from datetime import datetime, timezone
    with sqlite3.connect(_db()) as c:
        _schema(c)
        c.execute(
            "INSERT INTO veille_canaux_curseur (canal, dernier_id, maj_a, "
            " messages_lus) VALUES (?,?,?,?) "
            "ON CONFLICT(canal) DO UPDATE SET "
            "  dernier_id = max(dernier_id, excluded.dernier_id), "
            "  maj_a = excluded.maj_a, "
            "  messages_lus = messages_lus + excluded.messages_lus",
            (canal, int(dernier_id),
             datetime.now(timezone.utc).isoformat(timespec="seconds"), int(lus)))


# ─── L'aspiration ────────────────────────────────────────────────────────

def _client():
    """Le client MTProto. ⚠️ Importe tard : l'absence de telethon n'empeche
    pas le reste du module d'etre importable et testable."""
    from telethon.sync import TelegramClient
    SESSION.parent.mkdir(parents=True, exist_ok=True)
    cl = TelegramClient(str(SESSION), int(API_ID), API_HASH)
    return cl


def _droits_session() -> None:
    """La session vaut le compte : personne d'autre ne doit la lire."""
    for p in (SESSION, SESSION.with_suffix(".session")):
        try:
            if p.exists():
                p.chmod(0o600)
        except OSError as e:
            logger.warning("ingestion_telegram: droits de session (%s)", e)


def aspirer_un(client, canal: str, depuis_id: int | None = None,
               limite: int | None = None) -> list[dict]:
    """Les messages d'UN canal, plus recents que `depuis_id`.

    ⛔ `client` est injecte : c'est ce qui rend cette fonction testable sans
    Telegram, et ce qui permet au test d'exiger la lecture seule en fournissant
    un client qui leve sur toute autre methode.
    """
    depuis = curseur(canal) if depuis_id is None else int(depuis_id)
    plafond = PAR_PASSAGE if limite is None else int(limite)
    out: list[dict] = []
    vu_max = depuis
    for m in client.iter_messages(canal, limit=plafond,
                                  min_id=depuis or 0):
        mid = int(getattr(m, "id", 0) or 0)
        texte = (getattr(m, "message", None) or getattr(m, "text", None) or "")
        if mid <= depuis:
            continue
        vu_max = max(vu_max, mid)
        if not str(texte).strip():
            continue        # media sans legende : rien a analyser
        d = getattr(m, "date", None)
        out.append({
            "canal": canal,
            "message_id": str(mid),
            "texte": str(texte),
            "publie_a": d.isoformat() if hasattr(d, "isoformat") else None,
        })
    if vu_max > depuis:
        _poser_curseur(canal, vu_max, len(out))
    return out


def aspirer(client=None, canaux: tuple[str, ...] | None = None) -> dict:
    """Tous les canaux declares → ranges et classes. Rend un releve.

    ⚠️ Un canal en echec n'emporte pas les autres : meme defaut que le backfill
    d'admission du 02/10, ou un refus sur la 6e paire abandonnait les 42
    suivantes.
    """
    from backend.services import veille_canaux

    liste = canaux if canaux is not None else CANAUX
    if client is None:
        ok, motif = configure()
        if not ok:
            logger.info("ingestion_telegram: inactif — %s", motif)
            return {"actif": False, "motif": motif, "par_canal": {}}
        client = _client()
        client.start()
        _droits_session()

    par_canal: dict[str, dict] = {}
    for canal in liste:
        try:
            messages = aspirer_un(client, canal)
            bilan = veille_canaux.verser(messages)
            par_canal[canal] = {"lus": len(messages), **bilan}
        except Exception as e:  # noqa: BLE001 — un canal ne doit pas tout casser
            logger.warning("ingestion_telegram: %s echoue (%s: %s)",
                           canal, type(e).__name__, e)
            par_canal[canal] = {"erreur": f"{type(e).__name__}: {e}"[:160]}
    return {"actif": True, "par_canal": par_canal,
            "lus": sum(x.get("lus", 0) for x in par_canal.values()),
            "ranges": sum(x.get("ranges", 0) for x in par_canal.values())}
