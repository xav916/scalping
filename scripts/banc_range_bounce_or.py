"""Banc : le retour a la moyenne sur l'or a-t-il RAPPORTE ?

Pre-inscription : `docs/predictions/2026-10-31_range_bounce_or.md`, commitee
AVANT ce fichier -- `or-preinscription` le verifie par l'ancestralite git.

⛔ LECTURE SEULE. Aucun INSERT, aucun UPDATE, aucune ecriture. Un banc qui
ecrit sur la production n'est plus un banc.

Usage, depuis l'hote (le conteneur porte la base) :

    ssh ... 'sudo docker exec -i scalping-radar python3 -' < scripts/banc_range_bounce_or.py

Il IMPRIME des chiffres. Il ne publie aucun verdict : c'est `or-verdict` qui
decide si les chiffres peuvent sortir, et la pre-inscription dit deja qu'aucun
majorant ne sera annonce.
"""
from __future__ import annotations

import math
import random
import sqlite3

#: Fixee pour que le plafond soit reproductible a l'identique.
GRAINE = 42
N_PERMUTATIONS = 200

#: Les 3 cellules, telles que DECLAREES dans la pre-inscription. Les ajouter
#: ici apres coup serait du p-hacking : le plafond est calibre sur 3.
CELLULES = (
    ("1. range_bounce (tous sens)", lambda m: m.startswith("range_bounce")),
    ("2. range_bounce_up", lambda m: m == "range_bounce_up"),
    ("3. range_bounce_down", lambda m: m == "range_bounce_down"),
)


def welch_t(a: list[float], b: list[float]) -> float:
    """Le `t` de Welch, calcule a la main.

    Pas de dependance : un banc qui ne tourne pas faute de scipy sur l'hote
    ne mesure rien. La formule est courte et verifiable a l'oeil.
    """
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return float("nan")
    ma, mb = sum(a) / na, sum(b) / nb
    va = sum((x - ma) ** 2 for x in a) / (na - 1)
    vb = sum((x - mb) ** 2 for x in b) / (nb - 1)
    denom = math.sqrt(va / na + vb / nb)
    if denom == 0:
        return float("nan")
    return (ma - mb) / denom


def plafond_permutation(valeurs: list[float], n_dedans: int) -> float:
    """p95 de `|t|` obtenu en MELANGEANT l'etiquette de motif.

    🔑 C'est le temoin de la cellule : si le `t` reel ne depasse pas ce que le
    hasard produit en redistribuant les etiquettes, la cellule n'a rien dit.
    Le 14/10, sept cellules passaient a `t = 2` -- et le hasard seul en
    faisait passer autant.
    """
    rng = random.Random(GRAINE)
    obtenus = []
    copie = list(valeurs)
    for _ in range(N_PERMUTATIONS):
        rng.shuffle(copie)
        t = welch_t(copie[:n_dedans], copie[n_dedans:])
        if not math.isnan(t):
            obtenus.append(abs(t))
    if not obtenus:
        return float("nan")
    obtenus.sort()
    return obtenus[min(len(obtenus) - 1, int(0.95 * len(obtenus)))]


def main() -> None:
    from backend.services import pair_admission_controller as pac

    with sqlite3.connect("file:%s?mode=ro" % pac._db_path(), uri=True) as c:
        c.row_factory = sqlite3.Row
        lignes = c.execute("""
            SELECT p.pattern AS motif, b.pnl_net AS net, b.pnl AS brut
            FROM mt5_pushes p
            JOIN broker_close_snapshots b ON b.ticket = p.mt5_ticket
            WHERE p.pair = 'XAU/USD'
        """).fetchall()

    total = len(lignes)
    sans_net = sum(1 for r in lignes if r["net"] is None)
    part_manquant = (sans_net / total) if total else 1.0

    print("=== VALIDITE DU REJEU ===")
    print("  trades joints          : %d" % total)
    print("  sans pnl_net           : %d" % sans_net)
    print("  part manquante         : %.4f  (seuil de validite : < 0.02)"
          % part_manquant)
    valide = part_manquant < 0.02
    print("  REJEU %s" % ("VALIDE" if valide else "INVALIDE -- on ne juge pas"))
    if not valide:
        return

    retenus = [r for r in lignes if r["net"] is not None]
    print()
    print("=== LES 3 CELLULES DECLAREES ===")
    resultats = []
    for nom, dedans in CELLULES:
        a = [float(r["net"]) for r in retenus if dedans(r["motif"] or "")]
        b = [float(r["net"]) for r in retenus if not dedans(r["motif"] or "")]
        if len(a) < 2:
            print("  %-28s n=%d -- trop peu pour juger" % (nom, len(a)))
            continue
        t = welch_t(a, b)
        moy_a, moy_b = sum(a) / len(a), sum(b) / len(b)
        plaf = plafond_permutation(a + b, len(a))
        bat = (not math.isnan(t)) and (not math.isnan(plaf)) and abs(t) > plaf
        admis = (t > 2) and (moy_a > 0) and bat
        resultats.append((nom, len(a), moy_a, moy_b, t, plaf, bat, admis))
        print("  %-28s n=%-4d moyenne=%+8.3f EUR  (temoin %+8.3f)"
              % (nom, len(a), moy_a, moy_b))
        print("  %-28s t=%+6.3f   plafond p95=%5.3f   bat le plafond : %s"
              % ("", t, plaf, "OUI" if bat else "non"))
        print("  %-28s ADMISSION (t>+2 ET moyenne>0 ET bat le plafond) : %s"
              % ("", "OUI" if admis else "NON"))
        print()

    # --- P4 : le sens haussier est-il meilleur ? ---------------------------
    up = [float(r["net"]) for r in retenus if r["motif"] == "range_bounce_up"]
    dn = [float(r["net"]) for r in retenus if r["motif"] == "range_bounce_down"]
    print("=== P4 : ecart entre les deux sens ===")
    if len(up) >= 2 and len(dn) >= 2:
        ecart = sum(up) / len(up) - sum(dn) / len(dn)
        print("  up n=%d moyenne=%+.3f | down n=%d moyenne=%+.3f | ecart=%+.3f EUR"
              % (len(up), sum(up) / len(up), len(dn), sum(dn) / len(dn), ecart))
        print("  |ecart| < 2 EUR : %s" % ("OUI" if abs(ecart) < 2 else "NON"))
    else:
        print("  echantillon insuffisant")

    # --- de quoi juger les predictions, sans les juger ici -----------------
    print()
    print("=== MATIERE POUR LES PREDICTIONS (le verdict appartient a or-verdict) ===")
    c1 = next((r for r in resultats if r[0].startswith("1.")), None)
    if c1:
        print("  P1 moyenne nette negative      : moyenne = %+.3f EUR" % c1[2])
        print("  P2 indiscernable (|t| < 2)     : |t| = %.3f" % abs(c1[4]))
    au_dela = [r for r in resultats if abs(r[4]) > 2]
    print("  P3 cellules a |t| > 2          : %d sur %d"
          % (len(au_dela), len(resultats)))
    for r in au_dela:
        print("     %-28s bat le plafond : %s" % (r[0], "OUI" if r[6] else "non"))
    print()
    print("  cellules ADMISES : %d" % sum(1 for r in resultats if r[7]))


if __name__ == "__main__":
    main()
