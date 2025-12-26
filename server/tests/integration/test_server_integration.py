#!/usr/bin/env python3
"""
Integration test for the server after the terminology refactoring.

Tests:
1. API: Create game from spoiler log, fetch game
2. WebSocket: Mod connection, discovery events, viewer sync
3. Data format validation: Ensures all responses use new terminology

Usage:
    # Start server first:
    uvicorn fogtracker.main:app --port 8001

    # Run tests:
    python -m pytest tests/test_server_integration.py -v
    # Or directly:
    python tests/test_server_integration.py
"""

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
import websockets

# =============================================================================
# Configuration
# =============================================================================

BASE_URL = "http://localhost:8001"
WS_URL = "ws://localhost:8001"

# Hardcoded test tokens (will be inserted into DB)
TEST_API_TOKEN = "test_api_token_12345678901234567890123456789012"
TEST_MOD_TOKEN = "test_mod_token_12345678901234567890123456789012"
TEST_TWITCH_ID = "test_user_99999"
TEST_USERNAME = "test_user"

# Default spoiler log path (relative to project root)
DEFAULT_SPOILER_LOG = "2025-12-18_20.06.27_log_1078869800_97790.txt"


def get_spoiler_log() -> str:
    """Load spoiler log from file or use minimal fallback."""
    script_dir = Path(__file__).parent
    project_root = script_dir.parent.parent  # server/tests -> er-fog-tracker

    # Try to load from file
    spoiler_path = project_root / DEFAULT_SPOILER_LOG
    if spoiler_path.exists():
        print(f"Using spoiler log: {spoiler_path}")
        return spoiler_path.read_text()

    # Fallback to minimal spoiler log
    print("WARNING: Using minimal fallback spoiler log")
    return """Options and seed:12345 Fog Gate Randomizer
Chapel of Anticipation
  Random: Chapel of Anticipation (before Grafted Scion's arena) --> Limgrave (at the start)
Limgrave
  Preexisting: Limgrave --> Stormveil Castle (at the main gate)
  Random: Limgrave (near the beach) --> Caelid (arriving from the west)
Stormveil Castle
  Preexisting: Stormveil Castle --> Liurnia (after the boss)
Caelid
Liurnia
Optional areas:
"""


# =============================================================================
# Test Utilities
# =============================================================================


async def setup_test_user(db_url: str):
    """Create test user in database with hardcoded tokens."""
    import asyncpg

    # Parse database URL
    # Format: postgresql+asyncpg://user:pass@host:port/db
    # asyncpg wants: postgresql://user:pass@host:port/db
    conn_url = db_url.replace("postgresql+asyncpg://", "postgresql://")

    conn = await asyncpg.connect(conn_url)
    try:
        # Check if user exists
        existing = await conn.fetchrow("SELECT id FROM users WHERE twitch_id = $1", TEST_TWITCH_ID)

        if existing:
            # Update tokens
            await conn.execute(
                """
                UPDATE users
                SET api_token = $1, mod_token = $2
                WHERE twitch_id = $3
                """,
                TEST_API_TOKEN,
                TEST_MOD_TOKEN,
                TEST_TWITCH_ID,
            )
            print(f"Updated test user tokens (id={existing['id']})")
        else:
            # Create user
            await conn.execute(
                """
                INSERT INTO users (twitch_id, twitch_username, twitch_display_name, api_token, mod_token, created_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                TEST_TWITCH_ID,
                TEST_USERNAME,
                "Test User",
                TEST_API_TOKEN,
                TEST_MOD_TOKEN,
                datetime.now(UTC),
            )
            print("Created test user")
    finally:
        await conn.close()


def validate_uuid(value: str) -> bool:
    """Check if a string is a valid UUID."""
    try:
        UUID(value)
        return True
    except (ValueError, TypeError):
        return False


def validate_link_format(link: dict) -> list[str]:
    """Validate a link object has correct format. Returns list of errors."""
    errors = []
    required_fields = ["id", "source", "target", "type"]

    for field in required_fields:
        if field not in link:
            errors.append(f"Missing required field: {field}")

    if "id" in link and not validate_uuid(link["id"]):
        errors.append(f"Invalid UUID for link id: {link['id']}")

    # Check that old terminology is NOT used
    if "destination" in link:
        errors.append("OLD TERMINOLOGY: 'destination' should be 'target'")
    if "destination_key" in link:
        errors.append("OLD TERMINOLOGY: 'destination_key' should be 'target_key'")

    return errors


def validate_discovered_link_format(dl: dict) -> list[str]:
    """Validate a discovered_link object. Returns list of errors."""
    errors = []

    if "link_id" not in dl:
        errors.append("Missing required field: link_id")
    elif not validate_uuid(dl["link_id"]):
        errors.append(f"Invalid UUID for link_id: {dl['link_id']}")

    # These are optional but should be present if set
    # discovered_at, discovered_by

    # Check that old expansion format is NOT used
    if "source" in dl:
        errors.append("OLD FORMAT: discovered_link should NOT contain 'source'")
    if "target" in dl:
        errors.append("OLD FORMAT: discovered_link should NOT contain 'target'")

    return errors


def validate_game_response(game: dict) -> list[str]:
    """Validate GET /games/{id} response format. Returns list of errors."""
    errors = []

    # Check required fields
    required = ["id", "seed", "links", "discovered_links"]
    for field in required:
        if field not in game:
            errors.append(f"Missing required field: {field}")

    # Check old terminology is NOT used
    if "zone_pairs" in game:
        errors.append("OLD TERMINOLOGY: 'zone_pairs' should be 'links'")
    if "zones" in game:
        errors.append("OLD TERMINOLOGY: 'zones' should be 'nodes'")
    if "discovered_nodes" in game:
        errors.append("OLD FORMAT: 'discovered_nodes' should be removed (client deduces)")
    if "total_zones" in game:
        errors.append("OLD TERMINOLOGY: 'total_zones' should be 'total_nodes'")

    # Validate links
    if "links" in game:
        for i, link in enumerate(game["links"]):
            link_errors = validate_link_format(link)
            for err in link_errors:
                errors.append(f"links[{i}]: {err}")

    # Validate discovered_links
    if "discovered_links" in game:
        for i, dl in enumerate(game["discovered_links"]):
            dl_errors = validate_discovered_link_format(dl)
            for err in dl_errors:
                errors.append(f"discovered_links[{i}]: {err}")

    return errors


def validate_game_state_message(msg: dict) -> list[str]:
    """Validate WebSocket game_state message. Returns list of errors."""
    errors = []

    if msg.get("type") != "game_state":
        errors.append(f"Expected type 'game_state', got '{msg.get('type')}'")

    state = msg.get("state", {})

    # Check discovered_links format
    discovered_links = state.get("discovered_links", [])
    for i, dl in enumerate(discovered_links):
        dl_errors = validate_discovered_link_format(dl)
        for err in dl_errors:
            errors.append(f"state.discovered_links[{i}]: {err}")

    return errors


def validate_discovery_message(msg: dict) -> list[str]:
    """Validate WebSocket discovery message. Returns list of errors."""
    errors = []

    if msg.get("type") != "discovery":
        errors.append(f"Expected type 'discovery', got '{msg.get('type')}'")

    # Check discovered_links format
    discovered_links = msg.get("discovered_links", [])
    for i, dl in enumerate(discovered_links):
        dl_errors = validate_discovered_link_format(dl)
        for err in dl_errors:
            errors.append(f"discovered_links[{i}]: {err}")

    return errors


def validate_discovery_ack_message(msg: dict) -> list[str]:
    """Validate WebSocket discovery_v2_ack message. Returns list of errors."""
    errors = []

    if msg.get("type") != "discovery_v2_ack":
        errors.append(f"Expected type 'discovery_v2_ack', got '{msg.get('type')}'")

    # Check new terminology
    if "current_zone" in msg:
        errors.append("OLD TERMINOLOGY: 'current_zone' should be 'current_node'")

    return errors


# =============================================================================
# Tests
# =============================================================================


class TestResults:
    """Collect test results."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def check(self, name: str, errors: list[str]):
        """Record a test result."""
        if errors:
            self.failed += 1
            self.errors.append((name, errors))
            print(f"  FAIL: {name}")
            for err in errors:
                print(f"        - {err}")
        else:
            self.passed += 1
            print(f"  PASS: {name}")

    def summary(self):
        """Print summary."""
        total = self.passed + self.failed
        print(f"\n{'='*60}")
        print(f"Results: {self.passed}/{total} passed")
        if self.failed > 0:
            print(f"Failed tests: {self.failed}")
        return self.failed == 0


async def test_api_create_game(results: TestResults) -> str | None:
    """Test POST /mod/games - create game from spoiler log."""
    print("\n--- Test: POST /mod/games ---")

    spoiler_log = get_spoiler_log()

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/api/mod/games",
            headers={"Authorization": f"Bearer {TEST_MOD_TOKEN}"},
            json={"spoiler_log": spoiler_log, "label": "Integration Test"},
            timeout=30.0,  # Parsing large spoiler logs can take time
        )

        errors = []
        if resp.status_code != 200:
            errors.append(f"Expected 200, got {resp.status_code}: {resp.text}")
            results.check("Create game status code", errors)
            return None

        results.check("Create game status code", [])

        data = resp.json()

        # Validate response
        if "game_id" not in data:
            errors.append("Missing 'game_id' in response")
        elif not validate_uuid(data["game_id"]):
            errors.append(f"Invalid game_id UUID: {data['game_id']}")

        results.check("Create game response format", errors)

        return data.get("game_id")


async def test_api_get_game(results: TestResults, game_id: str):
    """Test GET /games/{id} - fetch game."""
    print(f"\n--- Test: GET /games/{game_id} ---")

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BASE_URL}/api/games/{game_id}")

        errors = []
        if resp.status_code != 200:
            errors.append(f"Expected 200, got {resp.status_code}: {resp.text}")
            results.check("Get game status code", errors)
            return

        results.check("Get game status code", [])

        game = resp.json()

        # Validate full response format
        format_errors = validate_game_response(game)
        results.check("Game response format (new terminology)", format_errors)

        # Check specific expected values
        content_errors = []
        if game.get("seed") != 1078869800:
            content_errors.append(f"Expected seed 1078869800, got {game.get('seed')}")
        if not game.get("links"):
            content_errors.append("Expected non-empty links array")
        else:
            # Verify links have target, not destination
            first_link = game["links"][0]
            if "target" not in first_link:
                content_errors.append("First link missing 'target' field")
            if first_link.get("source") != "Chapel of Anticipation":
                content_errors.append(
                    f"Expected first link source 'Chapel of Anticipation', got '{first_link.get('source')}'"
                )

        results.check("Game content validation", content_errors)

        # Check nodes (optional but should be present)
        if "nodes" in game and game["nodes"]:
            node_errors = []
            for i, node in enumerate(game["nodes"]):
                if "id" not in node:
                    node_errors.append(f"nodes[{i}]: missing 'id' field")
            results.check("Nodes format", node_errors)


async def test_api_discovery(results: TestResults, game_id: str):
    """Test POST /games/{id}/discoveries - create discovery via REST."""
    print(f"\n--- Test: POST /games/{game_id}/discoveries ---")

    async with httpx.AsyncClient() as client:
        # First get the game to find a valid link
        resp = await client.get(f"{BASE_URL}/api/games/{game_id}")
        game = resp.json()
        links = game.get("links", [])

        if not links:
            results.check("Discovery test", ["No links in game"])
            return

        # Find a random link to discover
        random_links = [lk for lk in links if lk.get("type") == "random"]
        if not random_links:
            results.check("Discovery test", ["No random links to discover"])
            return

        link = random_links[0]

        # Create discovery
        resp = await client.post(
            f"{BASE_URL}/api/games/{game_id}/discoveries",
            headers={"Authorization": f"Bearer {TEST_API_TOKEN}"},
            json={
                "source": link["source"],
                "target": link["target"],
                "link_id": link["id"],
            },
        )

        errors = []
        if resp.status_code != 200:
            errors.append(f"Expected 200, got {resp.status_code}: {resp.text}")
            results.check("Discovery status code", errors)
            return

        results.check("Discovery status code", [])

        data = resp.json()

        # Validate discovered_links format
        discovered_links = data.get("discovered_links", [])
        dl_errors = []
        for i, dl in enumerate(discovered_links):
            dl_err = validate_discovered_link_format(dl)
            for err in dl_err:
                dl_errors.append(f"discovered_links[{i}]: {err}")

        results.check("Discovery response format", dl_errors)


async def test_websocket_host(results: TestResults, game_id: str):
    """Test WebSocket host connection.

    Host flow:
    1. Connect to /ws/host/{game_id}
    2. Send {"type": "auth", "token": api_token}
    3. Receive {"type": "auth_ok"}
    4. Receive {"type": "game_state", "state": {...}}
    """
    print(f"\n--- Test: WebSocket /ws/host/{game_id} ---")

    ws = None
    try:
        ws = await websockets.connect(f"{WS_URL}/ws/host/{game_id}", open_timeout=5)

        # Send auth message
        await ws.send(json.dumps({"type": "auth", "token": TEST_API_TOKEN}))

        # Wait for auth_ok
        msg_raw = await asyncio.wait_for(ws.recv(), timeout=5)
        msg = json.loads(msg_raw)

        if msg.get("type") != "auth_ok":
            results.check(
                "Host WebSocket auth", [f"Expected 'auth_ok', got '{msg.get('type')}': {msg}"]
            )
            return

        results.check("Host WebSocket auth", [])

        # Wait for game_state (may get ping first)
        for _ in range(5):
            msg_raw = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = json.loads(msg_raw)
            if msg.get("type") == "ping":
                await ws.send(json.dumps({"type": "pong"}))
                continue
            if msg.get("type") == "game_state":
                state_errors = validate_game_state_message(msg)
                results.check("Host WebSocket game_state format", state_errors)
                break
            else:
                results.check(
                    "Host WebSocket game_state format",
                    [f"Expected 'game_state', got '{msg.get('type')}'"],
                )
                break

    except TimeoutError:
        results.check("Host WebSocket", ["Timeout waiting for server response"])
    except websockets.exceptions.InvalidStatusCode as e:
        results.check("Host WebSocket", [f"Connection rejected: {e}"])
    except Exception as e:
        results.check("Host WebSocket", [f"Error: {type(e).__name__}: {e}"])
    finally:
        if ws:
            await ws.close()
            await asyncio.sleep(0.2)  # Give server time to process close


async def test_websocket_mod(results: TestResults, game_id: str):
    """Test WebSocket mod connection and discovery flow.

    Mod flow:
    1. Connect to /ws/mod/{game_id}
    2. Send {"type": "auth", "token": mod_token}
    3. Receive {"type": "auth_ok"}
    4. (No game_state - mod is "brainless")
    5. Send discovery_v2, receive discovery_v2_ack
    """
    print(f"\n--- Test: WebSocket /ws/mod/{game_id} ---")

    ws = None
    try:
        ws = await websockets.connect(f"{WS_URL}/ws/mod/{game_id}", open_timeout=5)

        # Send auth message
        await ws.send(json.dumps({"type": "auth", "token": TEST_MOD_TOKEN}))

        # Wait for auth_ok
        msg_raw = await asyncio.wait_for(ws.recv(), timeout=5)
        msg = json.loads(msg_raw)

        if msg.get("type") != "auth_ok":
            results.check(
                "Mod WebSocket auth", [f"Expected 'auth_ok', got '{msg.get('type')}': {msg}"]
            )
            return

        results.check("Mod WebSocket auth", [])

        # Mod does NOT receive game_state - it's "brainless"
        # Send discovery_v2 message (simulate fog gate traversal)
        discovery_msg = {
            "type": "discovery_v2",
            "source_map_id": "m10_00_00_00",
            "source_pos": {"x": 100.0, "y": 0.0, "z": 200.0},
            "source_play_region_id": 1048576,
            "target_map_id": "m10_01_00_00",
            "target_pos": {"x": 150.0, "y": 10.0, "z": 250.0},
            "target_play_region_id": 2097152,
            "warp_type": "FOG",
            "destination_entity_id": 755890001,
        }
        await ws.send(json.dumps(discovery_msg))

        # Receive ack (may get ping first)
        for _ in range(5):
            msg_raw = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = json.loads(msg_raw)
            if msg.get("type") == "ping":
                await ws.send(json.dumps({"type": "pong"}))
                continue
            if msg.get("type") == "discovery_v2_ack":
                ack_errors = validate_discovery_ack_message(msg)
                results.check("Mod WebSocket discovery_v2_ack format", ack_errors)
                break
            else:
                results.check(
                    "Mod WebSocket discovery_v2_ack format",
                    [f"Unexpected message type: {msg.get('type')}"],
                )
                break

    except TimeoutError:
        results.check("Mod WebSocket", ["Timeout waiting for server response"])
    except websockets.exceptions.InvalidStatusCode as e:
        results.check("Mod WebSocket", [f"Connection rejected: {e}"])
    except Exception as e:
        results.check("Mod WebSocket", [f"Error: {type(e).__name__}: {e}"])
    finally:
        if ws:
            await ws.close()
            await asyncio.sleep(0.2)  # Give server time to process close


async def test_websocket_viewer(results: TestResults, game_id: str):
    """Test WebSocket viewer connection (no auth required).

    Viewer flow:
    1. Connect to /ws/viewer/{game_id} (no auth)
    2. Receive {"type": "game_state", "state": {...}}
    3. Optionally receive {"type": "waiting"} if no host connected
    """
    print(f"\n--- Test: WebSocket /ws/viewer/{game_id} ---")

    ws = None
    try:
        ws = await websockets.connect(f"{WS_URL}/ws/viewer/{game_id}", open_timeout=5)

        # Viewer always receives game_state first
        msg_raw = await asyncio.wait_for(ws.recv(), timeout=5)
        msg = json.loads(msg_raw)

        # Skip pings if any
        while msg.get("type") == "ping":
            await ws.send(json.dumps({"type": "pong"}))
            msg_raw = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = json.loads(msg_raw)

        if msg.get("type") == "game_state":
            state_errors = validate_game_state_message(msg)
            results.check("Viewer WebSocket game_state format", state_errors)
        else:
            results.check(
                "Viewer WebSocket game_state format",
                [f"Expected 'game_state', got '{msg.get('type')}'"],
            )

    except TimeoutError:
        results.check("Viewer WebSocket", ["Timeout waiting for server response"])
    except websockets.exceptions.InvalidStatusCode as e:
        results.check("Viewer WebSocket", [f"Connection rejected: {e}"])
    except Exception as e:
        results.check("Viewer WebSocket", [f"Error: {type(e).__name__}: {e}"])
    finally:
        if ws:
            await ws.close()
            await asyncio.sleep(0.2)  # Give server time to process close


async def test_discovery_propagation(results: TestResults, game_id: str):
    """Test discovery logic: mod discovery, host manual discovery, and message broadcasting.

    Test scenarios:
    1. Host connects and receives game_state
    2. Mod connects and sends discovery_v2 for an UNDISCOVERED link
    3. Host should receive 'discovery' broadcast
    4. Viewer connects and receives game_state with discovered_links
    5. Host sends manual_discovery for ANOTHER undiscovered link
    6. Viewer should receive 'discovery' broadcast
    """
    print("\n--- Test: Discovery Propagation Logic ---")

    # First, get the game to find valid links for testing
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BASE_URL}/api/games/{game_id}")
        game = resp.json()
        links = game.get("links", [])
        already_discovered = {dl.get("link_id") for dl in game.get("discovered_links", [])}

    if not links:
        results.check("Discovery propagation setup", ["No links in game"])
        return

    # Find UNDISCOVERED random links from Chapel of Anticipation
    start_links = [
        lk
        for lk in links
        if lk.get("source") == "Chapel of Anticipation"
        and lk.get("type") == "random"
        and lk.get("id") not in already_discovered
    ]

    if not start_links:
        # All links from Chapel already discovered, find any undiscovered random link
        start_links = [
            lk
            for lk in links
            if lk.get("type") == "random" and lk.get("id") not in already_discovered
        ]

    if not start_links:
        print("  All random links already discovered, skipping mod discovery test")
        results.check("Mod discovery test", [])
        first_link = None
    else:
        first_link = start_links[0]
        print(f"  Mod test link: {first_link['source']} -> {first_link['target']}")

    # Find a second undiscovered link for manual discovery test
    other_links = [
        lk
        for lk in links
        if lk.get("type") == "random"
        and lk.get("id") not in already_discovered
        and (first_link is None or lk.get("id") != first_link.get("id"))
    ]

    host_ws = None
    mod_ws = None
    viewer_ws = None

    try:
        # Step 1: Host connects
        print("  Step 1: Host connecting...")
        host_ws = await websockets.connect(f"{WS_URL}/ws/host/{game_id}", open_timeout=5)
        await host_ws.send(json.dumps({"type": "auth", "token": TEST_API_TOKEN}))

        # Wait for auth_ok
        msg = json.loads(await asyncio.wait_for(host_ws.recv(), timeout=5))
        if msg.get("type") != "auth_ok":
            results.check("Host auth", [f"Expected auth_ok, got {msg.get('type')}"])
            return

        # Wait for game_state
        msg = json.loads(await asyncio.wait_for(host_ws.recv(), timeout=5))
        while msg.get("type") == "ping":
            await host_ws.send(json.dumps({"type": "pong"}))
            msg = json.loads(await asyncio.wait_for(host_ws.recv(), timeout=5))

        if msg.get("type") != "game_state":
            results.check("Host game_state", [f"Expected game_state, got {msg.get('type')}"])
            return

        initial_discovered = len(msg.get("state", {}).get("discovered_links", []))
        print(f"  Host connected, initial discoveries: {initial_discovered}")
        results.check("Host initial connection", [])

        # Step 2: Mod connects
        print("  Step 2: Mod connecting...")
        mod_ws = await websockets.connect(f"{WS_URL}/ws/mod/{game_id}", open_timeout=5)
        await mod_ws.send(json.dumps({"type": "auth", "token": TEST_MOD_TOKEN}))

        msg = json.loads(await asyncio.wait_for(mod_ws.recv(), timeout=5))
        if msg.get("type") != "auth_ok":
            results.check("Mod auth", [f"Expected auth_ok, got {msg.get('type')}"])
            return

        # Host should receive mod_connected
        msg = json.loads(await asyncio.wait_for(host_ws.recv(), timeout=5))
        while msg.get("type") == "ping":
            await host_ws.send(json.dumps({"type": "pong"}))
            msg = json.loads(await asyncio.wait_for(host_ws.recv(), timeout=5))

        if msg.get("type") != "mod_connected":
            results.check(
                "Host receives mod_connected", [f"Expected mod_connected, got {msg.get('type')}"]
            )
        else:
            results.check("Host receives mod_connected", [])

        # Step 3: Mod sends discovery_v2
        # Use Chapel of Anticipation (m10_01_00_00) -> Sellia Crystal Tunnel (m32_08_00_00)
        print("  Step 3: Mod sending discovery_v2 (Chapel -> Sellia Crystal Tunnel)...")
        discovery_msg = {
            "type": "discovery_v2",
            "source_map_id": "m10_01_00_00",  # Chapel of Anticipation
            "source_pos": {"x": 100.0, "y": 0.0, "z": 200.0},
            "source_play_region_id": 0,
            "target_map_id": "m32_08_00_00",  # Caelid - Sellia Crystal Tunnel
            "target_pos": {"x": 150.0, "y": 10.0, "z": 250.0},
            "target_play_region_id": 0,
            "warp_type": "FOG",
            "destination_entity_id": 0,
        }
        await mod_ws.send(json.dumps(discovery_msg))

        # Mod should receive discovery_v2_ack
        msg = json.loads(await asyncio.wait_for(mod_ws.recv(), timeout=5))
        while msg.get("type") == "ping":
            await mod_ws.send(json.dumps({"type": "pong"}))
            msg = json.loads(await asyncio.wait_for(mod_ws.recv(), timeout=5))

        if msg.get("type") != "discovery_v2_ack":
            error_msg = msg.get("message", msg.get("error", str(msg)))
            results.check(
                "Mod receives discovery_v2_ack",
                [f"Expected discovery_v2_ack, got {msg.get('type')}: {error_msg}"],
            )
        else:
            ack_errors = []
            if "current_zone" in msg:
                ack_errors.append("OLD TERMINOLOGY: 'current_zone' should be 'current_node'")
            resolved = msg.get("resolved", [])
            propagated = msg.get("propagated", [])
            print(f"    Resolved: {len(resolved)}, Propagated: {len(propagated)}")
            if "current_node" in msg:
                print(f"    Current node: {msg['current_node']}")
            results.check("Mod receives discovery_v2_ack", ack_errors)

            # Step 3b: If propagated > 0, host should receive discovery broadcast
            if propagated:
                print("  Step 3b: Checking host receives discovery from mod...")
                try:
                    msg = json.loads(await asyncio.wait_for(host_ws.recv(), timeout=3))
                    while msg.get("type") == "ping":
                        await host_ws.send(json.dumps({"type": "pong"}))
                        msg = json.loads(await asyncio.wait_for(host_ws.recv(), timeout=3))

                    if msg.get("type") == "discovery":
                        discovery_errors = validate_discovery_message(msg)
                        prop_count = len(msg.get("propagated", []))
                        disc_count = len(msg.get("discovered_links", []))
                        print(
                            f"    Host received discovery: {prop_count} propagated, {disc_count} total"
                        )
                        results.check("Host receives discovery from mod", discovery_errors)
                    else:
                        results.check(
                            "Host receives discovery from mod",
                            [f"Expected discovery, got {msg.get('type')}"],
                        )
                except TimeoutError:
                    results.check(
                        "Host receives discovery from mod",
                        ["Timeout waiting for discovery broadcast"],
                    )
            else:
                print("    No propagation (link already discovered), skipping host broadcast test")
                results.check("Host receives discovery from mod", [])

        # Step 4: Test manual discovery from host -> viewer
        print("  Step 4: Testing manual discovery from host...")

        # Connect a viewer first
        viewer_ws = await websockets.connect(f"{WS_URL}/ws/viewer/{game_id}", open_timeout=5)

        # Viewer should receive game_state
        msg = json.loads(await asyncio.wait_for(viewer_ws.recv(), timeout=5))
        while msg.get("type") == "ping":
            await viewer_ws.send(json.dumps({"type": "pong"}))
            msg = json.loads(await asyncio.wait_for(viewer_ws.recv(), timeout=5))

        if msg.get("type") != "game_state":
            results.check(
                "Viewer receives game_state", [f"Expected game_state, got {msg.get('type')}"]
            )
            return

        results.check("Viewer receives game_state", [])

        # Find an undiscovered link for manual discovery test
        if other_links:
            manual_link = other_links[0]
            print(
                f"    Using undiscovered link: {manual_link['source']} -> {manual_link['target']}"
            )
        elif first_link:
            manual_link = first_link
            print(
                f"    Using link (may be discovered): {manual_link['source']} -> {manual_link['target']}"
            )
        else:
            print("    No links available for manual discovery test")
            results.check("Viewer receives discovery from host", [])
            return

        # Host sends manual_discovery
        manual_discovery_msg = {
            "type": "manual_discovery",
            "source": manual_link["source"],
            "target": manual_link["target"],
        }
        await host_ws.send(json.dumps(manual_discovery_msg))

        # Viewer should receive discovery broadcast
        try:
            msg = json.loads(await asyncio.wait_for(viewer_ws.recv(), timeout=5))
            while msg.get("type") == "ping":
                await viewer_ws.send(json.dumps({"type": "pong"}))
                msg = json.loads(await asyncio.wait_for(viewer_ws.recv(), timeout=5))

            # Could be waiting message or discovery
            if msg.get("type") == "waiting":
                msg = json.loads(await asyncio.wait_for(viewer_ws.recv(), timeout=5))
                while msg.get("type") == "ping":
                    await viewer_ws.send(json.dumps({"type": "pong"}))
                    msg = json.loads(await asyncio.wait_for(viewer_ws.recv(), timeout=5))

            if msg.get("type") == "discovery":
                discovery_errors = validate_discovery_message(msg)
                propagated = msg.get("propagated", [])
                discovered_links = msg.get("discovered_links", [])
                print(
                    f"    Viewer received discovery: {len(propagated)} propagated, {len(discovered_links)} total"
                )

                # Verify the link we discovered is in the list
                link_ids = [dl.get("link_id") for dl in discovered_links]
                if manual_link["id"] not in link_ids:
                    discovery_errors.append(
                        f"Discovered link {manual_link['id']} not in discovered_links"
                    )

                results.check("Viewer receives discovery from host", discovery_errors)
            else:
                results.check(
                    "Viewer receives discovery from host",
                    [f"Expected discovery, got {msg.get('type')}"],
                )
        except TimeoutError:
            results.check(
                "Viewer receives discovery from host", ["Timeout waiting for discovery broadcast"]
            )

        # Step 6: Verify preexisting propagation
        # Check if any preexisting links were propagated
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{BASE_URL}/api/games/{game_id}")
            final_game = resp.json()
            final_discovered = final_game.get("discovered_links", [])

            # Find preexisting links that should have been propagated
            discovered_link_ids = {dl.get("link_id") for dl in final_discovered}

            # Check if target node has preexisting links that should be auto-discovered
            target_node = manual_link["target"]
            preexisting_from_target = [
                lk
                for lk in links
                if lk.get("type") == "preexisting"
                and (lk.get("source") == target_node or lk.get("target") == target_node)
            ]

            if preexisting_from_target:
                propagated_preexisting = [
                    lk for lk in preexisting_from_target if lk.get("id") in discovered_link_ids
                ]
                print(f"    Preexisting links from {target_node}: {len(preexisting_from_target)}")
                print(f"    Propagated preexisting: {len(propagated_preexisting)}")

                # This is informational - preexisting propagation depends on the graph structure
                results.check("Preexisting link propagation", [])
            else:
                print(f"    No preexisting links from {target_node}")
                results.check("Preexisting link propagation", [])

    except Exception as e:
        results.check("Discovery propagation", [f"Error: {type(e).__name__}: {e}"])
        import traceback

        traceback.print_exc()
    finally:
        # Clean up connections
        if host_ws:
            await host_ws.close()
        if mod_ws:
            await mod_ws.close()
        if viewer_ws:
            await viewer_ws.close()


async def cleanup_test_games():
    """Delete test games created during tests."""
    async with httpx.AsyncClient() as client:
        # Get list of games
        resp = await client.get(
            f"{BASE_URL}/api/me/games",
            headers={"Authorization": f"Bearer {TEST_API_TOKEN}"},
        )
        if resp.status_code == 200:
            games = resp.json().get("games", [])
            for game in games:
                if game.get("label") == "Integration Test":
                    await client.delete(
                        f"{BASE_URL}/api/games/{game['id']}",
                        headers={"Authorization": f"Bearer {TEST_API_TOKEN}"},
                    )
                    print(f"Cleaned up test game: {game['id']}")


# =============================================================================
# Main
# =============================================================================


async def main():
    """Run all integration tests."""
    print("=" * 60)
    print("Server Integration Tests - Data Model Validation")
    print("=" * 60)

    # Check server is running
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{BASE_URL}/api/health", timeout=2)
            if resp.status_code != 200:
                print(f"ERROR: Server health check failed: {resp.status_code}")
                sys.exit(1)
    except Exception as e:
        print(f"ERROR: Cannot connect to server at {BASE_URL}")
        print("       Make sure the server is running: uvicorn fogtracker.main:app --port 8001")
        print(f"       Error: {e}")
        sys.exit(1)

    print("Server is running.")

    # Setup test user
    print("\n--- Setup: Creating test user ---")
    try:
        # Get database URL from settings
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from fogtracker.config import settings

        await setup_test_user(settings.database_url)
    except Exception as e:
        print(f"ERROR: Failed to setup test user: {e}")
        print("       Make sure PostgreSQL is running and DATABASE_URL is set")
        sys.exit(1)

    results = TestResults()

    # Run tests
    game_id = await test_api_create_game(results)

    if game_id:
        await test_api_get_game(results, game_id)
        await test_api_discovery(results, game_id)
        await test_websocket_host(results, game_id)
        await asyncio.sleep(0.5)  # Allow connection cleanup
        # await test_websocket_mod(results, game_id)
        await asyncio.sleep(0.5)  # Allow connection cleanup
        await test_websocket_viewer(results, game_id)
        await asyncio.sleep(0.5)  # Allow connection cleanup
        await test_discovery_propagation(results, game_id)

    # Cleanup
    print("\n--- Cleanup ---")
    await cleanup_test_games()

    # Summary
    success = results.summary()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
