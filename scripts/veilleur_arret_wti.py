#!/usr/bin/env python3
"""Applique la regle d'arret du WTI : 10 ordres OU -30 €, le premier atteint.

    python scripts/veilleur_arret_wti.py            # regarde, et agit si besoin
    python scripts/veilleur_arret_wti.py --essai    # regarde SANS rien changer
    python scripts/veilleur_arret_wti.py --bilan    # envoie l'etat quoi qu'il arrive

⛔ Pose le 2026-10-05 a la demande de Xavier. Le motif d'admission de la
reouverture du WTI se terminait par « AUCUNE regle d arret n est posee », et
c'etait encore vrai trois jours plus tard.

🔑 Mode EVENEMENT : muet tant que la borne n'est pas atteinte. Un veilleur qui
parle a chaque passage n'est plus lu — et celui-ci passe toutes les 10 minutes.

## Ce qu'il fait quand la borne tombe

1. passe l'admission du WTI a **OBSERVED** sur `admin_live`, dans les DEUX
   sens — une paire fermee a l'achat et ouverte a la vente serait a moitie
   fermee, ce qui ne veut rien dire ;
2. ecrit un motif qui porte le releve, pour qu'on sache des l'audit POURQUOI ;
3. previent sur le fil du compte.

⚠️ Il n'arrete RIEN si le releve est indisponible : fermer une paire pour une
panne de lecture serait agir sur une mesure qu'on n'a pas.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services import regle_arret_wti as ra   # noqa: E402

DB = "/app/data/trades.db"


def _etat_actuel(db) -> dict:
    """L'etat d'admission courant du WTI sur le reel, par sens."""
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
        lignes = c.execute(
            "SELECT direction, state, MAX(state_since) FROM pair_admission_state "
            "WHERE pair = ? AND destination = ? GROUP BY direction",
            (ra.PAIRE, ra.DESTINATION)).fetchall()
    return {(d or "?"): s for d, s, _ in lignes}


def _fermer(db, motif: str) -> list[str]:
    """Passe les DEUX sens a OBSERVED. Rend les sens effectivement changes."""
    quand = datetime.now(timezone.utc).isoformat()
    changes = []
    with sqlite3.connect(db) as c:
        for sens in ("buy", "sell"):
            c.execute(
                "INSERT INTO pair_admission_state "
                "(pair, state, state_since, reason, transitioned_by, "
                " direction, destination) VALUES (?,?,?,?,?,?,?)",
                (ra.PAIRE, "OBSERVED", quand, motif,
                 "auto:regle_arret_wti", sens, ra.DESTINATION))
            changes.append(sens)
    return changes


def _prevenir(titre: str, corps: str) -> bool:
    from backend.services.canaux_telegram import canal_pour, notifier
    return notifier(canal_pour(ra.DESTINATION), titre, corps, timeout=15)


def main() -> int:
    essai = "--essai" in sys.argv
    bilan = "--bilan" in sys.argv

    m = ra.releve(DB)
    v = ra.verdict(m)
    etat = _etat_actuel(DB)
    deja = all(s == "OBSERVED" for s in etat.values()) and etat
    maintenant = datetime.now(timezone.utc).strftime("%H:%M")

    print(f"{maintenant} veilleur_arret_wti : {v['motif']}")
    print(f"   etat d'admission : {etat or 'aucune ligne'}")

    if bilan:
        corps = (f"**{ra.PAIRE}** sur le compte réel, depuis la réouverture du "
                 f"3 octobre :\n\n"
                 f"• Ordres : **{m['ordres'] if m else '?'}** / {ra.MAX_ORDRES}\n"
                 f"• P&L mesuré : **{m['pnl']:+.2f} €** / "
                 f"{ra.MAX_PERTE_EUR:+.0f} €\n" if m else "• relevé indisponible\n")
        if m and m["sans_pnl"]:
            corps += (f"• ⚠️ {m['sans_pnl']} trade(s) sans montant vérifié — "
                      f"la somme porte sur {m['couverture']*100:.0f} % seulement\n")
        corps += f"\nÉtat d'admission : `{etat or 'aucune ligne'}`"
        ok = _prevenir("🛢 Budget WTI", corps)
        print(f"   bilan envoyé : {'OK' if ok else 'ECHEC'}")
        return 0 if ok else 1

    if not v["arreter"]:
        print("   rien à faire")
        return 0
    if deja:
        print("   borne atteinte, mais le WTI est DÉJÀ en OBSERVED — rien à faire")
        return 0
    if essai:
        print("   (--essai : aucune écriture)")
        return 0

    motif = (f"2026-10-05, RÈGLE D'ARRÊT posée à la demande de Xavier et "
             f"déclenchée automatiquement. {v['motif']} "
             f"⛔ Le motif de réouverture du 03/10 disait « AUCUNE règle "
             f"d'arrêt n'est posée » — celle-ci la pose : budget de "
             f"{ra.MAX_ORDRES} ordres ou {ra.MAX_PERTE_EUR:+.0f} €, le premier "
             f"atteint. Le banc pré-enregistré avait rendu 0 retenue sur 493 "
             f"cellules. Réarmer demande une décision explicite, pas un "
             f"redémarrage.")
    sens = _fermer(DB, motif)
    ok = _prevenir(
        "🛑 WTI arrêté — budget atteint",
        f"Le **WTI** repasse en `OBSERVED` sur le compte réel.\n\n"
        f"{v['motif']}\n\n"
        f"Sens fermés : {', '.join(sens)}\n\n"
        f"ℹ️ Il ne passera plus d'ordre automatique. Le rouvrir demande une "
        f"décision explicite.")
    print(f"   ⛔ WTI ARRÊTÉ ({', '.join(sens)}) — alerte "
          f"{'OK' if ok else 'ECHEC'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
