"""Collecteurs AstroShield.

Source principale  : NASA NeoWs (feed des approches terrestres, 7 jours max / requête)
Source secondaire  : JPL SBDB (éléments orbitaux + paramètres physiques, enrichissement)
Bonus streaming    : simulateur d'observations télescope au format JSON Lines.

Toute réponse brute est conservée NON modifiée dans data/raw/ (zone rejouable).
Aucun secret dans le code : NASA_API_KEY est lu depuis l'environnement
(valeur DEMO_KEY par défaut, fortement limitée en quota).
"""
from __future__ import annotations

import json
import os
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

NEOWS_FEED_URL = "https://api.nasa.gov/neo/rest/v1/feed"
SBDB_URL = "https://ssd-api.jpl.nasa.gov/sbdb.api"

# Fenêtre de rejeu maximale acceptée par l'API NeoWs
NEOWS_WINDOW_DAYS = 7
# DEMO_KEY : 30 requêtes/min et 50 requêtes/jour -> on espace prudemment
RATE_LIMIT_SECONDS = 12.0


def utc_stamp() -> str:
    """Horodatage UTC au format contractuel YYYYMMDDTHHMMSSZ."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def collect_neows(
    start_date: str,
    end_date: str,
    api_key: str | None = None,
) -> list[Path]:
    """Télécharge le feed NeoWs par fenêtres de 7 jours.

    Écrit un fichier brut horodaté par fenêtre et retourne leurs chemins.
    Lève requests.HTTPError si la source est indisponible (géré par pipeline).
    """
    key = api_key or os.getenv("NASA_API_KEY", "DEMO_KEY")
    written: list[Path] = []
    cursor = datetime.fromisoformat(start_date)
    stop = datetime.fromisoformat(end_date)
    while cursor <= stop:
        window_end = min(cursor + timedelta(days=NEOWS_WINDOW_DAYS - 1), stop)
        params = {
            "start_date": cursor.date().isoformat(),
            "end_date": window_end.date().isoformat(),
            "api_key": key,
        }
        response = requests.get(NEOWS_FEED_URL, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()

        out = RAW_DIR / f"neows_{params['start_date']}_{params['end_date']}_{utc_stamp()}.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(out)

        cursor = window_end + timedelta(days=1)
        if cursor <= stop:
            time.sleep(RATE_LIMIT_SECONDS)
    return written


def collect_sbdb(neo_id: str) -> Path:
    """Enrichit UN astéroïde depuis la SBDB (éléments orbitaux + albedo).

    Le fichier brut permet de rejouer l'enrichissement sans rappeler l'API.
    """
    response = requests.get(
        SBDB_URL,
        params={"sstr": neo_id, "phys-par": "1", "orb": "1"},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    out = RAW_DIR / f"sbdb_{neo_id}_{utc_stamp()}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def collect_sbdb_batch(neo_ids: list[str], max_objects: int = 15, delay: float = 0.5) -> list[Path]:
    """Télécharge les éléments orbitaux SBDB pour une sélection d'astéroïdes."""
    written: list[Path] = []
    for nid in neo_ids[:max_objects]:
        try:
            written.append(collect_sbdb(str(nid)))
            time.sleep(delay)
        except Exception:
            continue
    return written


def simulate_telescope_stream(n_events: int = 50, seed: int = 42) -> Path:
    """Producteur simulé d'observations (partie streaming / alerte).

    Émet des événements `measurement.created` au format JSON Lines, pensés
    pour être publiés sur un topic Kafka dans la version cible (séance 3).
    """
    rng = random.Random(seed)
    out = RAW_DIR / f"telescope_events_{utc_stamp()}.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for i in range(n_events):
            event = {
                "event_id": f"evt-{i:05d}",
                "event_type": "measurement.created",
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "neo_id": f"SIM-{rng.randint(1, 20):03d}",
                "schema_version": 1,
                "payload": {
                    "value": round(rng.uniform(10.0, 28.0), 2),  # magnitude apparente
                    "unit": "mag",
                },
            }
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
            time.sleep(0.01)
    return out
