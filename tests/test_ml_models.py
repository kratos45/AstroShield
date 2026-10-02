"""Tests unitaires des modèles d'analyse et de ML."""
import pandas as pd
import numpy as np
from src.ml_models import train_hazard_classifier, train_diameter_regressor, detect_orbital_anomalies


def _dummy_ml_df() -> pd.DataFrame:
    rng = np.random.RandomState(42)
    n = 80
    h = rng.normal(20, 2, n)
    d = 10 ** ((22 - h) / 2.5)
    return pd.DataFrame({
        "neo_id": [str(i) for i in range(n)],
        "approach_date": ["2026-09-15"] * n,
        "absolute_magnitude_h": h,
        "miss_distance_km": rng.uniform(1e6, 5e7, n),
        "relative_velocity_kms": rng.uniform(10, 30, n),
        "diameter_mid_km": d,
        "albedo": rng.uniform(0.05, 0.35, n),
        "semi_major_axis_au": rng.uniform(1.0, 2.5, n),
        "eccentricity": rng.uniform(0.1, 0.5, n),
        "inclination_deg": rng.uniform(2.0, 25.0, n),
        "is_potentially_hazardous": [bool(i % 5 == 0) for i in range(n)],
    })


def test_hazard_classifier_trains():
    df = _dummy_ml_df()
    res = train_hazard_classifier(df, min_rows=40)
    assert res["status"] == "TRAINED"
    assert "f1_score" in res


def test_diameter_regressor_trains():
    df = _dummy_ml_df()
    res = train_diameter_regressor(df, min_rows=30)
    assert res["status"] == "TRAINED"
    assert res["r2_score"] is not None


def test_orbital_anomalies_trains():
    df = _dummy_ml_df()
    res = detect_orbital_anomalies(df, min_rows=20)
    assert res["status"] == "TRAINED"
    assert res["anomalies_detected"] >= 0
