#!/usr/bin/env python3
"""Sonde du test « LA MAIN EN EUROS » — déclaré dans `07a37d0`.

Elle attend que la fenêtre soit pleine, mesure UNE fois, et se taît ensuite.

⛔ LE GARDE-FOU CENTRAL : sous `N_MINIMUM`, elle ne CALCULE rien. Pas « elle ne
parle pas » — elle ne calcule pas. Un chiffre intermédiaire dans un journal
suffit à créer l'arrêt optionnel : on regarde à n=12, on n'aime pas, on attend
le suivant. C'est la tricherie la plus facile et la plus invisible du métier,
et elle ne se corrige pas par la discipline mais par le code.

⛔ ET ELLE NE PARLE QU'UNE FOIS. Un marqueur est écrit après le verdict.
Rejouer chaque semaine puis retenir la semaine favorable serait la même
tricherie par l'autre bout.
"""

from __future__ import annotations

import math
import os
import sqlite3
import statistics as st
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services import pair_pnl_regulator as reg  # noqa: E402
from backend.services.risk_eur import calculer  # noqa: E402

DEBUT = os.getenv("MAIN_EUR_DEBUT", "2026-10-01T00:00")
DEST = os.getenv("MAIN_EUR_DEST", "admin_live")
N_MINIMUM = int(os.getenv("MAIN_EUR_N_MIN", "30"))
SEUIL_MOYENNE = float(os.getenv("MAIN_EUR_SEUIL", "3.00"))
SEUIL_GARDE = float(os.getenv("MAIN_EUR_SEUIL_GARDE", "1.50"))
BARRE_T = float(os.getenv("MAIN_EUR_BARRE_T", "2.0"))
MARQUEUR = Path(os.getenv("MAIN_EUR_MARQUEUR",
                          "/app/data/.sonde-main-euros-dit"))


def telegram(msg: str) -> bool:
    jeton = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not jeton or not chat:
        return False
    data = urllib.parse.urlencode({"chat_id": chat, "text": msg}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(
                "https://api.telegram.org/bot%s/sendMessage" % jeton,
                data=data), timeout=10) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    if MARQUEUR.exists():
        print("verdict deja rendu le %s — silence" % MARQUEUR.read_text()[:19])
        return 0

    c = sqlite3.connect("file:" + reg._db_path() + "?mode=ro", uri=True)
    c.row_factory = sqlite3.Row

    # ⛔ D'ABORD LE COMPTE, ET RIEN D'AUTRE.
    n = c.execute("""
      select count(*) from contrefactuels_sortie
      where destination_id = ? and close_reason = 'MANUAL'
        and r_realise is not null and r_contrefactuel is not null
        and closed_at >= ?""", (DEST, DEBUT)).fetchone()[0]
    print("fenetre depuis %s : %d contrefactuels resolus (minimum %d)"
          % (DEBUT[:10], n, N_MINIMUM))
    if n < N_MINIMUM:
        print("  sous le minimum : AUCUNE mesure calculee, aucune trace.")
        print("  (c'est le garde-fou contre l'arret optionnel, pas un oubli)")
        return 0

    rows = list(c.execute("""
      select f.pair, f.entry_price, f.sl, f.r_realise, f.r_contrefactuel,
             f.issue, t.size_lot
      from contrefactuels_sortie f
      join personal_trades t on t.id = f.trade_id
      where f.destination_id = ? and f.close_reason = 'MANUAL'
        and f.r_realise is not null and f.r_contrefactuel is not null
        and f.closed_at >= ?""", (DEST, DEBUT)))

    gains, evites = [], 0
    for r in rows:
        if r["issue"] == "SL":
            evites += 1
        try:
            m = calculer(r["pair"], float(r["entry_price"]), float(r["sl"]),
                         0.0, float(r["size_lot"]))
        except Exception:  # noqa: BLE001
            continue
        if not m or m.get("risque_eur", 0) <= 0:
            continue
        gains.append((float(r["r_realise"]) - float(r["r_contrefactuel"]))
                     * m["risque_eur"])

    if len(gains) < N_MINIMUM:
        print("  %d gains calculables seulement — fenetre incomplete, on attend"
              % len(gains))
        return 0

    moyenne = st.mean(gains)
    mediane = st.median(gains)
    ecart = st.stdev(gains)
    t = moyenne / (ecart / math.sqrt(len(gains))) if ecart > 1e-9 else 0.0
    k = max(1, int(0.10 * len(gains)))
    tronquee = st.mean(sorted(gains)[k:-k]) if len(gains) > 2 * k else moyenne
    sans_meilleur = st.mean(sorted(gains)[:-1])

    g1 = mediane > 0
    g2 = tronquee > SEUIL_GARDE
    g3 = sans_meilleur > SEUIL_GARDE
    seuils = moyenne > SEUIL_MOYENNE and abs(t) > BARRE_T

    lignes = [
        "🔬 LA MAIN EN EUROS — verdict unique (declaration 07a37d0)",
        "",
        "n=%d · %d stops evites" % (len(gains), evites),
        "moyenne %+.2f EUR (seuil %+.2f) · t=%+.2f (barre %.1f)"
        % (moyenne, SEUIL_MOYENNE, t, BARRE_T),
        "mediane %+.2f · tronquee 10%% %+.2f · sans le meilleur %+.2f"
        % (mediane, tronquee, sans_meilleur),
        "",
        "garde-fous : mediane>0 %s · tronquee>%.2f %s · sans-meilleur>%.2f %s"
        % ("OK" if g1 else "NON", SEUIL_GARDE, "OK" if g2 else "NON",
           SEUIL_GARDE, "OK" if g3 else "NON"),
        "",
    ]
    if seuils and g1 and g2 and g3:
        lignes.append("✅ EFFET CONFIRME — le premier de ce projet.")
    elif seuils:
        lignes.append("⚠️ Seuils atteints mais un garde-fou tombe : effet PORTE "
                      "PAR LA QUEUE, non retenu.")
    else:
        lignes.append("⛔ REFUTE : la main n'est pas mecanisable en euros.")
    texte = "\n".join(lignes)
    print(texte)
    if telegram(texte):
        try:
            from datetime import datetime, timezone
            MARQUEUR.write_text(datetime.now(timezone.utc).isoformat())
            print("\nmarqueur ecrit : la sonde ne parlera plus")
        except OSError as e:
            print("marqueur non ecrit (%s) — elle reparlerait" % e, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
