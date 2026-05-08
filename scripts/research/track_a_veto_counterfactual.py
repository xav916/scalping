"""Track A × Veto géopolitique — analyse contrefactuelle.

Pour chaque setup Track A réconcilié dans `shadow_setups` :
- Extrait du snapshot ``geopolitical_features_json`` la décision
  contrefactuelle ``would_veto`` au moment du log + ``rules_matched``
- Groupe par "would_veto=True" vs "would_veto=False"
- Compare win_rate / PF / PnL% sur les 2 groupes
- Génère un rapport Markdown dans ``docs/superpowers/journal/``

But : objectiver "le veto géopolitique aurait-il amélioré ou détérioré
la performance Track A ?" sans avoir besoin de l'activer en hard rule
sur Track A. Le script est conçu pour tourner périodiquement (manuel
ou cron) jusqu'au gate S6 (2026-06-06).

Tant que ``n_recon < 30`` le verdict reste "sample insuffisant".
À partir de 30 outcomes, on peut commencer à observer un signal,
au-delà de 100 le signal devient statistiquement crédible.

Usage :
    python -m scripts.research.track_a_veto_counterfactual
    python -m scripts.research.track_a_veto_counterfactual --db /custom/path/trades.db
    python -m scripts.research.track_a_veto_counterfactual --no-write  # juste stdout
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent.parent


def _default_db_path() -> Path:
    """Résout le chemin par défaut de trades.db (équivalent trade_log_service)."""
    return ROOT / "trades.db"


# ─── Extraction ──────────────────────────────────────────────────────


def load_reconciled_setups(db_path: Path) -> list[dict]:
    """Retourne les setups Track A réconciliés (outcome != NULL) avec
    le payload ``geopolitical_features`` parsé.

    Filtre : geopolitical_features_json non-null (sinon snapshot pré-fix
    et pas exploitable pour l'analyse contrefactuelle).
    """
    if not db_path.exists():
        return []

    with sqlite3.connect(db_path) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            """
            SELECT id, system_id, pair, timeframe, direction,
                   bar_timestamp, outcome, exit_at,
                   pnl_pct_net, pnl_eur,
                   geopolitical_features_json
              FROM shadow_setups
             WHERE outcome IS NOT NULL
               AND geopolitical_features_json IS NOT NULL
             ORDER BY bar_timestamp ASC
            """
        ).fetchall()

    setups: list[dict] = []
    for r in rows:
        try:
            geo = json.loads(r["geopolitical_features_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        veto_eval = geo.get("veto_evaluated") or {}
        setups.append({
            "id": r["id"],
            "system_id": r["system_id"],
            "pair": r["pair"],
            "timeframe": r["timeframe"],
            "direction": r["direction"],
            "bar_timestamp": r["bar_timestamp"],
            "outcome": r["outcome"],
            "pnl_pct_net": r["pnl_pct_net"] or 0.0,
            "pnl_eur": r["pnl_eur"] or 0.0,
            "would_veto": bool(veto_eval.get("would_veto", False)),
            "rules_matched": list(veto_eval.get("rules_matched") or []),
            "polymarket": geo.get("polymarket") or {},
            "gdelt": geo.get("gdelt") or {},
        })
    return setups


# ─── Stats helpers ───────────────────────────────────────────────────


def compute_group_stats(setups: list[dict]) -> dict:
    """Calcule {n, win_rate, profit_factor, mean_pnl_pct, total_pnl_pct}.

    win = outcome == "TP1" (ou "TP2" si présent)
    loss = outcome == "SL"
    timeout = "TIMEOUT" : exclu du PF (ni gain franc ni perte franche),
              compté dans n_total.
    """
    n = len(setups)
    if n == 0:
        return {"n": 0, "win_rate": None, "pf": None, "mean_pnl_pct": None, "total_pnl_pct": 0.0,
                "n_tp": 0, "n_sl": 0, "n_timeout": 0}

    n_tp = sum(1 for s in setups if s["outcome"] in ("TP1", "TP2"))
    n_sl = sum(1 for s in setups if s["outcome"] == "SL")
    n_timeout = sum(1 for s in setups if s["outcome"] == "TIMEOUT")

    win_rate = (n_tp / (n_tp + n_sl)) * 100 if (n_tp + n_sl) > 0 else None

    gains = sum(s["pnl_pct_net"] for s in setups if (s["pnl_pct_net"] or 0) > 0)
    losses = abs(sum(s["pnl_pct_net"] for s in setups if (s["pnl_pct_net"] or 0) < 0))
    pf = (gains / losses) if losses > 0 else None

    total_pnl = sum(s["pnl_pct_net"] for s in setups)
    mean_pnl = total_pnl / n

    return {
        "n": n,
        "win_rate": win_rate,
        "pf": pf,
        "mean_pnl_pct": mean_pnl,
        "total_pnl_pct": total_pnl,
        "n_tp": n_tp,
        "n_sl": n_sl,
        "n_timeout": n_timeout,
    }


# ─── Sample size confidence ──────────────────────────────────────────


def _sample_verdict(n: int) -> str:
    """Verdict qualitatif sur la taille d'échantillon."""
    if n < 10:
        return "DÉRISOIRE — pas d'analyse statistiquement valide possible"
    if n < 30:
        return "INSUFFISANT — observer mais ne pas trancher"
    if n < 100:
        return "EXPLOITABLE — signal directionnel possible, intervalles larges"
    return "CRÉDIBLE — analyse statistique fiable"


# ─── Rapport Markdown ────────────────────────────────────────────────


def build_report(setups: list[dict], generated_at: datetime) -> str:
    """Construit un rapport Markdown complet."""
    n_total = len(setups)

    vetoed = [s for s in setups if s["would_veto"]]
    passed = [s for s in setups if not s["would_veto"]]

    stats_all = compute_group_stats(setups)
    stats_vetoed = compute_group_stats(vetoed)
    stats_passed = compute_group_stats(passed)

    # Stats par règle
    by_rule: dict[str, list[dict]] = defaultdict(list)
    for s in setups:
        for rule in s["rules_matched"]:
            by_rule[rule].append(s)

    # Stats par pair
    by_pair: dict[str, list[dict]] = defaultdict(list)
    for s in setups:
        by_pair[s["pair"]].append(s)

    lines: list[str] = []
    lines.append(f"# Track A × Veto géopolitique — analyse contrefactuelle")
    lines.append("")
    lines.append(f"**Généré :** {generated_at.isoformat(timespec='seconds')}")
    lines.append(f"**Source :** `shadow_setups` filtre `outcome IS NOT NULL AND geopolitical_features_json IS NOT NULL`")
    lines.append(f"**Échantillon :** {n_total} setups réconciliés")
    lines.append(f"**Confiance échantillon :** {_sample_verdict(n_total)}")
    lines.append("")

    if n_total == 0:
        lines.append("## Résultat")
        lines.append("")
        lines.append("Aucun setup réconcilié avec snapshot géopolitique. Le snapshot est capturé depuis le commit `3ac0d70` (2026-05-08). Les setups antérieurs n'ont pas de payload `geopolitical_features_json`.")
        lines.append("")
        lines.append("Re-lancer ce script dans 2-3 semaines pour avoir un sample exploitable.")
        return "\n".join(lines) + "\n"

    # ─── Vue d'ensemble
    lines.append("## Vue d'ensemble")
    lines.append("")
    lines.append("| Groupe | n | n_tp | n_sl | n_timeout | win_rate | PF | mean PnL% | total PnL% |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for label, st in (("Tous", stats_all), ("Would VETO", stats_vetoed), ("Would PASS", stats_passed)):
        wr = f"{st['win_rate']:.1f}%" if st["win_rate"] is not None else "—"
        pf = f"{st['pf']:.2f}" if st["pf"] is not None else "—"
        mp = f"{st['mean_pnl_pct']:+.2f}%" if st["mean_pnl_pct"] is not None else "—"
        tp = f"{st['total_pnl_pct']:+.2f}%"
        lines.append(f"| {label} | {st['n']} | {st['n_tp']} | {st['n_sl']} | {st['n_timeout']} | {wr} | {pf} | {mp} | {tp} |")
    lines.append("")

    # ─── Verdict directionnel
    lines.append("## Verdict directionnel")
    lines.append("")
    if stats_vetoed["n"] == 0:
        lines.append("Aucun setup réconcilié n'aurait été veto'd par les règles actuelles. Le contexte géopolitique au moment des entrées n'a déclenché aucune règle.")
    elif stats_passed["n"] == 0:
        lines.append("**Tous** les setups réconciliés auraient été veto'd. Configuration veto trop agressive ou contexte géopolitique extrême sur la fenêtre.")
    else:
        # Comparaison directe mean_pnl
        delta = (stats_passed["mean_pnl_pct"] or 0) - (stats_vetoed["mean_pnl_pct"] or 0)
        if abs(delta) < 0.05:
            verdict = "**ÉGAL** : le veto n'aurait pas changé matériellement la performance moyenne par trade"
        elif delta > 0:
            verdict = (
                f"**LE VETO AURAIT AIDÉ** : les setups que le veto aurait skip ont une mean PnL "
                f"de {stats_vetoed['mean_pnl_pct']:+.2f}% vs {stats_passed['mean_pnl_pct']:+.2f}% pour les autres "
                f"(écart {delta:+.2f}% par trade en faveur du veto)"
            )
        else:
            verdict = (
                f"**LE VETO AURAIT NUIT** : les setups que le veto aurait skip ont une mean PnL "
                f"de {stats_vetoed['mean_pnl_pct']:+.2f}% vs {stats_passed['mean_pnl_pct']:+.2f}% pour les autres "
                f"(écart {delta:+.2f}% par trade — le veto retire des trades gagnants)"
            )
        lines.append(verdict)
    lines.append("")

    # ─── Par règle
    if by_rule:
        lines.append("## Détail par règle de veto")
        lines.append("")
        lines.append("| Règle | n | n_tp | n_sl | mean PnL% |")
        lines.append("|---|---:|---:|---:|---:|")
        for rule, group in sorted(by_rule.items(), key=lambda x: -len(x[1])):
            st = compute_group_stats(group)
            mp = f"{st['mean_pnl_pct']:+.2f}%" if st["mean_pnl_pct"] is not None else "—"
            lines.append(f"| `{rule}` | {st['n']} | {st['n_tp']} | {st['n_sl']} | {mp} |")
        lines.append("")

    # ─── Par pair
    lines.append("## Détail par pair")
    lines.append("")
    lines.append("| Pair | n | n_tp | n_sl | n_timeout | mean PnL% |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for pair, group in sorted(by_pair.items(), key=lambda x: -len(x[1])):
        st = compute_group_stats(group)
        mp = f"{st['mean_pnl_pct']:+.2f}%" if st["mean_pnl_pct"] is not None else "—"
        lines.append(f"| {pair} | {st['n']} | {st['n_tp']} | {st['n_sl']} | {st['n_timeout']} | {mp} |")
    lines.append("")

    # ─── Notes méthodologiques
    lines.append("## Notes méthodologiques")
    lines.append("")
    lines.append("- `would_veto` est calculé au moment du log Track A (commit `3ac0d70`). Les seuils env vars `GEOPOLITICAL_VETO_*` au moment du log peuvent différer des seuils actuels.")
    lines.append("- Les setups antérieurs au 2026-05-08 (commit du snapshot) sont exclus.")
    lines.append("- Outcome `TIMEOUT` est compté dans `n_total` mais exclu du PF (pas de gain ni perte franche).")
    lines.append("- Track A reste **lecture seule** — le veto n'affecte ni les setups loggés ni les outcomes ; cette analyse est purement contrefactuelle.")
    lines.append("- Pour décision gate S6 (2026-06-06), viser `n ≥ 100` sur l'ensemble des systèmes Track A.")

    return "\n".join(lines) + "\n"


# ─── CLI ─────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--db",
        type=Path,
        default=_default_db_path(),
        help="Chemin SQLite (défaut: trades.db à la racine du repo)",
    )
    parser.add_argument(
        "--write",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Écrire le rapport dans docs/superpowers/journal/ (défaut: oui)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "docs" / "superpowers" / "journal",
        help="Dossier de sortie pour le rapport",
    )
    args = parser.parse_args()

    setups = load_reconciled_setups(args.db)
    generated_at = datetime.now(timezone.utc)

    report = build_report(setups, generated_at)
    print(report)

    if args.write:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        date_str = generated_at.strftime("%Y-%m-%d")
        out_path = args.out_dir / f"{date_str}-track-a-veto-counterfactual.md"
        out_path.write_text(report, encoding="utf-8")
        print(f"\n→ Rapport écrit : {out_path.relative_to(ROOT)}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
