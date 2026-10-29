"""La charge Python executee DANS le conteneur de production.

Elle existe pour une seule raison : les portes lisent la configuration
d'environnement et la base de production. Les juger depuis un poste, avec
d'autres variables, rendrait un verdict qui ne decrit aucune realite.

⛔ Elle APPELLE `_check_rejection` et `asset_class_for`. Elle n'en recopie
aucune clause : une porte reimplementee divergerait a la premiere
modification et rendrait une reponse assuree et fausse.

⚠️ UNE exception, declaree : la clause de classe d'actif (`allowed_asset_classes`
du `BridgeConfig`, code `asset_class_blocked`) EST reconstruite ici. La
production l'applique dans `mt5_bridge._push_to_destination`, apres
`_check_rejection` -- et cette fonction envoie des ordres, donc inutilisable
dans un miroir en lecture seule. C'est la SEULE porte reconstruite de toute
la skill (voir SKILL.md).
"""
from __future__ import annotations

import json

_SOURCE = '''
import json, sys
sys.path.insert(0, "/app")
from types import SimpleNamespace
from backend.services import mt5_bridge as M
from backend.services import bridge_destinations as BD
from backend.services import order_cooldown as OC
from backend.services import pair_admission_controller as A
from backend.services import rejection_service as RS
from backend.services import global_execution_switch as G
from config.settings import asset_class_for

LOT = json.loads(%(lot)s)

# La production itere `admin_destinations()` (`mt5_bridge.py:2612`), pas le
# registre : seules TROIS destinations y rendent un objet non-None le
# 2026-10-29 (admin_legacy, admin_live, admin_kraken). Le registre des
# destinations ne sert plus a decider quoi que ce soit ici.
_ACTIVES = {d.destination_id: d for d in BD.admin_destinations()}

def limites(d):
    sante = {}
    try:
        from backend.services import plafond_arbitrage as P
        sante = P._lire_health(d.destination_id, avec_compte=False) or {}
    except Exception:
        sante = {}
    gf = sante.get("garde_fous") or {}
    return {
        "order_cooldown_sec": OC.delai_requis(d),
        "max_risque_engage_pct": gf.get("max_risque_engage_pct"),
        "places_par_paire": gf.get("max_open_positions"),
    }

verdicts, lim, libelles, sans = [], {}, {}, set()
for nom in LOT["destinations"]:
    d = _ACTIVES.get(nom)
    if d is None:
        print(json.dumps({"erreur": "destination inconnue: %%s" %% nom,
                          "connues": sorted(_ACTIVES)}))
        raise SystemExit(0)
    lim[nom] = limites(d)
    for i, s in enumerate(LOT["setups"]):
        setup = SimpleNamespace(**s)
        try:
            code = M._check_rejection(setup, d)
            classe = asset_class_for(s["pair"])
            if not code and classe not in d.allowed_asset_classes:
                # ⚠️ SEULE porte RECONSTRUITE de toute la charge (cf.
                # SKILL.md). La production l'applique dans
                # `_push_to_destination`, APRES `_check_rejection` -- et
                # cette fonction envoie des ordres, donc inutilisable dans un
                # miroir en lecture seule. "asset_class_blocked" est donc
                # l'UNIQUE reason_code ecrit en dur ici, a dessein.
                code = "asset_class_blocked"
            admission = A.get_current_state(
                s["pair"], direction=s.get("direction"), destination=nom)
        except Exception as e:
            code = "porte_en_erreur:%%s" %% type(e).__name__
            classe = None
            admission = None
        if code and not code.startswith("_") and not code.startswith("porte_en_erreur:"):
            lab = RS.REASON_LABELS_FR.get(code)
            if lab:
                libelles[code] = lab
            else:
                sans.add(code)
        verdicts.append({
            "i": i, "destination": nom, "reason_code": code,
            "classe": classe,
            "admission": admission,
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
