"""Scraper temps réel — AstroShield.

Collecte en direct les alertes et découvertes d'astéroïdes géocroiseurs depuis :
1. Le Centre des Planètes Mineures (IAU / MPC - Near-Earth Object Confirmation Page)
   URL : https://www.minorplanetcenter.net/iau/NEO/neocp.txt
2. Le service CNEOS / JPL en direct (approches rapprochées planifiées aujourd'hui)
   URL : https://ssd-api.jpl.nasa.gov/cad.api

Usage :
    python -m src.realtime_scraper [--poll-interval 15] [--push-ws]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import websockets

import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AstroShield-RealTimeScraper")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RAW_DIR = ROOT / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)
SCRAPE_LOG = RAW_DIR / "realtime_scraped.jsonl"

MPC_NEOCP_URL = "https://www.minorplanetcenter.net/iau/NEO/neocp.txt"
JPL_CAD_URL = "https://ssd-api.jpl.nasa.gov/cad.api"
AU_TO_KM = 149_597_870.7
LD_TO_KM = 384_400.0


def scrape_mpc_neocp(timeout: int = 10) -> list[dict[str, Any]]:
    """Scrape la page de confirmation des nouveaux astéroïdes découverts (MPC IAU)."""
    try:
        resp = requests.get(MPC_NEOCP_URL, timeout=timeout)
        resp.raise_for_status()
    except Exception as exc:
        logger.error(f"Échec du scraping MPC NEOCP : {exc}")
        return []

    records: list[dict[str, Any]] = []
    lines = resp.text.strip().splitlines()

    for line in lines:
        parts = line.split()
        if len(parts) >= 8:
            try:
                temp_id = parts[0]
                score = int(parts[1]) if parts[1].isdigit() else 0
                epoch = f"{parts[2]}-{parts[3]}-{parts[4]}"
                ra = float(parts[5])
                dec = float(parts[6])
                v_mag = float(parts[7])

                # Estimation approximative du diamètre via magnitude V (albédo moyen ~ 0.14)
                diam_est_m = round(1329.0 / (0.14 ** 0.5) * (10 ** (-0.2 * v_mag)) * 1000.0, 1)

                records.append({
                    "source": "IAU Minor Planet Center (NEOCP)",
                    "temp_id": temp_id,
                    "name": f"NEOCP-{temp_id}",
                    "neo_score_pct": score,
                    "observation_epoch": epoch,
                    "ra_hours": ra,
                    "dec_degrees": dec,
                    "apparent_v_magnitude": v_mag,
                    "estimated_diameter_m": diam_est_m,
                    "urgency": "CRITIQUE" if score >= 80 else ("SURVEILLANCE" if score >= 50 else "STANDARD"),
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                })
            except (ValueError, IndexError):
                continue

    return records


def scrape_cneos_live(limit: int = 15, timeout: int = 10) -> list[dict[str, Any]]:
    """Récupère les approches d'astéroïdes réelles les plus imminentes (NASA JPL CNEOS)."""
    try:
        params = {
            "date-min": "now",
            "sort": "date",
            "limit": str(limit),
        }
        resp = requests.get(JPL_CAD_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.error(f"Échec de l'interrogation CNEOS Live : {exc}")
        return []

    fields = data.get("fields", [])
    rows = data.get("data", [])
    results: list[dict[str, Any]] = []

    for row in rows:
        item = dict(zip(fields, row))
        try:
            dist_au = float(item.get("dist", 0.0))
            dist_km = round(dist_au * AU_TO_KM, 1)
            dist_ld = round(dist_km / LD_TO_KM, 2)
            v_kms = round(float(item.get("v_rel", 0.0)), 2)
            h_mag = float(item.get("h", 22.0)) if item.get("h") else None

            # Diamètre moyen estimé (km)
            d_km = round(10 ** ((22.0 - h_mag) / 2.5), 3) if h_mag else 0.15

            results.append({
                "source": "NASA JPL CNEOS (Live CAD)",
                "designation": item.get("des"),
                "name": item.get("des"),
                "approach_datetime_utc": item.get("cd"),
                "miss_distance_km": dist_km,
                "lunar_distance_ld": dist_ld,
                "relative_velocity_kms": v_kms,
                "absolute_magnitude_h": h_mag,
                "estimated_diameter_km": d_km,
                "is_potentially_hazardous": bool(dist_ld < 19.5 and (h_mag and h_mag <= 22.0)),
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            })
        except (ValueError, TypeError):
            continue

    return results


async def push_batch_to_websocket(ws_url: str, events: list[dict[str, Any]]) -> int:
    """Envoie un lot d'événements au serveur WebSocket en une seule connexion si disponible."""
    if not events:
        return 0
    try:
        async with websockets.connect(ws_url, open_timeout=0.4) as ws:
            await asyncio.wait_for(ws.recv(), timeout=0.8)
            for evt in events:
                await ws.send(json.dumps(evt, ensure_ascii=False))
            return len(events)
    except Exception:
        return 0


def run_live_scraper(
    poll_interval: float = 15.0,
    push_ws: bool = True,
    ws_url: str = "ws://127.0.0.1:8765",
    max_cycles: int | None = None,
) -> None:
    """Boucle de scraping en direct avec détection de nouveautés et archivage."""
    logger.info("Démarrage du Scraper Temps Réel AstroShield (MPC NEOCP + NASA CNEOS)...")
    seen_mpc_ids: set[str] = set()
    cycle = 0

    while True:
        cycle += 1
        logger.info(f"--- Cycle #{cycle} : Collecte télescope en direct ---")

        # 1. Scraping MPC NEOCP
        mpc_candidates = scrape_mpc_neocp()
        new_candidates = [c for c in mpc_candidates if c["temp_id"] not in seen_mpc_ids]
        logger.info(f"MPC NEOCP : {len(mpc_candidates)} candidats actifs ({len(new_candidates)} nouvelles découvertes)")

        ws_batch: list[dict[str, Any]] = []
        for cand in new_candidates:
            seen_mpc_ids.add(cand["temp_id"])
            # Log append-only dans data/raw/realtime_scraped.jsonl
            with SCRAPE_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(cand, ensure_ascii=False) + "\n")

            if cand["neo_score_pct"] >= 80:
                logger.warning(
                    f"🚨 NOUVELLE DÉCOUVERTE GÉOCROISEUR (Score: {cand['neo_score_pct']}%) : "
                    f"Identifiant {cand['temp_id']} | Mag V: {cand['apparent_v_magnitude']} | "
                    f"Diamètre estimé: {cand['estimated_diameter_m']} m"
                )

            ws_batch.append({
                "event_type": "mpc.new_candidate_discovery",
                "event_id": f"MPC-{cand['temp_id']}",
                "name": cand["name"],
                "neo_score": cand["neo_score_pct"],
                "diameter_km": cand["estimated_diameter_m"] / 1000.0,
                "alert": cand["neo_score_pct"] >= 80,
                "occurred_at": cand["scraped_at"],
            })

        if push_ws and ws_batch:
            sent_count = asyncio.run(push_batch_to_websocket(ws_url, ws_batch))
            if sent_count:
                logger.info(f"Diffusé {sent_count} découvertes au serveur WebSocket.")

        # 2. Scraping NASA CNEOS Live
        cneos_approaches = scrape_cneos_live(limit=5)
        logger.info(f"NASA CNEOS Live : {len(cneos_approaches)} approches terrestres imminentes recensées.")

        for app in cneos_approaches[:2]:
            logger.info(
                f"🪐 Approche NASA : {app['name']} le {app['approach_datetime_utc']} "
                f"à {app['lunar_distance_ld']} LD ({app['miss_distance_km']:,} km)"
            )

        if max_cycles and cycle >= max_cycles:
            logger.info(f"Fin du scraping après {max_cycles} cycles.")
            break

        time.sleep(poll_interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scraper temps réel AstroShield (MPC & NASA CNEOS)")
    parser.add_argument("--poll-interval", type=float, default=15.0, help="Intervalle d'interrogation en secondes")
    parser.add_argument("--push-ws", action="store_true", default=True, help="Relayer les événements vers le serveur WebSocket")
    parser.add_argument("--ws-url", default="ws://127.0.0.1:8765", help="URL du serveur WebSocket")
    parser.add_argument("--cycles", type=int, default=0, help="Nombre de cycles (0 = infini)")
    args = parser.parse_args()

    max_c = args.cycles if args.cycles > 0 else None
    try:
        run_live_scraper(
            poll_interval=args.poll_interval,
            push_ws=args.push_ws,
            ws_url=args.ws_url,
            max_cycles=max_c,
        )
    except KeyboardInterrupt:
        logger.info("Arrêt du scraper temps réel.")


if __name__ == "__main__":
    main()
