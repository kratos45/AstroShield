"""Tests unitaires et d'intégration pour le serveur Live AstroShield (Starlette/WebSockets)."""
from __future__ import annotations

import json
import pytest
from src.live_server import (
    create_app,
    create_simulated_radar_observation,
    fetch_mpc_neocp,
    fetch_cneos_live,
    get_db_recent_approaches,
)


def test_create_simulated_radar_observation():
    """Vérifie la génération d'un signal radar avec toutes les métriques physiques."""
    obs = create_simulated_radar_observation(seed=42)
    assert "event_id" in obs
    assert "name" in obs
    assert "miss_distance_km" in obs
    assert "lunar_distance_ld" in obs
    assert "tnt_megatons" in obs
    assert "crater_diameter_km" in obs
    assert "torino_scale" in obs
    assert obs["lunar_distance_ld"] > 0
    assert obs["tnt_megatons"] >= 0


def test_get_db_recent_approaches():
    """Vérifie la lecture des approches récentes depuis SQLite."""
    rows = get_db_recent_approaches(10)
    assert isinstance(rows, list)
    if rows:
        row = rows[0]
        assert "name" in row
        assert "miss_distance_km" in row


def test_create_app_structure():
    """Vérifie l'initialisation de l'application Starlette et ses routes."""
    app = create_app()
    route_paths = [getattr(r, "path", None) for r in app.routes]
    assert "/" in route_paths
    assert "/api/initial-state" in route_paths
    assert "/api/simulate-threat" in route_paths
    assert "/ws" in route_paths
