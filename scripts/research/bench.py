#!/usr/bin/env python3
"""Banc d'essai hors-échantillon — ligne de commande.

    python -m scripts.research.bench counter
    python -m scripts.research.bench declare h4-or-vente \
        --hypothese "Le 4h sur l'or à la vente porte un edge" \
        --paires XAU/USD --sens sell --destinations admin_live \
        --variantes 6 --echantillon 30 --auteur xavier
    python -m scripts.research.bench list
    python -m scripts.research.bench status h4-or-vente
    python -m scripts.research.bench evaluate h4-or-vente

⛔ `evaluate` scelle le verdict. Il ne se rejoue pas — c'est ce qui empêche de
réessayer jusqu'à ce que ça passe.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services import research_bench as rb  # noqa: E402


def _fmt(x, n=4):
    return "—" if x is None else f"{x:+.{n}f}"


def cmd_counter(_):
    n = rb.counter()
    print(f"N = {n} variantes déclarées\n")
    print("Plafond du hasard, selon la longueur d'échantillon de l'essai :")
    print(f"  {'jours':>6} {'Sharpe/jour':>13} {'annualisé':>11}")
    for T in (128, 182, 365, 730, 1095):
        s0 = rb.sharpe_attendu_sous_h0(rb.var_sr_h0(T), n)
        print(f"  {T:>6} {s0:>13.4f} {s0 * (365 ** 0.5):>11.2f}")
    print("\n⛔ Le plafond décroît en 1/√T : un essai long est jugé sur une barre")
    print("   plus basse. Un essai qui déclare la dispersion mesurée entre ses")
    print("   variantes (--var-sr) est jugé sur elle plutôt que sur ce repli.")


def cmd_declare(a):
    selector = {}
    if a.paires:
        selector["pairs"] = a.paires
    if a.sens:
        selector["direction"] = a.sens
    if a.confiance is not None:
        selector["min_confidence"] = a.confiance
    if a.destinations:
        selector["destinations"] = a.destinations
    rb.declare(a.slug, a.hypothese, selector, a.variantes, a.auteur, a.echantillon,
               var_sr=a.var_sr)
    t = rb.get_trial(a.slug)
    print(f"Essai « {a.slug} » ouvert le {t['declared_at'][:19]}")
    print(f"  sélecteur   {json.dumps(t['selector'], ensure_ascii=False)}")
    print(f"  variantes   {t['variants_declared']}   échantillon requis {t['min_sample']}")
    print(f"  empreinte   {t['declaration_hash'][:16]}…")
    print(f"\n⛔ Seules les clôtures postérieures à cet instant compteront.")
    print(f"N passe à {rb.counter()}.")


def cmd_list(a):
    trials = rb.list_trials(a.statut)
    if not trials:
        print("Aucun essai.")
        return
    print(f"{'slug':<28} {'statut':<10} {'var':>4} {'n':>5} {'DSR':>8}  verdict")
    for t in trials:
        print(f"{t['slug'][:28]:<28} {t['status']:<10} {t['variants_declared']:>4} "
              f"{t['n_obs'] or 0:>5} {_fmt(t['dsr'], 4) if t['dsr'] is not None else '       —':>8}"
              f"  {(t['verdict'] or '')[:44]}")


def cmd_status(a):
    t = rb.get_trial(a.slug)
    if not t:
        print(f"Essai inconnu : {a.slug}", file=sys.stderr)
        sys.exit(1)
    print(f"« {t['slug'] } » — {t['status']}")
    print(f"  déclaré le  {t['declared_at'][:19]} par {t['author']}")
    print(f"  hypothèse   {t['hypothesis']}")
    print(f"  sélecteur   {json.dumps(t['selector'], ensure_ascii=False)}")
    print(f"  variantes   {t['variants_declared']}   échantillon requis {t['min_sample']}")
    if t["status"] == "open":
        # ⛔ `status` ne déclenche JAMAIS d'évaluation : consulter un essai ne doit
        # pas dépenser son unique verdict.
        print("  → ouvert. `evaluate` scelle le verdict, une seule fois.")
    if t["verdict"]:
        print(f"  verdict     {t['verdict']}")
        print(f"  DSR {_fmt(t['dsr'])}   SR {_fmt(t['sr'])}   seuil H0 {_fmt(t['sr0'])}"
              f"   n={t['n_obs']}   N={t['n_trials_at_verdict']}")


def cmd_evaluate(a):
    r = rb.evaluate(a.slug)
    if r["status"] == "open":
        print(f"Rien à lire : {r['n_obs']}/{r['min_sample']} clôtures.")
        return
    print(f"« {a.slug} » — {r['verdict']}")
    print(f"  clôtures    {r['n_obs']}   P&L {r['sum_pnl']:+.2f} €   jours {r['T']}")
    print(f"  Sharpe/jour {_fmt(r['sr'])}   plafond H0 {_fmt(r['sr0'])}   N={r['n_trials']}")
    print(f"  variance retenue {r['var_sr']:.6f}"
          f"{'  (declaree)' if r['var_sr'] != rb.var_sr_h0(r['T']) else '  (repli 1/T)'}")
    print(f"  dissymétrie {r['skew']:+.3f}   aplatissement {r['kurt']:.3f}")
    print(f"  DSR         {r['dsr']:.4f}   seuil {rb.DSR_SEUIL}")
    print("\n" + ("✅ PASSÉ" if r["passed"] else "⛔ REFUSÉ"))
    sys.exit(0 if r["passed"] else 2)


def cmd_abandon(a):
    print("abandonné." if rb.abandon(a.slug, a.motif) else "aucun essai ouvert sous ce slug.")
    print(f"N reste à {rb.counter()} — abandonner ne rend pas les variantes.")


def cmd_seed(a):
    rb.seed_legacy(a.slug, a.variantes, a.note)
    print(f"Héritage inscrit. N = {rb.counter()}.")


def cmd_grant(a):
    rb.grant_legacy(a.pair, a.sens, a.destination, a.motif)
    print(f"Antériorité accordée à {a.pair}/{a.sens or 'tous sens'}@{a.destination or 'toutes'}.")


def main(argv=None):
    p = argparse.ArgumentParser(prog="bench", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("counter", help="N et le plafond du hasard associé").set_defaults(f=cmd_counter)

    d = sub.add_parser("declare", help="pré-enregistrer une hypothèse")
    d.add_argument("slug")
    d.add_argument("--hypothese", required=True)
    d.add_argument("--variantes", type=int, required=True,
                   help="combien de configurations ce test balaie — alimente N")
    d.add_argument("--auteur", default="xavier")
    d.add_argument("--paires", nargs="*")
    d.add_argument("--sens", choices=["buy", "sell"])
    d.add_argument("--confiance", type=float)
    d.add_argument("--destinations", nargs="*")
    d.add_argument("--echantillon", type=int, default=30)
    d.add_argument("--var-sr", dest="var_sr", type=float,
                   help="dispersion MESUREE des Sharpe entre les variantes de cet essai ; "
                        "sans elle, le repli theorique 1/T s'applique")
    d.set_defaults(f=cmd_declare)

    l = sub.add_parser("list", help="les essais du registre")
    l.add_argument("--statut", choices=["open", "spent", "abandoned", "legacy"])
    l.set_defaults(f=cmd_list)

    s = sub.add_parser("status", help="le détail d'un essai")
    s.add_argument("slug"); s.set_defaults(f=cmd_status)

    e = sub.add_parser("evaluate", help="sceller le verdict — une seule fois")
    e.add_argument("slug"); e.set_defaults(f=cmd_evaluate)

    ab = sub.add_parser("abandon", help="fermer sans verdict ; N ne bouge pas")
    ab.add_argument("slug"); ab.add_argument("--motif", required=True)
    ab.set_defaults(f=cmd_abandon)

    sd = sub.add_parser("seed-legacy", help="inscrire l'héritage du journal dans N")
    sd.add_argument("slug"); sd.add_argument("--variantes", type=int, required=True)
    sd.add_argument("--note", required=True); sd.set_defaults(f=cmd_seed)

    g = sub.add_parser("grant-legacy", help="clause d'antériorité pour l'existant")
    g.add_argument("pair"); g.add_argument("--sens", choices=["buy", "sell"])
    g.add_argument("--destination"); g.add_argument("--motif", required=True)
    g.set_defaults(f=cmd_grant)

    a = p.parse_args(argv)
    # ⛔ Un refus attendu n'est pas un plantage. Le banc refuse par conception —
    # rejeu d'un essai dépensé, déclaration altérée, slug déjà pris. Laisser
    # remonter une trace d'exécution dirait « le programme est cassé » au moment
    # précis où il fait son travail, et la première réaction serait de le réparer.
    try:
        a.f(a)
    except (rb.EssaiDepense, rb.DeclarationAlteree, ValueError) as e:
        print(f"refusé : {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
