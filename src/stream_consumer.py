"""Consommateur client WebSocket — AstroShield.

Se connecte au flux télescope en direct, filtre les alertes de défense
planétaire et affiche les passages rapprochés en temps réel.

Usage :
    python -m src.stream_consumer [--url ws://127.0.0.1:8765] [--max-events 20]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import datetime

import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AstroShield-Consumer")


async def consume(url: str, max_events: int | None = None) -> list[dict]:
    """Écoute le flux WebSocket et retourne les événements collectés."""
    received = []
    logger.info(f"Connexion au serveur WebSocket sur {url}...")

    async with websockets.connect(url) as ws:
        logger.info("Connexion établie avec succès. En attente d'événements...")

        async for raw_msg in ws:
            event = json.loads(raw_msg)
            event_type = event.get("event_type")

            if event_type == "server.connected":
                logger.info(f"Message serveur : {event.get('message')}")
                continue

            received.append(event)
            name = event.get("name", "Inconnu")
            dist_ld = event.get("lunar_distance_ld", 0)
            tnt = event.get("tnt_megatons", 0)
            torino = event.get("torino_scale", 0)
            alert = event.get("alert", False)

            if alert:
                logger.warning(
                    f"🚨 [ALERTE DÉFENSE PLANÉTAIRE] {name} | Distance: {dist_ld:.2f} LD | "
                    f"Énergie: {tnt:,.1f} Mt | Turin: {torino}/10 | "
                    f"Cratère est.: {event.get('crater_diameter_km', 0)} km"
                )
            else:
                logger.info(
                    f"🔭 [OBSERVATION NORMALE] {name} | Distance: {dist_ld:.1f} LD ({event.get('miss_distance_km'):,.0f} km) | "
                    f"Vitesse: {event.get('relative_velocity_kms')} km/s"
                )

            if max_events and len(received) >= max_events:
                logger.info(f"Nombre maximum d'événements ({max_events}) atteint.")
                break

    return received


def main() -> None:
    parser = argparse.ArgumentParser(description="Consommateur WebSocket AstroShield")
    parser.add_argument("--url", default="ws://127.0.0.1:8765", help="URL du serveur WebSocket")
    parser.add_argument("--max-events", type=int, default=10, help="Arrêt après N événements (0 = infini)")
    args = parser.parse_args()

    max_ev = args.max_events if args.max_events > 0 else None
    try:
        asyncio.run(consume(args.url, max_ev))
    except KeyboardInterrupt:
        logger.info("Arrêt du consommateur.")
    except Exception as exc:
        logger.error(f"Erreur de connexion : {exc}")


if __name__ == "__main__":
    main()
