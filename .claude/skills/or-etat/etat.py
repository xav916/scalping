"""Suis-je arme, et par quoi ? Les TROIS voies d'ordre, pas un drapeau.

Le 25/10, repondre a « l'auto-trading est-il desactive ? » a demande vingt
minutes et quatre detours, et la bonne reponse n'etait pas un drapeau :

  1. _push_to_destination -> decision REM-002
  2. _mirror_fill_to_live -> _mirror_active()
  3. la file de l'EA      -> PENDING dans mt5_pending_orders

La voie 3 ne passe meme pas par le backend : l'EA fait un OrderSend natif a
partir de la table. Un seul drapeau n'est donc pas une reponse.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from or_commun import distant  # noqa: E402

REQUIS = ("rem002_allowed", "rem002_reason", "mirror_active", "pending",
          "pont_live", "pont_demo", "fingerprint_running", "fingerprint_armed")


def juger(etat: dict) -> tuple[int, list[str]]:
    """`(code_de_sortie, lignes)`. JAMAIS 0 sur une information absente ou None."""
    lignes: list[str] = []
    manquants = [c for c in REQUIS if c not in etat]
    nones = [c for c in REQUIS if c in etat and etat[c] is None]
    fautifs = manquants + nones
    if fautifs:
        return 1, ["ECHEC : information absente ou indeterminable, l'etat n'est pas "
                   "determinable -> %s" % ", ".join(fautifs)]

    arme = bool(etat["rem002_allowed"])
    lignes.append("=== les 3 voies d'ordre")
    lignes.append("  1. _push_to_destination : %s (%s)"
                  % ("OUVERTE" if arme else "FERMEE", etat["rem002_reason"]))
    lignes.append("  2. _mirror_fill_to_live : %s"
                  % ("ACTIF" if etat["mirror_active"] else "inactif"))
    lignes.append("  3. file de l'EA         : %d PENDING" % int(etat["pending"]))
    lignes.append("")
    lignes.append("  equite %.2f EUR | %d position(s) ouverte(s)"
                  % (float(etat.get("equity") or 0), int(etat.get("positions") or 0)))
    lignes.append("  pont live : http=%s | pont demo : http=%s (informatif)"
                  % (etat["pont_live"], etat["pont_demo"]))

    if etat["fingerprint_running"] != etat["fingerprint_armed"]:
        lignes.append("  empreintes DIFFERENTES (%s / %s) : un rearmement "
                      "exigerait une decision neuve"
                      % (etat["fingerprint_running"], etat["fingerprint_armed"]))

    code = 0
    if int(etat["pont_live"]) != 200:
        lignes.append("ECHEC : le pont live ne repond pas (http=%s) -- ni prix, "
                      "ni execution" % etat["pont_live"])
        code = 1
    if not arme and (etat["mirror_active"] or int(etat["pending"]) > 0):
        lignes.append("ECHEC : etat incoherent -- REM-002 ferme mais une autre "
                      "voie est ouverte")
        code = 1
    lignes.append("")
    lignes.append("=> %s, verifie sur les 3 voies"
                  % ("ARME" if arme else "DESARME"))
    return code, lignes


def collecter(depot: pathlib.Path) -> dict:
    """Interroge la production en LECTURE SEULE. Non testee (reseau)."""
    pyt = (
        "import json,sys; sys.path.insert(0,'/app');"
        "from backend.services import global_execution_switch as G,"
        " mt5_bridge as M;"
        "import sqlite3;"
        "c=sqlite3.connect('file:/app/data/trades.db?mode=ro',uri=True);"
        "p=c.execute(\"select count(*) from mt5_pending_orders where"
        " upper(coalesce(status,''))='PENDING'\").fetchone()[0];"
        "d=G.execution_allowed();e=d.as_details();"
        "print(json.dumps({'rem002_allowed':d.allowed,"
        "'rem002_reason':e.get('reason_code'),'mirror_active':M._mirror_active(),"
        "'pending':p,'fingerprint_running':e.get('fingerprint_running'),"
        "'fingerprint_armed':e.get('fingerprint_armed')}))"
    )
    brut = distant.derniere_ligne_json(distant.executer(depot, pyt))

    # Deuxieme appel pour les ponts
    pont = (
        "import json,os,urllib.request as u\n"
        "def h(url):\n"
        "    try:\n"
        "        return u.urlopen(url.rstrip('/')+'/health',timeout=8).getcode()\n"
        "    except Exception:\n"
        "        return 0\n"
        "L=os.environ.get('MT5_BRIDGE_LIVE_URL','');"
        "D=os.environ.get('MT5_BRIDGE_URL','')\n"
        "a={}\n"
        "try:\n"
        "    r=u.Request(L.rstrip('/')+'/account',"
        "headers={'X-API-Key':os.environ.get('MT5_BRIDGE_LIVE_API_KEY','')})\n"
        "    a=json.loads(u.urlopen(r,timeout=8).read())\n"
        "except Exception:\n"
        "    pass\n"
        "print(json.dumps({'pont_live':h(L),'pont_demo':h(D),"
        "'equity':a.get('equity'),'positions':a.get('positions_count')}))"
    )
    # ⛔ Pas de `if second is not None` : un echec ici doit REMONTER. Avaler
    # le silence laissait `pont_live`/`pont_demo` absents, et `juger()`
    # annoncait « information absente » sans jamais nommer la cause.
    brut.update(distant.derniere_ligne_json(distant.executer(depot, pont)))
    return brut


def main() -> int:
    depot = pathlib.Path(__file__).resolve().parents[3]
    try:
        brut = collecter(depot)
    except Exception as e:  # noqa: BLE001
        print("ECHEC : production injoignable (%s) -- etat INDETERMINE" % e)
        return 1
    code, lignes = juger(brut)
    for l in lignes:
        print(l)
    return code


if __name__ == "__main__":
    sys.exit(main())
