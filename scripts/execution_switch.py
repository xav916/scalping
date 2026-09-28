#!/usr/bin/env python3
"""Armer / fermer / interroger le verrou d'execution global — REM-002.

    python scripts/execution_switch.py status
    python scripts/execution_switch.py arm   --raison "..." --par "prenom"
    python scripts/execution_switch.py close --raison "..." --par "prenom"
    python scripts/execution_switch.py bloquer   <nom> --raison "..."
    python scripts/execution_switch.py debloquer <nom>

⛔ A lancer DANS le conteneur, jamais sur l'hote : c'est le conteneur qui voit
le manifest de l'image et le volume d'etat.

    sudo docker exec -it scalping python scripts/execution_switch.py status

🔑 Apres chaque deploiement, l'execution est FERMEE. C'est voulu : le
deploiement est le moment ou l'on ne sait plus ce qui tourne. `arm` est le
geste qui dit « j'ai verifie ce code-la ».

⚠️ `arm` refuse si l'integrite du deploiement n'est pas bonne. Ce n'est pas un
obstacle a contourner : c'est le controle qui fonctionne.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services import deployment_manifest as dm  # noqa: E402
from backend.services import global_execution_switch as ges  # noqa: E402


def _afficher_statut() -> int:
    v = dm.public_version()
    st = ges.status()
    print("─── CODE QUI TOURNE " + "─" * 41)
    print(f"  integrite          {v['status']}")
    print(f"  commit (image)     {(v['git_commit_sha'] or '?')[:12]}"
          f"  branche {v['git_branch']}")
    print(f"  commit attendu     {(v['expected_commit'] or '(non pose)')[:12]}")
    print(f"  build              {v['build_timestamp']}")
    print(f"  environnement      {v['build_environment']}")
    print("─── EXECUTION " + "─" * 47)
    print(f"  LIVE EXECUTION     {st['live_execution']}")
    print(f"  decision           {st['decision']}  ({st['reason_code']})")
    if st.get("detail"):
        print(f"  detail             {st['detail']}")
    print(f"  arme pour          {st['fingerprint_armed'] or '(rien)'}")
    print(f"  tourne             {st['fingerprint_running'] or '(inconnu)'}")
    if st.get("armed_at"):
        print(f"  arme le            {st['armed_at']} par {st['armed_by']}")
        print(f"  raison             {st['armed_reason']}")
    if st.get("blocages"):
        print(f"  ⛔ BLOCAGES         {', '.join(st['blocages'])}")
    if st.get("configuration_drift"):
        print("  ⚠️  DERIVE DE CONFIGURATION depuis l'armement")
        print(f"     armee   {st['configuration_hash_armed']}")
        print(f"     courante {st['configuration_hash_current']}")
        print("     🔴 REM-023 non livre : cette derive NE ferme PAS la porte.")
    print("─" * 60)
    return 0 if st["live_execution"] == "ON" else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="etat complet, lisible")
    for nom, aide in (("arm", "ouvrir l'execution pour CE deploiement"),
                      ("close", "fermer l'execution")):
        p = sub.add_parser(nom, help=aide)
        p.add_argument("--raison", required=True)
        p.add_argument("--par", default="manual")
    pb = sub.add_parser("bloquer", help="poser un blocage d'integrite")
    pb.add_argument("nom")
    pb.add_argument("--raison", default=None)
    pd = sub.add_parser("debloquer", help="lever un blocage d'integrite")
    pd.add_argument("nom")
    sub.add_parser("json", help="statut brut en JSON")

    a = ap.parse_args()

    if a.cmd == "status":
        return _afficher_statut()

    if a.cmd == "json":
        print(json.dumps(
            {"version": dm.public_version(), "execution": ges.status()},
            indent=2, ensure_ascii=False))
        return 0

    if a.cmd == "arm":
        d = ges.arm(a.raison, by=a.par)
        if not d.allowed:
            print(f"⛔ ARMEMENT REFUSE : {d.reason_code}", file=sys.stderr)
            print(f"   {d.detail}", file=sys.stderr)
            print("   Ce refus est le controle qui fonctionne. Corriger la "
                  "cause, ne pas le contourner.", file=sys.stderr)
            _afficher_statut()
            return 2
        print(f"✅ execution ARMEE pour {d.fingerprint_armed}")
        return _afficher_statut()

    if a.cmd == "close":
        ges.disarm(a.raison, by=a.par)
        print("⛔ execution FERMEE")
        return _afficher_statut()

    if a.cmd == "bloquer":
        if a.nom not in ges.BLOCAGES_CONNUS:
            print(f"⚠️  « {a.nom} » n'est pas un blocage declare. Il est pose "
                  f"quand meme (un blocage inconnu doit fermer).\n"
                  f"   Declares : {', '.join(ges.BLOCAGES_CONNUS)}",
                  file=sys.stderr)
        ges.set_blocage(a.nom, True, detail=a.raison)
        return _afficher_statut()

    if a.cmd == "debloquer":
        ges.set_blocage(a.nom, False)
        return _afficher_statut()

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
