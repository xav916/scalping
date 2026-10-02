"""Verse les setups d'une source tierce dans le journal fantome. N'execute RIEN.

Demande de Xavier le 2026-10-02 : brancher un diffuseur MQL5 sur l'outil, et
<< c'est plus un branchement INFORMATIF qu'un branchement qui va produire des
trades >>.

## 🔑 L'appareil existait, personne ne l'avait alimente

`shadow_setups` compte **43 400 lignes et 26 673 issues resolues** depuis le
18/05. Un setup y est enregistre, `shadow_reconciliation` rejoue les bougies de
5 min en avant, s'arrete des qu'un TP ou un SL est touche, et inscrit
TP1 / SL / TIMEOUT avec MFE et MAE. **Aucun ordre ne part jamais.**

Deux proprietes du schema, verifiees avant d'ecrire une ligne :

1. La reconciliation est **agnostique du systeme** (`WHERE outcome IS NULL`,
   aucun filtre de provenance) ⇒ toute ligne versee ici obtient son issue
   gratuitement, par le job qui tourne deja.
2. `UNIQUE (system_id, bar_timestamp)` ⇒ l'idempotence est native, a condition
   que le `system_id` encode la paire ET le sens, comme le fait `shadow_v1`.

## ⛔ Ce module n'execute rien

Le chemin d'ingestion existant — `external_signals` + `POST /api/signals/external`
— **dispatche vers le demo** : il execute, derriere les 27 portes. C'est le bon
outil pour juger une SELECTION en conditions reelles ; ce n'en est pas un pour
observer. Ici, ni `send_setup`, ni `resolve_destinations`, ni aucune destination.
Un test le prouve par le comportement, pas en relisant ce fichier.

## ⛔ Et il ne DERIVE rien

`take_profit` est obligatoire. La reconciliation en a besoin pour conclure TP1,
et deriver une cible — un 1,8 R par exemple — fabriquerait exactement ce qu'on
veut mesurer : **la cible de la source**. Une source qui ne publie pas sa cible
n'est pas observable, et on le dit au lieu de combler.

⚠️ Les formules derivees et les constantes de dimensionnement sont celles de
`shadow_v1`. Un second jeu de chiffres rendrait la source incomparable avec nos
propres cellules — ce qui est tout l'objet de la mesure.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

PREFIXE = "OBS"

OK = "ok"
CAUSE_FORME = "forme"
CAUSE_DOUBLON = "doublon"

_SENS = ("buy", "sell")
_OBLIGATOIRES = ("source", "pair", "direction", "timeframe", "bar_timestamp",
                 "entry_price", "stop_loss", "take_profit")
_NUMERIQUES = ("entry_price", "stop_loss", "take_profit")

# Le motif inscrit en colonne `pattern` : NOT NULL, et il ne faut pas pretendre
# connaitre la figure qu'a vue la source. On nomme la provenance, pas une forme.
_MOTIF = "observation_externe"


def _db_path() -> str:
    from backend.services.trade_log_service import _DB_PATH
    return str(_DB_PATH)


def system_id_for(source: str, pair: str, direction: str) -> str:
    """`OBS_<SOURCE>_<PAIRE>_<sens>`, sur le modele de `shadow_v1.system_id_for`.

    ⛔ La paire ET le sens doivent y figurer : `UNIQUE (system_id,
    bar_timestamp)` ferait sinon se manger deux trades d'une meme source au
    meme horodatage sur deux paires differentes.
    """
    propre = re.sub(r"[^A-Z0-9]+", "_", str(source).upper()).strip("_")
    return f"{PREFIXE}_{propre}_{str(pair).replace('/', '')}_{direction}"


def _en_date(v) -> datetime | None:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _valider(charge: dict) -> tuple[dict | None, str]:
    """`(observation propre, detail)` — `None` si la charge est refusee.

    Le detail NOMME le champ fautif : une source qui ne sait pas pourquoi elle
    est refusee croit qu'on l'ignore, et de notre cote << elle n'emet rien >>
    deviendrait indiscernable de << on jette tout >>.
    """
    manquants = [c for c in _OBLIGATOIRES
                 if charge.get(c) is None or charge.get(c) == ""]
    if manquants:
        return None, "champ(s) manquant(s) : " + ", ".join(manquants)

    sens = str(charge["direction"]).strip().lower()
    if sens not in _SENS:
        return None, f"sens inconnu : {charge['direction']!r} (attendu buy/sell)"

    nombres = {}
    for c in _NUMERIQUES:
        try:
            nombres[c] = float(charge[c])
        except (TypeError, ValueError):
            return None, f"nombre illisible pour {c} : {charge[c]!r}"

    entree, stop, cible = nombres["entry_price"], nombres["stop_loss"], nombres["take_profit"]
    if entree <= 0 or stop <= 0 or cible <= 0:
        return None, "entry_price, stop_loss et take_profit doivent etre > 0"

    risque = abs(entree - stop)
    if risque <= 0:
        return None, "risque nul : stop_loss egal a entry_price"

    # ⛔ Un stop du mauvais cote n'est pas un stop : un achat protege SOUS
    # l'entree, une vente AU-DESSUS. Accepter l'inverse enregistrerait un
    # trade dont la reconciliation conclurait n'importe quoi.
    if sens == "buy" and stop >= entree:
        return None, "achat : le stop doit etre SOUS l'entree"
    if sens == "sell" and stop <= entree:
        return None, "vente : le stop doit etre AU-DESSUS de l'entree"

    quand = _en_date(charge["bar_timestamp"])
    if quand is None:
        return None, f"bar_timestamp illisible : {charge['bar_timestamp']!r}"

    return {
        "system_id": system_id_for(charge["source"], charge["pair"], sens),
        "pair": str(charge["pair"]),
        "timeframe": str(charge["timeframe"]),
        "direction": sens,
        "bar_timestamp": quand.isoformat(),
        "entry_price": entree,
        "stop_loss": stop,
        "take_profit_1": cible,
        "take_profit_2": (float(charge["take_profit_2"])
                          if charge.get("take_profit_2") not in (None, "")
                          else None),
        "risk_pct": risque / entree,
        "rr": abs(cible - entree) / risque,
    }, ""


def verser(charge: dict) -> tuple[bool, str, str]:
    """`(accepte, cause, detail)`. Ecrit dans `shadow_setups`, rien d'autre.

    `accepte` vaut True aussi sur un DOUBLON : un rejeu n'est pas un echec, et
    le marquer comme tel apprendrait a la source a reessayer — soit exactement
    ce que l'idempotence evite.
    """
    propre, detail = _valider(charge or {})
    if propre is None:
        logger.info("observation_externe: REFUS (%s) — %s", CAUSE_FORME, detail)
        return False, CAUSE_FORME, detail

    from backend.services.shadow_v1 import (DEFAULT_CAPITAL_EUR,
                                            DEFAULT_RISK_PCT)
    perte_max = DEFAULT_CAPITAL_EUR * DEFAULT_RISK_PCT
    position = perte_max / propre["risk_pct"]

    try:
        with sqlite3.connect(_db_path()) as c:
            c.execute(
                """
                INSERT INTO shadow_setups (
                    cycle_at, bar_timestamp, system_id, pair, timeframe,
                    direction, pattern, entry_price, stop_loss,
                    take_profit_1, take_profit_2, risk_pct, rr,
                    sizing_capital_eur, sizing_risk_pct,
                    sizing_position_eur, sizing_max_loss_eur
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (datetime.now(timezone.utc).isoformat(),
                 propre["bar_timestamp"], propre["system_id"], propre["pair"],
                 propre["timeframe"], propre["direction"], _MOTIF,
                 propre["entry_price"], propre["stop_loss"],
                 propre["take_profit_1"], propre["take_profit_2"],
                 propre["risk_pct"], propre["rr"],
                 DEFAULT_CAPITAL_EUR, DEFAULT_RISK_PCT,
                 position, perte_max),
            )
    except sqlite3.IntegrityError:
        # ⚠️ Collision UNIQUE : ce trade est deja verse. Comportement VOULU.
        logger.debug("observation_externe: doublon %s @ %s",
                     propre["system_id"], propre["bar_timestamp"])
        return True, CAUSE_DOUBLON, "deja verse"

    logger.info("observation_externe: verse %s @ %s (rr %.2f, risque %.3f%%)",
                propre["system_id"], propre["bar_timestamp"],
                propre["rr"], propre["risk_pct"] * 100)
    return True, OK, ""
