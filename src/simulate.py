"""Générateur de données synthétiques cohérentes (mode démo hors-ligne).

Produit un fichier brut au format exact de l'API NeoWs afin que le pipeline
complet (validation, transformation, ML) soit rejouable sans réseau ni clé.
Inclut volontairement ~5 % d'erreurs et des doublons pour démontrer les
règles de qualité et l'idempotence.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def build_synthetic_raw(n_asteroids: int = 25, n_days: int = 14, seed: int = 7) -> Path:
    rng = random.Random(seed)
    start = datetime(2026, 9, 15, tzinfo=timezone.utc)
    neo_names = [
        "2020 AB", "2021 BF", "2022 CX", "2023 DT", "2024 EP", "2025 FQ",
        "2026 GR", "2019 HS", "2018 IT", "2017 JU", "2016 KV", "2015 LW",
        "2014 MX", "2013 NY", "2012 OZ", "2011 PA", "2010 QB", "2009 RC",
        "2008 SD", "2007 TE", "2006 UF", "2005 VG", "2004 WH", "2003 XJ",
        "2002 YK",
    ]
    AU_KM = 149_597_870.7

    # 1. Génération des fichiers SBDB correspondants (enrichissement orbital)
    raw_dir = ROOT / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for idx in range(n_asteroids):
        nid = str(1000000 + idx)
        name = neo_names[idx % len(neo_names)]
        a = round(rng.uniform(0.95, 2.5), 4)
        e = round(rng.uniform(0.12, 0.60), 4)
        i = round(rng.uniform(2.5, 30.0), 2)
        q = round(a * (1.0 - e), 4)
        ad = round(a * (1.0 + e), 4)
        albedo = round(rng.choice([rng.uniform(0.03, 0.07), rng.uniform(0.12, 0.25), rng.uniform(0.28, 0.45)]), 3)
        sbdb_payload = {
            "object": {
                "spkid": nid,
                "fullname": f"({name})",
                "des": name,
                "orbit_id": str(rng.randint(10, 45)),
            },
            "orbit": {
                "a": str(a),
                "e": str(e),
                "i": str(i),
                "q": str(q),
                "ad": str(ad),
            },
            "phys_par": [
                {"name": "albedo", "value": str(albedo)},
            ],
        }
        sbdb_file = raw_dir / f"sbdb_{nid}.json"
        sbdb_file.write_text(json.dumps(sbdb_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # 2. Génération du feed NeoWs
    near_earth_objects: dict[str, list] = {}
    for day in range(n_days):
        date_str = (start + timedelta(days=day)).date().isoformat()
        entries = []
        for i in range(rng.randint(8, 20)):
            ast_idx = rng.randint(0, n_asteroids - 1)
            neo_id = str(1000000 + ast_idx)
            h = round(rng.gauss(22, 3), 2)          # magnitude absolue
            dmid = round(10 ** ((22.0 - h) / 2.5), 3)  # conversion H -> diamètre (km, albedo 0.14)
            # majorité d'approches proches (< 0.5 UA), ~4 % d'objets lointains rejouant la règle de domaine
            miss_ua = rng.uniform(0.55, 1.2) if rng.random() < 0.04 else rng.uniform(0.01, 0.45)
            miss_km = round(miss_ua * AU_KM, 1)
            cad = {
                "close_approach_date": date_str,
                "close_approach_date_full": f"{date_str} 00:00",
                "epoch_date_close_approach": int((start + timedelta(days=day)).timestamp() * 1000),
                "relative_velocity": {
                    "kilometers_per_second": str(round(rng.uniform(4, 35), 3)),
                },
                "miss_distance": {"kilometers": str(miss_km)},
                "orbiting_body": "Earth",
            }
            # ~2 % de données volontairement invalides pour la démo des rejets
            if rng.random() < 0.02:
                cad["miss_distance"]["kilometers"] = str(-round(rng.uniform(100, 5000), 1))
            if rng.random() < 0.02:
                cad["close_approach_date"] = None
            entries.append({
                "id": neo_id,
                "neo_reference_id": neo_id,
                "name": f"({neo_names[ast_idx]})",
                "absolute_magnitude_h": h,
                "is_potentially_hazardous_asteroid": bool(h < 22.0 and miss_km < 7_480_000),
                "estimated_diameter": {"kilometers": {
                    "estimated_diameter_min": round(dmid * 0.8, 3),
                    "estimated_diameter_max": round(dmid * 1.25, 3),
                }},
                "close_approach_data": [cad],
            })
        near_earth_objects[date_str] = entries

    # ~10 % de doublons (même astéroïde, même jour) pour tester l'idempotence
    for date_str, entries in near_earth_objects.items():
        if len(entries) >= 2 and rng.random() < 0.5:
            entries.append(json.loads(json.dumps(entries[0])))

    payload = {
        "links": {"next": "", "prev": "", "self": ""},
        "element_count": sum(len(v) for v in near_earth_objects.values()),
        "near_earth_objects": near_earth_objects,
    }
    out = ROOT / "data" / "raw" / "sample_source.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


if __name__ == "__main__":
    path = build_synthetic_raw()
    print(f"Jeu synthétique écrit : {path}")
