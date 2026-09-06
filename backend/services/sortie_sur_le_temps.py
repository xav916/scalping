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
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


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
