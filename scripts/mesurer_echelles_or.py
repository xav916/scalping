"""Les échelles M15/M30 sur l'or produisent-elles quelque chose EN JOURNÉE ?

⛔ **Pourquoi cette sonde existe** (2026-09-09). En cherchant à ouvrir l'or au
compte réel, j'ai mesuré que **156 des 156** signaux M15/M30 de l'or tombaient
entre 21 h et 05 h UTC, et j'en ai conclu que les échelles agrégées produisaient
« au moment précis où l'or coûte trop cher ».

**C'était FAUX** : le module a été déployé le 08/09 à 16:14 UTC et la mesure a
été faite à 05:15. La fenêtre d'observation ne contenait presque aucune heure de
journée — et les rares qu'elle contenait étaient celles où le tampon se
remplissait encore. *Un motif horaire mesuré sur treize heures de nuit n'est pas
un motif horaire.*

⇒ Cette sonde laisse passer une séance de JOUR complète et rend le chiffre qui
manque : **combien de signaux M15/M30 l'or produit hors de la fenêtre nocturne,
et à quelle porte ils meurent.**

## Ce qu'elle mesure, et pourquoi ainsi

Le compte réel refuse ces signaux à `horizon_not_allowed` — la première porte.
On ne peut donc PAS y voir ce que feraient les portes suivantes. Le **démo**,
lui, sert ces échelles : les mêmes signaux y traversent toute la chaîne. C'est
lui qui dit ce qui arriverait au réel.

⚠️ **Et ce n'est pas une équivalence.** « Le démo pilote le réel » est faux hors
miroir, et le réel est **moins** filtré que le démo. Le chiffre du démo est donc
une **borne basse** de ce que l'ouverture libérerait, jamais une prédiction. La
sonde le DIT dans son message : un chiffre dont on ignore le sens de l'erreur
est pire qu'une absence de chiffre.

## Invariants respectés

- **Une observation ne déplace rien** : lecture seule, aucun curseur, aucun état.
- **Un seul message par passage**, avec `dedup_key`.
- **Elle dit son BUT et son VERDICT**, pas seulement des nombres.
- **Un envoi raté est annoncé**, jamais avalé.
- `substr(created_at,1,10)` et **jamais `date()`** : les horodatages portent un
  `T`, et le piège de la fenêtre SQLite a déjà mordu deux fois.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timezone

DB = os.environ.get("TRADES_DB", "/app/data/trades.db")
PAIRE = os.environ.get("ECHELLES_OR_PAIRE", "XAU/USD")

# ⚠️ Convention ASSUMÉE, pas mesurée : la porte de spread de l'or n'a refusé
# qu'entre 20 h et 05 h UTC sur les données du 08-09/09. On la déclare ici pour
# que le message puisse dire « en journée » sans que le lecteur ait à deviner
# — et on affiche la répartition horaire complète pour qu'il puisse la réfuter.
HEURES_NUIT = {"20", "21", "22", "23", "00", "01", "02", "03", "04", "05"}

# La porte qui déciderait vraiment si l'horizon s'ouvrait sur le réel.
PORTE_SUIVANTE = "heure_spread_defavorable"


def _lignes(c: sqlite3.Connection, jour: str) -> list[tuple[str, str, str]]:
    """`(heure, destination, motif)` des signaux M15/M30 de la paire, ce jour."""
    return [
        (t[11:13], d or "?", m or "?")
        for t, d, m in c.execute(
            "SELECT created_at, destination_id, reason_code "
            "  FROM signal_rejections "
            " WHERE pair = ? AND substr(created_at,1,10) = ? "
            "   AND (details LIKE '%15min%' OR details LIKE '%30min%')",
            (PAIRE, jour),
        )
    ]


def _trades_du_jour(c: sqlite3.Connection, jour: str) -> int:
    """Trades M15/M30 réellement ouverts sur le démo — le seul chiffre qui
    prouve que la chaîne entière peut être franchie."""
    try:
        return c.execute(
            "SELECT COUNT(*) FROM personal_trades "
            " WHERE pair = ? AND destination_id = 'admin_legacy' "
            "   AND horizon IN ('15min','30min') "
            "   AND substr(created_at,1,10) = ?",
            (PAIRE, jour),
        ).fetchone()[0]
    except Exception:
        return 0


def verdict(jour_n: int, nuit_n: int, motifs_jour: dict[str, int],
            trades: int) -> tuple[str, str]:
    """`(titre, phrase)` — le sens du chiffre, pas le chiffre.

    ⛔ Séparé du reste pour être testable sans base ni réseau : c'est la seule
    partie qui peut se tromper en silence.
    """
    if jour_n == 0:
        return ("aucun signal en journée",
                "Aucun signal M15/M30 hors de la fenêtre nocturne. "
                "Ouvrir ces échelles sur le compte réel ne produirait donc "
                "RIEN de plus qu'aujourd'hui. ⚠️ Une seule séance ne fait pas "
                "un motif — il en faut plusieurs avant de conclure.")
    if trades > 0:
        return ("des trades sont passés",
                f"{trades} trade(s) M15/M30 ouvert(s) sur le démo : la chaîne "
                "entière peut être franchie. Ouvrir le réel produirait "
                "vraisemblablement des trades — c'est le cas où la question "
                "se pose vraiment.")
    bloquant = max(motifs_jour, key=motifs_jour.get) if motifs_jour else None
    if bloquant == PORTE_SUIVANTE:
        return ("bloqués par le spread, même en journée",
                f"{jour_n} signal(aux) en journée, mais {PORTE_SUIVANTE} "
                "les arrête quand même. Ouvrir l'horizon sur le réel ne "
                "servirait à rien : la porte suivante refuse.")
    return ("bloqués ailleurs",
            f"{jour_n} signal(aux) en journée, aucun trade. Le motif dominant "
            f"est {bloquant} — ce n'est PAS la porte de spread. "
            "Ouvrir l'horizon ne suffirait pas ; c'est cette porte-là qu'il "
            "faudrait examiner.")


def construire(lignes, trades: int, jour: str) -> tuple[str, str]:
    par_heure = Counter(h for h, _, _ in lignes)
    jour_n = sum(v for h, v in par_heure.items() if h not in HEURES_NUIT)
    nuit_n = sum(v for h, v in par_heure.items() if h in HEURES_NUIT)

    motifs_jour = Counter(
        m for h, d, m in lignes if h not in HEURES_NUIT and d == "admin_legacy")
    reel_horizon = sum(
        1 for _, d, m in lignes if d == "admin_live" and m == "horizon_not_allowed")

    court, phrase = verdict(jour_n, nuit_n, dict(motifs_jour), trades)

    corps = [
        f"BUT — décider si ouvrir les échelles M15/M30 sur le compte "
        f"réel produirait des trades sur {PAIRE}.",
        "",
        f"Signaux M15/M30 du {jour} : {jour_n + nuit_n}  "
        f"(journée 06-19h UTC : {jour_n} · nuit 20-05h : {nuit_n})",
    ]
    if par_heure:
        detail = " ".join(f"{h}h:{par_heure[h]}" for h in sorted(par_heure))
        corps.append(detail)
    corps.append("")

    if motifs_jour:
        corps.append("Ce qui les arrête EN JOURNÉE, sur le démo "
                     "(seul compte qui sert ces échelles) :")
        for m, n in motifs_jour.most_common(6):
            corps.append(f"  • {m} — {n}")
    else:
        corps.append("Aucun refus en journée sur le démo.")
    corps += [
        "",
        f"Trades M15/M30 réellement ouverts sur le démo : {trades}",
        f"Signaux morts a horizon_not_allowed sur le réel : {reel_horizon}",
        "",
        f"VERDICT — {court}. {phrase}",
        "",
        "⚠️ Le démo n'est pas le réel : il est PLUS filtré. Ce chiffre est une "
        "borne basse de ce que l'ouverture libérerait, pas une prédiction.",
    ]
    return (f"🔬 Échelles M15/M30 sur l'or — {court}", "\n".join(corps))


def _poster(titre: str, corps: str) -> int:
    jeton = os.environ.get("NOTIFY_TOKEN",
                           "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg")
    # ⛔ `channel=ic_markets` et non `infra`. La convention du 06/09 envoie sur
    # `infra` une mesure qui COMPARE des courtiers — elle n'appartient au fil
    # d'aucun compte. Ici c'est le cas complémentaire : la décision porte sur
    # UN compte, `admin_live`. Et le 09/09 a montré trois fois qu'un fait qui
    # engage l'argent réel se noie sur `infra`.
    url = ("https://app.scalping-radar.online/api/admin/notify-infra-telegram"
           f"?token={jeton}&channel=ic_markets")
    charge = json.dumps({"title": titre, "body": corps,
                         "dedup_key": "echelles_or_journee",
                         "cooldown_seconds": 3600}).encode()
    if os.environ.get("DRY_RUN") == "1":
        print(f"[DRY_RUN] {titre}\n{corps}\n")
        return 0
    try:
        req = urllib.request.Request(
            url, data=charge, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            print(f"bilan poste, HTTP {r.status}")
        return 0
    except Exception as e:  # noqa: BLE001
        # ⛔ Un bilan qui n'arrive pas est un bilan qui n'existe pas. On le DIT,
        # et on recrache le corps pour qu'il survive dans le log.
        print(f"⚠️ ENVOI DU BILAN ECHOUE : {e}")
        print(f"{titre}\n{corps}")
        return 1


def main() -> int:
    jour = os.environ.get(
        "ECHELLES_OR_JOUR",
        datetime.now(timezone.utc).date().isoformat())
    try:
        with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as c:
            lignes = _lignes(c, jour)
            trades = _trades_du_jour(c, jour)
    except Exception as e:  # noqa: BLE001
        return _poster("⚠️ Échelles M15/M30 sur l'or : mesure impossible",
                       f"La base est illisible ({e}). "
                       "Le verdict reste SANS RÉPONSE, et non « rien à voir ».")
    titre, corps = construire(lignes, trades, jour)
    return _poster(titre, corps)


if __name__ == "__main__":
    sys.exit(main())
