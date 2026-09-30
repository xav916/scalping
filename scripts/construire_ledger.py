#!/usr/bin/env python3
"""REM-005 — construit le ledger financier et publie ce qu'il IGNORE.

    python scripts/construire_ledger.py                 # construit + rapport
    python scripts/construire_ledger.py --rapport       # rapport seul
    python scripts/construire_ledger.py --base /tmp/c.db  # sur une COPIE

⛔ LE RAPPORT EST LA LIVRAISON, autant que la table. Un ledger à 31 colonnes
dont on ne dit pas lesquelles sont vides invite précisément à la conclusion
qu'il devait empêcher : « la colonne existe, donc le chiffre est connu ».

🔑 `--base` sert à construire le ledger AILLEURS que sur la base vivante :
sur une copie pour un essai à blanc, ou sur une sauvegarde restaurée pour
vérifier une histoire. Sans lui, la seule façon d'essayer serait d'écrire
dans la base de production.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services import pair_pnl_regulator as reg  # noqa: E402
from backend.services import trade_ledger as ledger  # noqa: E402

# Les colonnes dont le vide est une DÉCISION documentée, pas un manque à
# combler. Les afficher comme un trou parmi d'autres laisserait croire qu'un
# prochain chantier les remplira ; le module explique pourquoi non.
VIDES_ASSUMEES = {
    "strategy_id": "aucune notion de strategie dans les donnees",
    "experiment_id": "aucune notion d experience dans les donnees",
    "spread_cost": "integre au prix par le courtier, non separable",
    "fx_effect": "deja dans le P&L en devise de compte",
    "deployment_commit": "REM-003 n horodate que depuis le 28/09",
    "configuration_hash": "l empreinte actuelle hache des valeurs vides",
}


def main() -> int:
    rapport_seul = "--rapport" in sys.argv
    chemin = reg._db_path()
    if "--base" in sys.argv:
        chemin = sys.argv[sys.argv.index("--base") + 1]
    print("base : %s\n" % chemin)
    conn = sqlite3.connect(chemin)

    if not rapport_seul:
        res = ledger.construire(conn)
        print("LEDGER CONSTRUIT — %d lignes pour %d trades"
              % (res["lignes"], res["trades"]))
        print("  le %s\n" % res["construit_le"][:19])
    else:
        ledger.creer_table(conn)
        print("RAPPORT SEUL — la table n a pas ete reecrite\n")

    print("=== CE QUE LE LEDGER SAIT, colonne par colonne")
    connu = inconnu = assume = 0
    for li in ledger.rapport_completude(conn):
        col, pct = li["colonne"], li["pct"]
        note = ""
        if col in VIDES_ASSUMEES:
            note = "  <- vide ASSUME : %s" % VIDES_ASSUMEES[col]
            assume += 1
        elif pct >= 99.0:
            connu += 1
        elif pct < 50.0:
            inconnu += 1
        barre = "#" * int(pct / 5) + "." * (20 - int(pct / 5))
        print("  %-20s %5d / %-5d %5.1f%% %s%s"
              % (col, li["rempli"], li["sur"], pct, barre, note))

    print("\n  %d colonnes quasi completes · %d sous 50%% · %d vides assumees"
          % (connu, inconnu, assume))

    print("\n=== PROVENANCE DE L ARGENT — la question qui decide tout")
    for col in ("src_argent", "src_entree", "src_sortie", "src_cloture",
                "src_risque"):
        # ⚠️ `tuple(r)` est obligatoire : `construire()` a posé un
        # `row_factory = sqlite3.Row` sur la connexion, et un `Row` ne se
        # déballe pas par `%`. Sans lui le rapport meurt APRÈS avoir écrit
        # le ledger — la table serait bonne et la livraison illisible.
        lots = [tuple(r) for r in conn.execute(
            "select coalesce(%s,'(inconnu)'), count(*) from %s "
            "group by 1 order by 2 desc" % (col, ledger.TABLE))]
        print("  %-12s %s" % (col, " · ".join("%s=%d" % r for r in lots)))

    print("\n=== L IDENTITE DU COURTIER : net = brut + swap + commission + fee")
    v = ledger.verifier_identite_courtier(conn)
    print("  concordent %d · divergent %d" % (v["concordent"], v["divergent"]))
    for d in v["pires"][:5]:
        print("     ticket %-12s ecart %+8.2f  (brut %+8.2f  net %+8.2f)"
              % (d["ticket"], d["ecart"], d["brut"], d["net"]))

    print("\n=== REM-006 — LE P&L PAR CATEGORIE, sur l argent VERIFIE")
    print("  (les trades sans instantane courtier sont EXCLUS : leur net est")
    print("   inconnu, et les sommer produirait un total d air)")
    for li in ledger.rapport_categories(conn):
        marque = "  ⛔ BUG_AFFECTED" if li["bug_affected"] == 1 else ""
        print("  %-20s n=%-5d net %+9.2f EUR%s"
              % (li["categorie"] or "(non classable)", li["trades"],
                 li["net"] or 0.0, marque))
    non_classables = conn.execute(
        "select count(*) from %s where categorie_pnl is null" % ledger.TABLE
    ).fetchone()[0]
    sans_env = conn.execute(
        "select count(*) from %s where environment is null" % ledger.TABLE
    ).fetchone()[0]
    print("  ⚠️ %d trades NON CLASSABLES au total —" % non_classables)
    print("     le cahier exigeait « exactement une categorie » ; ces trades")
    print("     n en ont aucune, et leur en donner une serait l inventer.")
    # 🔑 L'ECART AVEC LES SANS-ENVIRONNEMENT EST NORMAL et doit etre dit :
    # une cloture a la main reste attribuable meme quand le compte est
    # inconnu, puisque c'est la main qui a decide du sort du trade.
    print("     (%d trades sans environnement, dont %d restent classes par la"
          % (sans_env, sans_env - non_classables))
    print("      main — elle a decide du resultat, compte connu ou non)")

    print("\n=== CE QUI EST DEFENDABLE, une fois le ledger lu")
    n = conn.execute("select count(*) from %s" % ledger.TABLE).fetchone()[0]
    verifie = conn.execute(
        "select count(*) from %s where src_argent='courtier'"
        % ledger.TABLE).fetchone()[0]
    reel = conn.execute(
        "select count(*) from %s where environment='REAL' "
        "and src_argent='courtier'" % ledger.TABLE).fetchone()[0]
    somme = conn.execute(
        "select sum(net_pnl) from %s where src_argent='courtier' "
        "and environment='REAL'" % ledger.TABLE).fetchone()[0]
    affectes = conn.execute(
        "select count(*) from %s where bug_affected=1" % ledger.TABLE
    ).fetchone()[0]
    print("  %d trades au total, dont %d avec un argent VERIFIE au courtier"
          % (n, verifie))
    print("  sur argent reel ET verifie : %d trades, net %+.2f EUR"
          % (reel, somme or 0.0))
    print("  marques BUG_AFFECTED : %d — les %d autres sont NON QUALIFIES,"
          % (affectes, n - affectes))
    print("     ce qui n est pas la meme chose que « sains ».")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
