"""Optional Silver-Fox-style ML approval gate for crypto opportunities."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable


class MLFilter:
    """Load a saved sklearn/xgboost model and approve feature snapshots."""

    def __init__(self, model_path: str = "data/ml_filter.pkl", scaler_path: str = "data/ml_scaler.pkl"):
        self.model_path = Path(model_path)
        self.scaler_path = Path(scaler_path)
        self.model = None
        self.scaler = None
        self.loaded = False
        self.load_error = ""

    def load(self) -> bool:
        if not self.model_path.exists() or not self.scaler_path.exists():
            self.load_error = "model_files_missing"
            return False

        try:
            import joblib  # type: ignore
        except Exception as exc:
            self.load_error = f"joblib_unavailable:{type(exc).__name__}"
            return False

        try:
            self.model = joblib.load(self.model_path)
            self.scaler = joblib.load(self.scaler_path)
            self.loaded = True
            self.load_error = ""
            return True
        except Exception as exc:
            self.load_error = f"model_load_failed:{type(exc).__name__}"
            self.loaded = False
            return False

    def predict_proba(self, feature_dict: dict, feature_cols: Iterable[str]) -> float:
        if not self.loaded or self.model is None or self.scaler is None:
            return 0.5
        row = [[float(feature_dict.get(col, 0.0) or 0.0) for col in feature_cols]]
        scaled = self.scaler.transform(row)
        return float(self.model.predict_proba(scaled)[0][1])

    def approve(
        self,
        feature_dict: dict,
        feature_cols: Iterable[str],
        threshold: float = 0.55,
        fail_open: bool = True,
    ) -> tuple[bool, float | None, str]:
        """Return (approved, probability, reason)."""
        if not self.loaded:
            return fail_open, None, self.load_error or "model_not_loaded"
        prob = self.predict_proba(feature_dict, feature_cols)
        if prob >= threshold:
            return True, prob, "approved"
        return False, prob, f"ml_probability_below_threshold:{prob:.3f}<{threshold:.3f}"
