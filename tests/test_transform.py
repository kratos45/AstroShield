"""Tests unitaires des modules de transformation et publication."""
import sqlite3
import pandas as pd
from pathlib import Path
from src.transform import add_derived, enrich_sbdb, publish

ROOT = Path(__file__).resolve().parent.parent


def test_add_derived_calculates_energy_and_spectral_family():
    df = pd.DataFrame({
        "neo_id": ["1", "2"],
        "name": ["A", "B"],
        "approach_date": ["2026-09-20", "2026-09-21"],
        "miss_distance_km": [1_000_000.0, 2_000_000.0],
        "relative_velocity_kms": [15.0, 20.0],
        "diameter_mid_km": [0.5, 1.2],
        "albedo": [0.05, 0.25],
        "is_potentially_hazardous": [False, True],
    })
    res = add_derived(df)
    assert "energy_proxy_j" in res.columns
    assert res["energy_proxy_j"].iloc[0] > 0
    assert "tnt_megatons" in res.columns
    assert res["tnt_megatons"].iloc[0] > 0
    assert "crater_diameter_km" in res.columns
    assert res["crater_diameter_km"].iloc[0] > 0
    assert "lunar_distance_ld" in res.columns
    assert "spectral_family" in res.columns
    assert "carbonée" in str(res["spectral_family"].iloc[0])
    assert "métallique" in str(res["spectral_family"].iloc[1])


def test_add_derived_dynamical_class_and_tisserand():
    df = pd.DataFrame({
        "neo_id": ["1"],
        "name": ["A"],
        "approach_date": ["2026-09-20"],
        "semi_major_axis_au": [1.4],
        "eccentricity": [0.3],
        "inclination_deg": [12.0],
        "perihelion_au": [0.98],
        "aphelion_au": [1.82],
        "is_potentially_hazardous": [True],
        "diameter_mid_km": [1.5],
        "miss_distance_km": [2_000_000.0],
    })
    res = add_derived(df)
    assert "tisserand_jupiter" in res.columns
    assert res["tisserand_jupiter"].iloc[0] > 0
    assert "dynamical_class" in res.columns
    assert "Apollo" in res["dynamical_class"].iloc[0]
    assert "hazard_level" in res.columns
    assert "Extinction" in res["hazard_level"].iloc[0]


def test_enrich_sbdb_matches_by_id_and_norm_name(tmp_path):
    # Fichier SBDB simulé
    import json
    sbdb_path = tmp_path / "sbdb_123.json"
    sbdb_path.write_text(json.dumps({
        "object": {"spkid": "123", "fullname": "(Test Asteroid)"},
        "orbit": {"a": "1.5", "e": "0.2", "i": "10.0", "q": "1.2", "ad": "1.8"},
        "phys_par": [{"name": "albedo", "value": "0.15"}],
    }), encoding="utf-8")

    df = pd.DataFrame({
        "neo_id": ["123", "999"],
        "name": ["(Test Asteroid)", "Other"],
        "approach_date": ["2026-09-20", "2026-09-21"],
    })
    enriched = enrich_sbdb(df, raw_dir=tmp_path)
    assert "semi_major_axis_au" in enriched.columns
    assert enriched.loc[enriched["neo_id"] == "123", "semi_major_axis_au"].iloc[0] == 1.5
    assert enriched.loc[enriched["neo_id"] == "123", "albedo"].iloc[0] == 0.15
    assert pd.isna(enriched.loc[enriched["neo_id"] == "999", "semi_major_axis_au"].iloc[0])
