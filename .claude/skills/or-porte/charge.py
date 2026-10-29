"""La charge Python executee DANS le conteneur de production.

Elle existe pour une seule raison : les portes lisent la configuration
d'environnement et la base de production. Les juger depuis un poste, avec
d'autres variables, rendrait un verdict qui ne decrit aucune realite.

⛔ Elle APPELLE `_check_rejection` et `asset_class_for`. Elle n'en recopie
aucune clause : une porte reimplementee divergerait a la premiere
modification et rendrait une reponse assuree et fausse.
"""
from __future__ import annotations

import json

_SOURCE = '''
import json, sys
sys.path.insert(0, "/app")
from types import SimpleNamespace
from backend.services import mt5_bridge as M
from backend.services import destinations_registry as R
from backend.services import pair_admission_controller as A
from backend.services import rejection_service as RS
from backend.services import global_execution_switch as G
from config.settings import asset_class_for

LOT = json.loads(%(lot)s)

def limites(d):
    sante = {}
    try:
        from backend.services import plafond_arbitrage as P
        sante = P._lire_health(d.id, avec_compte=False) or {}
    except Exception:
        sante = {}
    gf = sante.get("garde_fous") or {}
    return {
        "max_correlated_positions": getattr(d, "max_correlated_positions", None),
        "order_cooldown_sec": getattr(d, "order_cooldown_sec", None),
        "max_risque_engage_pct": gf.get("max_risque_engage_pct"),
        "places_par_paire": gf.get("max_open_positions"),
    }

verdicts, lim, libelles, sans = [], {}, {}, set()
for nom in LOT["destinations"]:
    d = R.get(nom)
    if d is None:
        print(json.dumps({"erreur": "destination inconnue: %%s" %% nom,
                          "connues": sorted(R.ids())}))
        raise SystemExit(0)
    lim[nom] = limites(d)
    for i, s in enumerate(LOT["setups"]):
        setup = SimpleNamespace(**s)
        try:
            code = M._check_rejection(setup, d)
        except Exception as e:
            code = "porte_en_erreur:%%s" %% type(e).__name__
        if code and not code.startswith("_"):
            lab = RS.REASON_LABELS_FR.get(code)
            if lab:
                libelles[code] = lab
            else:
                sans.add(code)
        verdicts.append({
            "i": i, "destination": nom, "reason_code": code,
            "classe": asset_class_for(s["pair"]),
            "admission": A.get_current_state(
                s["pair"], direction=s.get("direction"), destination=nom),
        })

det = G.execution_allowed().as_details()
print(json.dumps({
    "fingerprint_running": det.get("fingerprint_running"),
    "rem002_allowed": G.execution_allowed().allowed,
    "rem002_reason": det.get("reason_code"),
    "verdicts": verdicts, "limites": lim,
    "libelles": libelles, "sans_libelle": sorted(sans),
}))
'''


def construire(lot: dict) -> str:
    """Le code Python a executer dans le conteneur, lot embarque en JSON."""
    return _SOURCE % {"lot": json.dumps(json.dumps(lot))}
