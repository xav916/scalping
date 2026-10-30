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

🔴 Dans `_CHARGE`, CHAQUE champ d'UNE destination est lu isolement (`_champ`) :
une levee sur un seul champ (ex. `RG.get` indisponible) ne doit jamais faire
tomber les champs deja lus de la MEME destination, ni les autres destinations
du lot -- une seule destination fautive ne doit pas couter tout le rapport
(round 1 de revue). Les defauts choisis font lire ILLISIBLE aux regles
concernees plutot que CONFORME muet, et `reel` defaut a `True` (fail-closed :
une destination dont on ne sait plus si c'est de l'argent reel est jugee
comme si elle l'etait).

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

# Filtres en OPT-IN STRICT, ou le vide signifie « rien ne passe » -- donc
# l'inverse de la semantique MT5 ci-dessus. La destination est INSCRITE ici
# des que le mecanisme existe, meme si sa liste est vide : c'est la presence
# dans cette map qui porte la semantique, pas son contenu.
BACKEND = {}
BACKEND_ERREURS = {}
_SENTINELLE = object()
try:
    from backend.services import kraken_bridge_client as _kbc
    # ⛔ « ABSENTE » n'est PAS « VIDE », et la nuance est tout l'enjeu :
    # vide => tout bloque (CONFORME) ; absente => rien ne filtre (FAIL).
    # Sans cette sentinelle, un conteneur ou le filtre n'est PAS DEPLOYE
    # rapportait regle 1 CONFORME -- une protection affirmee qui n'existe
    # pas. Faux-sur trouve et corrige le 2026-10-30, apres l'avoir
    # effectivement produit.
    _v = getattr(_kbc, "_KRAKEN_WHITELIST_PAIRS", _SENTINELLE)
    if _v is not _SENTINELLE:
        BACKEND["admin_kraken"] = sorted(_v or ())
    else:
        BACKEND_ERREURS["admin_kraken"] = (
            "_KRAKEN_WHITELIST_PAIRS absente du module : filtre NON deploye")
except Exception as _e:
    # ⛔ On NE se tait PAS. La direction est pourtant sure -- un filtre
    # illisible laisse la destination hors de la map, donc regle 1 = FAIL --
    # mais un echec que personne ne lit n'est pas une garde. Le motif remonte
    # au pied du rapport.
    BACKEND_ERREURS["admin_kraken"] = "%s: %s" % (type(_e).__name__, _e)

def gardes(d):
    try:
        from backend.services import plafond_arbitrage as P
        s = P._lire_health(d.destination_id, avec_compte=False) or {}
    except Exception:
        s = {}
    return s.get("garde_fous") or {}

def _champ(fn, defaut, erreurs, nom):
    """Lit UN champ. Une levee ne doit JAMAIS emporter les autres champs
    deja lus ni les autres destinations -- une seule destination fautive ne
    doit pas couter tout le rapport (REM-003, round 1)."""
    try:
        return fn()
    except Exception as e:
        erreurs.append("%s=%s" % (nom, type(e).__name__))
        return defaut

dests = []
for d in BD.admin_destinations():
    i = d.destination_id
    erreurs = []
    reg = _champ(lambda: RG.get(i), None, erreurs, "registre")
    rec = {
        "destination_id": i,
        "bridge_type": _champ(lambda: getattr(d, "bridge_type", "mt5"),
                              "mt5", erreurs, "bridge_type"),
        # fail-closed : une destination dont on ne sait plus si c'est de
        # l'argent reel est traitee COMME SI c'etait le cas, jamais exemptee.
        "reel": _champ(lambda: bool(RG.is_real_money(i)), True, erreurs,
                       "reel"),
        # defaut non numerique -> regle 3 ILLISIBLE, jamais CONFORME muet.
        "min_confidence": _champ(
            lambda: getattr(d, "min_confidence", None),
            "ILLISIBLE: champ non lu", erreurs, "min_confidence"),
        "classes_porte": _champ(
            lambda: sorted(getattr(d, "allowed_asset_classes", ()) or ()),
            [], erreurs, "classes_porte"),
        "classes_registre": _champ(
            lambda: sorted(getattr(reg, "asset_classes", ()) or ())
            if reg else [], [], erreurs, "classes_registre"),
        "connue_du_registre": _champ(lambda: bool(RG.is_known(i)), False,
                                     erreurs, "connue_du_registre"),
        # defaut truthy sans len() -> regle 2 ILLISIBLE, jamais CONFORME muet.
        "garde_fous": _champ(lambda: gardes(d), True, erreurs,
                             "garde_fous"),
    }
    if erreurs:
        rec["erreur"] = ", ".join(erreurs)
    dests.append(rec)

from backend.services import global_execution_switch as G
det = G.execution_allowed().as_details()
print(json.dumps({
    "fingerprint_running": det.get("fingerprint_running"),
    "rem002_allowed": G.execution_allowed().allowed,
    "rem002_reason": det.get("reason_code"),
    "listes_blanches": BLANCHES,
    "filtres_backend": BACKEND,
    "erreurs_filtres": BACKEND_ERREURS,
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
    backend = etat.get("filtres_backend") or {}
    erreurs_filtres = etat.get("erreurs_filtres") or {}
    lignes = ["=== or-politique | empreinte_code %s" % empreinte,
              "  armement : %s (%s)"
              % ("OUVERT" if etat.get("rem002_allowed") else "FERME",
                 etat.get("rem002_reason")),
              "  ⚠️ seule la configuration DECLAREE est jugee, pas son "
              "fonctionnement (REM-002 court-circuite toute sonde)",
              ""]

    n_fail = n_illisible = n_warn = 0
    faits_non_lus = []
    for d in dests:
        lignes.append("  %-14s bridge=%-12s argent reel=%s"
                      % (d.get("destination_id"), d.get("bridge_type"),
                         "OUI" if d.get("reel") else "non"))
        erreur = d.get("erreur")
        if erreur:
            n_illisible += 1
            lignes.append("      ⚠️ fait non lu : %s" % erreur)
            faits_non_lus.append("%s: %s" % (d.get("destination_id"), erreur))
        for v in R.juger_destination(d, blanches, backend):
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
    if faits_non_lus:
        lignes.append("=> faits non lus (donnee qu'on n'a pas pu lire, "
                      "comptee en ILLISIBLE) :")
        for f in faits_non_lus:
            lignes.append("   - %s" % f)
    # ⛔ Un filtre backend illisible laisse sa destination hors de la map, donc
    # regle 1 = FAIL : la direction est sure. Mais le MOTIF doit se voir, sinon
    # on lit « aucune liste blanche » en croyant qu'il n'y en a pas, alors
    # qu'on n'a pas su la lire. Deux phrases differentes.
    if erreurs_filtres:
        lignes.append("=> filtre(s) backend ILLISIBLE(S) -- la regle 1 les "
                      "traite comme absents (sens prudent) :")
        for nom, motif in sorted(erreurs_filtres.items()):
            lignes.append("   - %s : %s" % (nom, motif))
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
        # ⛔ Le caveat voyage AVEC la donnee. Un consommateur machine perdait
        # « seule la configuration DECLAREE est jugee » : le code de sortie
        # restait juste, mais la reserve disparaissait -- et c'est elle qui
        # dit ce que l'outil NE prouve pas. Les verdicts aussi, pour que le
        # JSON porte la meme chose que le rapport lu par un humain.
        print(json.dumps(dict(
            etat,
            _caveat="Seule la configuration DECLAREE est jugee, pas son "
                    "fonctionnement : REM-002 court-circuite toute sonde.",
            _code_de_sortie=code,
            _verdicts=[v for d in (etat.get("destinations") or [])
                       for v in R.juger_destination(
                           d, etat.get("listes_blanches") or {},
                           etat.get("filtres_backend") or {})],
        ), indent=2, ensure_ascii=False))
    else:
        for l in lignes:
            print(l)
    return code


if __name__ == "__main__":
    sys.exit(main())
