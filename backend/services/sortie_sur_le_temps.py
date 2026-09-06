"""Sortie sur le temps : fermer une position ouverte depuis plus de N heures.

Demandé le 2026-09-06 après la mesure du contrefactuel de sortie : sur
`[RÉEL · IC_MARKETS]`, 21 clôtures manuelles ont battu leurs propres niveaux de
**+0,66 R** (t = 2,27). L'hypothèse : reproduire cet effet par une règle.

⛔ **DEUX MESURES POINTENT EN SENS OPPOSÉS, et la plus lourde dit NON.**

```
porte de durée 16 h, contrefactuel du 13/08   n=5690   Δ=−0,151 R   t=−6,83
sorties manuelles rejouées, 06/09             n=  21   Δ=+0,660 R   t=+2,27
```

⚠️ Et la note du 13/08 décrit le piège à l'identique : le live suggérait alors
+215 € d'économie sur l'or, le backtest a **inversé** le verdict — l'or était
le pire cas (−0,42 R). Un petit échantillon vivant qui propose une règle qu'un
grand échantillon réfute.

⚠️ La mesure du 06/09 va dans le même sens : les trades qui auraient fini au
stop ont été coupés à **2,6 h** de médiane, ceux qui auraient fini à l'objectif
à **10,2 h**. La main a coupé les perdants PLUS TÔT que les gagnants — un
couperet à N heures ne distingue pas, il coupe les deux.

🔑 **Ce module est donc livré DÉSARMÉ**, et son défaut est le démo. Il existe
pour être MESURÉ, pas pour être cru : en mode observation il journalise ce
qu'il aurait fermé, sans rien fermer. C'est le seul usage que les mesures
existantes autorisent.

Réglages (tous à défaut sûr) ::

    SORTIE_TEMPS_ENABLED=false          # rien ne part tant que c'est faux
    SORTIE_TEMPS_DESTINATIONS=admin_legacy   # le DÉMO, jamais le réel par défaut
    SORTIE_TEMPS_HEURES=16
    SORTIE_TEMPS_OBSERVER=true          # journalise sans fermer
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DB = Path("/app/data/trades.db") if Path("/app").exists() else Path("trades.db")


def _conn():
    c = sqlite3.connect(str(_DB), isolation_level=None)
    c.row_factory = sqlite3.Row
    return c


def init_schema() -> None:
    """Une observation par (ticket, passage) — la premiere seule compte.

    ⛔ La cle est le TICKET, pas la ligne : la regle repasse toutes les 30 min
    et reverrait la meme position eligible indefiniment. Sans unicite, une
    position tenue trois jours pesserait 144 fois dans la mesure.
    """
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS observations_sortie_temps (
                ticket INTEGER PRIMARY KEY,
                destination_id TEXT NOT NULL,
                symbol TEXT,
                observe_a TEXT NOT NULL,
                seuil_h REAL NOT NULL,
                age_h REAL,
                prix_a_l_observation REAL,
                entry_price REAL,
                sl REAL,
                direction TEXT,
                r_si_coupe REAL,        -- R que la regle aurait obtenu
                r_reel REAL,            -- R finalement obtenu, a la cloture
                resolu_a TEXT
            );
        """)


def r_au_prix(entry, prix, sl, achat) -> float | None:
    """R obtenu en sortant a ``prix``. ``None`` si le risque est indefini."""
    try:
        entry, prix, sl = float(entry), float(prix), float(sl)
    except (TypeError, ValueError):
        return None
    d = abs(entry - sl)
    if d <= 0 or entry <= 0:
        return None
    return (prix - entry) * (1.0 if achat else -1.0) / d


def enregistrer_observation(position: dict, destination_id: str, cfg: dict,
                            age_h: float | None) -> bool:
    """Fige ce que la regle AURAIT obtenu, au prix de l'instant.

    🔑 On enregistre le PRIX au moment ou la regle aurait coupe — pas une
    reconstruction posterieure. C'est exact, et cela ne coute aucun appel
    supplementaire : `/positions` porte deja le prix courant.

    ⛔ `INSERT OR IGNORE` sur le ticket : la premiere observation seule compte.
    """
    init_schema()
    achat = str(position.get("type") or position.get("side") or "").lower().startswith(("b", "l"))
    prix = position.get("price_current") or position.get("price")
    entry = position.get("price_open") or position.get("price_entry") or position.get("entry_price")
    sl = position.get("sl")
    r = r_au_prix(entry, prix, sl, achat)
    try:
        with _conn() as c:
            cur = c.execute(
                """INSERT OR IGNORE INTO observations_sortie_temps
                   (ticket, destination_id, symbol, observe_a, seuil_h, age_h,
                    prix_a_l_observation, entry_price, sl, direction, r_si_coupe)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (position.get("ticket"), destination_id, position.get("symbol"),
                 datetime.now(timezone.utc).isoformat(), cfg["heures"], age_h,
                 prix, entry, sl, position.get("type") or position.get("side"), r))
            return cur.rowcount > 0
    except Exception as e:  # noqa: BLE001
        # ⛔ Une observation qui ne s'ecrit pas ne doit pas empecher le passage :
        # la regle OBSERVE, elle ne protege rien. Mais on le dit.
        logger.warning("sortie_temps: observation non enregistree : %s", e)
        return False


def resoudre_observations(trades_fermes=None) -> int:
    """Renseigne le R REELLEMENT obtenu, une fois la position fermee.

    ``trades_fermes`` : ``{ticket: (exit_price,)}``. Sans argument, on lit
    `personal_trades`.
    """
    init_schema()
    if trades_fermes is None:
        trades_fermes = {}
        try:
            with _conn() as c:
                # ⛔ La colonne s'appelle `mt5_ticket`, PAS `ticket`. Avec le
                # mauvais nom la requete leve, l'exception est avalee et la
                # resolution rend 0 — une jointure vide qui ressemble a « rien
                # a resoudre ». Verrouille par un test.
                for r in c.execute(
                        "SELECT mt5_ticket, exit_price FROM personal_trades "
                        "WHERE mt5_ticket IS NOT NULL AND exit_price IS NOT NULL"):
                    try:
                        trades_fermes[int(r["mt5_ticket"])] = (r["exit_price"],)
                    except (TypeError, ValueError):
                        continue
        except Exception as e:  # noqa: BLE001
            logger.warning("sortie_temps: clotures illisibles : %s", e)
            return 0

    n = 0
    with _conn() as c:
        lignes = [dict(r) for r in c.execute(
            "SELECT * FROM observations_sortie_temps WHERE r_reel IS NULL")]
    for l in lignes:
        info = trades_fermes.get(l["ticket"])
        if not info:
            continue          # toujours ouverte : rien a conclure, et on le laisse
        achat = str(l["direction"] or "").lower().startswith(("b", "l"))
        r = r_au_prix(l["entry_price"], info[0], l["sl"], achat)
        if r is None:
            continue
        with _conn() as c:
            c.execute("UPDATE observations_sortie_temps SET r_reel=?, resolu_a=? "
                      "WHERE ticket=?",
                      (r, datetime.now(timezone.utc).isoformat(), l["ticket"]))
        n += 1
    return n


def bilan_apparie(destination_id: str = "admin_legacy") -> dict:
    """Comparaison APPARIEE : le meme trade, avec et sans la regle.

    🔑 C'est tout l'interet de l'observation sur le demo : chaque trade fournit
    les DEUX resultats. La variance entre trades s'annule, et la significativite
    s'atteint avec bien moins d'observations que deux periodes separees.
    """
    init_schema()
    with _conn() as c:
        L = [dict(r) for r in c.execute(
            "SELECT * FROM observations_sortie_temps WHERE destination_id=? "
            "AND r_reel IS NOT NULL AND r_si_coupe IS NOT NULL", (destination_id,))]
    if not L:
        # ⛔ « Pas encore de verdict » n'est pas « pas d'ecart ».
        return {"n": 0, "verdict": "aucune observation resolue — question ouverte"}
    import statistics
    ecarts = [l["r_si_coupe"] - l["r_reel"] for l in L]
    m = statistics.mean(ecarts)
    sortie = {
        "n": len(L),
        "r_si_coupe_moyen": round(statistics.mean(l["r_si_coupe"] for l in L), 3),
        "r_reel_moyen": round(statistics.mean(l["r_reel"] for l in L), 3),
        "ecart_moyen": round(m, 3),
    }
    if len(L) > 2:
        import math
        se = statistics.stdev(ecarts) / math.sqrt(len(L))
        sortie["t"] = round(m / se, 2) if se else None
        sortie["ic95"] = [round(m - 1.96 * se, 3), round(m + 1.96 * se, 3)]
        # ⚠️ Le seuil de preuve n'est pas la significativite : c'est la mesure
        # DEJA faite, n=5690 t=-6,83 contre la porte de duree.
        sortie["verdict"] = (
            "couper aurait MIEUX fait" if sortie.get("t") and sortie["t"] > 2
            else "couper aurait NUI" if sortie.get("t") and sortie["t"] < -2
            else "indistinguable du hasard")
    return sortie



def _bool(nom: str, defaut: str = "false") -> bool:
    return os.getenv(nom, defaut).strip().lower() in ("1", "true", "yes", "on")


def reglages() -> dict:
    """Lus à CHAQUE appel — un réglage figé à l'import ne se désarme pas sans
    redémarrage, et un mécanisme de sortie doit pouvoir s'arrêter vite."""
    return {
        "actif": _bool("SORTIE_TEMPS_ENABLED"),
        "observer": _bool("SORTIE_TEMPS_OBSERVER", "true"),
        "heures": float(os.getenv("SORTIE_TEMPS_HEURES", "16") or 16),
        "destinations": frozenset(
            x.strip() for x in os.getenv(
                "SORTIE_TEMPS_DESTINATIONS", "admin_legacy").split(",") if x.strip()),
    }


def _age_heures(ouverture, maintenant=None) -> float | None:
    """⛔ ``None`` si l'ouverture est indatable — jamais 0, qui se lirait
    « vient d'ouvrir » et protégerait la position pour la mauvaise raison."""
    if not ouverture:
        return None
    try:
        t = datetime.fromisoformat(str(ouverture).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    maintenant = maintenant or datetime.now(timezone.utc)
    return (maintenant - t).total_seconds() / 3600.0


def eligible(position: dict, destination_id: str, cfg: dict | None = None,
             maintenant=None) -> tuple[bool, str]:
    """Cette position doit-elle être fermée par la règle de durée ?

    Quatre verrous, chacun suffisant pour refuser :

    1. la règle est désarmée (`SORTIE_TEMPS_ENABLED`) ;
    2. la destination n'est pas déclarée — ⛔ **le réel n'y est pas par
       défaut**, conformément à la stratégie du 06/09 : stops manuels sur
       l'argent réel tant que l'automatique n'est pas gagnant sur le démo ;
    3. l'ouverture est **indatable** — on ne coupe pas une position dont on ne
       sait pas l'âge. C'est le sens sur lequel se tromper : côté MT5, un
       décalage d'heure serveur faisait passer des positions pour plus vieilles
       qu'elles n'étaient ;
    4. l'âge est sous le seuil.
    """
    cfg = cfg or reglages()
    if not cfg["actif"]:
        return False, "règle désarmée (SORTIE_TEMPS_ENABLED)"
    if destination_id not in cfg["destinations"]:
        return False, f"destination hors périmètre ({destination_id})"
    age = _age_heures(position.get("fill_time") or position.get("time")
                      or position.get("opened_at"), maintenant)
    if age is None:
        return False, "ouverture indatable — âge inconnu"
    if age < cfg["heures"]:
        return False, f"âge {age:.1f} h < seuil {cfg['heures']:.0f} h"
    return True, f"âge {age:.1f} h ≥ seuil {cfg['heures']:.0f} h"


def passer(positions, destination_id: str, fermer=None, cfg: dict | None = None,
           maintenant=None) -> dict:
    """Un passage de la règle. Rend ce qui a été fermé, observé, et écarté.

    ⚠️ En mode **observation** (`SORTIE_TEMPS_OBSERVER=true`, le défaut), rien
    n'est fermé : les positions éligibles sont seulement JOURNALISÉES. C'est ce
    qui permet de mesurer la règle sans la subir — et vu que la mesure de
    référence donne Δ=−0,151 R sur n=5690, c'est le seul mode que les données
    autorisent aujourd'hui.
    """
    cfg = cfg or reglages()
    rapport = {"fermees": [], "observees": [], "ignorees": 0,
               "mode": "observation" if cfg["observer"] else "ACTIF",
               "seuil_h": cfg["heures"], "actif": cfg["actif"]}
    for p in positions or []:
        ok, motif = eligible(p, destination_id, cfg, maintenant)
        if not ok:
            rapport["ignorees"] += 1
            continue
        ligne = {"symbol": p.get("symbol"), "ticket": p.get("ticket"),
                 "motif": motif}
        if cfg["observer"] or fermer is None:
            # 🔑 On fige le PRIX de l'instant : c'est celui que la regle aurait
            # obtenu. Le reconstruire plus tard couterait des bougies et serait
            # moins exact.
            age = _age_heures(p.get("fill_time") or p.get("time")
                              or p.get("opened_at"), maintenant)
            ligne["neuve"] = enregistrer_observation(p, destination_id, cfg, age)
            logger.info("[SORTIE TEMPS] observation : %s aurait ete fermee — %s",
                        ligne["symbol"], motif)
            rapport["observees"].append(ligne)
            continue
        try:
            res = fermer(p)
            ligne["resultat"] = res
            rapport["fermees"].append(ligne)
        except Exception as e:  # noqa: BLE001
            # ⛔ Une fermeture qui échoue ne se compte pas comme faite : la
            # position reste ouverte, et le dire est le minimum.
            ligne["erreur"] = str(e)
            rapport["fermees"].append(ligne)
            logger.error("[SORTIE TEMPS] fermeture ECHOUEE %s : %s",
                         ligne["symbol"], e)
    return rapport
