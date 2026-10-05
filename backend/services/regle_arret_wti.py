"""La regle d'arret du WTI : 10 ordres OU -30 €, le premier atteint.

## ⛔ POURQUOI ELLE EXISTE

Le motif d'admission signe par Xavier le 2026-10-03, a la reouverture du WTI
sur l'argent reel, se termine par :

    ⛔ AUCUNE regle d arret n est posee.

Elle etait encore vraie le 2026-10-05 au soir. Le WTI tradait sans limite
propre sur un compte de 608 €, avec pour seul garde-fou le plafond journalier
global.

🔑 Cette regle transforme un **pari ouvert** en **experience bornee**. Elle ne
pretend pas que le WTI va gagner — elle decide d'avance combien on accepte de
payer pour le savoir.

## Ce que les mesures disent du WTI

    banc pre-enregistre : 493 cellules sur 97 886 bougies, 0 retenue
    le seul candidat    : tue par la phase, puis +0,48 -> -0,49 hors echantillon
    cout a 5 min        : 8 % du risque par trade
    historique reel     : -20,6 % puis -28,1 % sur 30 trades (pf 0,72 puis 0,63)

## ⚠️ LE PIEGE DU P&L

`sum(pnl)` **ignore les NULL en silence**. Sur ce depot, l'argent n'est verifie
chez le courtier que sur 36,7 % des trades : un total tire des 100 % serait un
total d'air.

⇒ La somme peut donc **sous-estimer** les pertes et declencher TROP TARD. C'est
pourquoi le compteur d'ordres est le declencheur principal : il ne depend
d'aucune valeur manquante. La couverture est mesuree et annoncee dans le motif.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

PAIRE = "WTI/USD"
DESTINATION = "admin_live"

# ⚠️ Reglables sans redeploiement : une experience bornee doit pouvoir voir ses
# bornes bouger quand Xavier le decide, pas quand une image se reconstruit.
MAX_ORDRES = int(os.getenv("WTI_ARRET_MAX_ORDRES", "10"))
MAX_PERTE_EUR = float(os.getenv("WTI_ARRET_MAX_PERTE_EUR", "-30"))

# La reouverture au reel, ligne 383 de `pair_admission_state`.
DEPUIS = os.getenv("WTI_ARRET_DEPUIS", "2026-10-03T09:47:53+00:00")


def releve(db, depuis: str = DEPUIS) -> dict | None:
    """Compte les ordres et somme l'argent VERIFIE depuis la reouverture.

    ⛔ Rend `None` si la base est injoignable. Trois etats, jamais deux :
    « je n'ai pas pu regarder » n'est pas « rien a signaler ».
    """
    try:
        with sqlite3.connect(f"file:{Path(db)}?mode=ro", uri=True) as c:
            n, somme, sans = c.execute(
                "SELECT COUNT(*), "
                "       COALESCE(SUM(CASE WHEN pnl IS NOT NULL THEN pnl END), 0), "
                "       SUM(CASE WHEN status = 'CLOSED' AND pnl IS NULL "
                "                THEN 1 ELSE 0 END) "
                "FROM personal_trades "
                "WHERE pair = ? AND destination_id = ? AND created_at >= ?",
                (PAIRE, DESTINATION, depuis)).fetchone()
    except Exception as e:  # noqa: BLE001
        logger.warning("regle_arret_wti: base illisible (%s)", e)
        return None
    n = int(n or 0)
    sans = int(sans or 0)
    return {"ordres": n, "pnl": float(somme or 0.0), "sans_pnl": sans,
            "couverture": 0.0 if n == 0 else (n - sans) / n}


def verdict(m: dict | None) -> dict:
    """Applique les deux bornes. Le compteur d'ordres passe EN PREMIER.

    ⛔ Un releve absent n'arrete RIEN : agir sur une mesure qu'on n'a pas
    fermerait une paire pour une panne de lecture.
    """
    if not m:
        return {"arreter": False,
                "motif": "relevé indisponible — on n'arrête pas sur une "
                         "mesure qu'on n'a pas"}

    couv = (f" (somme portant sur {m['couverture'] * 100:.0f} % des trades, "
            f"{m['sans_pnl']} sans montant vérifié)"
            if m.get("sans_pnl") else "")

    if m["ordres"] >= MAX_ORDRES:
        return {"arreter": True,
                "motif": f"{m['ordres']} ordres atteints sur un budget de "
                         f"{MAX_ORDRES}. P&L mesuré {m['pnl']:+.2f} €{couv}."}
    if m["pnl"] <= MAX_PERTE_EUR:
        return {"arreter": True,
                "motif": f"P&L {m['pnl']:+.2f} € sous la borne de "
                         f"{MAX_PERTE_EUR:+.0f} € en {m['ordres']} ordres{couv}."}
    return {"arreter": False,
            "motif": f"{m['ordres']}/{MAX_ORDRES} ordres, P&L "
                     f"{m['pnl']:+.2f} € / {MAX_PERTE_EUR:+.0f} €{couv}."}
