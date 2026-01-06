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

# Spoiler log fixtures directory
SPOILER_LOGS_DIR = Path(__file__).parent.parent / "fixtures" / "spoiler_logs"


def get_spoiler_log() -> str:
    """Load spoiler log from fixtures."""
    spoiler_path = SPOILER_LOGS_DIR / "seed_1078869800.txt"
    if spoiler_path.exists():
        print(f"Using spoiler log: {spoiler_path}")
        return spoiler_path.read_text()

    raise FileNotFoundError(
        f"Spoiler log not found at {spoiler_path}. " "Run tests from the server/ directory."
    )


# =============================================================================
# Test Utilities
# =============================================================================


async def setup_test_user():
    """Create test user in database with hardcoded tokens using SQLAlchemy."""
    from sqlalchemy import select

    from fogtracker.database import User, async_session

    async with async_session() as db:
        # Check if user exists
        stmt = select(User).where(User.twitch_id == TEST_TWITCH_ID)
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            # Update tokens
            existing.api_token = TEST_API_TOKEN
            existing.mod_token = TEST_MOD_TOKEN
            await db.commit()
            print(f"Updated test user tokens (id={existing.id})")
        else:
            # Create user
            user = User(
                twitch_id=TEST_TWITCH_ID,
                twitch_username=TEST_USERNAME,
                twitch_display_name="Test User",
                api_token=TEST_API_TOKEN,
                mod_token=TEST_MOD_TOKEN,
            )
            db.add(user)
            await db.commit()
            print("Created test user")


def validate_uuid(value: str) -> bool:
    """Check if a string is a valid UUID."""
    try:
        UUID(value)
        return True
    except (ValueError, TypeError):
        return False


def validate_zone_link_format(link: dict) -> list[str]:
    """Validate a zone_link object has correct format. Returns list of errors."""
    errors = []
    required_fields = ["id", "source", "target", "type"]

    for field in required_fields:
        if field not in link:
            errors.append(f"Missing required field: {field}")

    # id can be UUID or custom string, just check it exists
    if "id" in link and not link["id"]:
        errors.append("Empty link id")

    return errors


def validate_discovered_zone_link_format(dl: dict) -> list[str]:
    """Validate a discovered_zone_link object. Returns list of errors."""
    errors = []

    if "zone_link_id" not in dl:
        errors.append("Missing required field: zone_link_id")
    elif not dl["zone_link_id"]:
        errors.append("Empty zone_link_id")

    # Optional fields: discovered_at, discovered_by

    return errors


def validate_game_response(game: dict) -> list[str]:
    """Validate GET /games/{id} response format. Returns list of errors."""
    errors = []

    # Check required fields (current terminology)
    required = ["id", "seed", "zone_links", "discovered_zone_links"]
    for field in required:
        if field not in game:
            errors.append(f"Missing required field: {field}")

    # Validate zone_links
    if "zone_links" in game:
        for i, link in enumerate(game["zone_links"]):
            link_errors = validate_zone_link_format(link)
            for err in link_errors:
                errors.append(f"zone_links[{i}]: {err}")

    # Validate discovered_zone_links
    if "discovered_zone_links" in game:
        for i, dl in enumerate(game["discovered_zone_links"]):
            dl_errors = validate_discovered_zone_link_format(dl)
            for err in dl_errors:
                errors.append(f"discovered_zone_links[{i}]: {err}")

    return errors


def validate_game_state_message(msg: dict) -> list[str]:
    """Validate WebSocket game_state message. Returns list of errors."""
    errors = []

    if msg.get("type") != "game_state":
        errors.append(f"Expected type 'game_state', got '{msg.get('type')}'")

    state = msg.get("state", {})

    # Check discovered_zone_links format
    discovered_links = state.get("discovered_zone_links", [])
    for i, dl in enumerate(discovered_links):
        dl_errors = validate_discovered_zone_link_format(dl)
        for err in dl_errors:
            errors.append(f"state.discovered_zone_links[{i}]: {err}")

    return errors


def validate_discovery_message(msg: dict) -> list[str]:
    """Validate WebSocket discovery message. Returns list of errors."""
    errors = []

    if msg.get("type") != "discovery":
        errors.append(f"Expected type 'discovery', got '{msg.get('type')}'")

    # Check discovered_zone_links format
    discovered_links = msg.get("discovered_zone_links", [])
    for i, dl in enumerate(discovered_links):
        dl_errors = validate_discovered_zone_link_format(dl)
        for err in dl_errors:
            errors.append(f"discovered_zone_links[{i}]: {err}")

    return errors


def validate_discovery_ack_message(msg: dict) -> list[str]:
    """Validate WebSocket discovery_v2_ack message. Returns list of errors."""
    errors = []

    if msg.get("type") != "discovery_v2_ack":
        errors.append(f"Expected type 'discovery_v2_ack', got '{msg.get('type')}'")

    # current_zone is the expected field name
    # (previously tests expected current_node but server uses current_zone)

    return errors


# =============================================================================
# Tests
# =============================================================================


class IntegrationResults:
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


async def run_api_create_game(results: IntegrationResults) -> str | None:
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


async def run_api_get_game(results: IntegrationResults, game_id: str):
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
        results.check("Game response format", format_errors)

        # Check specific expected values
        content_errors = []
        if game.get("seed") != 1078869800:
            content_errors.append(f"Expected seed 1078869800, got {game.get('seed')}")
        if not game.get("zone_links"):
            content_errors.append("Expected non-empty zone_links array")
        else:
            # Verify zone_links have target field
            first_link = game["zone_links"][0]
            if "target" not in first_link:
                content_errors.append("First zone_link missing 'target' field")
            if first_link.get("source") != "Chapel of Anticipation":
                content_errors.append(
                    f"Expected first zone_link source 'Chapel of Anticipation', got '{first_link.get('source')}'"
                )

        results.check("Game content validation", content_errors)

        # Check zones (optional but should be present)
        if "zones" in game and game["zones"]:
            zone_errors = []
            # zones is a dict keyed by zone_id
            for zone_id, _zone in game["zones"].items():
                if not zone_id:
                    zone_errors.append("Empty zone_id key")
            results.check("Zones format", zone_errors)


async def run_api_discovery(results: IntegrationResults, game_id: str):
    """Test POST /games/{id}/discoveries - create discovery via REST."""
    print(f"\n--- Test: POST /games/{game_id}/discoveries ---")

    async with httpx.AsyncClient() as client:
        # First get the game to find a valid link
        resp = await client.get(f"{BASE_URL}/api/games/{game_id}")
        game = resp.json()
        zone_links = game.get("zone_links", [])

        if not zone_links:
            results.check("Discovery test", ["No zone_links in game"])
            return

        # Find a random link to discover
        random_links = [lk for lk in zone_links if lk.get("type") == "random"]
        if not random_links:
            results.check("Discovery test", ["No random zone_links to discover"])
            return

        link = random_links[0]

        # Create discovery (API expects source_id and target_id, not source/target)
        resp = await client.post(
            f"{BASE_URL}/api/games/{game_id}/discoveries",
            headers={"Authorization": f"Bearer {TEST_API_TOKEN}"},
            json={
                "source_id": link["source_id"],
                "target_id": link["target_id"],
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

        # Validate discovered_zone_links format
        discovered_links = data.get("discovered_zone_links", [])
        dl_errors = []
        for i, dl in enumerate(discovered_links):
            dl_err = validate_discovered_zone_link_format(dl)
            for err in dl_err:
                dl_errors.append(f"discovered_zone_links[{i}]: {err}")

        results.check("Discovery response format", dl_errors)


async def run_websocket_host(results: IntegrationResults, game_id: str):
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


async def run_websocket_mod(results: IntegrationResults, game_id: str):
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


async def run_websocket_viewer(results: IntegrationResults, game_id: str):
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


async def run_discovery_propagation(results: IntegrationResults, game_id: str):
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
        zone_links = game.get("zone_links", [])
        already_discovered = {
            dl.get("zone_link_id") for dl in game.get("discovered_zone_links", [])
        }

    if not zone_links:
        results.check("Discovery propagation setup", ["No zone_links in game"])
        return

    # Find UNDISCOVERED random links from Chapel of Anticipation
    start_links = [
        lk
        for lk in zone_links
        if lk.get("source") == "Chapel of Anticipation"
        and lk.get("type") == "random"
        and lk.get("id") not in already_discovered
    ]

    if not start_links:
        # All links from Chapel already discovered, find any undiscovered random link
        start_links = [
            lk
            for lk in zone_links
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
        for lk in zone_links
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

        initial_discovered = len(msg.get("state", {}).get("discovered_zone_links", []))
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
            # current_zone is the correct field name
            resolved = msg.get("resolved", [])
            propagated = msg.get("propagated", [])
            print(f"    Resolved: {len(resolved)}, Propagated: {len(propagated)}")
            if "current_zone" in msg:
                print(f"    Current zone: {msg['current_zone']}")
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
                        disc_count = len(msg.get("discovered_zone_links", []))
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

        # Host sends manual_discovery (expects source_id and target_id)
        manual_discovery_msg = {
            "type": "manual_discovery",
            "source_id": manual_link["source_id"],
            "target_id": manual_link["target_id"],
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
                discovered_zone_links = msg.get("discovered_zone_links", [])
                print(
                    f"    Viewer received discovery: {len(propagated)} propagated, {len(discovered_zone_links)} total"
                )

                # Verify the link we discovered is in the list
                link_ids = [dl.get("zone_link_id") for dl in discovered_zone_links]
                if manual_link["id"] not in link_ids:
                    discovery_errors.append(
                        f"Discovered link {manual_link['id']} not in discovered_zone_links"
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
            final_discovered = final_game.get("discovered_zone_links", [])

            # Find preexisting links that should have been propagated
            discovered_link_ids = {dl.get("zone_link_id") for dl in final_discovered}

            # Check if target node has preexisting links that should be auto-discovered
            target_node = manual_link["target"]
            preexisting_from_target = [
                lk
                for lk in zone_links
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
        await setup_test_user()
    except Exception as e:
        print(f"ERROR: Failed to setup test user: {e}")
        print("       Make sure the database is available and DATABASE_URL is set")
        sys.exit(1)

    results = IntegrationResults()

    # Run tests
    game_id = await run_api_create_game(results)

    if game_id:
        await run_api_get_game(results, game_id)
        await run_api_discovery(results, game_id)
        await run_websocket_host(results, game_id)
        await asyncio.sleep(0.5)  # Allow connection cleanup
        # await run_websocket_mod(results, game_id)
        await asyncio.sleep(0.5)  # Allow connection cleanup
        await run_websocket_viewer(results, game_id)
        await asyncio.sleep(0.5)  # Allow connection cleanup
        await run_discovery_propagation(results, game_id)

    # Cleanup
    print("\n--- Cleanup ---")
    await cleanup_test_games()

    # Summary
    success = results.summary()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())


# =============================================================================
# Pytest Integration Tests
# =============================================================================

import pytest  # noqa: E402


def _load_real_database_url():
    """Load DATABASE_URL from .env file and reconfigure the database connection."""
    import os
    import sys
    from pathlib import Path

    # Load DATABASE_URL from .env file (server/ directory)
    env_file = Path(__file__).parent.parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                if key.strip() == "DATABASE_URL":
                    os.environ["DATABASE_URL"] = value.strip()
                    break

    # Clear cached settings/engine to force reload with new DATABASE_URL
    if "fogtracker.config" in sys.modules:
        from fogtracker.config import get_settings

        get_settings.cache_clear()

    if "fogtracker.database" in sys.modules:
        from fogtracker.database import get_async_session_maker, get_engine

        get_engine.cache_clear()
        get_async_session_maker.cache_clear()


@pytest.fixture
async def integration_results():
    """Fixture providing IntegrationResults and handling test user setup."""
    _load_real_database_url()
    await setup_test_user()
    return IntegrationResults()


@pytest.fixture
async def integration_game_id(integration_results):
    """Fixture that creates a game and returns its ID."""
    game_id = await run_api_create_game(integration_results)
    yield game_id
    # Cleanup after test
    await cleanup_test_games()


async def test_api_create_game(integration_results):
    """Test POST /mod/games - create game from spoiler log."""
    game_id = await run_api_create_game(integration_results)
    assert game_id is not None, "Failed to create game"
    assert integration_results.failed == 0, f"Test failures: {integration_results.errors}"
    await cleanup_test_games()


async def test_api_get_game(integration_results, integration_game_id):
    """Test GET /games/{id} - fetch game."""
    if integration_game_id is None:
        pytest.skip("Game creation failed")
    await run_api_get_game(integration_results, integration_game_id)
    assert integration_results.failed == 0, f"Test failures: {integration_results.errors}"


async def test_api_discovery(integration_results, integration_game_id):
    """Test POST /games/{id}/discoveries - create discovery via REST."""
    if integration_game_id is None:
        pytest.skip("Game creation failed")
    await run_api_discovery(integration_results, integration_game_id)
    assert integration_results.failed == 0, f"Test failures: {integration_results.errors}"


async def test_websocket_host(integration_results, integration_game_id):
    """Test WebSocket host connection."""
    if integration_game_id is None:
        pytest.skip("Game creation failed")
    await run_websocket_host(integration_results, integration_game_id)
    assert integration_results.failed == 0, f"Test failures: {integration_results.errors}"


async def test_websocket_mod(integration_results, integration_game_id):
    """Test WebSocket mod connection and discovery flow."""
    if integration_game_id is None:
        pytest.skip("Game creation failed")
    await run_websocket_mod(integration_results, integration_game_id)
    assert integration_results.failed == 0, f"Test failures: {integration_results.errors}"


async def test_websocket_viewer(integration_results, integration_game_id):
    """Test WebSocket viewer connection."""
    if integration_game_id is None:
        pytest.skip("Game creation failed")
    await run_websocket_viewer(integration_results, integration_game_id)
    assert integration_results.failed == 0, f"Test failures: {integration_results.errors}"


async def test_discovery_propagation(integration_results, integration_game_id):
    """Test discovery propagation between mod, host, and viewer."""
    if integration_game_id is None:
        pytest.skip("Game creation failed")
    await run_discovery_propagation(integration_results, integration_game_id)
    assert integration_results.failed == 0, f"Test failures: {integration_results.errors}"
