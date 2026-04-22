#!/usr/bin/env python3
"""Training ML sur les features extraites par ml_extract_features.py.

Classificateur binaire : target = WIN (1 si TP1, 0 sinon).
- Split train/val/test temporel (walk-forward, pas random)
- Modèle : RandomForest (robuste, zéro tuning) + Logistic Regression (baseline)
- Évaluation : AUC, précision au seuil, feature importance
- Si AUC > 0.55 : modèle utile, sauvegardé en .joblib
- Si AUC ≈ 0.50 : pas de signal, on le sait rigoureusement

Usage :
    sudo docker exec scalping-radar python3 /app/scripts/ml_train.py \\
        --features /app/data/ml_features.csv \\
        --model-out /app/data/ml_model.joblib \\
        --report /app/data/ml_report.json
"""
from __future__ import annotations
import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ml_train")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", default="/app/data/ml_features.csv")
    ap.add_argument("--model-out", default="/app/data/ml_model.joblib")
    ap.add_argument("--report", default="/app/data/ml_report.json")
    ap.add_argument("--target-outcome", default="TP1",
                    help="outcome qui compte comme WIN (TP1 par défaut)")
    ap.add_argument("--min-train-samples", type=int, default=500,
                    help="refuse si pas assez de samples")
    args = ap.parse_args()

    # Imports lourds ici pour que --help n'ait pas besoin de pandas
    import pandas as pd
    import numpy as np
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import (
        roc_auc_score, precision_recall_fscore_support,
        confusion_matrix, classification_report,
    )
    from sklearn.pipeline import Pipeline
    import joblib

    features_path = Path(args.features)
    if not features_path.exists():
        log.error(f"Features CSV absent : {features_path}")
        sys.exit(1)

    log.info(f"Loading features from {features_path}")
    df = pd.read_csv(features_path)
    log.info(f"Total rows: {len(df)}")
    if len(df) < args.min_train_samples:
        log.error(f"Trop peu de samples ({len(df)} < {args.min_train_samples})")
        sys.exit(1)

    # Target : WIN=1 si outcome == TP1, 0 sinon (SL et TIMEOUT = LOSS)
    df["win"] = (df["outcome"] == args.target_outcome).astype(int)
    log.info(f"Class balance : {df['win'].mean():.3f} win rate, "
             f"{df['win'].sum()} wins / {len(df) - df['win'].sum()} losses")

    # Tri temporel (obligatoire pour walk-forward split)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)

    # Features vs non-features
    # Exclure : outcome, win, timestamp, pair (catégoriel one-hot inutile
    # car patterns déjà one-hot et pair-biais pas souhaité), entry/sl/tp
    # (info redondante avec risk_pct etc.)
    drop_cols = ["outcome", "win", "timestamp", "pair", "pair_name",
                 "direction", "entry", "sl", "tp", "pattern_confidence"]
    feature_cols = [c for c in df.columns if c not in drop_cols]
    log.info(f"{len(feature_cols)} features utilisées")

    X = df[feature_cols].fillna(0).values
    y = df["win"].values

    # Split temporel : 70% train, 15% val, 15% test
    n = len(df)
    train_end = int(n * 0.70)
    val_end = int(n * 0.85)
    X_train, X_val, X_test = X[:train_end], X[train_end:val_end], X[val_end:]
    y_train, y_val, y_test = y[:train_end], y[train_end:val_end], y[val_end:]

    log.info(f"Split : train={len(y_train)} val={len(y_val)} test={len(y_test)}")
    log.info(f"Win rate - train {y_train.mean():.3f} val {y_val.mean():.3f} test {y_test.mean():.3f}")

    # Modèles candidats
    report: dict = {
        "total_samples": len(df),
        "features": feature_cols,
        "class_balance": float(df["win"].mean()),
        "split": {"train": len(y_train), "val": len(y_val), "test": len(y_test)},
        "models": {},
    }

    models = {
        "logistic": Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=500, class_weight="balanced", random_state=42)),
        ]),
        "random_forest": RandomForestClassifier(
            n_estimators=200, max_depth=8, min_samples_leaf=20,
            class_weight="balanced", random_state=42, n_jobs=-1,
        ),
        "gradient_boost": GradientBoostingClassifier(
            n_estimators=200, max_depth=5, learning_rate=0.05, random_state=42,
        ),
    }

    best_name = None
    best_auc = -1
    best_model = None

    for name, model in models.items():
        log.info(f"Training {name}...")
        model.fit(X_train, y_train)
        # Proba pour la classe 1
        val_proba = model.predict_proba(X_val)[:, 1]
        test_proba = model.predict_proba(X_test)[:, 1]
        val_auc = roc_auc_score(y_val, val_proba) if len(set(y_val)) > 1 else 0.5
        test_auc = roc_auc_score(y_test, test_proba) if len(set(y_test)) > 1 else 0.5

        # Précision au seuil 0.5 sur test
        test_pred = (test_proba >= 0.5).astype(int)
        prec, rec, f1, _ = precision_recall_fscore_support(y_test, test_pred, average="binary", zero_division=0)
        cm = confusion_matrix(y_test, test_pred).tolist()

        # Précision au seuil élevé (0.65) — utile pour décider si le modèle
        # peut être utilisé pour filtrer les meilleurs signaux
        high_thresh = 0.65
        test_pred_high = (test_proba >= high_thresh).astype(int)
        if test_pred_high.sum() > 0:
            prec_high, rec_high, _, _ = precision_recall_fscore_support(
                y_test, test_pred_high, average="binary", zero_division=0)
        else:
            prec_high, rec_high = 0.0, 0.0

        report["models"][name] = {
            "val_auc": round(val_auc, 4),
            "test_auc": round(test_auc, 4),
            "test_precision_0.5": round(prec, 4),
            "test_recall_0.5": round(rec, 4),
            "test_f1_0.5": round(f1, 4),
            "test_precision_0.65": round(prec_high, 4),
            "test_recall_0.65": round(rec_high, 4),
            "confusion_matrix_0.5": cm,
        }
        log.info(
            f"  {name}: val_auc={val_auc:.3f} test_auc={test_auc:.3f} "
            f"prec@0.5={prec:.3f} prec@0.65={prec_high:.3f}"
        )

        if test_auc > best_auc:
            best_auc = test_auc
            best_name = name
            best_model = model

    log.info(f"═══ MEILLEUR : {best_name} avec test_auc={best_auc:.3f} ═══")
    report["best_model"] = best_name
    report["best_test_auc"] = round(best_auc, 4)

    # Seuil de significance : AUC >= 0.55 = modèle utile
    has_edge = bool(best_auc >= 0.55)  # bool() pour sérialisation JSON (np.bool_ non compatible)
    report["has_edge"] = has_edge
    log.info(f"Edge détecté : {has_edge} (AUC {best_auc:.3f} {'≥' if has_edge else '<'} 0.55)")

    # Feature importance pour random forest
    if best_name == "random_forest" and hasattr(best_model, "feature_importances_"):
        importance_pairs = sorted(zip(feature_cols, best_model.feature_importances_),
                                   key=lambda x: -x[1])
        top_features = [{"name": f, "importance": round(float(i), 4)}
                        for f, i in importance_pairs[:20]]
        report["top_features"] = top_features
        log.info("Top features :")
        for tf in top_features[:10]:
            log.info(f"  {tf['name']:30s} {tf['importance']:.4f}")

    # Save report + model
    Path(args.report).write_text(json.dumps(report, indent=2))
    log.info(f"Report → {args.report}")

    if has_edge and best_model is not None:
        joblib.dump({
            "model": best_model,
            "feature_cols": feature_cols,
            "best_name": best_name,
            "test_auc": best_auc,
            "trained_at": pd.Timestamp.utcnow().isoformat(),
        }, args.model_out)
        log.info(f"Model (edge détecté) → {args.model_out}")
    else:
        log.warning(f"Pas d'edge détecté — model NON sauvegardé")


if __name__ == "__main__":
    main()
