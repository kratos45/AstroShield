"""Serveur Web et WebSocket AstroShield — Dashboard Temps Réel & Scraper Autonome.

Ce serveur unifié Starlette / Uvicorn :
1. Fait tourner un scraper autonome en arrière-plan (MPC NEOCP + NASA JPL CNEOS)
   sans aucun bouton requis — les données sont collectées et poussées continuellement.
2. Sert l'interface web avancée (HTML/CSS/JS) sur http://127.0.0.1:8000.
3. Expose le flux WebSocket bidirectionnel sur ws://127.0.0.1:8000/ws.
4. Sert les logos et actifs statiques (/logos et /static).

Usage :
    python -m src.live_server [--host 127.0.0.1] [--port 8000] [--scrape-interval 12]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import sqlite3
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Set



import numpy as np
import requests
import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

# Initialisation du logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AstroShield-LiveServer")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)
SCRAPE_LOG = RAW_DIR / "realtime_scraped.jsonl"
DB_PATH = DATA_DIR / "astroshield.db"
WEB_DIR = ROOT / "web"
WEB_DIR.mkdir(parents=True, exist_ok=True)
LOGOS_DIR = ROOT / "logos"

# Sources externes
MPC_NEOCP_URL = "https://www.minorplanetcenter.net/iau/NEO/neocp.txt"
JPL_CAD_URL = "https://ssd-api.jpl.nasa.gov/cad.api"
AU_TO_KM = 149_597_870.7
LD_TO_KM = 384_400.0

# Gestion des clients WebSocket
CONNECTED_CLIENTS: Set[WebSocket] = set()
LATEST_MPC_CANDIDATES: list[dict[str, Any]] = []
LATEST_CNEOS_APPROACHES: list[dict[str, Any]] = []
EVENT_COUNTER = 0


# ============================================================================
# Logique de Scraping et Génération Astrophysique
# ============================================================================

def fetch_mpc_neocp() -> list[dict[str, Any]]:
    """Scrape le Centre des Planètes Mineures (NEOCP) en direct."""
    try:
        resp = requests.get(MPC_NEOCP_URL, timeout=8)
        resp.raise_for_status()
    except Exception as exc:
        logger.debug(f"MPC Scrape pass (réseau ou timeout) : {exc}")
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
                diam_est_m = round(1329.0 / (0.14 ** 0.5) * (10 ** (-0.2 * v_mag)) * 1000.0, 1)

                records.append({
                    "source": "MPC NEOCP",
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


def fetch_cneos_live(limit: int = 15) -> list[dict[str, Any]]:
    """Scrape les approches réelles imminentes depuis la NASA JPL CNEOS."""
    try:
        params = {"date-min": "now", "sort": "date", "limit": str(limit)}
        resp = requests.get(JPL_CAD_URL, params=params, timeout=8)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.debug(f"CNEOS Scrape pass : {exc}")
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
            d_km = round(10 ** ((22.0 - h_mag) / 2.5), 3) if h_mag else 0.15

            # Calculs physiques
            d_m = d_km * 1000.0
            mass_kg = (4.0 / 3.0) * np.pi * ((d_m / 2.0) ** 3) * 2600.0
            energy_joules = 0.5 * mass_kg * ((v_kms * 1000.0) ** 2)
            tnt_mt = round(energy_joules / 4.184e15, 2)
            crater_km = round(1.15 * (d_km ** 0.78) * (v_kms ** 0.44), 2)

            is_pha = bool(dist_ld < 19.5 and (h_mag and h_mag <= 22.0))
            torino = 0
            if dist_ld <= 1.0 and is_pha:
                torino = 4 if tnt_mt > 100 else 2
            elif dist_ld <= 3.0 and is_pha:
                torino = 1

            results.append({
                "source": "NASA CNEOS",
                "designation": item.get("des"),
                "name": item.get("des"),
                "approach_datetime_utc": item.get("cd"),
                "miss_distance_km": dist_km,
                "lunar_distance_ld": dist_ld,
                "relative_velocity_kms": v_kms,
                "absolute_magnitude_h": h_mag,
                "estimated_diameter_km": d_km,
                "tnt_megatons": tnt_mt,
                "crater_diameter_km": crater_km,
                "torino_scale": torino,
                "is_potentially_hazardous": is_pha,
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            })
        except (ValueError, TypeError):
            continue
    return results


def get_db_recent_approaches(limit: int = 40) -> list[dict[str, Any]]:
    """Récupère les dernières approches enregistrées dans la base SQLite."""
    if not DB_PATH.exists():
        return []
    try:
        con = sqlite3.connect(str(DB_PATH))
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute(
            """
            SELECT neo_id, name, approach_date, miss_distance_km, lunar_distance_ld,
                   relative_velocity_kms, diameter_mid_km, absolute_magnitude_h,
                   is_potentially_hazardous, tnt_megatons, crater_diameter_km,
                   spectral_family, torino_scale, dynamical_class, hazard_level
            FROM neo_approaches
            ORDER BY miss_distance_km ASC
            LIMIT ?
            """,
            (limit,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        con.close()
        return rows
    except Exception as exc:
        logger.error(f"Erreur lecture SQLite : {exc}")
        return []


def create_simulated_radar_observation(seed: int | None = None) -> dict[str, Any]:
    """Génère un signal télescopique temps réel pour l'animation radar continue."""
    global EVENT_COUNTER
    EVENT_COUNTER += 1
    rng = random.Random(seed) if seed is not None else random.Random()

    known_names = [
        "2026 TB", "Apophis (99942)", "Bennu (101955)", "2026 RH4", "2024 YR4",
        "Didymos (65803)", "2026 AA", "1950 DA", "2022 EB5", "2026 DX",
        "2023 DW", "2026 VC", "Ryugu (162173)", "2026 LK", "2025 QP"
    ]
    name = rng.choice(known_names)
    dist_ld = round(rng.uniform(0.35, 38.0), 2)
    dist_km = round(dist_ld * LD_TO_KM, 1)
    v_kms = round(rng.uniform(11.2, 34.8), 1)
    diam_km = round(10 ** rng.uniform(-1.8, 0.7), 3)

    # Physique
    d_m = diam_km * 1000.0
    mass_kg = (4.0 / 3.0) * np.pi * ((d_m / 2.0) ** 3) * 2600.0
    energy_joules = 0.5 * mass_kg * ((v_kms * 1000.0) ** 2)
    tnt_mt = round(energy_joules / 4.184e15, 2)
    crater_km = round(1.15 * (diam_km ** 0.78) * (v_kms ** 0.44), 2)
    pha = bool(dist_ld < 19.5 and diam_km > 0.14)

    torino = 0
    if dist_ld < 1.0 and pha:
        torino = 4 if tnt_mt > 50 else 2
    elif dist_ld < 3.0 and pha:
        torino = 1

    # Angle de position radar en degrés (0 à 360)
    angle_deg = round(rng.uniform(0.0, 360.0), 1)

    return {
        "event_id": f"RADAR-{EVENT_COUNTER:05d}",
        "event_type": "telescope.radar_ping",
        "source": "Réseau Radar Terrestre Goldstone / Arecibo NextGen",
        "name": name,
        "miss_distance_km": dist_km,
        "lunar_distance_ld": dist_ld,
        "relative_velocity_kms": v_kms,
        "diameter_km": diam_km,
        "tnt_megatons": tnt_mt,
        "crater_diameter_km": crater_km,
        "torino_scale": torino,
        "is_potentially_hazardous": pha,
        "position_angle_deg": angle_deg,
        "alert": bool(dist_ld < 3.0 or torino >= 2),
        "alert_level": "CRITICAL" if (dist_ld < 1.5 or torino >= 3) else ("WARNING" if dist_ld < 5.0 else "SAFE"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ============================================================================
# Diffusion WebSocket Asynchrone
# ============================================================================

async def broadcast_ws(payload: dict[str, Any]) -> None:
    """Diffuse un message JSON à tous les clients connectés au dashboard."""
    if not CONNECTED_CLIENTS:
        return
    msg = json.dumps(payload, ensure_ascii=False)
    disconnected: list[WebSocket] = []
    for client in list(CONNECTED_CLIENTS):
        try:
            await client.send_text(msg)
        except Exception:
            disconnected.append(client)

    for dead in disconnected:
        CONNECTED_CLIENTS.discard(dead)


# ============================================================================
# Boucle de Scraping Autonome en Temps Réel (ZÉRO BOUTON REQUIS)
# ============================================================================

async def autonomous_scraper_loop(scrape_interval: float = 12.0) -> None:
    """Tâche de fond perpétuelle :
    1. Scrape automatiquement MPC NEOCP et NASA CNEOS.
    2. Diffuse les nouvelles découvertes et les positions radar en direct.
    3. Met à jour les métriques globales.
    """
    global LATEST_MPC_CANDIDATES, LATEST_CNEOS_APPROACHES
    logger.info("🛰️ Démarrage du scraper autonome en temps réel (MPC + CNEOS)...")

    seen_mpc_ids: set[str] = set()
    loop_count = 0

    while True:
        try:
            loop_count += 1

            # 1. Scrape MPC toutes les ~12 secondes
            mpc_data = await asyncio.to_thread(fetch_mpc_neocp)
            if mpc_data:
                LATEST_MPC_CANDIDATES = mpc_data
                new_discoveries = [c for c in mpc_data if c["temp_id"] not in seen_mpc_ids]
                for disc in new_discoveries:
                    seen_mpc_ids.add(disc["temp_id"])
                    # Sauvegarde append-only
                    with SCRAPE_LOG.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(disc, ensure_ascii=False) + "\n")

                    # Diffusion immédiate au WebSocket
                    await broadcast_ws({
                        "event_type": "scraper.mpc_discovery",
                        "source": "IAU Minor Planet Center (NEOCP)",
                        "name": disc["name"],
                        "temp_id": disc["temp_id"],
                        "neo_score": disc["neo_score_pct"],
                        "magnitude": disc["apparent_v_magnitude"],
                        "diameter_m": disc["estimated_diameter_m"],
                        "urgency": disc["urgency"],
                        "alert": disc["neo_score_pct"] >= 75,
                        "timestamp": disc["scraped_at"],
                    })

            # 2. Scrape CNEOS (approches réelles imminentes)
            if loop_count % 2 == 1:
                cneos_data = await asyncio.to_thread(fetch_cneos_live, 12)
                if cneos_data:
                    LATEST_CNEOS_APPROACHES = cneos_data
                    # Diffuser le statut de synchronisation
                    await broadcast_ws({
                        "event_type": "scraper.cneos_sync",
                        "source": "NASA JPL CNEOS Live",
                        "approaches_count": len(cneos_data),
                        "closest_approach": cneos_data[0] if cneos_data else None,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

            # 3. Émission d'un événement Radar haute cadence pour fluidité du Live Dashboard
            radar_evt = create_simulated_radar_observation()
            await broadcast_ws(radar_evt)

            # Émission de télémétrie de statut
            await broadcast_ws({
                "event_type": "telemetry.heartbeat",
                "mpc_active_count": len(LATEST_MPC_CANDIDATES),
                "cneos_active_count": len(LATEST_CNEOS_APPROACHES),
                "clients_connected": len(CONNECTED_CLIENTS),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        except Exception as exc:
            logger.error(f"Erreur dans la boucle de scraping : {exc}")

        await asyncio.sleep(scrape_interval)


async def radar_high_freq_tick() -> None:
    """Diffuse des signaux radar rapides toutes les 2.5 secondes pour animer l'écran sans attente."""
    while True:
        await asyncio.sleep(2.5)
        if CONNECTED_CLIENTS:
            try:
                evt = create_simulated_radar_observation()
                await broadcast_ws(evt)
            except Exception:
                pass


# ============================================================================
# Routes HTTP / API
# ============================================================================

async def api_initial_state(request) -> JSONResponse:
    """Retourne l'état complet initial au chargement du Dashboard."""
    db_approaches = get_db_recent_approaches(50)
    return JSONResponse({
        "status": "online",
        "scraper_active": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mpc_candidates": LATEST_MPC_CANDIDATES[:30],
        "cneos_approaches": LATEST_CNEOS_APPROACHES,
        "database_approaches": db_approaches,
        "metrics": {
            "total_monitored": len(db_approaches) + len(LATEST_MPC_CANDIDATES) + len(LATEST_CNEOS_APPROACHES),
            "mpc_count": len(LATEST_MPC_CANDIDATES),
            "cneos_count": len(LATEST_CNEOS_APPROACHES),
            "pha_count": sum(1 for a in db_approaches if a.get("is_potentially_hazardous")),
            "closest_ld": min((a.get("lunar_distance_ld", 999.0) for a in db_approaches), default=1.2),
        },
    })


async def api_simulate_threat(request) -> JSONResponse:
    """Injecte une simulation de menace critique pour tester le protocole de défense."""
    threat_evt = {
        "event_id": f"THREAT-{random.randint(1000, 9999)}",
        "event_type": "telescope.critical_threat",
        "source": "SIMULATION DÉFENSE PLANÉTAIRE",
        "name": "ASTÉROÏDE IMPACTEUR ALPHA-2026",
        "miss_distance_km": 154200.0,
        "lunar_distance_ld": 0.40,
        "relative_velocity_kms": 31.4,
        "diameter_km": 1.25,
        "tnt_megatons": 420000.0,
        "crater_diameter_km": 18.5,
        "torino_scale": 8,
        "is_potentially_hazardous": True,
        "position_angle_deg": 142.0,
        "alert": True,
        "alert_level": "CRITICAL",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await broadcast_ws(threat_evt)
    return JSONResponse({"status": "injected", "event": threat_evt})


async def index_view(request) -> FileResponse:
    """Sert l'application web principale."""
    index_path = WEB_DIR / "index.html"
    return FileResponse(index_path)


# ============================================================================
# Gestionnaire WebSocket
# ============================================================================

async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    CONNECTED_CLIENTS.add(websocket)
    logger.info(f"Client Web connecté. Total clients : {len(CONNECTED_CLIENTS)}")

    # Envoi immédiat du paquet de synchronisation initiale
    welcome_packet = {
        "event_type": "connection.accepted",
        "message": "Connecté au centre de commande AstroShield en temps réel",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mpc_candidates": LATEST_MPC_CANDIDATES[:15],
        "cneos_approaches": LATEST_CNEOS_APPROACHES[:10],
    }
    await websocket.send_text(json.dumps(welcome_packet))

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                action = msg.get("action")
                if action == "ping":
                    await websocket.send_text(json.dumps({"event_type": "pong", "time": datetime.now(timezone.utc).isoformat()}))
                elif action == "trigger_threat":
                    await api_simulate_threat(None)
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        CONNECTED_CLIENTS.discard(websocket)
        logger.info(f"Client Web déconnecté. Restants : {len(CONNECTED_CLIENTS)}")
    except Exception as exc:
        CONNECTED_CLIENTS.discard(websocket)
        logger.error(f"Erreur socket : {exc}")


# ============================================================================
# Démarrage de l'Application Starlette
# ============================================================================

def create_app() -> Starlette:
    routes = [
        Route("/", endpoint=index_view, methods=["GET"]),
        Route("/api/initial-state", endpoint=api_initial_state, methods=["GET"]),
        Route("/api/simulate-threat", endpoint=api_simulate_threat, methods=["POST"]),
        WebSocketRoute("/ws", endpoint=websocket_endpoint),
    ]

    # Mount statiques pour les logos et le dossier web
    if LOGOS_DIR.exists():
        routes.append(Mount("/logos", app=StaticFiles(directory=str(LOGOS_DIR)), name="logos"))
    if WEB_DIR.exists():
        routes.append(Mount("/static", app=StaticFiles(directory=str(WEB_DIR)), name="static"))

    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    ]

    @asynccontextmanager
    async def lifespan(app: Starlette):
        task1 = asyncio.create_task(autonomous_scraper_loop(10.0))
        task2 = asyncio.create_task(radar_high_freq_tick())
        yield
        task1.cancel()
        task2.cancel()

    app = Starlette(
        debug=False,
        routes=routes,
        middleware=middleware,
        lifespan=lifespan,
    )
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="AstroShield — Dashboard Temps Réel et Scraper")
    parser.add_argument("--host", default="127.0.0.1", help="Hôte d'écoute")
    parser.add_argument("--port", type=int, default=8000, help="Port d'écoute HTTP et WebSocket")
    parser.add_argument("--scrape-interval", type=float, default=10.0, help="Intervalle de scrape en secondes")
    args = parser.parse_args()

    print("=" * 72)
    print(" [ASTROSHIELD] CENTRE DE DEFENSE PLANETAIRE & DASHBOARD TEMPS REEL")
    print(f" [*] Dashboard Web    : http://{args.host}:{args.port}")
    print(f" [*] Flux WebSocket   : ws://{args.host}:{args.port}/ws")
    print(f" [*] Scraper Autonome : ACTIF (MPC NEOCP + NASA CNEOS sans aucun bouton)")
    print("=" * 72)

    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
