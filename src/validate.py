"""Validation qualité — les règles sont définies dans config/data_contract.yaml.

Aucune ligne n'est supprimée silencieusement : chaque rejet porte sa cause
dans la colonne `reject_reason`. Le rapport compte les échecs par règle.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = ROOT / "config" / "data_contract.yaml"


def load_contract(path: Path | None = None) -> dict:
    return yaml.safe_load(Path(path or CONTRACT_PATH).read_text(encoding="utf-8"))


def _is_blank(series: pd.Series) -> pd.Series:
    return series.isna() | (series.astype(str).str.strip() == "")


def validate(df: pd.DataFrame, contract: dict | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Retourne (accepted, rejected, quality_report)."""
    contract = contract or load_contract()
    rules = contract["quality_rules"]
    df = df.copy()
    df["reject_reason"] = ""
    reasons: list[pd.Series] = []

    def flag(mask: pd.Series, rule_name: str) -> None:
        mask = mask.fillna(False)
        reasons.append(pd.Series(mask.map(lambda b: rule_name if b else ""), index=df.index))
        report["rules"][rule_name] = int(mask.sum())

    report: dict = {"input_rows": int(len(df)), "rules": {}, "warnings": {}}

    # 1. Complétude
    flag(_is_blank(df["neo_id"]), "completeness_key")
    flag(_is_blank(df["approach_date"].astype(str)), "completeness_key")

    # 2. Validité de la date (normalisée UTC)
    parsed_dates = pd.to_datetime(df["approach_date"], errors="coerce", utc=True)
    flag(parsed_dates.isna(), "valid_date")
    df["approach_date"] = parsed_dates.dt.strftime("%Y-%m-%d")

    # 3. Domaine : distance de passage
    r = rules["domain_miss_distance"]
    miss = pd.to_numeric(df["miss_distance_km"], errors="coerce")
    flag(~miss.between(float(r["min"]), float(r["max"])), "domain_miss_distance")

    # 4. Domaine : diamètre (uniquement si renseigné)
    r = rules["domain_diameter"]
    dia = pd.to_numeric(df.get("diameter_mid_km"), errors="coerce")
    flag(dia.notna() & ~dia.between(float(r["min"]), float(r["max"])), "domain_diameter")

    # 5. Domaine : magnitude absolue
    r = rules["domain_magnitude"]
    h = pd.to_numeric(df.get("absolute_magnitude_h"), errors="coerce")
    flag(h.notna() & ~h.between(float(r["min"]), float(r["max"])), "domain_magnitude")

    # 6. Domaine : vitesse relative (plage astrophysique plausible)
    if "domain_velocity" in rules and "relative_velocity_kms" in df.columns:
        rv = rules["domain_velocity"]
        vel = pd.to_numeric(df.get("relative_velocity_kms"), errors="coerce")
        flag(vel.notna() & ~vel.between(float(rv["min"]), float(rv["max"])), "domain_velocity")

    # 7. Fraîcheur -> alerte (warning), pas rejet
    max_age = pd.Timedelta(hours=float(rules["freshness"]["max_age_hours"]))
    observed = pd.to_datetime(df.get("observed_at"), errors="coerce", utc=True)
    stale = observed.notna() & (pd.Timestamp.now(tz="UTC") - observed > max_age)
    report["warnings"]["freshness"] = int(stale.sum())

    # Clé métier pour unicité
    key = ["neo_id", "approach_date"]

    # Assemblage des causes
    if reasons:
        reasons_concat = pd.concat(reasons, axis=1)
        df["reject_reason"] = reasons_concat.apply(
            lambda row: ";".join(val for val in row if val), axis=1
        )

    rejected_mask = df["reject_reason"] != ""
    valid_candidates = df[~rejected_mask].copy()

    duplicates_mask = valid_candidates.duplicated(subset=key, keep="first")
    report["rules"]["uniqueness_business_key"] = int(duplicates_mask.sum())

    rejected = df[rejected_mask].copy()
    accepted = valid_candidates[~duplicates_mask].copy().drop(columns=["reject_reason"])

    report["accepted_rows"] = int(len(accepted))
    report["rejected_rows"] = int(len(rejected))
    report["duplicates_removed"] = int(report["rules"]["uniqueness_business_key"])
    ratio = report["rejected_rows"] / max(report["input_rows"], 1)
    has_warnings = any(v > 0 for v in report["warnings"].values())
    if ratio > float(contract["reject_threshold"]):
        report["quality_status"] = "FAIL"
    elif has_warnings:
        report["quality_status"] = "PASS_WITH_WARNINGS"
    else:
        report["quality_status"] = "PASS"

    # Profiling statistique automatique des données acceptées
    report["profiling"] = compute_data_profiling(accepted, report["input_rows"], report["rejected_rows"])
    return accepted, rejected, report


def compute_data_profiling(accepted: pd.DataFrame, input_count: int, rejected_count: int) -> dict:
    """Profilage statistique automatique et calcul du score de santé de la donnée."""
    if accepted.empty:
        return {"health_score_pct": 0.0, "columns_profile": {}}

    num_cols = ["miss_distance_km", "diameter_mid_km", "relative_velocity_kms", "absolute_magnitude_h"]
    metrics: dict[str, dict] = {}
    for c in num_cols:
        if c in accepted.columns and accepted[c].notna().any():
            s = pd.to_numeric(accepted[c], errors="coerce").dropna()
            if not s.empty:
                metrics[c] = {
                    "min": round(float(s.min()), 2),
                    "max": round(float(s.max()), 2),
                    "median": round(float(s.median()), 2),
                    "mean": round(float(s.mean()), 2),
                    "completeness_pct": round(float((len(s) / len(accepted)) * 100), 1),
                }

    health_score = max(0.0, min(100.0, (1.0 - (rejected_count / max(input_count, 1))) * 100.0))
    return {
        "health_score_pct": round(health_score, 1),
        "columns_profile": metrics,
    }
