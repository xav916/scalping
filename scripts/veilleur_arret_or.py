#!/usr/bin/env python3
"""Applique la regle d'arret de l'or : 60 ordres OU -50 EUR d'AUTOMATIQUE.

    python scripts/veilleur_arret_or.py            # regarde, et ALERTE si besoin
    python scripts/veilleur_arret_or.py --essai    # regarde SANS rien envoyer
    python scripts/veilleur_arret_or.py --bilan    # envoie l'etat quoi qu'il arrive
    python scripts/veilleur_arret_or.py --fermer   # ferme l'or si la borne est tombee

Pose le 2026-10-07. Le motif d'ouverture de tous les horizons de l'or
(2026-10-01, `dc3c067`) se terminait par « AUCUNE regle d arret n est posee »,
comme celui du WTI, et c'etait encore vrai une semaine plus tard.

Mode EVENEMENT : muet tant que la borne n'est pas atteinte. Un veilleur qui
parle a chaque passage n'est plus lu.

## CE QU'IL FAIT QUAND LA BORNE TOMBE -- ET CE QU'IL NE FAIT PAS

Il **previent, chiffre, et s'arrete la**. Contrairement au WTI, il ne ferme
RIEN de lui-meme.

    L'or a deux sorties : le code (18 fermetures, -22,25 EUR) et la main
    (6 fermetures, +72,34 EUR). La main ne peut fermer que ce que le code a
    OUVERT. Passer l'or en OBSERVED supprimerait donc les deux.

=> La decision reste a Xavier. `--fermer` existe pour qu'il puisse l'armer
explicitement, jamais par defaut.

Il n'alerte sur RIEN si le releve est indisponible : annoncer une borne
franchie sur une mesure qu'on n'a pas, c'est inventer.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services import regle_arret_or as ra   # noqa: E402

DB = "/app/data/trades.db"

# Une alerte par palier franchi, pas une par passage. Le palier est la borne
# elle-meme : tant qu'elle n'a pas bouge, l'or n'est annonce qu'une fois.
MARQUEUR = Path("/app/data/.arret_or_alerte")


def _etat_actuel(db) -> dict:
    """L'etat d'admission courant de l'or sur le reel, par sens."""
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
        lignes = c.execute(
            "SELECT direction, state, MAX(state_since) FROM pair_admission_state "
            "WHERE pair = ? AND destination = ? GROUP BY direction",
            (ra.PAIRE, ra.DESTINATION)).fetchall()
    return {(d or "?"): s for d, s, _ in lignes}


def _deja_annonce(cle: str) -> bool:
    """Best-effort : un marqueur illisible fait PARLER, jamais taire.

    Se tromper en parlant coute une notification. Se tromper en se taisant
    coute l'alerte elle-meme.
    """
    try:
        return MARQUEUR.read_text(encoding="utf-8").strip() == cle
    except Exception:  # noqa: BLE001
        return False


def _noter_annonce(cle: str) -> None:
    try:
        MARQUEUR.write_text(cle, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"   (marqueur non ecrit : {e} — l'alerte pourra se repeter)")


def _fermer(db, motif: str) -> list[str]:
    """Passe les DEUX sens a OBSERVED. Rend les sens effectivement changes.

    Une paire fermee a l'achat et ouverte a la vente serait a moitie fermee,
    ce qui ne veut rien dire.
    """
    quand = datetime.now(timezone.utc).isoformat()
    changes = []
    with sqlite3.connect(db) as c:
        for sens in ("buy", "sell"):
            c.execute(
                "INSERT INTO pair_admission_state "
                "(pair, state, state_since, reason, transitioned_by, "
                " direction, destination) VALUES (?,?,?,?,?,?,?)",
                (ra.PAIRE, "OBSERVED", quand, motif,
                 "auto:regle_arret_or", sens, ra.DESTINATION))
            changes.append(sens)
    return changes


def _prevenir(titre: str, corps: str) -> bool:
    from backend.services.canaux_telegram import canal_pour, notifier
    return notifier(canal_pour(ra.DESTINATION), titre, corps, timeout=15)


def _corps_bilan(m: dict | None, etat: dict) -> str:
    if not m:
        return "relevé indisponible — rien n'est conclu."
    corps = (
        f"**{ra.PAIRE}** sur le compte réel, depuis l'ouverture de tous ses "
        f"horizons le 1er octobre :\n\n"
        f"• Ordres : **{m['ordres']}** / {ra.MAX_ORDRES}\n"
        f"• Ce que le **code** a fait tout seul : **{m['pnl_auto']:+.2f} €** "
        f"/ {ra.MAX_PERTE_EUR:+.0f} €, sur {m['ordres_auto']} fermeture(s)\n"
        f"• Ce que **ta main** a fait : **{m['pnl_main']:+.2f} €** sur "
        f"{m['ordres_main']} fermeture(s) de positions **du radar**\n")
    # ⛔ 2026-10-09. L'adoption (`ac2823b`) fait entrer ses trades du TERMINAL
    # MT5 dans la base. Separes par la seule `close_reason`, ceux fermes par
    # leur stop tombaient dans la jambe AUTOMATIQUE : 87 % de la << perte du
    # code >> etaient ses propres stops, et la regle a franchi ses deux bornes
    # le jour du deploiement, par artefact.
    #
    # 🔑 Les sortir de la BORNE ne doit pas les sortir du MESSAGE : 45,42 € de
    # stops reels effaces du compte-rendu seraient une perte invisible.
    #
    # ⚠️ `.get` et non `[...]` : le `.py` est recopie par `docker cp` a chaque
    # passage du cron, veilleur et regle peuvent etre desynchronises une fois.
    # Un `KeyError` rendrait le bilan MUET, ce qui est pire qu'incomplet.
    if m.get("ordres_terminal"):
        corps += (f"• À part, **ouverts dans le terminal MT5** : "
                  f"**{m['pnl_terminal']:+.2f} €** sur "
                  f"{m['ordres_terminal']} trade(s) — **hors borne**, c'est "
                  f"ton volume à toi\n")
    if m["sans_pnl"]:
        corps += (f"• ⚠️ {m['sans_pnl']} clôture(s) sans montant vérifié — la "
                  f"somme ne porte que sur {m['couverture'] * 100:.0f} %\n")
    corps += (f"\nℹ️ La borne de perte ne juge que le **code** : tes gains à la "
              f"main ne témoignent pas de lui, et les mettre dans la somme "
              f"masquerait ses pertes.\n\n"
              f"État d'admission : `{etat or 'aucune ligne'}`")
    return corps


def main() -> int:
    essai = "--essai" in sys.argv
    bilan = "--bilan" in sys.argv
    fermer = "--fermer" in sys.argv

    m = ra.releve(DB)
    v = ra.verdict(m)
    etat = _etat_actuel(DB)
    deja_observed = bool(etat) and all(s == "OBSERVED" for s in etat.values())
    maintenant = datetime.now(timezone.utc).strftime("%H:%M")

    print(f"{maintenant} veilleur_arret_or : {v['motif']}")
    print(f"   etat d'admission : {etat or 'aucune ligne'}")

    if bilan:
        ok = _prevenir("🥇 Budget de l'or", _corps_bilan(m, etat))
        print(f"   bilan envoyé : {'OK' if ok else 'ECHEC'}")
        return 0 if ok else 1

    if not v["borne_atteinte"]:
        print("   rien à faire")
        return 0

    # La cle du palier : tant que les bornes ne bougent pas, une seule alerte.
    cle = f"{ra.MAX_ORDRES}/{ra.MAX_PERTE_EUR}"
    if _deja_annonce(cle) and not fermer:
        print("   borne atteinte, mais DÉJÀ annoncée pour ce palier")
        return 0
    if essai:
        print("   (--essai : rien envoyé, rien écrit)")
        return 0

    if fermer and not deja_observed:
        motif = (
            f"2026-10-07, RÈGLE D'ARRÊT de l'or, déclenchée avec --fermer. "
            f"{v['motif']} ⛔ L'ouverture de tous les horizons le 01/10 "
            f"(`dc3c067`) se faisait contre le laboratoire : 0 retenue sur "
            f"232 cellules, R négatif aux quatre échelles. Budget : "
            f"{ra.MAX_ORDRES} ordres ou {ra.MAX_PERTE_EUR:+.0f} € "
            f"d'automatique, le premier atteint. Réarmer demande une décision "
            f"explicite, pas un redémarrage.")
        sens = _fermer(DB, motif)
        ok = _prevenir(
            "🛑 Or arrêté — budget atteint",
            f"L'**or** repasse en `OBSERVED` sur le compte réel.\n\n"
            f"{v['motif']}\n\nSens fermés : {', '.join(sens)}\n\n"
            f"⚠️ Tes fermetures à la main s'arrêtent aussi : elles ne peuvent "
            f"fermer que ce que le code ouvre.")
        _noter_annonce(cle)
        print(f"   ⛔ OR ARRÊTÉ ({', '.join(sens)}) — alerte "
              f"{'OK' if ok else 'ECHEC'}")
        return 0

    ok = _prevenir(
        "⚠️ Or — budget de l'expérience atteint",
        f"La borne posée sur l'**or** est franchie. **Rien n'a été fermé** : "
        f"la décision est à toi.\n\n{v['motif']}\n\n"
        f"{_corps_bilan(m, etat)}\n\n"
        f"🔑 Trois issues : **laisser courir** (relever la borne), **arrêter "
        f"l'or** (il ne passera plus d'ordre automatique — et tu ne pourras "
        f"plus fermer à la main ce qu'il n'ouvre plus), ou **ne garder que "
        f"certains horizons**.")
    if ok:
        _noter_annonce(cle)
    print(f"   ⚠️ borne atteinte — alerte {'OK' if ok else 'ECHEC'} "
          f"(aucune fermeture : mode alerte)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
