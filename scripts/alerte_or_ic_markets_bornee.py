#!/usr/bin/env python3
"""Alerte bornee sur l'or d'IC Markets apres la reprise manuelle du 30/09.

POURQUOI
--------
Le 30/09, la pause du regulateur sur `XAU/USD` @ `admin_live` a ete levee a la
main alors que la mesure la JUSTIFIAIT (-11,245 R sur 28 trades). Xavier a
choisi une levee **bornee** : etre prevenu des que la reprise a produit assez
de donnee pour redecider, au lieu d'attendre 14 jours.

DEUX DECLENCHEURS, le premier atteint gagne :
  - 3 ordres or pousses sur `admin_live` depuis la reprise ;
  - -2 R cumules sur les trades or clotures depuis la reprise.

⛔ Le seuil du regulateur n'est pas touche : cette alerte ne bloque RIEN, elle
parle. Le garde-fou qui bloque reste `pair_pnl_regulator`, qui reprend la main
des `PAIR_PNL_REGULATOR_MIN_NOUVEAUX_APRES_REPRISE` trades nouveaux.

🔑 Le R est calcule par le code de PRODUCTION (`risk_eur.calculer` et le filtre
des stops placebos du laboratoire). Ne jamais le reimplementer ici : deux
arithmetiques du risque divergeraient, et c'est exactement le defaut qui a
fait poser quatre pauses fausses sur l'or.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.parse
import urllib.request
from pathlib import Path

PAIRE = os.getenv("ALERTE_OR_PAIRE", "XAU/USD")
DESTINATION = os.getenv("ALERTE_OR_DESTINATION", "admin_live")
SEUIL_ORDRES = int(os.getenv("ALERTE_OR_SEUIL_ORDRES", "3"))
SEUIL_R = float(os.getenv("ALERTE_OR_SEUIL_R", "-2.0"))
ETAT = Path(os.getenv("ALERTE_OR_ETAT", "/app/data/alerte_or_ic_markets.json"))


def _telegram(msg: str) -> bool:
    jeton = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not jeton or not chat:
        print("telegram non configure", file=sys.stderr)
        return False
    data = urllib.parse.urlencode(
        {"chat_id": chat, "text": msg, "disable_web_page_preview": "true"}
    ).encode()
    try:
        with urllib.request.urlopen(
            urllib.request.Request(
                "https://api.telegram.org/bot%s/sendMessage" % jeton, data=data
            ),
            timeout=10,
        ) as r:
            return r.status == 200
    except Exception as e:  # noqa: BLE001
        print("telegram echec: %s" % e, file=sys.stderr)
        return False


def _r_depuis(chemin_db: str, depuis: str) -> tuple[float, int, int]:
    """(somme des R, n mesurables, n total) des trades clotures depuis `depuis`.

    Reutilise strictement les regles du regulateur : stops placebos ecartes,
    risque converti en euros avant division.
    """
    from backend.services.laboratoire_or import PLACEBO_PCT
    from backend.services.risk_eur import calculer

    c = sqlite3.connect("file:" + chemin_db + "?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    rows = list(c.execute(
        """
        select entry_price, stop_loss, size_lot, pnl
        from personal_trades
        where pair = ? and destination_id = ? and pnl is not null
          and closed_at is not null and closed_at > ?
        """,
        (PAIRE, DESTINATION, depuis),
    ))
    somme, n_mes = 0.0, 0
    for r in rows:
        e, s, lot = r["entry_price"], r["stop_loss"], r["size_lot"]
        if e is None or s is None or not lot or float(e) <= 0:
            continue
        if abs(float(e) - float(s)) / float(e) < PLACEBO_PCT:
            continue
        mes = calculer(PAIRE, e, s, 0.0, lot)
        if not mes or mes["risque_eur"] <= 0:
            continue
        somme += float(r["pnl"]) / mes["risque_eur"]
        n_mes += 1
    return somme, n_mes, len(rows)


def main() -> int:
    from backend.services import pair_pnl_regulator as reg

    reprise = reg.derniere_reprise_manuelle(PAIRE, DESTINATION)
    if not reprise:
        print("aucune reprise manuelle sur %s@%s — rien a surveiller"
              % (PAIRE, DESTINATION))
        return 0

    etat = {}
    try:
        etat = json.loads(ETAT.read_text())
    except Exception:  # noqa: BLE001
        pass
    if etat.get("reprise") != reprise:
        etat = {"reprise": reprise, "annonce": False}  # nouvelle reprise

    chemin = reg._db_path()
    with sqlite3.connect("file:" + chemin + "?mode=ro", uri=True) as c:
        n_ordres = int(c.execute(
            "select count(*) from mt5_pushes where pair=? and destination_id=? "
            "and pushed_at > ?", (PAIRE, DESTINATION, reprise)).fetchone()[0])

    somme_r, n_mes, n_fermes = _r_depuis(chemin, reprise)

    print("reprise %s | %d ordre(s) | %d cloture(s) | %+.2f R sur %d mesurable(s)"
          % (reprise[:19], n_ordres, n_fermes, somme_r, n_mes))

    motifs = []
    if n_ordres >= SEUIL_ORDRES:
        motifs.append("%d ordres pousses (seuil %d)" % (n_ordres, SEUIL_ORDRES))
    if n_mes and somme_r <= SEUIL_R:
        motifs.append("%+.2f R cumules (seuil %+.1f)" % (somme_r, SEUIL_R))

    if not motifs:
        print("sous les deux seuils, silence")
        return 0
    if etat.get("annonce"):
        print("deja annonce pour cette reprise, silence")
        return 0

    msg = "\n".join([
        "🟡 [admin_live] OR sur IC Markets — la levee bornee a produit sa donnee",
        "",
        "Declencheur : " + " ET ".join(motifs),
        "",
        "Depuis la reprise du %s :" % reprise[:16],
        "  • %d ordre(s) pousse(s)" % n_ordres,
        "  • %d trade(s) cloture(s), %+.2f R sur %d mesurable(s)"
        % (n_fermes, somme_r, n_mes),
        "",
        "La fenetre qui avait justifie la pause valait -11,245 R sur 28 trades.",
        "A toi de redecider : laisser courir, ou refermer avec",
        "execution_switch / pair_pnl_regulator.",
    ])
    if _telegram(msg):
        etat["annonce"] = True
        try:
            ETAT.write_text(json.dumps(etat))
        except OSError as e:
            print("etat non ecrit: %s" % e, file=sys.stderr)
        print("alerte envoyee")
    return 0


if __name__ == "__main__":
    sys.exit(main())
