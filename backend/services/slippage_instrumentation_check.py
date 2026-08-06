"""Surveille que la mesure du coût d'exécution enregistre réellement quelque chose.

Pourquoi ce contrôle existe : `slippage_pips` et `fill_price` étaient présents
au schéma et **vides sur 1581/1581 trades réels** pendant onze mois. Le calcul
existait de bout en bout ; c'est la référence de comparaison qui manquait, et
rien n'a jamais signalé que la colonne restait nulle. Corrigé le 2026-08-06
(`fd369ab`) — ce module est là pour que le silence ne puisse pas se réinstaller.

Il ne surveille PAS le trading. Il surveille l'instrument de mesure.

Trois pièges qu'il évite volontairement :

- **Ne rien conclure sur trop peu de trades.** Sous `MIN_SAMPLE`, le verdict est
  `INSUFFISANT` et aucune alerte ne part : l'absence de mesure n'est pas
  distinguable de l'absence de trades.
- **Ne compter que les trades postérieurs au correctif.** Les anciens sont vides
  par construction et le resteront — le prix demandé n'a jamais été écrit.
- **Ne pas confondre « pas de glissement » et « glissement non observable ».**
  Quand le bridge se replie sur le prix demandé (`fill_source == "requested"`),
  il renseigne `fill_price` mais pas `slippage_pips`. Une couverture partielle de
  `slippage_pips` est donc normale ; une couverture nulle de `fill_price` ne
  l'est jamais.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone

# Instant du redéploiement du bridge portant la mesure. Les trades antérieurs
# sont vides par construction et doivent être exclus, sinon le contrôle se
# déclencherait à vie sur de l'historique irrécupérable.
DEFAULT_SINCE = "2026-08-06T09:21:00+00:00"

# En dessous, on ne conclut pas. 20 trades suffisent à distinguer « la colonne
# ne se remplit jamais » de « il n'y a pas encore eu de trade ».
DEFAULT_MIN_SAMPLE = 20

# Sous ce taux de renseignement de `fill_price`, quelque chose cloche même si
# ce n'est pas totalement mort (bridge partiellement déployé, une destination
# à jour et pas l'autre).
DEFAULT_MIN_COVERAGE = 0.5


def _since() -> datetime:
    raw = os.getenv("SLIPPAGE_CHECK_SINCE", DEFAULT_SINCE)
    return _parse_dt(raw) or _parse_dt(DEFAULT_SINCE)


def _parse_dt(raw) -> datetime | None:
    """Tolère les formats rencontrés en base (suffixe Z, naïf, décalage)."""
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d


def _db_path() -> str:
    from backend.services.trade_log_service import _DB_PATH
    return str(_DB_PATH)


def run() -> dict:
    """Rend le rapport de couverture. Ne lève jamais : un contrôle qui plante
    est un contrôle muet, et c'est précisément le mode de défaillance visé."""
    seuil = _since()
    try:
        mini = int(os.getenv("SLIPPAGE_CHECK_MIN_SAMPLE", DEFAULT_MIN_SAMPLE))
    except ValueError:
        mini = DEFAULT_MIN_SAMPLE
    try:
        couv_min = float(os.getenv("SLIPPAGE_CHECK_MIN_COVERAGE", DEFAULT_MIN_COVERAGE))
    except ValueError:
        couv_min = DEFAULT_MIN_COVERAGE

    rapport = {
        "depuis": seuil.isoformat(),
        "echantillon_minimum": mini,
        "trades_depuis": 0,
        "avec_fill_price": 0,
        "avec_slippage": 0,
        "couverture_fill": 0.0,
        "couverture_slippage": 0.0,
        "slippage_moyen_pips": None,
        "verdict": "INSUFFISANT",
        "alerte": False,
        "message": "",
    }

    try:
        with sqlite3.connect(_db_path()) as c:
            lignes = c.execute(
                "SELECT created_at, fill_price, slippage_pips "
                "FROM personal_trades WHERE is_auto = 1"
            ).fetchall()
    except Exception as e:
        rapport["verdict"] = "ERREUR"
        rapport["alerte"] = True
        rapport["message"] = f"Lecture de personal_trades impossible : {e}"
        return rapport

    recents = [r for r in lignes if (_parse_dt(r[0]) or seuil) >= seuil]
    n = len(recents)
    rapport["trades_depuis"] = n
    if n == 0:
        rapport["message"] = "Aucun trade automatique depuis le correctif — rien à conclure."
        return rapport

    fills = [r[1] for r in recents if r[1] is not None]
    slips = [r[2] for r in recents if r[2] is not None]
    rapport["avec_fill_price"] = len(fills)
    rapport["avec_slippage"] = len(slips)
    rapport["couverture_fill"] = round(len(fills) / n, 3)
    rapport["couverture_slippage"] = round(len(slips) / n, 3)
    if slips:
        rapport["slippage_moyen_pips"] = round(sum(slips) / len(slips), 2)

    if n < mini:
        rapport["message"] = (
            f"{n} trade(s) depuis le correctif, seuil de décision à {mini} — "
            f"trop tôt pour conclure."
        )
        return rapport

    if not fills:
        rapport["verdict"] = "MORTE"
        rapport["alerte"] = True
        rapport["message"] = (
            f"{n} trades depuis le correctif et **aucun** `fill_price` enregistré. "
            f"La mesure du coût d'exécution ne fonctionne pas. À vérifier : le bridge "
            f"tourne-t-il bien la version déployée (colonnes `entry_requested`, "
            f"`fill_price`, `fill_source` dans /audit) ?"
        )
    elif rapport["couverture_fill"] < couv_min:
        rapport["verdict"] = "PARTIELLE"
        rapport["alerte"] = True
        rapport["message"] = (
            f"`fill_price` renseigné sur {len(fills)}/{n} trades "
            f"({rapport['couverture_fill']:.0%}) — sous le seuil de {couv_min:.0%}. "
            f"Probablement une destination à jour et pas l'autre."
        )
    else:
        rapport["verdict"] = "OK"
        rapport["message"] = (
            f"`fill_price` sur {len(fills)}/{n} trades. Glissement mesurable sur "
            f"{len(slips)}/{n}"
            + (
                f", moyenne {rapport['slippage_moyen_pips']:+.2f} pips."
                if slips else "."
            )
        )

    return rapport


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, ensure_ascii=False, default=str))
