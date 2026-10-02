"""Modèles ML / DL — AstroShield.

1. hazard_classifier  : Random Forest (référence de base)
   -> classe is_potentially_hazardous (règle déterministe JPL : bon baseline)
2. diameter_regressor : GradientBoosting sur H -> diameter_mid_km
   -> vraie valeur ajoutée : le diamètre n'est mesuré que pour ~10 % des NEO
3. orbital_anomalies   : IsolationForest sur les éléments orbitaux
4. approach_forecast_lstm : prévision de la distance de passage suivante (DL)
   -> PyTorch, entraînement dégradé proprement si non installé

Les métriques sont renvoyées au rapport d'exécution; les modèles sont
versionnés dans data/models/ avec joblib.
"""
from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, IsolationForest, RandomForestClassifier
from sklearn.metrics import classification_report, mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "data" / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

FEATURES_HAZARD = [
    "absolute_magnitude_h", "miss_distance_km", "relative_velocity_kms",
    "diameter_mid_km", "semi_major_axis_au", "eccentricity", "inclination_deg",
]
FEATURES_DIAMETER = ["absolute_magnitude_h", "albedo"]


def _ready(df: pd.DataFrame, features: list[str], target: str,
           min_features: int = 3, min_rows: int = 30) -> tuple[pd.DataFrame, list[str]]:
    # Garde les features présentes et suffisamment renseignées
    available = [c for c in features if c in df.columns and df[c].notna().sum() >= min_rows]
    if len(available) < min_features or target not in df.columns:
        return df.iloc[0:0], available
    cols = available + [target]
    return df.dropna(subset=cols), available


def train_hazard_classifier(df: pd.DataFrame, min_rows: int = 50) -> dict:
    d, feats = _ready(df, FEATURES_HAZARD, "is_potentially_hazardous", min_rows=min_rows)
    if len(d) < min_rows:
        return {"status": "SKIPPED", "reason": f"seulement {len(d)} lignes exploitables (< {min_rows}) ; features dispo: {feats}"}
    
    y = d["is_potentially_hazardous"].astype(int)
    # Stratification sécurisée si au moins 2 classes avec >= 2 exemples
    strat = y if (y.nunique() > 1 and y.value_counts().min() >= 2) else None
    
    X_train, X_test, y_train, y_test = train_test_split(
        d[feats], y,
        test_size=0.25, random_state=42, stratify=strat,
    )
    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", RandomForestClassifier(n_estimators=300, class_weight="balanced", random_state=42)),
    ])
    pipe.fit(X_train, y_train)
    report = classification_report(y_test, pipe.predict(X_test), output_dict=True, zero_division=0)
    joblib.dump(pipe, MODELS_DIR / "hazard_classifier.joblib")
    
    f1 = report.get("1", {}).get("f1-score", report.get("1.0", {}).get("f1-score", 0.0))
    rec = report.get("1", {}).get("recall", report.get("1.0", {}).get("recall", 0.0))
    return {
        "status": "TRAINED",
        "f1_score": round(float(f1), 3),
        "recall_hazardous": round(float(rec), 3),
        "n_train": int(len(X_train)),
        "features": feats,
        "note": "baseline de référence : la classe JPL est quasi déterministe",
    }


def train_diameter_regressor(df: pd.DataFrame, min_rows: int = 30) -> dict:
    cols = [c for c in FEATURES_DIAMETER if c in df.columns and df[c].notna().sum() >= min_rows]
    d = df.dropna(subset=cols + ["diameter_mid_km"])
    if len(d) < min_rows or len(cols) == 0:
        return {"status": "SKIPPED", "reason": f"seulement {len(d)} diamètres connus et features={cols}"}
    X_train, X_test, y_train, y_test = train_test_split(
        d[cols], d["diameter_mid_km"], test_size=0.25, random_state=42,
    )
    model = GradientBoostingRegressor(random_state=42)
    model.fit(X_train, y_train)
    pred = model.predict(X_test)
    joblib.dump(model, MODELS_DIR / "diameter_regressor.joblib")
    return {
        "status": "TRAINED",
        "r2_score": round(float(r2_score(y_test, pred)), 3),
        "mae_km": round(float(mean_absolute_error(y_test, pred)), 3),
        "n_train": int(len(X_train)),
        "features": cols,
        "note": "imputation du diamètre inconnu (H -> diamètre, seul albedo connu à ~10 %)",
    }


def detect_orbital_anomalies(df: pd.DataFrame, min_rows: int = 20) -> dict:
    feats = [c for c in ["semi_major_axis_au", "eccentricity", "inclination_deg", "absolute_magnitude_h"] if c in df.columns and df[c].notna().sum() >= min_rows]
    if len(feats) < 2:
        return {"status": "SKIPPED", "reason": f"éléments orbitaux insuffisants (features={feats}) ; activer l'enrichissement SBDB"}
    d = df.dropna(subset=feats)
    if len(d) < min_rows:
        return {"status": "SKIPPED", "reason": f"seulement {len(d)} orbites complètes (< {min_rows})"}
    model = IsolationForest(contamination=0.05, random_state=42)
    preds = model.fit_predict(d[feats])
    n_anomalies = int((preds == -1).sum())
    joblib.dump(model, MODELS_DIR / "orbital_anomalies.joblib")
    return {
        "status": "TRAINED",
        "features": feats,
        "n_samples": int(len(d)),
        "anomalies_detected": n_anomalies,
        "contamination": 0.05,
    }


def train_approach_forecast_lstm(df: pd.DataFrame, epochs: int = 15, min_seq: int = 3) -> dict:
    """Prédit la distance de passage suivante à partir des N précédentes
    (par astéroïde). Nécessite torch ; se dégrade proprement sinon."""
    try:
        import torch
        import torch.nn as nn
    except ImportError:
        return {"status": "SKIPPED", "reason": "torch non installé (voir requirements, section optionnelle)"}

    seqs: list[list[float]] = []
    for _neo, grp in df.sort_values("approach_date").groupby("neo_id"):
        values = grp["miss_distance_km"].dropna().tolist()
        if len(values) >= min_seq:
            seqs.append(values)
    if len(seqs) < 5:
        return {"status": "SKIPPED", "reason": f"{len(seqs)} séries temporelles suffisamment longues"}

    class LSTMForecaster(nn.Module):
        def __init__(self, hidden: int = 32):
            super().__init__()
            self.lstm = nn.LSTM(input_size=1, hidden_size=hidden, batch_first=True)
            self.head = nn.Linear(hidden, 1)

        def forward(self, x):
            out, _ = self.lstm(x)
            return self.head(out[:, -1, :])

    def to_xy(values: list[float]):
        lo, hi = min(values), max(values)
        scale = max(hi - lo, 1e-6)
        norm = [(v - lo) / scale for v in values]
        xs = torch.tensor([[norm[i: i + min_seq]] for i in range(len(norm) - min_seq)]).transpose(1, 2).float()
        ys = torch.tensor([norm[i + min_seq] for i in range(len(norm) - min_seq)]).float().unsqueeze(1)
        return xs, ys

    X_all, y_all = [], []
    for s in seqs:
        xs, ys = to_xy(s)
        X_all.append(xs); y_all.append(ys)
    X = torch.cat(X_all); y = torch.cat(y_all)
    model = LSTMForecaster()
    opt = torch.optim.Adam(model.parameters(), lr=0.01)
    loss_fn = nn.MSELoss()
    model.train()
    for _ in range(epochs):
        opt.zero_grad()
        loss = loss_fn(model(X), y)
        loss.backward()
        opt.step()
    model.eval()
    with torch.no_grad():
        mse = float(loss_fn(model(X), y))
    torch.save(model.state_dict(), MODELS_DIR / "approach_forecast_lstm.pt")
    return {"status": "TRAINED", "train_mse": round(mse, 5), "n_sequences": len(seqs), "sequence_length": min_seq}


def run_all(df: pd.DataFrame) -> dict:
    return {
        "hazard_classifier": train_hazard_classifier(df),
        "diameter_regressor": train_diameter_regressor(df),
        "orbital_anomalies": detect_orbital_anomalies(df),
        "approach_forecast_lstm": train_approach_forecast_lstm(df),
    }
