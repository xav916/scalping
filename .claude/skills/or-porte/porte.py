"""La porte avant le pont : juge un lot de setups or, par destination.

Deux moities, comme `or-etat` : un juge PUR teste, et un collecteur impur
non teste. Les verdicts de production viennent d'une charge executee dans le
conteneur ; ce module n'en recopie aucun.

Les quatre contraintes ci-dessous sont un AJOUT de la skill, pas une
description de la production : `_check_rejection(setup, dest)` n'a aucun
parametre « fais comme si ceux-la etaient remplis ». Chaque verdict qu'elles
produisent porte donc `origine: lot`.
"""
from __future__ import annotations

import lot as L

ORIGINE_PRODUCTION = "production"
ORIGINE_LOT = "lot"

_LIMITES_REQUISES = ("max_correlated_positions", "order_cooldown_sec",
                     "max_risque_engage_pct", "places_par_paire")


def cumul_vide() -> dict:
    """L'etat de remplissage simule, vide. Separe par destination."""
    return {"paires": {}, "classes": {}, "risque": {}, "cadence": {}}


def contraintes_lot(setup: dict, destination: str, classe: str,
                    limites: dict, cumul: dict) -> tuple[str | None, dict]:
    """`(reason_code ou None, nouveau_cumul)`. Fail-closed sur toute limite
    illisible : on ne laisse pas passer ce qu'on n'a pas pu verifier."""
    for champ in _LIMITES_REQUISES:
        if limites.get(champ) is None:
            return "limite_illisible", cumul

    paire = setup["pair"]
    cle_p = (destination, paire)
    cle_c = (destination, classe)

    if cumul["paires"].get(cle_p, 0) >= int(limites["places_par_paire"]):
        return "lot_places_par_paire", cumul
    if cumul["classes"].get(cle_c, 0) >= int(limites["max_correlated_positions"]):
        return "lot_exposition_correlee", cumul

    risque = float(setup.get("risk_pct") or 0.0)
    engage = cumul["risque"].get(destination, 0.0)
    if engage + risque > float(limites["max_risque_engage_pct"]):
        return "lot_risque_engage", cumul

    # Le lot n'a pas d'horloge : ses setups sont traites comme SIMULTANES,
    # donc le deuxieme sur la meme paire bloque des que la fenetre existe.
    if int(limites["order_cooldown_sec"]) > 0 and cumul["cadence"].get(cle_p):
        return "lot_cadence", cumul

    neuf = {
        "paires": {**cumul["paires"], cle_p: cumul["paires"].get(cle_p, 0) + 1},
        "classes": {**cumul["classes"], cle_c: cumul["classes"].get(cle_c, 0) + 1},
        "risque": {**cumul["risque"], destination: engage + risque},
        "cadence": {**cumul["cadence"], cle_p: True},
    }
    return None, neuf


_CORRECTIFS = {
    "below_confidence":
        "Confiance %(confidence_score)s jugee insuffisante par cette "
        "destination -- relever le score, ou viser une destination moins "
        "exigeante.",
    "pair_not_whitelisted":
        "La paire %(pair)s n'est pas dans la liste blanche de cette "
        "destination. Elargir la liste est une DECISION, pas un correctif.",
    "lot_places_par_paire":
        "Le lot a deja consomme toutes les places sur %(pair)s -- retirer un "
        "setup de cette paire du lot.",
    "lot_exposition_correlee":
        "Le lot a deja rempli le plafond de positions correlees de la classe "
        "-- retirer un setup de la meme classe.",
    "lot_risque_engage":
        "Le risque cumule du lot depasse le plafond -- baisser `risk_pct` ou "
        "retirer un setup.",
    "lot_cadence":
        "Un autre setup du lot vise deja %(pair)s, et la cadence de la "
        "destination interdit deux ordres rapproches.",
    "limite_illisible":
        "Une limite de la destination n'a pas pu etre lue : on BLOQUE plutot "
        "que de laisser passer ce qu'on n'a pas verifie.",
}


def correctif(reason_code: str, setup: dict) -> str:
    """Quoi changer, en nommant la valeur. Jamais « desserrer la regle »."""
    if reason_code.startswith("porte_en_erreur"):
        return ("La porte de production a leve (%s) -- le setup est bloque par "
                "prudence, la trace est en pied de rapport." % reason_code)
    modele = _CORRECTIFS.get(reason_code)
    if modele is None:
        return ("Refus rendu par la production sans correctif connu -- lire "
                "`%s` dans `mt5_bridge._check_rejection`." % reason_code)
    return modele % {k: setup.get(k) for k in L.CHAMPS_ADMIS}


def juger(lot_valide: dict, brut: dict) -> tuple[int, list[str], dict]:
    """`(code, lignes, etat)`. JAMAIS 0 sur une information absente."""
    lignes: list[str] = []
    empreinte_code = brut.get("fingerprint_running")
    if not empreinte_code:
        return 2, ["ECHEC : empreinte_code_illisible -- un verdict calcule "
                   "contre un code inconnu est NUL, rien n'est juge."], {}

    par_couple = {(v["i"], v["destination"]): v
                  for v in brut.get("verdicts") or []}
    limites = brut.get("limites") or {}
    libelles = brut.get("libelles") or {}
    sans_libelle = set(brut.get("sans_libelle") or [])

    lignes.append("=== or-porte | empreinte_code %s" % empreinte_code)
    lignes.append("  armement : %s (%s)"
                  % ("OUVERT" if brut.get("rem002_allowed") else "FERME",
                     brut.get("rem002_reason")))
    lignes.append("  ⚠️ les clauses `lot` sont un AJOUT de cette skill, pas un "
                  "comportement de production")
    lignes.append("")

    verdicts: list[dict] = []
    cumul = cumul_vide()
    erreurs: list[str] = []

    for dest in lot_valide["destinations"]:
        for i, setup in enumerate(lot_valide["setups"]):
            vp = par_couple.get((i, dest))
            if vp is None:
                return 2, lignes + [
                    "ECHEC : aucun verdict de production pour setup #%d / %s "
                    "-- le lot n'est pas jugeable." % (i, dest)], {}

            empreinte = L.empreinte_setup(setup)
            code_prod = vp.get("reason_code")
            resultat, reason, origine = "PASS", None, None

            if code_prod:
                resultat, reason, origine = "BLOCK", code_prod, ORIGINE_PRODUCTION
                if code_prod.startswith("porte_en_erreur"):
                    erreurs.append("setup #%d / %s : %s" % (i, dest, code_prod))
            else:
                reason_lot, cumul = contraintes_lot(
                    setup, dest, vp.get("classe"), limites.get(dest) or {}, cumul)
                if reason_lot:
                    resultat, reason, origine = "BLOCK", reason_lot, ORIGINE_LOT

            ligne = {
                "empreinte_setup": empreinte, "pair": setup["pair"],
                "direction": setup.get("direction"), "destination": dest,
                "resultat": resultat, "admission": vp.get("admission"),
            }
            if resultat == "BLOCK":
                ligne.update({
                    "reason_code": reason,
                    "libelle": libelles.get(reason, reason),
                    "origine": origine,
                    "correctif": correctif(reason, setup),
                })
            verdicts.append(ligne)

            lignes.append("  %-10s %-5s %-20s %s%s"
                          % (setup["pair"], setup.get("direction"), dest,
                             resultat,
                             "" if resultat == "PASS"
                             else " %s [%s] %s" % (ligne["libelle"],
                                                   origine, ligne["correctif"])))

    bloques = [v for v in verdicts if v["resultat"] == "BLOCK"]
    lignes.append("")
    if sans_libelle:
        lignes.append("  ⓘ motifs rencontres SANS libelle francais : %s"
                      % ", ".join(sorted(sans_libelle)))
    for e in erreurs:
        lignes.append("  ⓘ porte en erreur -- %s" % e)
    lignes.append("=> %d PASS, %d BLOCK sur %d couples"
                  % (len(verdicts) - len(bloques), len(bloques), len(verdicts)))

    etat = {"empreinte_code": empreinte_code, "verdicts": verdicts}
    return (1 if bloques else 0), lignes, etat
