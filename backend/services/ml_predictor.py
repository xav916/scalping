"""Wrapper pour charger un modèle ML joblib et prédire la proba de TP.

Le modèle est entraîné offline par `scripts/ml_train.py` sur les features
extraites par `scripts/ml_extract_features.py`. Cette interface permet de
l'utiliser en temps réel dans le scoring live — **s'il existe**.

Philosophie : **fail-safe par défaut**. Si aucun modèle n'est disponible,
`predict_win_proba` retourne 0.5 (neutre) → le scoring heuristique actuel
continue de fonctionner comme avant. Pas de dépendance dure.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MODEL_PATH = Path("/app/data/ml_model.joblib")

# Cache lazy : on charge au 1er appel, puis on garde en mémoire.
_model_cache: dict[str, Any] = {"model": None, "feature_cols": None, "loaded": False}


def _try_load() -> None:
    """Lazy load du modèle. Idempotent. Sécurisé si joblib pas dispo."""
    if _model_cache["loaded"]:
        return
    _model_cache["loaded"] = True
    if not _MODEL_PATH.exists():
        logger.info(f"ml_predictor: pas de modèle à {_MODEL_PATH}, mode neutre")
        return
    try:
        import joblib
        bundle = joblib.load(_MODEL_PATH)
        _model_cache["model"] = bundle.get("model")
        _model_cache["feature_cols"] = bundle.get("feature_cols")
        meta = {
            "best_name": bundle.get("best_name"),
            "test_auc": bundle.get("test_auc"),
            "trained_at": bundle.get("trained_at"),
        }
        logger.info(f"ml_predictor: modèle chargé — {meta}")
    except Exception as e:
        logger.warning(f"ml_predictor: load failed {e}, mode neutre")


def is_available() -> bool:
    """True si un modèle ML est chargé et utilisable."""
    _try_load()
    return _model_cache["model"] is not None


def predict_win_proba(feature_dict: dict[str, Any]) -> float:
    """Retourne la proba [0, 1] que TP1 soit hit avant SL.

    Fallback 0.5 (neutre) si :
    - Pas de modèle entraîné
    - Features manquantes ou invalides
    - Exception quelconque pendant predict

    Jamais de propagation d'exception — le scoring live ne doit pas tomber
    à cause d'un problème ML.
    """
    _try_load()
    model = _model_cache["model"]
    cols = _model_cache["feature_cols"]
    if model is None or not cols:
        return 0.5
    try:
        row = [float(feature_dict.get(c, 0) or 0) for c in cols]
        # predict_proba retourne shape (1, 2) pour binaire → proba classe 1 = [0][1]
        proba = float(model.predict_proba([row])[0][1])
        # Clamp [0, 1]
        return max(0.0, min(1.0, proba))
    except Exception as e:
        logger.debug(f"ml_predictor: predict failed {e}, fallback neutre")
        return 0.5


def model_meta() -> dict[str, Any]:
    """Métadonnées du modèle chargé (pour /api/ml/info)."""
    _try_load()
    return {
        "available": _model_cache["model"] is not None,
        "n_features": len(_model_cache["feature_cols"]) if _model_cache["feature_cols"] else 0,
        "model_path": str(_MODEL_PATH),
    }
