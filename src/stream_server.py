"""Serveur WebSocket de streaming en direct — AstroShield.

Simule et diffuse en temps réel un flux d'observations télescope et d'approches
géocroiseurs (NEO) vers tous les clients connectés (Dashboard, consommateurs, alertes).

Usage :
    python -m src.stream_server [--host 127.0.0.1] [--port 8765] [--interval 1.5]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Set

import numpy as np

import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AstroShield-StreamServer")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RAW_DIR = ROOT / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)
STREAM_LOG = RAW_DIR / "live_stream.jsonl"

CONNECTED_CLIENTS: Set = set()
EVENT_COUNTER = 0


def generate_telescope_event(critical_threat: bool = False, seed: int | None = None) -> dict:
    """Génère un événement d'approche géocroiseur en direct avec métriques physiques."""
    global EVENT_COUNTER
    EVENT_COUNTER += 1
    rng = random.Random(seed) if seed is not None else random.Random()

    names = [
        "2026 XF", "2025 YP", "2024 AA", "Apophis (99942)", "Bennu (101955)",
        "2026 QR", "2023 DW", "1950 DA", "2022 EB5", "Didymos (65803)",
        "2026 ZL", "2021 NY", "2019 OK", "2020 QG", "2026 BC"
    ]
    name = rng.choice(names) if not critical_threat else "IMMINENT-IMPACT-2026"
    nid = str(rng.randint(2000000, 2999999)) if not critical_threat else "9999999"

    if critical_threat:
        dist_ld = round(rng.uniform(0.1, 0.9), 2)  # Extrêmement proche (< 1 LD)
        diam_km = round(rng.uniform(0.5, 2.5), 2)
        v_kms = round(rng.uniform(22.0, 38.0), 1)
        pha = True
    else:
        dist_ld = round(rng.uniform(0.4, 45.0), 2)
        diam_km = round(10 ** rng.uniform(-1.5, 0.8), 3)  # 30 m à 6 km
        v_kms = round(rng.uniform(9.0, 32.0), 1)
        pha = bool(dist_ld < 19.5 and diam_km > 0.14)

    dist_km = round(dist_ld * 384400.0, 1)

    # Calculs physiques : énergie et cratère
    d_m = diam_km * 1000.0
    v_ms = v_kms * 1000.0
    mass_kg = (4.0 / 3.0) * np.pi * ((d_m / 2.0) ** 3) * 2600.0
    energy_joules = 0.5 * mass_kg * (v_ms ** 2)
    tnt_mt = round(energy_joules / 4.184e15, 2)
    crater_km = round(1.15 * (diam_km ** 0.78) * (v_kms ** 0.44), 2)

    # Indice Échelle de Turin
    if dist_ld > 10.0 or not pha:
        torino = 0
    elif tnt_mt < 1.0:
        torino = 1 if dist_ld < 2.0 else 0
    elif tnt_mt < 100.0:
        torino = 3 if dist_ld < 1.0 else 2
    elif tnt_mt < 10000.0:
        torino = 6 if dist_ld < 0.5 else 4
    else:
        torino = 9 if dist_ld < 0.5 else 7

    is_alert = bool(dist_ld < 5.0 or torino >= 3)
    dyn_classes = ["Apollo", "Amor", "Aten", "Atira"]
    spec_families = ["C (carbonée)", "S (silicatée)", "M (métallique)"]

    return {
        "event_id": f"EVT-{EVENT_COUNTER:06d}",
        "event_type": "telescope.approach_detected",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "neo_id": nid,
        "name": name,
        "miss_distance_km": dist_km,
        "lunar_distance_ld": dist_ld,
        "relative_velocity_kms": v_kms,
        "diameter_km": diam_km,
        "is_potentially_hazardous": pha,
        "tnt_megatons": tnt_mt,
        "crater_diameter_km": crater_km,
        "torino_scale": torino,
        "dynamical_class": rng.choice(dyn_classes) if not critical_threat else "Apollo",
        "spectral_family": rng.choice(spec_families),
        "alert": is_alert,
        "alert_level": "CRITICAL" if torino >= 5 else ("WARNING" if is_alert else "INFO"),
    }


async def broadcast_event(event: dict) -> None:
    """Diffuse l'événement à tous les clients connectés et l'archive en JSON Lines."""
    payload = json.dumps(event, ensure_ascii=False)

    # Persistance append-only dans la zone brute
    try:
        with STREAM_LOG.open("a", encoding="utf-8") as f:
            f.write(payload + "\n")
    except Exception as err:
        logger.error(f"Erreur d'écriture dans le journal stream : {err}")

    if not CONNECTED_CLIENTS:
        return

    # Diffusion asynchrone non-bloquante
    disconnected = set()
    for ws in list(CONNECTED_CLIENTS):
        try:
            await ws.send(payload)
        except Exception:
            disconnected.add(ws)

    for dead_ws in disconnected:
        CONNECTED_CLIENTS.discard(dead_ws)


async def handle_client(websocket) -> None:
    """Gestionnaire de connexion client WebSocket."""
    CONNECTED_CLIENTS.add(websocket)
    remote = getattr(websocket, "remote_address", "client")
    logger.info(f"Nouveau client connecté : {remote} (Total: {len(CONNECTED_CLIENTS)})")

    # Envoi d'un message de bienvenue
    welcome = {
        "event_type": "server.connected",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": "Connecté au flux télescope temps réel AstroShield",
        "connected_clients": len(CONNECTED_CLIENTS),
    }
    await websocket.send(json.dumps(welcome))

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                action = data.get("action")
                if action == "ping":
                    await websocket.send(json.dumps({"action": "pong", "time": datetime.now(timezone.utc).isoformat()}))
                elif action == "inject_threat":
                    logger.warning("ALERTE : Injection manuelle d'une menace critique demandée !")
                    threat_evt = generate_telescope_event(critical_threat=True)
                    await broadcast_event(threat_evt)
                elif action == "stats":
                    await websocket.send(json.dumps({
                        "event_type": "server.stats",
                        "events_emitted": EVENT_COUNTER,
                        "connected_clients": len(CONNECTED_CLIENTS),
                    }))
            except json.JSONDecodeError:
                pass
    except Exception:
        pass
    finally:
        CONNECTED_CLIENTS.discard(websocket)
        logger.info(f"Client déconnecté : {remote} (Restants: {len(CONNECTED_CLIENTS)})")


async def stream_generator(interval: float) -> None:
    """Boucle continue émettant des observations à intervalle régulier."""
    while True:
        await asyncio.sleep(interval)
        event = generate_telescope_event()
        if event["alert"]:
            logger.warning(f"🚨 ALERTE ASTÉROÏDE RAPPROCHÉ : {event['name']} à {event['lunar_distance_ld']} LD | {event['tnt_megatons']} Mt TNT")
        else:
            logger.info(f"📡 Passage détecté : {event['name']} ({event['miss_distance_km']:,} km)")
        await broadcast_event(event)


async def main_async(host: str, port: int, interval: float) -> None:
    import websockets.asyncio.server as ws_server

    logger.info(f"Démarrage du serveur WebSocket AstroShield sur ws://{host}:{port}")
    logger.info(f"Fréquence de diffusion : 1 événement toutes les {interval} secondes")

    # Lance le serveur et le générateur en concurrence
    async with ws_server.serve(handle_client, host, port):
        await stream_generator(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serveur WebSocket AstroShield Live")
    parser.add_argument("--host", default="127.0.0.1", help="Adresse IP d'écoute")
    parser.add_argument("--port", type=int, default=8765, help="Port WebSocket")
    parser.add_argument("--interval", type=float, default=2.0, help="Intervalle d'émission en secondes")
    args = parser.parse_args()

    try:
        asyncio.run(main_async(args.host, args.port, args.interval))
    except KeyboardInterrupt:
        logger.info("Arrêt du serveur WebSocket.")


if __name__ == "__main__":
    main()
