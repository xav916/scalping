"""Refuser une configuration qui laisse de l'argent reel sans garde.

⛔ Elle juge la configuration DECLAREE, jamais le comportement observe. Sonder
la porte serait plus fort, et c'est IMPOSSIBLE : `execution_globale_fermee` est
sa premiere clause et court-circuite tout tant que REM-002 est desarme (prouve
le 29/10 : 25 couples sur 25). Elle dit donc si une protection est DECLAREE,
pas si elle FONCTIONNE.

🔴 `ILLISIBLE` compte comme un ECHEC, exactement comme `FAIL` : c'est une
donnee qu'on n'a pas pu INTERPRETER, pas une donnee qui dit « rien a signaler ».
Ne compter que `FAIL` laisserait le fail-closed fuir par cette nouvelle voie --
une destination dont les garde-fous sont illisibles serait rapportee comme
conforme, le pire resultat que cette skill puisse produire. Les deux comptes
restent distincts dans le resume pour que le lecteur sache lequel il affronte.

Lecture seule. Elle ne bloque rien : rapport et code de sortie.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from or_commun import distant  # noqa: E402

import regles as R  # noqa: E402

_CHARGE = '''
import json, sys
sys.path.insert(0, "/app")
from backend.services import bridge_destinations as BD
from backend.services import destinations_registry as RG
from backend.services import mt5_bridge as M

# Le mappage destination <-> liste blanche n'existe que sous forme de
# `if dest_id_wl == "admin_live"` dans la porte : c'est le SEUL fait
# reconstruit ici, et il est declare dans SKILL.md.
BLANCHES = {}
for nom, cst in (("admin_live", "LIVE_WHITELIST_PAIRS"),
                 ("admin_legacy", "LEGACY_WHITELIST_PAIRS")):
    v = getattr(M, cst, None)
    if v:
        BLANCHES[nom] = sorted(v)

def gardes(d):
    try:
        from backend.services import plafond_arbitrage as P
        s = P._lire_health(d.destination_id, avec_compte=False) or {}
    except Exception:
        s = {}
    return s.get("garde_fous") or {}

dests = []
for d in BD.admin_destinations():
    i = d.destination_id
    dests.append({
        "destination_id": i,
        "bridge_type": getattr(d, "bridge_type", "mt5"),
        "reel": bool(RG.is_real_money(i)),
        "min_confidence": getattr(d, "min_confidence", None),
        "classes_porte": sorted(getattr(d, "allowed_asset_classes", ()) or ()),
        "classes_registre": sorted(
            getattr(RG.get(i), "asset_classes", ()) or ()) if RG.get(i) else [],
        "connue_du_registre": bool(RG.is_known(i)),
        "garde_fous": gardes(d),
    })

from backend.services import global_execution_switch as G
det = G.execution_allowed().as_details()
print(json.dumps({
    "fingerprint_running": det.get("fingerprint_running"),
    "rem002_allowed": G.execution_allowed().allowed,
    "rem002_reason": det.get("reason_code"),
    "listes_blanches": BLANCHES,
    "destinations": dests,
}))
'''


def juger(etat: dict) -> tuple[int, list[str]]:
    """`(code, lignes)`. JAMAIS 0 sur une information absente."""
    empreinte = etat.get("fingerprint_running")
    if not empreinte:
        return 2, ["ECHEC : empreinte de code illisible -- un verdict calcule "
                   "contre un code inconnu est NUL, rien n'est juge."]
    dests = etat.get("destinations") or []
    if not dests:
        return 2, ["ECHEC : aucune destination active -- invraisemblable, donc "
                   "suspect. On ne rend pas « conforme »."]

    blanches = etat.get("listes_blanches") or {}
    lignes = ["=== or-politique | empreinte_code %s" % empreinte,
              "  armement : %s (%s)"
              % ("OUVERT" if etat.get("rem002_allowed") else "FERME",
                 etat.get("rem002_reason")),
              "  ⚠️ seule la configuration DECLAREE est jugee, pas son "
              "fonctionnement (REM-002 court-circuite toute sonde)",
              ""]

    n_fail = n_illisible = n_warn = 0
    for d in dests:
        lignes.append("  %-14s bridge=%-12s argent reel=%s"
                      % (d.get("destination_id"), d.get("bridge_type"),
                         "OUI" if d.get("reel") else "non"))
        for v in R.juger_destination(d, blanches):
            if v["verdict"] == R.FAIL:
                n_fail += 1
            elif v["verdict"] == R.ILLISIBLE:
                n_illisible += 1
            elif v["verdict"] == R.WARN:
                n_warn += 1
            lignes.append("      %d. %-22s %-15s %s [%s]"
                          % (v["regle"], v["titre"], v["verdict"],
                             v["valeur"], v["source"]))
        lignes.append("")

    lignes.append("=> %d FAIL, %d ILLISIBLE, %d WARN sur %d destination(s) "
                  "active(s)" % (n_fail, n_illisible, n_warn, len(dests)))
    return (1 if (n_fail or n_illisible) else 0), lignes


def collecter(depot: pathlib.Path) -> dict:
    """Interroge la production en LECTURE SEULE. Non testee (reseau)."""
    return distant.derniere_ligne_json(distant.executer(depot, _CHARGE))


def main(argv: list[str] | None = None) -> int:
    depot = pathlib.Path(__file__).resolve().parents[3]
    ap = argparse.ArgumentParser(
        description="Refuser une configuration sans garde.")
    ap.add_argument("--json", action="store_true", dest="en_json")
    a = ap.parse_args(argv)
    try:
        etat = collecter(depot)
    except Exception as e:  # noqa: BLE001
        print("ECHEC : production injoignable ou illisible (%s) -- rien n'est "
              "juge" % e)
        return 2
    try:
        code, lignes = juger(etat)
    except Exception as e:  # noqa: BLE001
        print("ECHEC : le jugement a leve (%s) -- rien n'est conclu" % e)
        return 2
    if a.en_json:
        print(json.dumps(etat, indent=2, ensure_ascii=False))
    else:
        for l in lignes:
            print(l)
    return code


if __name__ == "__main__":
    sys.exit(main())
