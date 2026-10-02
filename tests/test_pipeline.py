"""Tests d'intégration du pipeline (end-to-end et idempotence)."""
from pathlib import Path
import pandas as pd
from src.pipeline import run

ROOT = Path(__file__).resolve().parent.parent


def test_pipeline_synthetic_execution():
    report = run(synthetic=True)
    assert report["pipeline"] == "astroshield"
    assert report["quality_status"] in ("PASS", "PASS_WITH_WARNINGS")
    assert report["accepted_rows"] > 0
    assert report["input_rows"] == report["accepted_rows"] + report["rejected_rows"] + report["duplicates_removed"]
    assert report["ml"]["hazard_classifier"]["status"] == "TRAINED"
    assert report["ml"]["orbital_anomalies"]["status"] == "TRAINED"


def test_pipeline_idempotence():
    """Vérifie qu'exécuter le pipeline 2 fois produit exactement les mêmes résultats."""
    rep1 = run(offline=True)
    csv1 = (ROOT / "data" / "curated" / "dataset.csv").read_bytes()

    rep2 = run(offline=True)
    csv2 = (ROOT / "data" / "curated" / "dataset.csv").read_bytes()

    assert rep1["accepted_rows"] == rep2["accepted_rows"]
    assert rep1["rejected_rows"] == rep2["rejected_rows"]
    assert rep1["duplicates_removed"] == rep2["duplicates_removed"]
    assert csv1 == csv2
