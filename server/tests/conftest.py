"""Shared pytest fixtures for fogtracker tests."""

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SPOILER_LOGS_DIR = FIXTURES_DIR / "spoiler_logs"


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
            "is_one_way": False,
        },
        {
            "id": "link-2",
            "source": "Limgrave",
            "target": "Stormveil Castle",
            "type": "preexisting",
            "source_details": None,
            "target_details": "at the main gate",
            "is_one_way": False,
        },
        {
            "id": "link-3",
            "source": "Stormveil Castle",
            "target": "Limgrave",
            "type": "preexisting",
            "source_details": None,
            "target_details": "back to Limgrave",
            "is_one_way": False,
        },
        {
            "id": "link-4",
            "source": "Limgrave",
            "target": "Caelid",
            "type": "random",
            "source_details": "near the beach",
            "target_details": "arriving from the west",
            "is_one_way": False,
        },
        {
            "id": "link-5",
            "source": "Caelid",
            "target": "Dragonbarrow",
            "type": "preexisting",
            "source_details": None,
            "target_details": None,
            "is_one_way": False,
        },
        {
            "id": "link-6",
            "source": "Dragonbarrow",
            "target": "Caelid",
            "type": "preexisting",
            "source_details": None,
            "target_details": None,
            "is_one_way": False,
        },
        {
            "id": "link-7",
            "source": "Isolated Zone",
            "target": "Another Isolated",
            "type": "random",
            "source_details": None,
            "target_details": None,
            "is_one_way": False,
        },
        {
            "id": "link-8",
            "source": "Sending Gate Origin",
            "target": "Divine Tower",
            "type": "random",
            "source_details": "using the sending gate",
            "target_details": "warp destination",
            "is_one_way": True,
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


# Spoiler log fixtures


@pytest.fixture
def spoiler_log_1078869800() -> str:
    """Real spoiler log for seed 1078869800."""
    return (SPOILER_LOGS_DIR / "seed_1078869800.txt").read_text()


@pytest.fixture
def spoiler_log_1851144969() -> str:
    """Real spoiler log for seed 1851144969."""
    return (SPOILER_LOGS_DIR / "seed_1851144969.txt").read_text()


@pytest.fixture
def backprop_preexisting_zone_pairs() -> list[dict]:
    """
    Zone pairs for testing preexisting propagation after back-propagation.

    Graph structure:
    START (Chapel) --random--> A --random--> B --preexisting--> C (source)
                                                               |
                                                               preexisting
                                                               |
                                                               v
                                                              Boss
    C --random--> Destination

    When discovering C -> Destination:
    1. C is not accessible from START
    2. Back-propagate: START -> A -> B -> C
    3. After backprop, C's preexisting link to Boss should also be discovered
    """
    return [
        # Path from START to C
        {
            "id": "link-start-a",
            "source": "Chapel of Anticipation",
            "target": "Zone A",
            "type": "random",
            "source_details": None,
            "target_details": None,
            "is_one_way": False,
        },
        {
            "id": "link-a-b",
            "source": "Zone A",
            "target": "Zone B",
            "type": "random",
            "source_details": None,
            "target_details": None,
            "is_one_way": False,
        },
        {
            "id": "link-b-c",
            "source": "Zone B",
            "target": "Zone C",
            "type": "preexisting",
            "source_details": None,
            "target_details": None,
            "is_one_way": False,
        },
        {
            "id": "link-c-b",
            "source": "Zone C",
            "target": "Zone B",
            "type": "preexisting",
            "source_details": None,
            "target_details": None,
            "is_one_way": False,
        },
        # Preexisting from C to Boss (should be discovered after backprop)
        {
            "id": "link-c-boss",
            "source": "Zone C",
            "target": "Boss Arena",
            "type": "preexisting",
            "source_details": None,
            "target_details": None,
            "is_one_way": False,
        },
        {
            "id": "link-boss-c",
            "source": "Boss Arena",
            "target": "Zone C",
            "type": "preexisting",
            "source_details": None,
            "target_details": None,
            "is_one_way": False,
        },
        # The discovery link: C -> Destination
        {
            "id": "link-c-dest",
            "source": "Zone C",
            "target": "Destination",
            "type": "random",
            "source_details": None,
            "target_details": None,
            "is_one_way": False,
        },
    ]
