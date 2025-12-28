"""Unit tests for the spoiler API endpoint.

Tests for POST /api/spoiler/parse.
"""

from fastapi.testclient import TestClient

from fogtracker.main import app

client = TestClient(app)


class TestSpoilerParseEndpoint:
    """Tests for POST /api/spoiler/parse endpoint."""

    def test_parse_valid_spoiler_log(self):
        """Test parsing a valid spoiler log."""
        spoiler_log = """Options and seed:12345 Fog Gate Randomizer
Chapel of Anticipation
  Random: Chapel of Anticipation (before boss) --> Limgrave (at start)
Limgrave
  Preexisting: Limgrave --> Stormveil Castle (at the main gate)
Stormveil Castle
Optional areas:
"""
        response = client.post(
            "/api/spoiler/parse",
            json={"spoiler_log": spoiler_log},
        )

        assert response.status_code == 200
        data = response.json()

        # Check seed
        assert data["seed"] == 12345

        # Check zones
        assert len(data["zones"]) == 3
        zone_names = {z["name"] for z in data["zones"]}
        assert "Chapel of Anticipation" in zone_names
        assert "Limgrave" in zone_names
        assert "Stormveil Castle" in zone_names

        # Check zone_links
        assert len(data["zone_links"]) == 2

        # Check first link (random)
        random_link = next(lk for lk in data["zone_links"] if lk["type"] == "random")
        assert random_link["source"] == "Chapel of Anticipation"
        assert random_link["target"] == "Limgrave"
        assert random_link["source_details"] == "before boss"
        assert random_link["target_details"] == "at start"
        assert random_link["is_inherently_one_way"] is False

        # Check second link (preexisting)
        preexisting_link = next(lk for lk in data["zone_links"] if lk["type"] == "preexisting")
        assert preexisting_link["source"] == "Limgrave"
        assert preexisting_link["target"] == "Stormveil Castle"

    def test_parse_invalid_spoiler_log_no_seed(self):
        """Test parsing an invalid spoiler log without seed."""
        response = client.post(
            "/api/spoiler/parse",
            json={"spoiler_log": "Invalid header\nLimgrave"},
        )

        assert response.status_code == 400
        assert "Invalid spoiler log" in response.json()["detail"]

    def test_parse_invalid_spoiler_log_no_zones(self):
        """Test parsing a spoiler log with no zones."""
        response = client.post(
            "/api/spoiler/parse",
            json={"spoiler_log": "Options and seed:12345\nOptional areas:"},
        )

        assert response.status_code == 400
        assert "Invalid spoiler log" in response.json()["detail"]

    def test_parse_invalid_spoiler_log_no_connections(self):
        """Test parsing a spoiler log with no connections."""
        response = client.post(
            "/api/spoiler/parse",
            json={"spoiler_log": "Options and seed:12345\nLimgrave\nCaelid"},
        )

        assert response.status_code == 400
        assert "Invalid spoiler log" in response.json()["detail"]

    def test_parse_empty_spoiler_log(self):
        """Test parsing an empty spoiler log."""
        response = client.post(
            "/api/spoiler/parse",
            json={"spoiler_log": ""},
        )

        assert response.status_code == 400
        assert "Invalid spoiler log" in response.json()["detail"]

    def test_parse_missing_spoiler_log_field(self):
        """Test request without spoiler_log field."""
        response = client.post(
            "/api/spoiler/parse",
            json={},
        )

        assert response.status_code == 422  # Validation error

    def test_parse_one_way_connection(self):
        """Test parsing a spoiler log with one-way connections."""
        spoiler_log = """Options and seed:99999 Fog Gate Randomizer
Divine Bridge
  Random: Divine Bridge (using the sending gate) --> Isolated Tower (warp destination)
Isolated Tower
Optional areas:
"""
        response = client.post(
            "/api/spoiler/parse",
            json={"spoiler_log": spoiler_log},
        )

        assert response.status_code == 200
        data = response.json()

        # Check one-way flag
        link = data["zone_links"][0]
        assert link["is_inherently_one_way"] is True

    def test_parse_boss_zone(self):
        """Test parsing a spoiler log with boss zones."""
        spoiler_log = """Options and seed:99999 Fog Gate Randomizer
Limgrave
  Preexisting: Limgrave --> Stormveil Castle
Stormveil Castle <<<<<
  Preexisting: Stormveil Castle --> Liurnia
Liurnia
Optional areas:
"""
        response = client.post(
            "/api/spoiler/parse",
            json={"spoiler_log": spoiler_log},
        )

        assert response.status_code == 200
        data = response.json()

        # Check boss zone flag
        boss_zones = [z for z in data["zones"] if z["is_boss"]]
        assert len(boss_zones) == 1
        assert boss_zones[0]["name"] == "Stormveil Castle"

    def test_parse_zone_with_scaling(self):
        """Test parsing a spoiler log with scaling info."""
        spoiler_log = """Options and seed:99999 Fog Gate Randomizer
Limgrave (scaling: 1-50)
  Random: Limgrave --> Caelid
Caelid (scaling: 60-80)
Optional areas:
"""
        response = client.post(
            "/api/spoiler/parse",
            json={"spoiler_log": spoiler_log},
        )

        assert response.status_code == 200
        data = response.json()

        # Check scaling info
        limgrave = next(z for z in data["zones"] if z["name"] == "Limgrave")
        assert limgrave["scaling"] == "1-50"

        caelid = next(z for z in data["zones"] if z["name"] == "Caelid")
        assert caelid["scaling"] == "60-80"

    def test_parse_no_auth_required(self):
        """Test that no authentication is required for this endpoint."""
        spoiler_log = """Options and seed:12345
A
  Random: A --> B
B
"""
        # No Authorization header
        response = client.post(
            "/api/spoiler/parse",
            json={"spoiler_log": spoiler_log},
        )

        assert response.status_code == 200

    def test_response_has_all_required_fields(self):
        """Test that response has all documented fields."""
        spoiler_log = """Options and seed:12345
A
  Random: A (at start) --> B (at end)
B
"""
        response = client.post(
            "/api/spoiler/parse",
            json={"spoiler_log": spoiler_log},
        )

        assert response.status_code == 200
        data = response.json()

        # Check top-level fields
        assert "seed" in data
        assert "zones" in data
        assert "zone_links" in data

        # Check zone fields
        zone = data["zones"][0]
        assert "id" in zone
        assert "name" in zone
        assert "is_boss" in zone
        assert "scaling" in zone

        # Check link fields
        link = data["zone_links"][0]
        assert "id" in link
        assert "source" in link
        assert "target" in link
        assert "type" in link
        assert "source_details" in link
        assert "target_details" in link
        assert "required_item" in link
        assert "required_item_from" in link
        assert "is_inherently_one_way" in link

    def test_parse_required_item_detected(self):
        """Test that required items are detected and returned."""
        spoiler_log = """Options and seed:99999 Fog Gate Randomizer
Raya Lucaria
  Random: Raya Lucaria (using the Academy Glintstone Key) --> Academy Entrance
Academy Entrance
Optional areas:
"""
        response = client.post(
            "/api/spoiler/parse",
            json={"spoiler_log": spoiler_log},
        )

        assert response.status_code == 200
        data = response.json()

        link = data["zone_links"][0]
        assert link["required_item"] == "Academy Glintstone Key"

    def test_parse_required_item_none_when_no_item(self):
        """Test that required_item is null when no item is needed."""
        spoiler_log = """Options and seed:99999 Fog Gate Randomizer
Limgrave
  Random: Limgrave (at the gate) --> Stormveil Castle (at entrance)
Stormveil Castle
Optional areas:
"""
        response = client.post(
            "/api/spoiler/parse",
            json={"spoiler_log": spoiler_log},
        )

        assert response.status_code == 200
        data = response.json()

        link = data["zone_links"][0]
        assert link["required_item"] is None


class TestWithRealSpoilerLogs:
    """Tests using real spoiler log files."""

    def test_parse_real_spoiler_log_1078869800(self, spoiler_log_1078869800):
        """Test parsing real spoiler log seed 1078869800."""
        response = client.post(
            "/api/spoiler/parse",
            json={"spoiler_log": spoiler_log_1078869800},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["seed"] == 1078869800
        assert len(data["zones"]) > 50
        assert len(data["zone_links"]) > 100

        # Verify Chapel of Anticipation exists
        zone_names = {z["name"] for z in data["zones"]}
        assert "Chapel of Anticipation" in zone_names

    def test_parse_real_spoiler_log_1851144969(self, spoiler_log_1851144969):
        """Test parsing real spoiler log seed 1851144969."""
        response = client.post(
            "/api/spoiler/parse",
            json={"spoiler_log": spoiler_log_1851144969},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["seed"] == 1851144969
        assert len(data["zones"]) > 50
        assert len(data["zone_links"]) > 100
