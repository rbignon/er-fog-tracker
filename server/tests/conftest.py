"""Shared pytest fixtures for fogtracker tests."""

# Set default environment variables for tests BEFORE importing any fogtracker modules.
# This prevents pydantic Settings validation errors when importing main.py.
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://:memory:")
os.environ.setdefault("TWITCH_CLIENT_ID", "test")
os.environ.setdefault("TWITCH_CLIENT_SECRET", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing")

import json
from pathlib import Path

import pytest

from fogtracker.zone_resolver import init_resolver

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SPOILER_LOGS_DIR = FIXTURES_DIR / "spoiler_logs"
DATA_DIR = Path(__file__).parent.parent / "data"


@pytest.fixture(scope="session", autouse=True)
def init_data_files():
    """Initialize zone resolver (includes grace mapping) for all tests."""
    init_resolver(DATA_DIR)


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


# Starting zone ID used in tests (mirrors Game.starting_zone_id)
TEST_STARTING_ZONE_ID = "chapel_start"


@pytest.fixture
def starting_zone_id() -> str:
    """The starting zone ID for tests."""
    return TEST_STARTING_ZONE_ID


@pytest.fixture
def simple_zone_pairs() -> list[dict]:
    """Minimal hand-crafted zone pairs for predictable tests."""
    return [
        {
            "id": "link-1",
            "source": "Chapel of Anticipation",
            "source_id": "chapel_start",
            "target": "Limgrave",
            "target_id": "limgrave",
            "type": "random",
            "source_details": "before Grafted Scion's arena",
            "target_details": "at the start",
            "is_one_way": False,
        },
        {
            "id": "link-2",
            "source": "Limgrave",
            "source_id": "limgrave",
            "target": "Stormveil Castle",
            "target_id": "stormveil_castle",
            "type": "preexisting",
            "source_details": None,
            "target_details": "at the main gate",
            "is_one_way": False,
        },
        {
            "id": "link-3",
            "source": "Stormveil Castle",
            "source_id": "stormveil_castle",
            "target": "Limgrave",
            "target_id": "limgrave",
            "type": "preexisting",
            "source_details": None,
            "target_details": "back to Limgrave",
            "is_one_way": False,
        },
        {
            "id": "link-4",
            "source": "Limgrave",
            "source_id": "limgrave",
            "target": "Caelid",
            "target_id": "caelid",
            "type": "random",
            "source_details": "near the beach",
            "target_details": "arriving from the west",
            "is_one_way": False,
        },
        {
            "id": "link-5",
            "source": "Caelid",
            "source_id": "caelid",
            "target": "Dragonbarrow",
            "target_id": "dragonbarrow",
            "type": "preexisting",
            "source_details": None,
            "target_details": None,
            "is_one_way": False,
        },
        {
            "id": "link-6",
            "source": "Dragonbarrow",
            "source_id": "dragonbarrow",
            "target": "Caelid",
            "target_id": "caelid",
            "type": "preexisting",
            "source_details": None,
            "target_details": None,
            "is_one_way": False,
        },
        {
            "id": "link-7",
            "source": "Isolated Zone",
            "source_id": "isolated_zone",
            "target": "Another Isolated",
            "target_id": "another_isolated",
            "type": "random",
            "source_details": None,
            "target_details": None,
            "is_one_way": False,
        },
        {
            "id": "link-8",
            "source": "Sending Gate Origin",
            "source_id": "sending_gate_origin",
            "target": "Divine Tower",
            "target_id": "divine_tower",
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
            "source_id": "chapel_start",
            "target": "Zone A",
            "target_id": "zone_a",
            "type": "random",
            "source_details": None,
            "target_details": None,
            "is_one_way": False,
        },
        {
            "id": "link-a-b",
            "source": "Zone A",
            "source_id": "zone_a",
            "target": "Zone B",
            "target_id": "zone_b",
            "type": "random",
            "source_details": None,
            "target_details": None,
            "is_one_way": False,
        },
        {
            "id": "link-b-c",
            "source": "Zone B",
            "source_id": "zone_b",
            "target": "Zone C",
            "target_id": "zone_c",
            "type": "preexisting",
            "source_details": None,
            "target_details": None,
            "is_one_way": False,
        },
        {
            "id": "link-c-b",
            "source": "Zone C",
            "source_id": "zone_c",
            "target": "Zone B",
            "target_id": "zone_b",
            "type": "preexisting",
            "source_details": None,
            "target_details": None,
            "is_one_way": False,
        },
        # Preexisting from C to Boss (should be discovered after backprop)
        {
            "id": "link-c-boss",
            "source": "Zone C",
            "source_id": "zone_c",
            "target": "Boss Arena",
            "target_id": "boss_arena",
            "type": "preexisting",
            "source_details": None,
            "target_details": None,
            "is_one_way": False,
        },
        {
            "id": "link-boss-c",
            "source": "Boss Arena",
            "source_id": "boss_arena",
            "target": "Zone C",
            "target_id": "zone_c",
            "type": "preexisting",
            "source_details": None,
            "target_details": None,
            "is_one_way": False,
        },
        # The discovery link: C -> Destination
        {
            "id": "link-c-dest",
            "source": "Zone C",
            "source_id": "zone_c",
            "target": "Destination",
            "target_id": "destination",
            "type": "random",
            "source_details": None,
            "target_details": None,
            "is_one_way": False,
        },
    ]


@pytest.fixture
def preexisting_adjacent_zone_pairs() -> list[dict]:
    """
    Zone pairs for testing preexisting-adjacent fallback.

    This simulates the Volcano Manor bug where:
    - Player is in "Prison Town Church" (volcano_pretown)
    - Player walks through preexisting one-way door to "Prison Town" (volcano_town)
    - Player uses fog gate in Prison Town that leads to a boss
    - Mod reports source as volcano_pretown (cached), not volcano_town

    Graph structure:
    START (Chapel) --random--> volcano_pretown --preexisting(one-way)--> volcano_town
                                                                            |
                                                                          random
                                                                            v
                                                                      limgrave_tunnels_boss

    The fix should expand volcano_pretown to include volcano_town via the preexisting
    link when matching, so that the spoiler log link (volcano_town -> limgrave_tunnels_boss)
    can be found.
    """
    return [
        {
            "id": "link-start-church",
            "source": "Chapel of Anticipation",
            "source_id": "chapel_start",
            "target": "Volcano Manor Prison Town Church",
            "target_id": "volcano_pretown",
            "type": "random",
            "source_details": None,
            "target_details": None,
            "is_one_way": False,
        },
        # Preexisting one-way link: Church -> Town (one-way door)
        {
            "id": "link-church-town",
            "source": "Volcano Manor Prison Town Church",
            "source_id": "volcano_pretown",
            "target": "Volcano Manor Prison Town",
            "target_id": "volcano_town",
            "type": "preexisting",
            "source_details": None,
            "target_details": "opening the door to Prison Town",
            "is_one_way": True,  # One-way door
        },
        # Random fog gate: Town -> Boss (the actual link in spoiler log)
        {
            "id": "link-town-boss",
            "source": "Volcano Manor Prison Town",
            "source_id": "volcano_town",
            "target": "Limgrave Tunnels - Stonedigger Troll",
            "target_id": "limgrave_tunnels_boss",
            "type": "random",
            "source_details": "at the fog gate in Prison Town",
            "target_details": "before Stonedigger Troll's arena",
            "is_one_way": False,
        },
    ]


@pytest.fixture
def target_preexisting_adjacent_zone_pairs() -> list[dict]:
    """
    Zone pairs for testing target-side preexisting-adjacent expansion.

    This simulates the Academy -> Altus/Gelmir bug where:
    - Player is in academy_entrance
    - Player uses fog gate that leads to Mt. Gelmir (Wyndham Catacombs)
    - Landing position resolves to Altus Plateau (wrong zone due to boundary)
    - The fix should expand target candidates to include Mt. Gelmir (preexisting-adjacent)

    Graph structure:
    START (Chapel) --random--> academy_entrance --random--> altus (wrong match)
                                        |
                                      random
                                        v
                                     gelmir <--preexisting--> altus
                                   (correct match)

    The fix should expand target candidates from [altus] to [altus, gelmir]
    so both matches are found, and backprop cost can select the correct one.
    """
    return [
        # Random link to academy_entrance
        {
            "id": "link-start-academy",
            "source": "Chapel of Anticipation",
            "source_id": "chapel_start",
            "target": "Academy of Raya Lucaria Main Entrance",
            "target_id": "academy_entrance",
            "type": "random",
            "source_details": None,
            "target_details": None,
            "is_one_way": False,
        },
        # Preexisting bidirectional link: Altus <-> Gelmir (shared map boundary)
        {
            "id": "link-altus-gelmir",
            "source": "Altus Plateau",
            "source_id": "altus",
            "target": "Mt. Gelmir",
            "target_id": "gelmir",
            "type": "preexisting",
            "source_details": None,
            "target_details": "in map",
            "is_one_way": False,
        },
        {
            "id": "link-gelmir-altus",
            "source": "Mt. Gelmir",
            "source_id": "gelmir",
            "target": "Altus Plateau",
            "target_id": "altus",
            "type": "preexisting",
            "source_details": None,
            "target_details": "in map",
            "is_one_way": False,
        },
        # Random fog gate: Academy -> Altus (at Sainted Hero's Grave)
        {
            "id": "link-altus-academy",
            "source": "Altus Plateau",
            "source_id": "altus",
            "target": "Academy of Raya Lucaria Main Entrance",
            "target_id": "academy_entrance",
            "type": "random",
            "source_details": "at the entrance to Sainted Hero's Grave",
            "target_details": "arriving at Raya Lucaria Main Academy Gate from the East",
            "is_one_way": False,
        },
        # Random fog gate: Academy -> Gelmir (at Wyndham Catacombs) - THE CORRECT LINK
        {
            "id": "link-gelmir-academy",
            "source": "Mt. Gelmir",
            "source_id": "gelmir",
            "target": "Academy of Raya Lucaria Main Entrance",
            "target_id": "academy_entrance",
            "type": "random",
            "source_details": "at the entrance to Wyndham Catacombs",
            "target_details": "arriving at Raya Lucaria Main Academy Gate from the South",
            "is_one_way": False,
        },
    ]


@pytest.fixture
def parallel_links_zone_pairs() -> list[dict]:
    """
    Zone pairs with parallel links (multiple fog gates between same zones).

    This simulates the Divine Tower of Caelid scenario where there are
    3 different entrances from Dragonbarrow to the tower.

    Graph structure:
    START (Chapel) --random--> Dragonbarrow --parallel random x3--> Divine Tower
                                    |
                                    preexisting (bidirectional)
                                    |
                                    v
                                  Caelid
    """
    return [
        # Initial link from START
        {
            "id": "link-start-dragonbarrow",
            "source": "Chapel of Anticipation",
            "source_id": "chapel_start",
            "target": "Dragonbarrow",
            "target_id": "dragonbarrow",
            "type": "random",
            "source_details": "before Grafted Scion's arena",
            "target_details": "arriving in Dragonbarrow",
            "is_one_way": False,
        },
        # Parallel link 1: Dragonbarrow -> Divine Tower (middle entrance)
        {
            "id": "link-parallel-1",
            "source": "Dragonbarrow",
            "source_id": "dragonbarrow",
            "target": "Divine Tower of Caelid",
            "target_id": "caelid_tower",
            "type": "random",
            "source_details": "at the middle entrance to Divine Tower of Caelid",
            "target_details": "at the right exit to Dragonbarrow",
            "is_one_way": False,
        },
        # Parallel link 2: Dragonbarrow -> Divine Tower (right entrance)
        {
            "id": "link-parallel-2",
            "source": "Dragonbarrow",
            "source_id": "dragonbarrow",
            "target": "Divine Tower of Caelid",
            "target_id": "caelid_tower",
            "type": "random",
            "source_details": "at the right entrance to Divine Tower of Caelid",
            "target_details": "before Godskin Apostle's arena",
            "is_one_way": False,
            "blocks_propagation": True,
        },
        # Parallel link 3: Dragonbarrow -> Divine Tower Boss (left entrance)
        {
            "id": "link-parallel-3",
            "source": "Dragonbarrow",
            "source_id": "dragonbarrow",
            "target": "Divine Tower of Caelid - Boss",
            "target_id": "caelid_tower_boss",
            "type": "random",
            "source_details": "at the left entrance to Divine Tower of Caelid",
            "target_details": "at the front of Godskin Apostle's arena",
            "is_one_way": False,
        },
        # Preexisting link: Dragonbarrow <-> Caelid
        {
            "id": "link-dragonbarrow-caelid",
            "source": "Dragonbarrow",
            "source_id": "dragonbarrow",
            "target": "Caelid",
            "target_id": "caelid",
            "type": "preexisting",
            "source_details": None,
            "target_details": None,
            "is_one_way": False,
        },
        {
            "id": "link-caelid-dragonbarrow",
            "source": "Caelid",
            "source_id": "caelid",
            "target": "Dragonbarrow",
            "target_id": "dragonbarrow",
            "type": "preexisting",
            "source_details": None,
            "target_details": None,
            "is_one_way": False,
        },
        # Preexisting inside tower
        {
            "id": "link-tower-inner",
            "source": "Divine Tower of Caelid",
            "source_id": "caelid_tower",
            "target": "Divine Tower of Caelid - Boss",
            "target_id": "caelid_tower_boss",
            "type": "preexisting",
            "source_details": None,
            "target_details": None,
            "is_one_way": False,
        },
        {
            "id": "link-tower-boss-inner",
            "source": "Divine Tower of Caelid - Boss",
            "source_id": "caelid_tower_boss",
            "target": "Divine Tower of Caelid",
            "target_id": "caelid_tower",
            "type": "preexisting",
            "source_details": None,
            "target_details": None,
            "is_one_way": False,
        },
    ]
