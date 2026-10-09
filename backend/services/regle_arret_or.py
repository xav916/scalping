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
# 800 ordres : RECALIBRE le 2026-10-09, a la demande de Xavier, apres
#             l'ouverture de l'or sur toute la fenetre hebdomadaire.
#
#             Les 60 d'origine venaient d'un rythme de 25 ordres en 6 jours
#             (4,2/jour). Deux choses ont change :
#               1. l'objectif court de 2 EUR rend les trades CONSECUTIFS --
#                  mesure sur les 3 dernieres heures pleinement armees du
#                  09/10 : 5,0 ordres/h ;
#               2. la fenetre est passee de 70,0 h a 114,6 h par semaine
#                  (+64 %), soit 22,9 h par jour de marche au lieu de 14,0.
#
#               taux bas  (32 ordres / 14 h = 2,3/h)  ->  53 ordres/jour
#               taux haut (15 ordres /  3 h = 5,0/h)  -> 115 ordres/jour
#
#             Pour 10 jours de marche -- l'intention d'origine etait
#             « ~9 jours » -- cela donne 530 a 1 150. On retient 800 : ~7
#             jours au taux haut, ~15 au taux bas. Tres au-dessus du plancher
#             statistique qui justifiait 60.
#
#             ⚠️ La borne d'ARGENT tombera probablement bien avant : au
#             -0,145 EUR/trade mesure sur le RADAR SEUL, 115 ordres/jour font
#             ~-17 EUR/jour. C'est voulu : « le premier atteint ».
#
# -50 EUR   : INCHANGE. 8,4 % d'un compte de 596 EUR, juste SOUS le seuil de
#             retrogradation automatique du systeme (10 % sur 7 jours) -- elle
#             parle donc AVANT que le cliquet ne tombe. Xavier a demande de
#             recalibrer le BUDGET D'ORDRES ; la borne d'argent n'etait pas
#             dans sa demande.
MAX_ORDRES = int(os.getenv("OR_ARRET_MAX_ORDRES", "800"))
MAX_PERTE_EUR = float(os.getenv("OR_ARRET_MAX_PERTE_EUR", "-50"))

# `dc3c067`, « Tous les horizons sur l or » -- 2026-10-01 18:35:48 +0200.
DEPUIS = os.getenv("OR_ARRET_DEPUIS", "2026-10-01T16:35:48+00:00")

# Toute sortie qui n'est pas la main. `close_reason` NULL = position ouverte :
# elle compte dans les ordres, jamais dans l'argent.
MAIN = "MANUAL"

# ⛔ La marque que l'adoption (`ac2823b`) pose sur les trades nes
# DANS LE TERMINAL MT5. Meme forme que `mt5_sync` : un LIKE, pas une
# egalite.
MARQUE_TERMINAL = "MANUEL-TERM"


def _a_la_colonne_notes(c) -> bool:
    """⚠️ Toutes les bases ne portent pas `notes`. Une requete qui leve rendrait
    `None`, et un releve absent ne conclut sur RIEN : la regle deviendrait
    MUETTE au lieu de se degrader. On regarde avant d'ecrire la requete.
    """
    try:
        return any(r[1] == "notes"
                   for r in c.execute("PRAGMA table_info(personal_trades)"))
    except Exception:  # noqa: BLE001
        return False


def releve(db, depuis: str = DEPUIS) -> dict | None:
    """Compte les ordres et separe l'argent selon QUI A OUVERT, puis qui a ferme.

    Rend `None` si la base est injoignable. Trois etats, jamais deux :
    « je n'ai pas pu regarder » n'est pas « rien a signaler ».

    ## ⛔ POURQUOI L'ORIGINE, ET PAS SEULEMENT LA FERMETURE (2026-10-09)

    L'adoption des positions du courtier (`ac2823b`) fait entrer dans
    `personal_trades` les trades que Xavier ouvre **dans le terminal MT5**,
    marques `MANUEL-TERM`. Un tel trade ferme par son stop porte
    `close_reason = 'SL'` : separer par la seule fermeture le rangeait donc
    dans la jambe **AUTOMATIQUE**, celle qui borne l'experience du radar.

    Mesure du soir du deploiement, sur la fenetre de la regle :

        jambe "auto"  RADAR     n=48    -6,96 EUR
        jambe "auto"  TERMINAL  n= 7   -45,42 EUR   <- les stops de Xavier
        compteur d'ordres : RADAR 59 + TERMINAL 43 = 102, budget 60

    ⇒ **87 % de la « perte de l'automatique » etaient ses propres stops**, et la
    regle a franchi ses DEUX bornes le jour meme du deploiement, par artefact.

    ## Quatre populations, une seule borne

    - `pnl_auto` / `ordres_auto` : ouvert par le RADAR, ferme par le CODE.
      **La seule qui borne quoi que ce soit.**
    - `pnl_main` / `ordres_main` : ouvert par le RADAR, ferme A LA MAIN. C'est
      cette main-la que « couper l'or couperait aussi » : elle vit de ce que le
      code ouvre (+42,35 EUR sur 11 fermetures, 65 % du gain de la main).
    - `pnl_terminal` / `ordres_terminal` : ouvert DANS LE TERMINAL, toutes
      fermetures confondues. Se lit, ne borne rien.
    - `ordres` : les ordres du RADAR seuls, ce que le budget compte.
    """
    try:
        with sqlite3.connect(f"file:{Path(db)}?mode=ro", uri=True) as c:
            # 🔑 Sans la colonne, tout est cense venir du radar : c'est l'etat
            # d'avant l'adoption, et c'est le bon repli.
            if _a_la_colonne_notes(c):
                radar = ("COALESCE(notes,'') NOT LIKE '%"
                         + MARQUE_TERMINAL + "%'")
            else:
                radar = "1=1"
            terminal = "NOT (" + radar + ")"
            code = "close_reason IS NOT NULL AND close_reason <> ?"
            ligne = c.execute(
                # les ordres du RADAR : ce que le budget compte
                f"SELECT SUM(CASE WHEN {radar} THEN 1 ELSE 0 END), "
                # ouvert par le RADAR, ferme par le CODE -> la borne d'argent
                f"       COALESCE(SUM(CASE WHEN {radar} AND pnl IS NOT NULL "
                f"                          AND {code} THEN pnl END), 0), "
                f"       SUM(CASE WHEN {radar} AND {code} THEN 1 ELSE 0 END), "
                # ouvert par le RADAR, ferme A LA MAIN -> dit, jamais bornant
                f"       COALESCE(SUM(CASE WHEN {radar} AND close_reason = ? "
                f"                         THEN pnl END), 0), "
                f"       SUM(CASE WHEN {radar} AND close_reason = ? "
                f"                THEN 1 ELSE 0 END), "
                # ne DANS LE TERMINAL -> dit, jamais bornant
                f"       COALESCE(SUM(CASE WHEN {terminal} THEN pnl END), 0), "
                f"       SUM(CASE WHEN {terminal} THEN 1 ELSE 0 END), "
                # ce que la somme ne voit pas, sur les ordres du radar
                f"       SUM(CASE WHEN {radar} AND status = 'CLOSED' "
                f"                AND pnl IS NULL THEN 1 ELSE 0 END) "
                f"FROM personal_trades "
                f"WHERE pair = ? AND destination_id = ? AND created_at >= ?",
                (MAIN, MAIN, MAIN, MAIN, PAIRE, DESTINATION,
                 depuis)).fetchone()
    except Exception as e:  # noqa: BLE001
        logger.warning("regle_arret_or: base illisible (%s)", e)
        return None

    (n, pnl_auto, n_auto, pnl_main, n_main, pnl_term, n_term, sans) = ligne
    n = int(n or 0)
    sans = int(sans or 0)
    return {
        "ordres": n,
        "pnl_auto": float(pnl_auto or 0.0),
        "ordres_auto": int(n_auto or 0),
        "pnl_main": float(pnl_main or 0.0),
        "ordres_main": int(n_main or 0),
        "pnl_terminal": float(pnl_term or 0.0),
        "ordres_terminal": int(n_term or 0),
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
            f"{m['ordres_main']} fermeture(s) sur des positions du RADAR — "
            f"elle ne borne rien, mais couper l'or la couperait aussi.")

    # ⛔ 2026-10-09 : les trades nes DANS LE TERMINAL sortent de la borne, ils
    # ne sortent PAS du message. 45,42 € de stops reels effaces du compte-rendu
    # seraient une perte invisible -- et c'est en les confondant avec
    # l'automatique que la regle a franchi ses deux bornes par artefact.
    term = ""
    if m.get("ordres_terminal"):
        term = (f" À part : {m['ordres_terminal']} trade(s) ouvert(s) dans le "
                f"terminal MT5, {m['pnl_terminal']:+.2f} € — hors borne, "
                f"c'est son volume à lui.")

    if m["ordres"] >= MAX_ORDRES:
        return {"borne_atteinte": True,
                "motif": f"{m['ordres']} ordres atteints sur un budget de "
                         f"{MAX_ORDRES}. Automatique "
                         f"{m['pnl_auto']:+.2f} € en {m['ordres_auto']} "
                         f"fermeture(s){couv}.{main}{term}"}
    if m["pnl_auto"] <= MAX_PERTE_EUR:
        return {"borne_atteinte": True,
                "motif": f"L'automatique est à {m['pnl_auto']:+.2f} €, sous la "
                         f"borne de {MAX_PERTE_EUR:+.0f} €, en "
                         f"{m['ordres_auto']} fermeture(s) sur "
                         f"{m['ordres']} ordres{couv}.{main}{term}"}
    return {"borne_atteinte": False,
            "motif": f"{m['ordres']}/{MAX_ORDRES} ordres, automatique "
                     f"{m['pnl_auto']:+.2f} € / {MAX_PERTE_EUR:+.0f} € "
                     f"en {m['ordres_auto']} fermeture(s){couv}.{main}{term}"}
