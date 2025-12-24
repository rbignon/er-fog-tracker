"""Shared pytest fixtures for fogvizu tests."""

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests (requires running server on localhost:8001)",
    )


def normalize_zone_link(link: dict) -> dict:
    """Normalize old terminology (destination -> target).

    The JSON fixtures use the old 'destination' field name,
    but the codebase now uses 'target'.
    """
    normalized = link.copy()
    if "destination" in normalized:
        normalized["target"] = normalized.pop("destination")
    return normalized


def load_zone_pairs(filename: str) -> list[dict]:
    """Load and normalize zone pairs from a fixture file."""
    with open(FIXTURES_DIR / filename) as f:
        return [normalize_zone_link(zp) for zp in json.load(f)]


@pytest.fixture
def zone_pairs_small() -> list[dict]:
    """Small dataset for quick tests (~100 links, seed 1078869800)."""
    return load_zone_pairs("1078869800.json")


@pytest.fixture
def zone_pairs_large() -> list[dict]:
    """Large dataset for exhaustive tests (~150 links, seed 1567343926)."""
    return load_zone_pairs("1567343926.json")


@pytest.fixture
def simple_zone_pairs() -> list[dict]:
    """Minimal hand-crafted zone pairs for predictable tests."""
    return [
        {
            "id": "link-1",
            "source": "Chapel of Anticipation",
            "target": "Limgrave",
            "type": "random",
            "source_details": "before Grafted Scion's arena",
            "target_details": "at the start",
            "is_inherently_one_way": False,
        },
        {
            "id": "link-2",
            "source": "Limgrave",
            "target": "Stormveil Castle",
            "type": "preexisting",
            "source_details": None,
            "target_details": "at the main gate",
            "is_inherently_one_way": False,
        },
        {
            "id": "link-3",
            "source": "Stormveil Castle",
            "target": "Limgrave",
            "type": "preexisting",
            "source_details": None,
            "target_details": "back to Limgrave",
            "is_inherently_one_way": False,
        },
        {
            "id": "link-4",
            "source": "Limgrave",
            "target": "Caelid",
            "type": "random",
            "source_details": "near the beach",
            "target_details": "arriving from the west",
            "is_inherently_one_way": False,
        },
        {
            "id": "link-5",
            "source": "Caelid",
            "target": "Dragonbarrow",
            "type": "preexisting",
            "source_details": None,
            "target_details": None,
            "is_inherently_one_way": False,
        },
        {
            "id": "link-6",
            "source": "Dragonbarrow",
            "target": "Caelid",
            "type": "preexisting",
            "source_details": None,
            "target_details": None,
            "is_inherently_one_way": False,
        },
        {
            "id": "link-7",
            "source": "Isolated Zone",
            "target": "Another Isolated",
            "type": "random",
            "source_details": None,
            "target_details": None,
            "is_inherently_one_way": False,
        },
        {
            "id": "link-8",
            "source": "Sending Gate Origin",
            "target": "Divine Tower",
            "type": "random",
            "source_details": "using the sending gate",
            "target_details": "warp destination",
            "is_inherently_one_way": True,
        },
    ]


@pytest.fixture
def discovered_chapel_to_limgrave(simple_zone_pairs: list[dict]) -> list[dict]:
    """Discovered links: Chapel -> Limgrave (makes Limgrave accessible)."""
    return [{"zone_link_id": "link-1"}]


@pytest.fixture
def discovered_to_caelid(simple_zone_pairs: list[dict]) -> list[dict]:
    """Discovered links: Chapel -> Limgrave -> Caelid."""
    return [
        {"zone_link_id": "link-1"},
        {"zone_link_id": "link-4"},
    ]
