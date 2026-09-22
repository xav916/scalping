"""Remet `WTI/USD` en AUTO_EXEC sur la DÉMO, pour que son essai de banc accumule.

## Ce que ce script fait, et sa limite

Décision de Xavier du 2026-09-22 : réhabiliter `WTI/USD`. L'essai
`rehabilitation-wti-2026-09-22` est déclaré au banc, mais le banc ne juge que des
clôtures `is_auto = 1` **postérieures** à la déclaration. Un instrument qui ne
s'auto-exécute nulle part n'en produira jamais une seule, et l'essai resterait
ouvert indéfiniment sans rien mesurer.

⛔ **Démo uniquement.** La destination est codée en dur à `admin_legacy` et n'est
pas paramétrable. Aucun argent réel n'est engagé, et le passage au réel demandera
trois conditions distinctes (essai passé, contrôle inter-paires,
`r_contrefactuel_moyen >= 0`).

## 🔑 Pourquoi ce script DIAGNOSTIQUE avant d'agir

L'état d'admission n'est que le quatrième maillon de la chaîne. `_check_rejection`
consulte, dans cet ordre :

    1. `MT5_BRIDGE_BLOCKED_PAIRS`   — blocklist chirurgicale
    2. whitelist PAR DESTINATION    — opt-in STRICT : si elle est non vide,
                                      seules ses paires passent
    3. `pair_pnl_regulator`         — pause automatique par paire
    4. `pair_admission_state`       — ce que ce script modifie

⚠️ **Basculer le 4 sans vérifier les 1 à 3 produit un silence**, pas un trade : la
paire serait « AUTO_EXEC » dans la table et refusée en amont à chaque cycle. C'est
exactement le motif qui a coûté cher au registre des destinations — quatre endroits
à changer, quatre oublis, aucune erreur levée.

Le script affiche donc l'état des quatre maillons, et dit si la bascule suffira.

## Usage

    sudo docker exec scalping-radar python scripts/reouvrir_wti_demo.py
    sudo docker exec scalping-radar python scripts/reouvrir_wti_demo.py --vraiment
"""
from __future__ import annotations

import argparse
import pathlib
import sys

# ⛔ `python scripts/x.py` met `scripts/` dans sys.path, PAS la racine du projet :
# `import backend` echoue alors avec ModuleNotFoundError. Meme piege que le
# lanceur du bilan croise (2026-09-09), qui exigeait un PYTHONPATH a l'appel.
# On le resout ICI plutot que dans chaque invocation — un script qui ne tourne
# que sous une variable d'environnement finit par ne pas tourner.
_RACINE = str(pathlib.Path(__file__).resolve().parent.parent)
if _RACINE not in sys.path:
    sys.path.insert(0, _RACINE)

PAIRE = "WTI/USD"
DESTINATION = "admin_legacy"          # ⛔ la démo, et rien d'autre
SENS = ("buy", "sell")

MOTIF = (
    "reouverture manuelle 2026-09-22 sur decision de Xavier : mesurer la "
    "rehabilitation de WTI/USD sous les trois protections entrees en service "
    "depuis ses mauvais chiffres (NO_FRIDAY_LATE_OPEN_ENERGY 03/08, fermeture "
    "du vendredi elargie 04/09, blackout news repare 20/09). DEMO uniquement. "
    "Essai de banc : rehabilitation-wti-2026-09-22. Prior defavorable assume : "
    "116 trades reels a 6,1 % de reussite, shadow a WR 11 % pour -205 EUR."
)


def _diagnostic(pac) -> list[str]:
    """Rend la liste des maillons qui bloqueraient ENCORE apres la bascule."""
    from config import settings
    blocages = []

    bloquees = {p.upper() for p in getattr(settings, "MT5_BRIDGE_BLOCKED_PAIRS", ())}
    print(f"  1. blocklist            : {sorted(bloquees) or 'vide'}")
    if PAIRE.upper() in bloquees:
        blocages.append("MT5_BRIDGE_BLOCKED_PAIRS contient WTI/USD")

    from backend.services import mt5_bridge
    wl = {p.upper() for p in getattr(mt5_bridge, "LEGACY_WHITELIST_PAIRS", ())}
    print(f"  2. whitelist {DESTINATION} : {sorted(wl) or 'vide (= tout passe)'}")
    if wl and PAIRE.upper() not in wl:
        blocages.append(
            f"la whitelist {DESTINATION} est non vide et ne contient pas WTI/USD "
            "— opt-in STRICT, la bascule ne suffira pas")

    try:
        from backend.services import pair_pnl_regulator
        en_pause = pair_pnl_regulator.is_paused(PAIRE, DESTINATION)
    except Exception as e:  # noqa: BLE001
        en_pause = None
        print(f"  3. regulateur PnL       : illisible ({e})")
    if en_pause is not None:
        print(f"  3. regulateur PnL       : {'EN PAUSE' if en_pause else 'ouvert'}")
        if en_pause:
            blocages.append("pair_pnl_regulator tient WTI/USD en pause")

    print("  4. etat d'admission     :")
    for sens in SENS:
        etat = pac.get_current_state(PAIRE, sens, DESTINATION)
        print(f"       {sens:5} -> {etat}")
    return blocages


def main() -> int:
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("--vraiment", action="store_true",
                   help="applique la bascule (sinon : diagnostic seul)")
    args = a.parse_args()

    from backend.services import pair_admission_controller as pac

    print(f"{PAIRE} sur {DESTINATION} — les quatre maillons :\n")
    blocages = _diagnostic(pac)
    print()

    if blocages:
        print("⚠️ LA BASCULE NE SUFFIRA PAS. Bloque encore en amont :")
        for b in blocages:
            print(f"   - {b}")
        print("   Traiter ces points d'abord, sinon la paire sera AUTO_EXEC dans")
        print("   la table et refusee a chaque cycle — un silence, pas un trade.")
        print()

    if not args.vraiment:
        print("DIAGNOSTIC SEUL — rien n'a ete modifie. Relancer avec --vraiment.")
        return 0

    change = 0
    for sens in SENS:
        try:
            r = pac.set_state(PAIRE, pac.STATE_AUTO_EXEC, MOTIF, direction=sens,
                              transitioned_by="manual:xavier", destination=DESTINATION)
        except PermissionError as e:
            print(f"  {sens:5} REFUSE par le banc : {e}")
            return 1
        if r == -1:
            print(f"  {sens:5} deja AUTO_EXEC — sans effet")
        else:
            print(f"  {sens:5} -> AUTO_EXEC")
            change += 1

    print(f"\n{change} transition(s) ecrite(s).")
    if blocages:
        print("⚠️ Rappel : un maillon amont bloque encore (voir ci-dessus).")
    else:
        print("Les quatre maillons sont ouverts : WTI peut produire des clotures,")
        print("et l'essai rehabilitation-wti-2026-09-22 commencera a accumuler.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
