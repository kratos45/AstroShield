"""Tests unitaires de la couche validation (pytest tests/)."""
import pandas as pd

from src.validate import load_contract, validate


def _base_df() -> pd.DataFrame:
    return pd.DataFrame({
        "neo_id": ["A", "A", "B", "C"],
        "approach_date": ["2026-09-20", "2026-09-20", "not-a-date", "2026-09-21"],
        "miss_distance_km": [1_000_000.0, 1_000_000.0, 2_000_000.0, -5.0],
        "diameter_mid_km": [0.5, 0.5, 2000.0, 0.3],
        "absolute_magnitude_h": [20.0, 20.0, 22.0, 99.0],
        "observed_at": pd.Timestamp.now(tz="UTC"),
        "is_potentially_hazardous": [False, False, True, False],
    })


def test_contract_loads():
    contract = load_contract()
    assert contract["dataset"] == "neo_approaches"
    assert len(contract["quality_rules"]) >= 5


def test_invalid_rows_are_rejected_with_cause():
    accepted, rejected, report = validate(_base_df())
    # B : date invalide ; C : distance négative + magnitude hors domaine
    assert set(rejected["neo_id"]) == {"B", "C"}
    assert rejected.loc[rejected["neo_id"] == "C", "reject_reason"].str.contains("domain_").all()
    assert report["input_rows"] == 4


def test_duplicates_are_deduplicated_not_lost():
    accepted, _rejected, report = validate(_base_df())
    # la paire (A, 2026-09-20) apparaît deux fois -> une seule acceptée
    assert len(accepted[accepted["neo_id"] == "A"]) == 1
    assert report["duplicates_removed"] == 1


def test_no_silent_drop():
    accepted, rejected, report = validate(_base_df())
    assert report["accepted_rows"] + report["rejected_rows"] + report["duplicates_removed"] == report["input_rows"]
