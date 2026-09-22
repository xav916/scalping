"""Ce qui bloque `XAU/USD` et `WTI/USD` sur **IC Markets (argent réel)**, et pourquoi.

⛔ **Ce script ne modifie RIEN.** Il n'écrit pas en base, ne touche aucune variable
d'environnement, ne promeut aucune paire. Il lit et il rapporte.

Écrit le 2026-09-22, Xavier ayant décidé de rouvrir les deux instruments sur
`admin_live`. Avant d'en discuter, il faut savoir ce que le système exige — et il
exige plus qu'une bascule d'état d'admission.

## Les six portes de `admin_live`

`_check_rejection` et `set_state` consultent, dans cet ordre :

    1. MT5_BRIDGE_BLOCKED_PAIRS           blocklist globale
    2. MT5_BRIDGE_LIVE_WHITELIST_PAIRS    opt-in STRICT : non vide => seules ses paires
    3. MT5_BRIDGE_ALLOWED_ASSET_CLASSES   WTI exige la classe « energy »
    4. pair_pnl_regulator                 pause automatique par paire
    5. pair_admission_state               l'etat d'admission
    6. research_bench.gate_promotion      la porte vers l'argent reel

⚠️ Les portes 1 à 3 vivent dans `.env`, pas en base : aucun script Python ne les
ouvre. La 6 est la seule qui soit une décision de méthode.

## Ce que dit la porte 6

Elle refuse une promotion en AUTO_EXEC sur une destination qui engage de l'argent
réel, sauf si un essai passé la couvre, si la clause d'antériorité la couvre, ou si
le banc est désarmé (`RESEARCH_BENCH_GATE_ENABLED` absent — c'est le défaut, et
c'est le constat R-2 du rapport d'audit).

🔑 Les deux essais déclarés le 2026-09-22 portent sur `admin_legacy`. Ils ne
couvriront **jamais** `admin_live`, quel que soit leur verdict. Ouvrir la porte 6
légitimement demande un essai déclaré **sur cette destination**, et son échantillon.

## Usage

    sudo docker exec scalping-radar python scripts/diagnostic_or_wti_live.py
"""
from __future__ import annotations

import pathlib
import sys

_RACINE = str(pathlib.Path(__file__).resolve().parent.parent)
if _RACINE not in sys.path:
    sys.path.insert(0, _RACINE)

PAIRES = ("XAU/USD", "WTI/USD")
DESTINATION = "admin_live"
SENS = ("buy", "sell")


def main() -> int:
    from config import settings
    from backend.services import pair_admission_controller as pac
    from backend.services import pair_pnl_regulator, research_bench
    from backend.services.mt5_bridge import LIVE_WHITELIST_PAIRS, asset_class_for

    bloquees = {p.upper() for p in getattr(settings, "MT5_BRIDGE_BLOCKED_PAIRS", ())}
    classes = set(getattr(settings, "MT5_BRIDGE_ALLOWED_ASSET_CLASSES", ()) or ())
    wl = {p.upper() for p in LIVE_WHITELIST_PAIRS}
    banc_arme = bool(getattr(settings, "RESEARCH_BENCH_GATE_ENABLED", False))

    print("⛔ admin_live — ARGENT REEL. Etat des six portes.\n")
    print(f"  1. blocklist globale     : {sorted(bloquees) or 'vide'}")
    print(f"  2. whitelist admin_live  : {sorted(wl) or 'vide (= tout passe)'}")
    print(f"  3. classes admises       : {sorted(classes) or 'non lisible'}")
    print(f"  6. banc d'essai          : "
          f"{'ARME — il refusera' if banc_arme else 'DESARME (constat R-2 du rapport)'}")
    print()

    for paire in PAIRES:
        classe = asset_class_for(paire)
        print(f"  {paire}  (classe « {classe} »)")
        murs = []
        if paire.upper() in bloquees:
            murs.append("porte 1 : blocklist globale")
        if wl and paire.upper() not in wl:
            murs.append("porte 2 : absente de la whitelist admin_live (opt-in STRICT)")
        if classes and classe not in classes:
            murs.append(f"porte 3 : classe « {classe} » non admise")
        try:
            if pair_pnl_regulator.is_paused(paire, DESTINATION):
                murs.append("porte 4 : pair_pnl_regulator en pause")
        except Exception as e:  # noqa: BLE001
            print(f"     porte 4 illisible : {e}")
        for sens in SENS:
            etat = pac.get_current_state(paire, sens, DESTINATION)
            ok, motif = research_bench.gate_promotion(
                paire, "AUTO_EXEC", direction=sens, destination=DESTINATION)
            verdict = "PASSERAIT" if ok else "REFUSEE"
            print(f"     {sens:5} etat={etat:9} porte 6 : {verdict} — {motif}")
        for m in murs:
            print(f"     ⚠️ {m}")
        print()

    print("Rappel : les portes 1 a 3 vivent dans `.env`. La porte 6 se leve par un")
    print("essai declare SUR admin_live et passe — pas par les essais du 22/09, qui")
    print("portent sur admin_legacy et ne couvriront jamais cette destination.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
