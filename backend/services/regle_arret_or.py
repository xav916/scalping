"""La regle d'arret de l'or : une experience BORNEE, qui ALERTE sans couper.

## POURQUOI ELLE EXISTE

Le 2026-10-01, Xavier a ouvert **tous les horizons de l'or** sur l'argent reel
(`dc3c067`), contre la mesure du jour : le laboratoire avait rendu
**0 retenue sur 232 cellules**, R negatif aux quatre echelles. Le motif de
cette ouverture se terminait, comme celui du WTI, par :

    AUCUNE regle d arret n est posee.

C'etait encore vrai une semaine plus tard, et l'or est le **premier
producteur** du compte.

Comme pour le WTI (`regle_arret_wti`), cette regle transforme un **pari
ouvert** en **experience bornee** : elle decide d'avance combien on accepte de
payer pour savoir.

## MAIS ELLE N'ARRETE PAS L'OR -- ET C'EST VOULU

Le WTI n'avait aucun avantage a la main : le couper ne coutait rien. L'or, si.
Mesure au 2026-10-07 18h58 UTC, sur les DEUX fenetres possibles -- elles disent
la meme chose, c'est ce qui rend le constat solide :

    DEPUIS dc3c067 (16h35 UTC le 01/10) -- la fenetre que la regle applique
        21 ordres | automatique  -16,78 EUR (16 fermetures)
                  | a la main    +39,69 EUR ( 4 fermetures)

    DEPUIS 00h00 le 01/10 -- la journee entiere, plus large
        25 ordres | automatique  -22,25 EUR (18 fermetures, 7 gagnantes)
                  | a la main    +72,34 EUR ( 6 fermetures, 6 gagnantes)

La main ne peut fermer que ce que l'algorithme a **ouvert**. Passer l'or en
`OBSERVED` supprimerait donc les **deux** : la perte du code ET le gain de la
main. Un arret automatique ferait ici plus de degats que le defaut qu'il
corrige.

=> Le veilleur **alerte et chiffre**, la decision reste a Xavier. Fermer demande
le drapeau explicite `--fermer`.

## POURQUOI LES DEUX COMPTEURS NE PORTENT PAS SUR LA MEME CHOSE

- **Le budget d'ORDRES compte TOUT.** Chaque ordre, quelle que soit sa sortie,
  est une decision d'**ouverture** de l'algorithme. C'est bien lui qu'on eprouve.
- **La borne de PERTE ne compte que l'AUTOMATIQUE.** Les gains de la main ne
  temoignent pas du code : les mettre dans la somme masquerait ses pertes.
  Sur la journee entiere, le total (+50,09 EUR) est positif alors que
  l'automatique est a -22,25 EUR ; sur la fenetre de la regle, +22,91 EUR de
  total contre -16,78 EUR d'automatique. Une borne sur le total ne tomberait
  JAMAIS, dans les deux cas.

## LE PIEGE DU P&L

`sum(pnl)` **ignore les NULL en silence** : sur ce depot l'argent n'est verifie
chez le courtier que sur 36,7 % des trades. La somme peut donc **sous-estimer**
les pertes et declencher trop tard. C'est pourquoi le compteur d'ordres est le
declencheur principal : il ne depend d'aucune valeur manquante. La couverture
est mesuree et annoncee.

La regle lit `close_reason`, verifie chez le courtier depuis le 2026-09-04
seulement. La fenetre de l'experience commence le 01/10 : elle est dans la zone
verifiee.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

PAIRE = "XAU/USD"
DESTINATION = "admin_live"

# Reglables sans redeploiement : une experience bornee doit pouvoir voir ses
# bornes bouger quand Xavier le decide, pas quand une image se reconstruit.
#
# 60 ordres : ~9 jours au rythme constate (25 ordres en 6 jours). En dessous,
#             une proportion de 39 % de gagnants ne se distingue pas du hasard.
# -50 EUR   : 8,4 % d'un compte de 596 EUR, juste SOUS le seuil de
#             retrogradation automatique du systeme (10 % sur 7 jours) -- elle
#             parle donc AVANT que le cliquet ne tombe.
MAX_ORDRES = int(os.getenv("OR_ARRET_MAX_ORDRES", "60"))
MAX_PERTE_EUR = float(os.getenv("OR_ARRET_MAX_PERTE_EUR", "-50"))

# `dc3c067`, « Tous les horizons sur l or » -- 2026-10-01 18:35:48 +0200.
DEPUIS = os.getenv("OR_ARRET_DEPUIS", "2026-10-01T16:35:48+00:00")

# Toute sortie qui n'est pas la main. `close_reason` NULL = position ouverte :
# elle compte dans les ordres, jamais dans l'argent.
MAIN = "MANUAL"


def releve(db, depuis: str = DEPUIS) -> dict | None:
    """Compte les ordres et separe l'argent de l'automatique de celui de la main.

    Rend `None` si la base est injoignable. Trois etats, jamais deux :
    « je n'ai pas pu regarder » n'est pas « rien a signaler ».
    """
    try:
        with sqlite3.connect(f"file:{Path(db)}?mode=ro", uri=True) as c:
            ligne = c.execute(
                "SELECT COUNT(*), "
                # l'automatique : sortie connue, et ce n'est pas la main
                "       COALESCE(SUM(CASE WHEN pnl IS NOT NULL "
                "                          AND close_reason IS NOT NULL "
                "                          AND close_reason <> ? "
                "                         THEN pnl END), 0), "
                "       SUM(CASE WHEN close_reason IS NOT NULL "
                "                 AND close_reason <> ? THEN 1 ELSE 0 END), "
                # la main, chiffree pour etre DITE, jamais pour borner
                "       COALESCE(SUM(CASE WHEN close_reason = ? "
                "                         THEN pnl END), 0), "
                "       SUM(CASE WHEN close_reason = ? THEN 1 ELSE 0 END), "
                # ce que la somme ne voit pas
                "       SUM(CASE WHEN status = 'CLOSED' AND pnl IS NULL "
                "                THEN 1 ELSE 0 END) "
                "FROM personal_trades "
                "WHERE pair = ? AND destination_id = ? AND created_at >= ?",
                (MAIN, MAIN, MAIN, MAIN, PAIRE, DESTINATION, depuis)).fetchone()
    except Exception as e:  # noqa: BLE001
        logger.warning("regle_arret_or: base illisible (%s)", e)
        return None

    n, pnl_auto, n_auto, pnl_main, n_main, sans = ligne
    n = int(n or 0)
    sans = int(sans or 0)
    return {
        "ordres": n,
        "pnl_auto": float(pnl_auto or 0.0),
        "ordres_auto": int(n_auto or 0),
        "pnl_main": float(pnl_main or 0.0),
        "ordres_main": int(n_main or 0),
        "sans_pnl": sans,
        "couverture": 0.0 if n == 0 else (n - sans) / n,
    }


def verdict(m: dict | None) -> dict:
    """Applique les deux bornes. Le compteur d'ordres passe EN PREMIER.

    Un releve absent ne conclut sur RIEN : annoncer une borne franchie sur une
    mesure qu'on n'a pas, c'est inventer.
    """
    if not m:
        return {"borne_atteinte": False,
                "motif": "relevé indisponible — on ne conclut pas sur une "
                         "mesure qu'on n'a pas"}

    couv = (f" (somme portant sur {m['couverture'] * 100:.0f} % des trades, "
            f"{m['sans_pnl']} sans montant vérifié)"
            if m.get("sans_pnl") else "")
    main = (f" La main, elle, a fait {m['pnl_main']:+.2f} € en "
            f"{m['ordres_main']} fermeture(s) — elle ne borne rien, mais "
            f"couper l'or la couperait aussi.")

    if m["ordres"] >= MAX_ORDRES:
        return {"borne_atteinte": True,
                "motif": f"{m['ordres']} ordres atteints sur un budget de "
                         f"{MAX_ORDRES}. Automatique "
                         f"{m['pnl_auto']:+.2f} € en {m['ordres_auto']} "
                         f"fermeture(s){couv}.{main}"}
    if m["pnl_auto"] <= MAX_PERTE_EUR:
        return {"borne_atteinte": True,
                "motif": f"L'automatique est à {m['pnl_auto']:+.2f} €, sous la "
                         f"borne de {MAX_PERTE_EUR:+.0f} €, en "
                         f"{m['ordres_auto']} fermeture(s) sur "
                         f"{m['ordres']} ordres{couv}.{main}"}
    return {"borne_atteinte": False,
            "motif": f"{m['ordres']}/{MAX_ORDRES} ordres, automatique "
                     f"{m['pnl_auto']:+.2f} € / {MAX_PERTE_EUR:+.0f} € "
                     f"en {m['ordres_auto']} fermeture(s){couv}.{main}"}
