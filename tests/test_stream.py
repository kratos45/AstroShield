"""Tests du serveur et client WebSocket en temps réel."""
import asyncio
import json
import pytest
import websockets
from src.stream_server import generate_telescope_event, handle_client


def test_generate_telescope_event():
    evt = generate_telescope_event(seed=42)
    assert evt["event_type"] == "telescope.approach_detected"
    assert "lunar_distance_ld" in evt
    assert evt["lunar_distance_ld"] > 0
    assert "tnt_megatons" in evt
    assert evt["tnt_megatons"] >= 0
    assert "torino_scale" in evt
    assert 0 <= evt["torino_scale"] <= 10


def test_critical_threat_generation():
    evt = generate_telescope_event(critical_threat=True, seed=99)
    assert evt["alert"] is True
    assert evt["lunar_distance_ld"] < 1.0
    assert evt["is_potentially_hazardous"] is True


@pytest.mark.anyio
async def test_websocket_server_communication():
    import websockets.asyncio.server as ws_server

    # Démarre un serveur de test sur un port éphémère (ex: 8899)
    test_port = 8899
    server = await ws_server.serve(handle_client, "127.0.0.1", test_port)

    try:
        async with websockets.connect(f"ws://127.0.0.1:{test_port}") as ws:
            # 1. Message de bienvenue
            raw_welcome = await asyncio.wait_for(ws.recv(), timeout=2.0)
            welcome = json.loads(raw_welcome)
            assert welcome["event_type"] == "server.connected"

            # 2. Test Ping / Pong
            await ws.send(json.dumps({"action": "ping"}))
            raw_pong = await asyncio.wait_for(ws.recv(), timeout=2.0)
            pong = json.loads(raw_pong)
            assert pong["action"] == "pong"

            # 3. Test injection d'alerte manuelle
            await ws.send(json.dumps({"action": "inject_threat"}))
            raw_threat = await asyncio.wait_for(ws.recv(), timeout=2.0)
            threat = json.loads(raw_threat)
            assert threat["alert"] is True
            assert threat["lunar_distance_ld"] < 1.0
    finally:
        server.close()
        await server.wait_closed()


def test_realtime_scraper_mpc_and_cneos():
    from src.realtime_scraper import scrape_mpc_neocp, scrape_cneos_live
    mpc_items = scrape_mpc_neocp()
    assert isinstance(mpc_items, list)
    if mpc_items:
        first = mpc_items[0]
        assert "temp_id" in first
        assert "neo_score_pct" in first

    cneos_items = scrape_cneos_live(limit=3)
    assert isinstance(cneos_items, list)
    if cneos_items:
        first_c = cneos_items[0]
        assert "name" in first_c
        assert "lunar_distance_ld" in first_c
