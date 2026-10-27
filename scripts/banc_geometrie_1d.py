#!/usr/bin/env python3
"""Banc : la geometrie des setups `1d` peut-elle payer ?

PRE-INSCRIT `ecbe33c` -- `docs/preinscriptions/2026-10-26-geometrie-1d.md`.
Ce banc n'a le droit d'appliquer QUE les branches de ce bloc machine. Aucun
seuil n'est decide ici.

LA QUESTION. A R:R 1,8 il faut 35,71 % de reussite (1 / (1 + 1,8)). Les setups
`1d` exigent un TP median de 21,3 % du prix, contre 0,64 % en `4h`. Est-ce
coherent avec la formule, et cette geometrie obtient-elle son seuil ?

⛔ CE QUE CE BANC NE PEUT PAS DIRE, pre-inscrit comme tel : AUCUN PLACEBO n'est
execute. Il ne compare pas a des entrees tirees au hasard sur les memes paires
et le meme horizon. Il peut donc dire si une geometrie atteint son propre seuil
ARITHMETIQUE -- jamais s'il existe un edge. Un `z` significatif ici ne
prouverait aucune information predictive.

⛔ LECTURE SEULE. Connexion `mode=ro` explicite : ce banc ne doit rien pouvoir
ecrire, meme sur defaut de code.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys

CRYPTO_BINANCE = ("BTC/USD", "ETH/USD", "XRP/USD", "LTC/USD",
                  "DOT/USD", "SOL/USD", "ADA/USD", "DOGE/USD")

# ─── Les seuils PRE-INSCRITS. Recopies ici, et verifies contre le fichier. ───
RR_ATTENDU = 1.80
RR_TOLERANCE = 0.05
REUSSITE_REQUISE_PCT = 35.71
Z_SEUIL = -2.00
VALIDITE_N_MIN = 300
VALIDITE_MFE_PCT_MIN = 99.0
VALIDITE_RR_PCT_MIN = 95.0
P2_RISK_PCT_MIN = 9.0
P2_RISK_PCT_MAX = 15.0
P4_RR_PCT_MIN = 95.0
INDECIDABLE_ECART_PT = 5.0


# ─── Fonctions pures, testables ─────────────────────────────────────────────


def rapport_rr(entry: float, sl: float, tp: float) -> float | None:
    """`|TP - entry| / |entry - SL|`. `None` si le risque est nul."""
    risque = abs(entry - sl)
    if risque <= 0:
        return None
    return abs(tp - entry) / risque


def rr_conforme(r: float | None) -> bool:
    """Le R:R vaut-il 1,80 a la tolerance pre-inscrite pres ?"""
    return r is not None and abs(r - RR_ATTENDU) <= RR_TOLERANCE


def z_binomial(succes: int, n: int, p0: float) -> float | None:
    """Statistique z UNILATERALE d'une proportion contre `p0`.

    ⛔ `None` si `n` est nul : rendre 0,0 ferait passer un echantillon VIDE
    pour « conforme au seuil », ce qui est le contraire de ne pas savoir.
    """
    if n <= 0:
        return None
    ecart_type = math.sqrt(p0 * (1.0 - p0) / n)
    if ecart_type <= 0:
        return None
    return (succes / n - p0) / ecart_type


def mediane(valeurs: list[float]) -> float | None:
    if not valeurs:
        return None
    v = sorted(valeurs)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def reussite_convention_B(issues: list[str]) -> tuple[int, int]:
    """TIMEOUT EXCLU : succes = TP1, population = TP1 + SL.

    C'est la question de GEOMETRIE : quand le prix atteint une borne, laquelle
    atteint-il ?
    """
    tp = sum(1 for o in issues if o == "TP1")
    sl = sum(1 for o in issues if o == "SL")
    return tp, tp + sl


def reussite_convention_A(lignes: list[tuple[str, float | None]]) -> tuple[int, int]:
    """TIMEOUT COMPTE a son P&L reel : un TIMEOUT gagnant compte comme succes.

    ⚠️ Un TIMEOUT sort au DERNIER PRIX CONNU, donc son signe vient d'une
    cloture arbitraire, pas d'une decision. C'est precisement pourquoi la
    pre-inscription exige que les deux conventions concordent a moins de 5
    points, et declare INDECIDABLE sinon.
    """
    succes = 0
    for issue, pnl in lignes:
        if issue == "TP1":
            succes += 1
        elif issue == "TIMEOUT" and pnl is not None and pnl > 0:
            succes += 1
    return succes, len(lignes)


def branche(reussite_pct: float | None, z: float | None,
            ecart_conventions_pt: float | None,
            valide: bool) -> str:
    """Applique MECANIQUEMENT les branches pre-inscrites. Aucun jugement.

    L'ordre compte : la validite d'abord (sinon le banc ne conclut rien dans
    aucun sens), puis l'indecidabilite, puis admission/rejet.
    """
    if not valide:
        return "NON_CONCLUANT_VALIDITE"
    if ecart_conventions_pt is None or abs(ecart_conventions_pt) >= INDECIDABLE_ECART_PT:
        return "INDECIDABLE_CONVENTIONS"
    if reussite_pct is None or z is None:
        return "NON_CONCLUANT_MESURE_ABSENTE"
    if reussite_pct >= REUSSITE_REQUISE_PCT and z >= Z_SEUIL:
        return "ADMISSION_horizon_1d_CONSERVE"
    if reussite_pct < REUSSITE_REQUISE_PCT and z < Z_SEUIL:
        return "REJET_horizon_1d_ECARTE"
    # Les deux branches exigent un ACCORD entre le taux et le z. Leur
    # desaccord n'est ni une admission ni un rejet : c'est un entre-deux, et le
    # dire est plus honnete que de choisir la branche qui arrange.
    return "NON_CONCLUANT_TAUX_ET_Z_EN_DESACCORD"


# ─── Le banc ────────────────────────────────────────────────────────────────


def mesure(db: str) -> dict:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    trous = ",".join("?" * len(CRYPTO_BINANCE))

    def lire(tf: str) -> list[tuple]:
        return c.execute(
            "SELECT pair, entry_price, stop_loss, take_profit_1, outcome,"
            "       pnl_pct_net, mfe_pct"
            "  FROM shadow_setups"
            " WHERE resolved_backfill = 1 AND timeframe = ?", (tf,)).fetchall()

    un_jour = lire("1d")
    quatre_h = lire("4h")

    # ─── P1 : la formule est-elle appliquee correctement en 1d ? ───
    rr_1d = [rapport_rr(e, sl, tp) for _, e, sl, tp, *_ in un_jour]
    conformes_1d = sum(1 for r in rr_1d if rr_conforme(r))
    p1_pct = 100.0 * conformes_1d / len(rr_1d) if rr_1d else None

    # ─── P4 : controle 4h ───
    rr_4h = [rapport_rr(e, sl, tp) for _, e, sl, tp, *_ in quatre_h]
    conformes_4h = sum(1 for r in rr_4h if rr_conforme(r))
    p4_pct = 100.0 * conformes_4h / len(rr_4h) if rr_4h else None

    # ─── P2 : le risque en 1d ───
    risques = [100.0 * abs(e - sl) / e for _, e, sl, tp, *_ in un_jour if e > 0]
    p2_med = mediane(risques)

    # ─── Les deux conventions ───
    issues_1d = [r[4] for r in un_jour]
    succes_b, n_b = reussite_convention_B(issues_1d)
    succes_a, n_a = reussite_convention_A([(r[4], r[5]) for r in un_jour])
    pct_b = 100.0 * succes_b / n_b if n_b else None
    pct_a = 100.0 * succes_a / n_a if n_a else None
    ecart_pt = (pct_a - pct_b) if (pct_a is not None and pct_b is not None) else None
    z_b = z_binomial(succes_b, n_b, REUSSITE_REQUISE_PCT / 100.0)

    # ─── La VALIDITE du rejeu, pre-inscrite ───
    avec_mfe = sum(1 for r in un_jour if r[6] is not None)
    mfe_pct = 100.0 * avec_mfe / len(un_jour) if un_jour else None
    valide = bool(
        n_b >= VALIDITE_N_MIN
        and mfe_pct is not None and mfe_pct > VALIDITE_MFE_PCT_MIN
        and p1_pct is not None and p1_pct > VALIDITE_RR_PCT_MIN
    )

    verdict = branche(pct_b, z_b, ecart_pt, valide)

    return {
        "preinscription": "docs/preinscriptions/2026-10-26-geometrie-1d.md",
        "commit_preinscription": "ecbe33c",
        "population": "resolved_backfill=1",
        # `n` et `t` sous les noms que `or-verdict` lit. Ce ne sont pas des
        # alias de complaisance : `n` EST la population du test (les 1d dont
        # une borne a ete touchee) et un `z` EST une statistique de test
        # standardisee, a variance connue. Les emettre sous ces noms est
        # exact ; ce qui serait faux, c est de fabriquer `ecart_par_trade`.
        "n": n_b,
        "t": z_b,
        "n_1d_total": len(un_jour),
        "n_1d_resolus_TP1_ou_SL": n_b,
        "n_4h_total": len(quatre_h),
        # P1
        "P1_rr_conforme_1d_pct": p1_pct,
        "P1_rr_median_1d": mediane([r for r in rr_1d if r is not None]),
        "P1_passe": (p1_pct is not None and p1_pct > VALIDITE_RR_PCT_MIN),
        # P2
        "P2_risk_pct_1d_median": p2_med,
        "P2_passe": (p2_med is not None
                     and P2_RISK_PCT_MIN <= p2_med <= P2_RISK_PCT_MAX),
        # P3
        "reussite_requise_pct": REUSSITE_REQUISE_PCT,
        "P3_reussite_1d_convention_B_pct": pct_b,
        "P3_z_binomial": z_b,
        "P3_passe": (pct_b is not None and z_b is not None
                     and pct_b < REUSSITE_REQUISE_PCT and z_b < Z_SEUIL),
        # P4
        "P4_rr_conforme_4h_pct": p4_pct,
        "P4_rr_median_4h": mediane([r for r in rr_4h if r is not None]),
        "P4_passe": (p4_pct is not None and p4_pct > P4_RR_PCT_MIN),
        # P5
        "P5_reussite_convention_A_pct": pct_a,
        "P5_ecart_conventions_pt": ecart_pt,
        "P5_passe": (ecart_pt is not None
                     and abs(ecart_pt) < INDECIDABLE_ECART_PT),
        # validite
        "validite_n_min": VALIDITE_N_MIN,
        "validite_mfe_non_nul_pct": mfe_pct,
        "valide": valide,
        "verdict": verdict,
        # ⛔ Ce que ce banc N'EST PAS. `or-verdict` attend `ecart_par_trade`,
        # qui mesure la fidelite d'un REJEU a la realite. Ce banc ne rejoue
        # rien : il lit des issues deja calculees et les compare a un seuil
        # arithmetique. Il n'a pas de second bras, donc pas d'ecart par trade.
        # Emettre 0.0 ferait croire a un rejeu parfait -- un chiffre faux vaut
        # pire que pas de chiffre.
        "ecart_par_trade": None,
        "placebo": "NON_EXECUTE",
        "limite": ("aucun placebo : ce banc ne peut dire que si une geometrie"
                   " atteint son propre seuil arithmetique, jamais s'il"
                   " existe un edge"),
    }


def rapport(r: dict) -> str:
    l = []
    a = l.append
    a("=== BANC : la geometrie 1d peut-elle payer ?")
    a(f"    pre-inscrit {r['commit_preinscription']} · population"
      f" {r['population']}")
    a("")
    a(f"  n 1d total {r['n_1d_total']}   dont resolus TP1/SL"
      f" {r['n_1d_resolus_TP1_ou_SL']}   (4h de controle : {r['n_4h_total']})")
    a("")
    a("  VALIDITE DU REJEU")
    a(f"    n resolus >= {r['validite_n_min']} ................"
      f" {r['n_1d_resolus_TP1_ou_SL']}")
    a(f"    mfe non nul > 99 % ..................... {_p(r['validite_mfe_non_nul_pct'])}")
    a(f"    R:R conforme > 95 % .................... {_p(r['P1_rr_conforme_1d_pct'])}")
    a(f"    => valide : {r['valide']}")
    a("")
    a("  PREDICTIONS")
    a(f"    P1  R:R conforme en 1d .... {_p(r['P1_rr_conforme_1d_pct'])}"
      f"  (median {_f(r['P1_rr_median_1d'])})   {_ok(r['P1_passe'])}")
    a(f"    P2  risque median en 1d ... {_p(r['P2_risk_pct_1d_median'])}"
      f"  (attendu 9-15 %)        {_ok(r['P2_passe'])}")
    a(f"    P3  reussite (conv. B) .... {_p(r['P3_reussite_1d_convention_B_pct'])}"
      f"  contre {r['reussite_requise_pct']} % requis,"
      f" z = {_f(r['P3_z_binomial'])}   {_ok(r['P3_passe'])}")
    a(f"    P4  R:R conforme en 4h .... {_p(r['P4_rr_conforme_4h_pct'])}"
      f"  (median {_f(r['P4_rr_median_4h'])})   {_ok(r['P4_passe'])}")
    a(f"    P5  ecart conventions ..... {_f(r['P5_ecart_conventions_pt'])} pt"
      f"  (A {_p(r['P5_reussite_convention_A_pct'])})      {_ok(r['P5_passe'])}")
    a("")
    a(f"  VERDICT : {r['verdict']}")
    a("")
    a(f"  ⛔ {r['limite']}")
    return "\n".join(l)


def _p(v):
    return "   --  " if v is None else f"{v:6.2f} %"


def _f(v):
    return "  --  " if v is None else f"{v:+6.3f}"


def _ok(b):
    return "PASSE" if b else "echoue"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default="/app/data/trades.db")
    p.add_argument("--json", help="ecrire le resultat machine ici")
    a = p.parse_args()
    r = mesure(a.db)
    print(rapport(r))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(r, f, indent=2, ensure_ascii=False)
        print(f"\n  resultat machine : {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
