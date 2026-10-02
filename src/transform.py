"""Transformation et publication — de la donnée validée au warehouse.

- aplatit le JSON brut NeoWs (une ligne = une approche, cf. contrat)
- normalise les dates en UTC, convertit les unités
- enrichit avec les éléments orbitaux SBDB (a, e, i, q, ad, albedo)
- ajoute des variables calculées (diameter_mid_km, energy_proxy)
- écrit : Parquet (lake), CSV (curated), SQLite avec UPSERT (warehouse)
  et deux data marts Gold (mart_risk_daily, mart_characterization)
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CURATED_DIR = ROOT / "data" / "curated"
REJECTED_DIR = ROOT / "data" / "rejected"
DB_PATH = ROOT / "data" / "astroshield.db"
CURATED_DIR.mkdir(parents=True, exist_ok=True)
REJECTED_DIR.mkdir(parents=True, exist_ok=True)

BUSINESS_KEY = ["neo_id", "approach_date"]


def _to_float(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def flatten_neows(raw_path: Path, observed_at: pd.Timestamp | None = None) -> pd.DataFrame:
    """JSON brut NeoWs -> DataFrame au grain du contrat (1 ligne = 1 approche).

    observed_at provient du fichier brut (heure de collecte) : rejouer le
    même fichier produit exactement le même résultat (idempotence)."""
    payload = json.loads(Path(raw_path).read_text(encoding="utf-8"))
    rows: list[dict] = []
    for _date, neos in payload.get("near_earth_objects", {}).items():
        for neo in neos:
            dia = neo.get("estimated_diameter", {}).get("kilometers", {})
            for cad in neo.get("close_approach_data", []):
                vel = cad.get("relative_velocity", {})
                miss = cad.get("miss_distance", {})
                rows.append({
                    "neo_id": str(neo.get("neo_reference_id") or neo.get("id") or ""),
                    "name": neo.get("name"),
                    "approach_date": cad.get("close_approach_date"),
                    "miss_distance_km": _to_float(miss.get("kilometers")),
                    "relative_velocity_kms": _to_float(vel.get("kilometers_per_second")),
                    "diameter_min_km": _to_float(dia.get("estimated_diameter_min")),
                    "diameter_max_km": _to_float(dia.get("estimated_diameter_max")),
                    "absolute_magnitude_h": _to_float(neo.get("absolute_magnitude_h")),
                    "is_potentially_hazardous": bool(neo.get("is_potentially_hazardous_asteroid")),
                    "orbiting_body": cad.get("orbiting_body"),
                })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["diameter_mid_km"] = df[["diameter_min_km", "diameter_max_km"]].mean(axis=1)
        if observed_at is None:
            observed_at = pd.Timestamp(Path(raw_path).stat().st_mtime, unit="s", tz="UTC")
        df["observed_at"] = observed_at
    return df


def enrich_sbdb(accepted: pd.DataFrame, raw_dir: Path | None = None) -> pd.DataFrame:
    """Joint les éléments orbitaux SBDB disponibles dans la zone raw."""
    raw_dir = raw_dir or (ROOT / "data" / "raw")
    records: list[dict] = []
    for path in sorted(raw_dir.glob("sbdb_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            obj = payload.get("object", {})
            spkid = str(obj.get("spkid") or obj.get("neo_id") or "").strip()
            fullname = str(obj.get("fullname", obj.get("des", ""))).strip().strip("()")
            orbit = payload.get("orbit", {})
            phys = {p.get("name"): p.get("value") for p in payload.get("phys_par", []) if isinstance(p, dict)}
            records.append({
                "neo_id": spkid,
                "norm_name": fullname,
                "semi_major_axis_au": _to_float(orbit.get("a")),
                "eccentricity": _to_float(orbit.get("e")),
                "inclination_deg": _to_float(orbit.get("i")),
                "perihelion_au": _to_float(orbit.get("q")),
                "aphelion_au": _to_float(orbit.get("ad")),
                "albedo": _to_float(phys.get("albedo")),
                "orbit_id": str(obj.get("orbit_id", "")),
            })
        except (json.JSONDecodeError, KeyError, TypeError):
            continue  # fichier brut corrompu : ignoré, tracé par le rapport
    if not records:
        return accepted

    enrich = pd.DataFrame(records).drop_duplicates(subset=["neo_id", "norm_name"])
    orbital_cols = [
        "semi_major_axis_au", "eccentricity", "inclination_deg",
        "perihelion_au", "aphelion_au", "albedo", "orbit_id"
    ]
    
    acc = accepted.copy()
    # 1. Tentative de jointure par neo_id (spkid)
    merged = acc.merge(
        enrich[enrich["neo_id"].ne("")][["neo_id"] + orbital_cols].drop_duplicates(subset=["neo_id"]),
        on="neo_id",
        how="left"
    )

    # 2. Complément de jointure par nom normalisé pour les lignes non appariées
    if merged["semi_major_axis_au"].isna().any() and "name" in merged.columns:
        unmatched_mask = merged["semi_major_axis_au"].isna()
        acc_norm = merged.loc[unmatched_mask, ["name"]].copy()
        acc_norm["norm_name"] = acc_norm["name"].astype(str).str.replace(r"[()]", "", regex=True).str.strip()
        by_name = acc_norm.merge(
            enrich[enrich["norm_name"].ne("")][["norm_name"] + orbital_cols].drop_duplicates(subset=["norm_name"]),
            on="norm_name",
            how="left"
        )
        for col in orbital_cols:
            merged.loc[unmatched_mask, col] = by_name[col].values

    # Cohérence : périhélie < aphélie (règle croisée, signalée en warning pipeline)
    bad = merged["perihelion_au"].notna() & merged["aphelion_au"].notna() & (
        merged["perihelion_au"] >= merged["aphelion_au"]
    )
    merged.loc[bad, ["perihelion_au", "aphelion_au"]] = None
    return merged


def add_derived(df: pd.DataFrame) -> pd.DataFrame:
    """Calcul de variables astrophysiques avancées et indicateurs de risque."""
    df = df.copy()

    # 1. Distance en Distances Lunaires (1 LD ~ 384 400 km)
    if "miss_distance_km" in df.columns:
        df["lunar_distance_ld"] = (pd.to_numeric(df["miss_distance_km"], errors="coerce") / 384400.0).round(2)

    # 2. Énergie cinétique d'impact (Joules) et équivalent Mégatonnes de TNT
    # 1 Mt TNT = 4.184e15 J ; masse sphérique avec densité chondrite ~ 2600 kg/m³
    if {"diameter_mid_km", "relative_velocity_kms"} <= set(df.columns):
        d_m = pd.to_numeric(df["diameter_mid_km"], errors="coerce") * 1000.0
        v_ms = pd.to_numeric(df["relative_velocity_kms"], errors="coerce") * 1000.0
        mass_kg = (4.0 / 3.0) * np.pi * ((d_m / 2.0) ** 3) * 2600.0
        df["energy_proxy_j"] = (0.5 * mass_kg * (v_ms ** 2)).round(2)
        df["tnt_megatons"] = (df["energy_proxy_j"] / 4.184e15).round(2)

        # 3. Diamètre théorique du cratère d'impact (loi d'échelle de Schmidt-Holsapple sur socle rocheux)
        # D_crater (km) ~ 1.15 * D_proj^0.78 * v_kms^0.44
        d_km = pd.to_numeric(df["diameter_mid_km"], errors="coerce")
        v_kms = pd.to_numeric(df["relative_velocity_kms"], errors="coerce")
        df["crater_diameter_km"] = (1.15 * (d_km ** 0.78) * (v_kms ** 0.44)).round(2)

    # 4. Famille spectrale déduite de l'albédo (Tholen / DeMeo simplifié)
    if "albedo" in df.columns:
        bins = [-1, 0.08, 0.20, 1.0]
        labels = ["C (carbonée)", "S (silicatée)", "M (métallique)"]
        df["spectral_family"] = pd.cut(df["albedo"], bins=bins, labels=labels).astype(str)
        df.loc[df["albedo"].isna(), "spectral_family"] = None

    # 5. Indice sur l'Échelle de Turin (Proxy standard 0 - 10)
    # 0 = aucun risque, 1 = normal, 2-4 = attention astronomes, 5-7 = menace critique, 8-10 = collision cataclysmique
    if {"tnt_megatons", "lunar_distance_ld"} <= set(df.columns):
        def calc_torino(row):
            ld = row.get("lunar_distance_ld")
            mt = row.get("tnt_megatons")
            pha = row.get("is_potentially_hazardous")
            if pd.isna(ld) or pd.isna(mt) or ld > 10.0 or not pha:
                return 0
            if mt < 1.0:
                return 1 if ld < 2.0 else 0
            elif mt < 100.0:
                return 3 if ld < 1.0 else 2
            elif mt < 10000.0:
                return 6 if ld < 0.5 else 4
            else:
                return 9 if ld < 0.5 else 7
        df["torino_scale"] = df.apply(calc_torino, axis=1)

    # 6. Paramètre de Tisserand par rapport à Jupiter (T_J)
    # T_J = a_J / a + 2 * cos(i) * sqrt(a / a_J * (1 - e²)) avec a_J = 5.2044 UA
    if {"semi_major_axis_au", "eccentricity", "inclination_deg"} <= set(df.columns):
        a = pd.to_numeric(df["semi_major_axis_au"], errors="coerce")
        e = pd.to_numeric(df["eccentricity"], errors="coerce")
        i_deg = pd.to_numeric(df["inclination_deg"], errors="coerce")
        valid_orbit = a.notna() & e.notna() & i_deg.notna() & (a > 0) & (e < 1.0)
        t_j = pd.Series(index=df.index, dtype=float)
        if valid_orbit.any():
            a_v = a[valid_orbit]
            e_v = e[valid_orbit]
            i_rad = np.radians(i_deg[valid_orbit])
            a_jup = 5.2044
            t_j[valid_orbit] = (a_jup / a_v) + 2.0 * np.cos(i_rad) * np.sqrt((a_v / a_jup) * (1.0 - e_v**2))
        df["tisserand_jupiter"] = t_j.round(3)

    # 7. Classification dynamique de l'orbite géocroiseur (Apollo, Amor, Aten, Atira)
    if {"semi_major_axis_au", "perihelion_au", "aphelion_au"} <= set(df.columns):
        def classify_orbit(row):
            a = row.get("semi_major_axis_au")
            q = row.get("perihelion_au")
            ad = row.get("aphelion_au")
            if pd.isna(a) or pd.isna(q) or pd.isna(ad):
                return "Non classifié"
            if a < 1.0 and ad < 0.983:
                return "Atira (Intérieur)"
            elif a < 1.0 and ad >= 0.983:
                return "Aten (Croiseur int.)"
            elif a >= 1.0 and q <= 1.017:
                return "Apollo (Croiseur ext.)"
            elif a > 1.0 and 1.017 < q <= 1.30:
                return "Amor (Frôleur ext.)"
            elif q > 1.30:
                return "Autre (Ceinture)"
            return "Géocroiseur"
        df["dynamical_class"] = df.apply(classify_orbit, axis=1)

    # 8. Niveau d'alerte et de létalité opérationnelle
    if {"is_potentially_hazardous", "diameter_mid_km", "miss_distance_km"} <= set(df.columns):
        def calc_hazard_level(row):
            pha = bool(row.get("is_potentially_hazardous"))
            d = row.get("diameter_mid_km") or 0.0
            dist_ld = row.get("lunar_distance_ld") or 999.0
            if pha and d >= 1.0:
                return "Extinction globale (> 1 km)"
            elif pha and d >= 0.14:
                return "Dévastation régionale (> 140 m)"
            elif pha or dist_ld < 5.0:
                return "Surveillance rapprochée"
            return "Risque mineur"
        df["hazard_level"] = df.apply(calc_hazard_level, axis=1)

    return df


def publish(accepted: pd.DataFrame) -> dict:
    """Écrit lake (Parquet), curated (CSV), warehouse SQLite (UPSERT) + marts."""
    df = add_derived(accepted)
    df = df.drop_duplicates(subset=BUSINESS_KEY, keep="first")  # idempotence fichier

    df.to_csv(CURATED_DIR / "dataset.csv", index=False)
    # Zone lake : Parquet si pyarrow disponible, CSV gz sinon (repli documenté)
    try:
        df.to_parquet(CURATED_DIR / "neo_approaches.parquet", index=False)
        lake_format = "parquet"
    except ImportError:
        df.to_csv(CURATED_DIR / "neo_approaches.csv.gz", index=False, compression="gzip")
        lake_format = "csv.gz"

    con = sqlite3.connect(DB_PATH)
    df.to_sql("neo_approaches", con, if_exists="replace", index=False,
              dtype={"approach_date": "TEXT", "neo_id": "TEXT"})
    con.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_neo_approach "
        "ON neo_approaches(neo_id, approach_date)"
    )

    # --- Data marts Gold ---
    risk_agg = {
        "neo_count": ("neo_id", "nunique"),
        "pha_count": ("is_potentially_hazardous", "sum"),
        "min_miss_km": ("miss_distance_km", "min"),
        "avg_miss_km": ("miss_distance_km", "mean"),
        "avg_diameter_km": ("diameter_mid_km", "mean"),
        "max_energy_proxy": ("energy_proxy_j", "max"),
    }
    if "lunar_distance_ld" in df.columns:
        risk_agg["min_miss_ld"] = ("lunar_distance_ld", "min")
    if "tnt_megatons" in df.columns:
        risk_agg["max_tnt_megatons"] = ("tnt_megatons", "max")
    if "torino_scale" in df.columns:
        risk_agg["max_torino"] = ("torino_scale", "max")

    risk = df.groupby("approach_date", as_index=False).agg(**risk_agg)
    risk.to_sql("mart_risk_daily", con, if_exists="replace", index=False)

    charac_agg = {
        "observation_count": ("approach_date", "count"),
        "min_miss_km": ("miss_distance_km", "min"),
        "avg_diameter_km": ("diameter_mid_km", "mean"),
        "is_pha": ("is_potentially_hazardous", "max"),
    }
    for opt_col in ["spectral_family", "dynamical_class", "hazard_level", "tisserand_jupiter", "crater_diameter_km", "tnt_megatons"]:
        if opt_col in df.columns:
            charac_agg[opt_col] = (opt_col, "last")

    charac = df.groupby(["neo_id", "name"], as_index=False).agg(**charac_agg)
    if "is_pha" in charac.columns:
        charac["is_pha"] = charac["is_pha"].astype(int)
    for str_col in ["spectral_family", "dynamical_class", "hazard_level"]:
        if str_col in charac.columns:
            charac[str_col] = charac[str_col].astype(str).replace({"None": None, "nan": None})
    charac.to_sql("mart_characterization", con, if_exists="replace", index=False)
    con.commit()
    con.close()

    lake_path = CURATED_DIR / ("neo_approaches.parquet" if lake_format == "parquet" else "neo_approaches.csv.gz")
    lake_kb = lake_path.stat().st_size / 1024
    csv_kb = (CURATED_DIR / "dataset.csv").stat().st_size / 1024
    return {
        "curated_rows": int(len(df)),
        "lake_format": lake_format,
        "lake_kb": round(lake_kb, 1),
        "csv_kb": round(csv_kb, 1),
        "compression_ratio": round(csv_kb / max(lake_kb, 0.1), 2),
        "marts": {"mart_risk_daily": int(len(risk)), "mart_characterization": int(len(charac))},
    }


def write_rejected(rejected: pd.DataFrame) -> Path:
    out = REJECTED_DIR / "rejected_rows.csv"
    rejected.to_csv(out, index=False)
    return out
