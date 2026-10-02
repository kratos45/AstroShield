"""Orchestrateur du pipeline AstroShield (batch, reproductible, idempotent).

Usage :
    python -m src.pipeline --synthetic          # démo complète hors-ligne
    python -m src.pipeline --offline            # rejoue data/raw/sample_source.json
    python -m src.pipeline --start 2026-09-01 --end 2026-09-30   # données réelles
    python -m src.pipeline --offline --inject-error  # + 1 ligne invalide (démo rejet)

Idempotence : clé métier (neo_id, approach_date), déduplication contrôlée,
UPSERT SQLite via index unique. Relancer deux fois ne duplique rien.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import collect, ml_models, transform, validate  # noqa: E402


def run(offline: bool = False, synthetic: bool = False,
        start: str | None = None, end: str | None = None,
        inject_error: bool = False, enrich_sbdb: bool = False,
        simulate_stream: bool = False) -> dict:
    t0 = time.perf_counter()
    started = datetime.now(timezone.utc)
    raw_files: list[Path] = []

    # 1. COLLECTE
    if synthetic:
        from src.simulate import build_synthetic_raw
        raw_files = [build_synthetic_raw()]
    elif offline:
        sample_path = ROOT / "data" / "raw" / "sample_source.json"
        if not sample_path.exists():
            from src.simulate import build_synthetic_raw
            sample_path = build_synthetic_raw()
        raw_files = [sample_path]
    else:
        try:
            raw_files = collect.collect_neows(start or "2026-09-01", end or "2026-09-30")
        except Exception as exc:  # source indisponible -> incident tracé, pas de crash silencieux
            return {
                "pipeline": "astroshield", "executed_at": started.isoformat(),
                "quality_status": "FAIL", "error": f"collecte impossible: {exc}",
                "duration_seconds": round(time.perf_counter() - t0, 2),
            }

    # 2. APLATISSEMENT + concaténation des fichiers bruts
    observed_at = pd.Timestamp(max(p.stat().st_mtime for p in raw_files), unit="s", tz="UTC")
    frames = [transform.flatten_neows(p, observed_at=observed_at) for p in raw_files]
    df = pd.concat(frames, ignore_index=True)

    if inject_error:  # donnée volontairement invalide pour la démonstration des rejets
        bad = df.iloc[[0]].copy()
        bad["neo_id"] = "BAD-DEMO-001"
        bad["miss_distance_km"] = -12345.0
        bad["approach_date"] = None
        df = pd.concat([df, bad], ignore_index=True)

    # 3. VALIDATION (7 règles du contrat YAML)
    accepted, rejected, quality = validate.validate(df)

    # Enrichissement SBDB en direct si demandé (en mode live)
    if enrich_sbdb and not (synthetic or offline):
        unique_neos = accepted["neo_id"].dropna().unique().tolist()
        collect.collect_sbdb_batch(unique_neos, max_objects=15)

    # Flux streaming simulé (bonus séance 3)
    stream_file = None
    if simulate_stream:
        stream_file = str(collect.simulate_telescope_stream().relative_to(ROOT))

    # 4. ENRICHISSEMENT SBDB + PUBLICATION (lake / curated / warehouse / marts)
    enriched = transform.enrich_sbdb(accepted)
    publish_stats = transform.publish(enriched)
    rejected_path = transform.write_rejected(rejected)

    # 5. ML / DL (dégradation propre si données insuffisantes)
    try:
        ml_results = ml_models.run_all(enriched)
    except Exception as exc:  # le pipeline ne doit pas mourir pour le ML
        ml_results = {"status": "FAILED", "error": str(exc)}

    # 6. RAPPORT
    report = {
        "pipeline": "astroshield",
        "executed_at": started.isoformat(),
        "mode": "synthetic" if synthetic else ("offline" if offline else "live"),
        "source_files": [p.name for p in raw_files],
        "input_rows": quality["input_rows"],
        "accepted_rows": quality["accepted_rows"],
        "rejected_rows": quality["rejected_rows"],
        "duplicates_removed": quality["duplicates_removed"],
        "rules": quality["rules"],
        "warnings": quality["warnings"],
        "quality_status": quality["quality_status"],
        "rejected_file": str(rejected_path.relative_to(ROOT)),
        "stream_file": stream_file,
        "publish": publish_stats,
        "ml": ml_results,
        "duration_seconds": round(time.perf_counter() - t0, 2),
        "idempotence": "clé métier (neo_id, approach_date) + UPSERT SQLite : relancer ne duplique rien",
    }
    out = ROOT / "reports" / "run_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline AstroShield")
    parser.add_argument("--offline", action="store_true", help="rejoue le fichier raw d'exemple")
    parser.add_argument("--synthetic", action="store_true", help="génère un jeu synthétique cohérent")
    parser.add_argument("--live", action="store_true", help="lance la collecte en direct via NASA NeoWs")
    parser.add_argument("--start", default="2026-09-01", help="date début (mode live)")
    parser.add_argument("--end", default="2026-09-30", help="date fin (mode live)")
    parser.add_argument("--inject-error", action="store_true", help="ajoute une ligne invalide (démo)")
    parser.add_argument("--enrich-sbdb", action="store_true", help="interroge l'API JPL SBDB pour enrichir")
    parser.add_argument("--stream", action="store_true", help="simule l'émission d'un flux d'événements télescope")
    args = parser.parse_args()

    report = run(
        offline=args.offline,
        synthetic=args.synthetic,
        start=args.start,
        end=args.end,
        inject_error=args.inject_error,
        enrich_sbdb=args.enrich_sbdb,
        simulate_stream=args.stream,
    )
    print(json.dumps({k: report[k] for k in
                      ["quality_status", "input_rows", "accepted_rows",
                       "rejected_rows", "duplicates_removed", "duration_seconds"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
