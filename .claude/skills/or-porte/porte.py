"""La porte avant le pont : juge un lot de setups or, par destination.

Deux moities, comme `or-etat` : un juge PUR teste, et un collecteur impur
non teste. Les verdicts de production viennent d'une charge executee dans le
conteneur ; ce module n'en recopie aucun.

Les TROIS contraintes ci-dessous sont un AJOUT de la skill, pas une
description de la production : `_check_rejection(setup, dest)` n'a aucun
parametre « fais comme si ceux-la etaient remplis ». Chaque verdict qu'elles
produisent porte donc `origine: lot`.

⛔ Il n'y en a plus QUATRE. La clause « exposition correlee » retiree le
2026-10-29 cle par CLASSE D'ACTIF : la production n'a rien de tel. Son garde-
fou de correlation est PAR COUPLE (destination, paire), fonde sur des
coefficients (`correlation_guard.SEUIL_CORRELATION`), et lit les positions
REELLEMENT ouvertes chez le courtier (`pari_deja_pris()`) -- on ne peut pas
lui demander « et si ceux-la se remplissaient aussi » sans une fonction de
production qui n'existe pas. Inventer un plafond par classe aurait ete
fabriquer une porte.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from or_commun import distant  # noqa: E402

import charge
import lot as L

ORIGINE_PRODUCTION = "production"
ORIGINE_LOT = "lot"

# `max_risque_engage_or_argent_pct` est TOUJOURS requise, meme pour un setup
# non-metal : c'est sa valeur (>0 ou non) qui decide si la poche or/argent
# est separee de la commune (cf. `poche_risque`), donc elle doit etre lue
# avant de savoir laquelle des deux poches s'applique.
_LIMITES_REQUISES = ("order_cooldown_sec", "max_risque_engage_pct",
                     "max_risque_engage_or_argent_pct", "max_open_positions")


def cumul_vide() -> dict:
    """L'etat de remplissage simule, vide.

    `destinations` : places consommees, par destination SEULE -- c'est un
    budget GLOBAL du pont, jamais par paire (cf. `poche_risque` et le
    commentaire de `contraintes_lot`). `risque` : par (destination, poche),
    les deux poches de risque engage ne se pretant jamais rien. `cadence` :
    par (destination, paire), inchange.
    """
    return {"destinations": {}, "risque": {}, "cadence": {}}


def poche_risque(classe: str | None,
                 limites: dict) -> tuple[str | None, float | None]:
    """`(nom_de_poche, plafond_pct)` pour CE setup, ou `(None, None)` si l'une
    des deux valeurs necessaires est illisible.

    Reproduit EXACTEMENT `mt5_bridge.bridge` (`bridge.py:1103-1107`) :
    `poches_separees = MAX_RISQUE_ENGAGE_OR_ARGENT_PCT > 0`. L'or/argent n'a
    sa poche PROPRE que si cette valeur est > 0 -- sinon il retombe dans la
    poche commune comme tout le reste, exactement comme en production.
    `/health` publie les deux valeurs separement (5 % contre 15-20 % releve
    le 2026-10-29) : juger l'or contre la poche commune le bloquerait 3x
    trop tot.
    """
    plafond_or = limites.get("max_risque_engage_or_argent_pct")
    plafond_commun = limites.get("max_risque_engage_pct")
    if plafond_or is None or plafond_commun is None:
        return None, None
    if classe == "metal" and plafond_or > 0:
        return "or_argent", plafond_or
    return "autres", plafond_commun


def contraintes_lot(setup: dict, destination: str, classe: str | None,
                    limites: dict, cumul: dict) -> tuple[str | None, dict]:
    """`(reason_code ou None, nouveau_cumul)`. Fail-closed sur toute limite
    illisible : on ne laisse pas passer ce qu'on n'a pas pu verifier."""
    for champ in _LIMITES_REQUISES:
        if limites.get(champ) is None:
            return "limite_illisible", cumul

    poche, plafond_risque_pct = poche_risque(classe, limites)
    if poche is None:
        return "limite_illisible", cumul

    paire = setup["pair"]

    # ⚠️ `max_open_positions` est le plafond GLOBAL du pont
    # (`bridge.py:1089`), consomme par CHAQUE PASS sur cette destination,
    # quelle que soit la paire -- jamais une allocation par paire. Le cap
    # PAR PAIRE reel de production (`mt5_bridge._max_positions_for_pair`,
    # defaut 2) est deja applique DANS `_check_rejection`, en amont de cette
    # clause ; la recopier ici aurait ete reimplementer une porte.
    if cumul["destinations"].get(destination, 0) >= int(limites["max_open_positions"]):
        return "lot_places_destination", cumul

    risque = float(setup.get("risk_pct") or 0.0)
    cle_risque = (destination, poche)
    engage = cumul["risque"].get(cle_risque, 0.0)
    if engage + risque > float(plafond_risque_pct):
        return "lot_risque_engage", cumul

    # Le lot n'a pas d'horloge : ses setups sont traites comme SIMULTANES,
    # donc le deuxieme sur la meme paire bloque des que la fenetre existe.
    cle_p = (destination, paire)
    if int(limites["order_cooldown_sec"]) > 0 and cumul["cadence"].get(cle_p):
        return "lot_cadence", cumul

    neuf = {
        "destinations": {**cumul["destinations"],
                         destination: cumul["destinations"].get(destination, 0) + 1},
        "risque": {**cumul["risque"], cle_risque: engage + risque},
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
    "asset_class_blocked":
        "La classe d'actif de %(pair)s n'est pas dans `allowed_asset_classes` "
        "de cette destination -- reconstruite ici (SEULE exception, cf. "
        "charge.py), appliquee en production par "
        "`mt5_bridge._push_to_destination` (mt5_bridge.py:2278), APRES "
        "`_check_rejection` -- pas dedans.",
    "lot_places_destination":
        "Le lot a deja consomme toutes les places GLOBALES de cette "
        "destination (`max_open_positions`, tous couples confondus) -- "
        "retirer un setup de cette destination.",
    "lot_risque_engage":
        "Le risque cumule du lot depasse le plafond de sa poche -- baisser "
        "`risk_pct` ou retirer un setup.",
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
    entete = list(lignes)

    verdicts: list[dict] = []
    cumul = cumul_vide()
    erreurs: list[str] = []

    for dest in lot_valide["destinations"]:
        for i, setup in enumerate(lot_valide["setups"]):
            vp = par_couple.get((i, dest))
            if vp is None:
                # Code 2 = rien n'est juge : ne JAMAIS rendre les lignes
                # PASS/BLOCK des couples deja traites, qui mentiraient sur
                # un run que l'on declare par ailleurs injugeable.
                return 2, entete + [
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


def collecter(depot: pathlib.Path, lot_valide: dict) -> dict:
    """Interroge la production en LECTURE SEULE. Non testee (reseau).

    Le parsing prend la DERNIERE ligne commencant par `{` : la banniere ssh
    pollue stdout, et c'est le contournement deja eprouve par `or-etat`.
    """
    src = charge.construire(lot_valide)
    brut = distant.derniere_ligne_json(distant.executer(depot, src))
    if "erreur" in brut:
        raise RuntimeError("%s (connues : %s)"
                           % (brut["erreur"],
                              ", ".join(brut.get("connues") or [])))
    return brut


def _lot_depuis_vivier(depot: pathlib.Path, destination: str) -> dict:
    """Construit un lot depuis les buckets AUTO_EXEC, par la CASCADE.

    ⛔ Jamais par requete sur `pair_admission_state` : cette table est un
    HISTORIQUE de transitions, et la lire par etat rend 166 la ou la cascade
    rend 1.

    🔑 R18 (2026-10-29) : resout la destination par
    `bridge_destinations.admin_destinations()` et filtre par
    `allowed_asset_classes`, exactement comme la charge principale -- jamais
    par `destinations_registry.asset_classes`, dont l'ensemble est FAUX
    (admin_kraken y a "metal" en plus, qui n'est pas dans ce que la
    production accepte reellement). Une destination absente d'
    `admin_destinations()` echoue explicitement, jamais un lot vide en
    silence.
    """
    dest_lit = json.dumps(destination)
    src = (
        "import json,sys; sys.path.insert(0,'/app')\n"
        "from backend.services import pair_admission_controller as A\n"
        "from backend.services import bridge_destinations as BD\n"
        "from config.settings import asset_class_for, WATCHED_PAIRS\n"
        "NOM=%s\n" % dest_lit +
        "_ACTIVES={x.destination_id:x for x in BD.admin_destinations()}\n"
        "d=_ACTIVES.get(NOM)\n"
        "if d is None:\n"
        "    print(json.dumps({'erreur':'destination inconnue: '+NOM,\n"
        "                      'connues':sorted(_ACTIVES)}))\n"
        "    sys.exit(0)\n"
        "out=[]\n"
        "for p in sorted({str(x).upper() for x in WATCHED_PAIRS}):\n"
        "    if asset_class_for(p) not in d.allowed_asset_classes: continue\n"
        "    for s in ('buy','sell'):\n"
        "        if A.get_current_state(p,direction=s,destination=d.destination_id)"
        "=='AUTO_EXEC':\n"
        "            out.append({'pair':p,'direction':s})\n"
        "print(json.dumps(out))"
    )
    couples = distant.derniere_ligne_json(distant.executer(depot, src), prefixe="[")
    # ⚠️ Important 4 : seuls `pair`/`direction` sont REELS ici. Les NEUF
    # autres champs sont FABRIQUES, chacun desarme une porte precise -- la
    # banniere imprimee par `main()` doit nommer la MEME liste :
    #   entry_price=0, stop_loss=0     -> toute porte dependant du prix
    #   confidence_score=100           -> `below_confidence` (permissif)
    #   verdict_blockers=[]            -> geopolitical/macro/verdict veto
    #   is_simulated=False             -> `simulated_data`
    #   pattern/horizon/chaine/
    #   shadow_system_id=None          -> listes de motifs/horizons admis,
    #                                      ouverture par chaine, cout de
    #                                      portage -- jugent une valeur
    #                                      absente, ni PASS ni BLOCK n'est
    #                                      significatif
    #   risk_pct=0.0 (lot, pas production) -> `lot_risque_engage`
    return {"destinations": [destination], "setups": [
        {"pair": c["pair"], "direction": c["direction"],
         "entry_price": 0.0, "stop_loss": 0.0, "confidence_score": 100,
         "pattern": None, "horizon": None, "chaine": None,
         "shadow_system_id": None, "is_simulated": False,
         "verdict_blockers": [], "risk_pct": 0.0}
        for c in couples]}


def main(argv: list[str] | None = None) -> int:
    depot = pathlib.Path(__file__).resolve().parents[3]
    ap = argparse.ArgumentParser(description="La porte avant le pont.")
    ap.add_argument("--lot", default=str(depot / "or" / "lot.json"))
    ap.add_argument("--json", action="store_true", dest="en_json")
    ap.add_argument("--no-write", action="store_true", dest="sans_ecrire")
    ap.add_argument("--depuis-vivier", default=None, metavar="DESTINATION")
    a = ap.parse_args(argv)

    def _echec(motif: str, cause: str) -> int:
        """Sortie 2, LISIBLE DANS LES DEUX MODES (2026-10-31).

        ⛔ Le defaut : `--json` n'agissait qu'a la toute fin. Chaque echec
        precoce imprimait de la PROSE, donc un consommateur machine recevait
        du texte non analysable avec un code 2 ; et quand `juger` rendait 2
        avec un etat vide, `--json` imprimait `{}` -- techniquement du JSON,
        et qui ne dit RIEN.

        🔑 Un mode machine qui retombe en prose sur l'echec est pire qu'absent :
        il marche a tous les essais sauf celui ou l'on a besoin de savoir
        pourquoi.
        """
        if a.en_json:
            print(json.dumps({"code": 2, "verdict": "ECHEC",
                              "motif": motif, "cause": cause,
                              "etat": None},
                             indent=2, ensure_ascii=False))
        else:
            print("ECHEC : %s -- %s" % (motif, cause))
        return 2

    try:
        if a.depuis_vivier:
            brut_lot = _lot_depuis_vivier(depot, a.depuis_vivier)
        else:
            brut_lot = json.loads(pathlib.Path(a.lot).read_text(encoding="utf-8"))
        lot_valide = L.valider_lot(brut_lot)
    except L.ErreurLot as e:
        return _echec("lot non jugeable", str(e))
    except Exception as e:  # noqa: BLE001
        return _echec("lot illisible", "%s: %s" % (type(e).__name__, e))

    try:
        brut = collecter(depot, lot_valide)
    except Exception as e:  # noqa: BLE001
        return _echec("production injoignable",
                      "%s: %s -- rien n'est juge" % (type(e).__name__, e))

    try:
        code, lignes, etat = juger(lot_valide, brut)
    except Exception as e:  # noqa: BLE001
        return _echec("lot non jugeable",
                      "%s: %s -- rien n'est juge" % (type(e).__name__, e))
    if a.depuis_vivier:
        # Important 4 : `_lot_depuis_vivier` fabrique DIX des onze champs que
        # les portes lisent (seuls `pair`/`direction` viennent du vivier) --
        # la banniere doit les nommer TOUS, pas seulement le prix.
        print("⚠️ lot issu du vivier : seuls `pair`/`direction` sont reels, "
              "TOUT LE RESTE est fabrique :\n"
              "   entry_price=0, stop_loss=0 -- tout refus dependant du prix "
              "n'est pas significatif\n"
              "   confidence_score=100 -- MAXIMALEMENT permissif : "
              "`below_confidence` ne peut JAMAIS bloquer ici\n"
              "   verdict_blockers=[] -- `geopolitical_veto`/`macro_veto`/"
              "`verdict_blocker` ne peuvent JAMAIS bloquer ici\n"
              "   is_simulated=False -- `simulated_data` ne peut JAMAIS "
              "bloquer ici\n"
              "   pattern=None, horizon=None, chaine=None, "
              "shadow_system_id=None -- toute porte qui les lit (liste de "
              "motifs/horizons autorises, ouverture par chaine, cout de "
              "portage) juge une valeur absente, pas celle du setup reel : "
              "ni son PASS ni son BLOCK n'est significatif\n"
              "   risk_pct=0.0 -- la clause de lot `lot_risque_engage` ne "
              "peut JAMAIS bloquer ici (clause d'ORIGINE lot, pas production)")
    if a.en_json:
        # ⛔ Ne JAMAIS imprimer `etat` nu : vide, il rendait `{}` -- du JSON
        # valide qui ne dit ni le code, ni pourquoi. Le code de sortie et le
        # verdict sont toujours portes, et `lignes` reste disponible pour que
        # le consommateur machine ait acces a la MEME explication que
        # l'humain, sans avoir a la reconstituer.
        print(json.dumps({"code": code,
                          "verdict": {0: "PASS", 1: "BLOCK"}.get(code, "ECHEC"),
                          "etat": etat or None,
                          "lignes": lignes},
                         indent=2, ensure_ascii=False))
    else:
        for l in lignes:
            print(l)
    if etat and not a.sans_ecrire:
        cible = depot / "or" / "state" / "porte.json"
        cible.parent.mkdir(parents=True, exist_ok=True)
        etat["juge_le"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cible.write_text(json.dumps(etat, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
