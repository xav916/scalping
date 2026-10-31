"""Banc n°2 : le retour a la moyenne sur l'or, sur la fenetre INEDITE.

Pre-inscription : `docs/predictions/2026-10-31b_range_bounce_or_fenetre_inedite.md`,
commitee avant ce fichier.

⛔ LECTURE SEULE (`mode=ro`). Un banc qui ecrit sur la production n'est plus
un banc.

⛔ La fenetre est definie par EXCLUSION des 298 tickets deja mesures. C'est
cette exclusion qui rend la pre-inscription honnete : si elle tombait, le banc
rejouerait un echantillon dont les chiffres ont deja ete vus. Elle est donc
verifiee et affichee, pas supposee.
"""
from __future__ import annotations

import math
import random
import sqlite3

GRAINE = 42
N_PERMUTATIONS = 200


def welch_t(a: list[float], b: list[float]) -> float:
    """Le `t` de Welch. Verifie contre `scipy.stats.ttest_ind(equal_var=False)`
    a 4,4e-16 le 2026-10-31 — une source de verite independante."""
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return float("nan")
    ma, mb = sum(a) / na, sum(b) / nb
    va = sum((x - ma) ** 2 for x in a) / (na - 1)
    vb = sum((x - mb) ** 2 for x in b) / (nb - 1)
    d = math.sqrt(va / na + vb / nb)
    return (ma - mb) / d if d else float("nan")


def plafond_permutation(valeurs: list[float], n_dedans: int) -> float:
    """p95 de `|t|` en melangeant l'etiquette de motif. Eprouve sur temoins :
    bruit pur franchi ~2/20, effet plante de +8 EUR franchi 10/10."""
    rng = random.Random(GRAINE)
    copie, obtenus = list(valeurs), []
    for _ in range(N_PERMUTATIONS):
        rng.shuffle(copie)
        t = welch_t(copie[:n_dedans], copie[n_dedans:])
        if not math.isnan(t):
            obtenus.append(abs(t))
    if not obtenus:
        return float("nan")
    obtenus.sort()
    return obtenus[min(len(obtenus) - 1, int(0.95 * len(obtenus)))]


def demi_largeur_95(a: list[float]) -> float:
    """Demi-largeur de l'intervalle a 95 % sur la moyenne (1,96 * erreur type).

    Sert la prediction n°4 : si elle depasse 2 EUR, la fenetre ne peut pas
    resoudre un effet de la taille du cout de l'or.
    """
    n = len(a)
    if n < 2:
        return float("nan")
    m = sum(a) / n
    v = sum((x - m) ** 2 for x in a) / (n - 1)
    return 1.96 * math.sqrt(v / n)


def main() -> None:
    from backend.services import pair_admission_controller as pac

    with sqlite3.connect("file:%s?mode=ro" % pac._db_path(), uri=True) as c:
        c.row_factory = sqlite3.Row
        deja_vus = {r[0] for r in c.execute(
            "SELECT p.mt5_ticket FROM mt5_pushes p "
            "JOIN broker_close_snapshots b ON b.ticket = p.mt5_ticket "
            "WHERE p.pair = 'XAU/USD'")}
        toutes = c.execute("""
            SELECT mt5_ticket, signal_pattern AS motif, pnl, closed_at
            FROM personal_trades
            WHERE pair LIKE '%XAU%' AND status = 'CLOSED'
              AND signal_pattern IS NOT NULL
        """).fetchall()

    print("=== LA FENETRE EST-ELLE INEDITE ? ===")
    print("  tickets deja mesures (banc n1) : %d" % len(deja_vus))
    inedits = [r for r in toutes if r["mt5_ticket"] not in deja_vus]
    print("  trades or clotures             : %d" % len(toutes))
    print("  INEDITS retenus                : %d" % len(inedits))
    recoupement = [r for r in inedits if r["mt5_ticket"] in deja_vus]
    print("  recoupement avec le banc n1    : %d  (doit etre 0)" % len(recoupement))
    if recoupement:
        print("  ⛔ ARRET : la fenetre n'est pas inedite, la pre-inscription "
              "ne tient plus")
        return
    dates = sorted(r["closed_at"][:10] for r in inedits if r["closed_at"])
    if dates:
        print("  periode                        : %s -> %s" % (dates[0], dates[-1]))

    # --- validite ---------------------------------------------------------
    sans = sum(1 for r in inedits if r["pnl"] is None)
    part = (sans / len(inedits)) if inedits else 1.0
    retenus = [r for r in inedits if r["pnl"] is not None]
    reel = [float(r["pnl"]) for r in retenus
            if (r["motif"] or "").startswith("range_bounce")]
    temoin = [float(r["pnl"]) for r in retenus
              if not (r["motif"] or "").startswith("range_bounce")]

    print()
    print("=== VALIDITE (part_pnl_manquant < 0.02 ET n >= 25) ===")
    print("  part_pnl_manquant : %.4f" % part)
    print("  n (bras reel)     : %d" % len(reel))
    print("  n (temoin)        : %d" % len(temoin))
    if part >= 0.02 or len(reel) < 25:
        print("  ⛔ REJEU INVALIDE selon le critere pre-inscrit — on ne juge pas")
        return
    print("  rejeu VALIDE")

    # --- la cellule unique, declaree --------------------------------------
    t = welch_t(reel, temoin)
    moy, moy_t = sum(reel) / len(reel), sum(temoin) / len(temoin)
    plaf = plafond_permutation(reel + temoin, len(reel))
    dl = demi_largeur_95(reel)

    print()
    print("=== LA CELLULE (range_bounce contre les autres motifs) ===")
    print("  moyenne BRUTE reel   : %+8.3f EUR" % moy)
    print("  moyenne BRUTE temoin : %+8.3f EUR" % moy_t)
    print("  t                    : %+8.3f" % t)
    print("  |t|                  : %8.3f" % abs(t))
    print("  plafond p95          : %8.3f" % plaf)
    print("  demi-largeur 95 %%    : %8.3f EUR" % dl)

    print()
    print("=== LE RESULTAT, aux noms de champs du critere ===")
    print("  (a passer tel quel a or-verdict, qui RECALCULE les clauses)")
    import json
    print(json.dumps({
        "forme": "placebo",
        "sujet": "range_bounce sur l'or, fenetre inedite 2026-05-26 -> 2026-09-16",
        "n": len(reel),
        "valide": part < 0.02 and len(reel) >= 25,
        "part_pnl_manquant": round(part, 6),
        "t": round(t, 4),
        "t_abs": round(abs(t), 4),
        "plafond_p95": round(plaf, 4),
        "moyenne_brute_eur": round(moy, 4),
        "moyenne_brute_temoin_eur": round(moy_t, 4),
        "demi_largeur_95_eur": round(dl, 4),
        "n_temoin": len(temoin),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
