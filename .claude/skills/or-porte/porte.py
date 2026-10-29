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
import subprocess
import sys
from datetime import datetime, timezone

import charge
import lot as L

ORIGINE_PRODUCTION = "production"
ORIGINE_LOT = "lot"

_LIMITES_REQUISES = ("order_cooldown_sec", "max_risque_engage_pct",
                     "places_par_paire")


def cumul_vide() -> dict:
    """L'etat de remplissage simule, vide. Separe par destination."""
    return {"paires": {}, "risque": {}, "cadence": {}}


def contraintes_lot(setup: dict, destination: str,
                    limites: dict, cumul: dict) -> tuple[str | None, dict]:
    """`(reason_code ou None, nouveau_cumul)`. Fail-closed sur toute limite
    illisible : on ne laisse pas passer ce qu'on n'a pas pu verifier."""
    for champ in _LIMITES_REQUISES:
        if limites.get(champ) is None:
            return "limite_illisible", cumul

    paire = setup["pair"]
    cle_p = (destination, paire)

    if cumul["paires"].get(cle_p, 0) >= int(limites["places_par_paire"]):
        return "lot_places_par_paire", cumul

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
                    setup, dest, limites.get(dest) or {}, cumul)
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


def _executer_a_distance(depot: pathlib.Path, src: str, timeout: int = 120):
    """Lance `src` dans le conteneur, par ssh. Non testee (reseau).

    `src` voyage par le STDIN de ssh (`python3 -`), jamais comme argument de
    `-c` : verifie le 2026-10-29 contre la production, deux defauts
    independants rendaient cette derniere voie non fiable --
      1. le shell distant (`bash -c`) ne convertit pas le `\\n` JSON en vrai
         saut de ligne -> `SyntaxError: unexpected character after line
         continuation character` sur tout script de plus d'une ligne ;
      2. meme une fois ce texte mis en base64 (donc sans saut de ligne), un
         seul argument de commande au-dela d'environ 8 Ko tronque en silence
         -> `bash: -c: ... unexpected EOF`. Le lot `--depuis-vivier` depasse
         deja ce seuil (25 buckets ~ 12,4 Ko encodes).
    Le flux stdin n'a ni l'un ni l'autre defaut : aucune conversion de
    caractere, aucune limite de longueur observee jusqu'a 50 Ko. `-n` est
    donc RETIRE (il couperait ce flux) et `docker exec` passe en `-i`.
    """
    return subprocess.run(
        ["ssh", "-i", str(depot / "scalping-key.pem"),
         "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes",
         "ec2-user@13.63.77.180",
         "sudo docker exec -i scalping-radar python3 -"],
        input=src, capture_output=True, text=True, timeout=timeout)


def collecter(depot: pathlib.Path, lot_valide: dict) -> dict:
    """Interroge la production en LECTURE SEULE. Non testee (reseau).

    Le parsing prend la DERNIERE ligne commencant par `{` : la banniere ssh
    pollue stdout, et c'est le contournement deja eprouve par `or-etat`.
    """
    src = charge.construire(lot_valide)
    out = _executer_a_distance(depot, src, timeout=120)
    for ligne in reversed(out.stdout.splitlines()):
        if ligne.strip().startswith("{"):
            brut = json.loads(ligne)
            if "erreur" in brut:
                raise RuntimeError("%s (connues : %s)"
                                   % (brut["erreur"],
                                      ", ".join(brut.get("connues") or [])))
            return brut
    raise RuntimeError("la production n'a rien rendu de lisible : %s"
                       % (out.stderr or out.stdout)[-300:])


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
    res = _executer_a_distance(depot, src, timeout=120)
    couples = None
    for ligne in reversed(res.stdout.splitlines()):
        t = ligne.strip()
        if t.startswith("["):
            couples = json.loads(t)
            break
        if t.startswith("{"):
            brut = json.loads(t)
            raise RuntimeError("%s (connues : %s)"
                               % (brut["erreur"],
                                  ", ".join(brut.get("connues") or [])))
    if couples is None:
        raise RuntimeError("vivier illisible : %s"
                           % (res.stderr or res.stdout)[-300:])
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

    try:
        if a.depuis_vivier:
            brut_lot = _lot_depuis_vivier(depot, a.depuis_vivier)
        else:
            brut_lot = json.loads(pathlib.Path(a.lot).read_text(encoding="utf-8"))
        lot_valide = L.valider_lot(brut_lot)
    except L.ErreurLot as e:
        print("ECHEC : lot non jugeable -- %s" % e)
        return 2
    except Exception as e:  # noqa: BLE001
        print("ECHEC : lot illisible (%s)" % e)
        return 2

    try:
        brut = collecter(depot, lot_valide)
    except Exception as e:  # noqa: BLE001
        print("ECHEC : production injoignable (%s) -- rien n'est juge" % e)
        return 2

    code, lignes, etat = juger(lot_valide, brut)
    if a.depuis_vivier:
        print("⚠️ lot issu du vivier : les setups ne portent PAS de prix\n"
              "   (entry_price=0, stop_loss=0) -- tout refus dependant du prix\n"
              "   n'est pas significatif")
    if a.en_json:
        print(json.dumps(etat, indent=2, ensure_ascii=False))
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
