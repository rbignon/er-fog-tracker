"""Unit tests for game_logic module.

Tests for discovery result formatting and related utilities.
"""

from fogvizu.game_logic import (
    DiscoveredLink,
    DiscoveryResult,
    format_discovery_summary,
    format_undiscovery_summary,
)


class TestDiscoveredLink:
    """Tests for DiscoveredLink dataclass."""

    def test_create_random_link(self):
        link = DiscoveredLink(source="Zone A", target="Zone B", link_type="random")
        assert link.source == "Zone A"
        assert link.target == "Zone B"
        assert link.link_type == "random"

    def test_create_preexisting_link(self):
        link = DiscoveredLink(source="Zone A", target="Zone B", link_type="preexisting")
        assert link.link_type == "preexisting"


class TestDiscoveryResult:
    """Tests for DiscoveryResult dataclass."""

    def test_empty_result(self):
        result = DiscoveryResult(origin="Zone A")
        assert result.origin == "Zone A"
        assert result.main_links == []
        assert result.backprop_links == []
        assert result.forward_links == []
        assert result.total_count() == 0
        assert result.all_links() == []

    def test_total_count(self):
        result = DiscoveryResult(origin="Zone A")
        result.main_links.append(DiscoveredLink("A", "B", "random"))
        result.backprop_links.append(DiscoveredLink("START", "A", "preexisting"))
        result.forward_links.append(DiscoveredLink("B", "C", "preexisting"))
        result.forward_links.append(DiscoveredLink("C", "D", "preexisting"))
        assert result.total_count() == 4

    def test_all_links_order(self):
        """all_links() returns backprop first, then main, then forward."""
        result = DiscoveryResult(origin="Zone A")
        result.backprop_links.append(DiscoveredLink("START", "A", "preexisting"))
        result.main_links.append(DiscoveredLink("A", "B", "random"))
        result.forward_links.append(DiscoveredLink("B", "C", "preexisting"))

        links = result.all_links()
        assert len(links) == 3
        assert links[0] == {"source": "START", "target": "A"}
        assert links[1] == {"source": "A", "target": "B"}
        assert links[2] == {"source": "B", "target": "C"}


class TestFormatDiscoverySummary:
    """Tests for format_discovery_summary function."""

    def test_simple_discovery_no_propagation(self):
        result = DiscoveryResult(origin="Limgrave")
        result.main_links.append(DiscoveredLink("Limgrave", "Stormveil Castle", "random"))

        summary = format_discovery_summary(result, "mod")

        assert "Discovery Summary" in summary
        assert "Origin:     Limgrave" in summary
        assert "Limgrave ───> Stormveil Castle" in summary
        assert "Total: 1 new link" in summary
        # No propagation sections
        assert "Back-propagation" not in summary
        assert "Forward-propagation" not in summary

    def test_discovery_with_forward_propagation(self):
        result = DiscoveryResult(origin="Zone A")
        result.main_links.append(DiscoveredLink("Zone A", "Zone B", "random"))
        result.forward_links.append(DiscoveredLink("Zone B", "Zone C", "preexisting"))
        result.forward_links.append(DiscoveredLink("Zone C", "Zone D", "preexisting"))

        summary = format_discovery_summary(result, "mod")

        assert "Forward-propagation (2)" in summary
        assert "Zone B ---> Zone C" in summary
        assert "Zone C ---> Zone D" in summary
        assert "Total: 3 new links" in summary

    def test_discovery_with_back_propagation(self):
        result = DiscoveryResult(origin="Zone C")
        result.backprop_links.append(DiscoveredLink("START", "Zone A", "preexisting"))
        result.backprop_links.append(DiscoveredLink("Zone A", "Zone B", "random"))
        result.backprop_links.append(DiscoveredLink("Zone B", "Zone C", "preexisting"))
        result.main_links.append(DiscoveredLink("Zone C", "Zone D", "random"))

        summary = format_discovery_summary(result, "mod")

        assert "Back-propagation (3)" in summary
        assert "START ---> Zone A" in summary
        assert "Zone A ───> Zone B" in summary  # random link
        assert "Zone B ---> Zone C" in summary  # preexisting link
        assert "Total: 4 new links" in summary

    def test_random_vs_preexisting_arrows(self):
        """Random links use ───>, preexisting use --->."""
        result = DiscoveryResult(origin="A")
        result.main_links.append(DiscoveredLink("A", "B", "random"))
        result.forward_links.append(DiscoveredLink("B", "C", "preexisting"))

        summary = format_discovery_summary(result, "mod")

        assert "A ───> B" in summary  # random: solid line
        assert "B ---> C" in summary  # preexisting: dashed line

    def test_with_progress_stats(self):
        result = DiscoveryResult(origin="Zone A")
        result.main_links.append(DiscoveredLink("Zone A", "Zone B", "random"))

        summary = format_discovery_summary(result, "mod", total_discovered=42, total_links=180)

        assert "Progress: 42/180 (23.3%)" in summary

    def test_without_progress_stats(self):
        result = DiscoveryResult(origin="Zone A")
        result.main_links.append(DiscoveredLink("Zone A", "Zone B", "random"))

        summary = format_discovery_summary(result, "mod")

        assert "Progress:" not in summary

    def test_full_scenario(self):
        """Test a complete discovery scenario with all propagation types."""
        result = DiscoveryResult(origin="Limgrave (Field)")
        # Back-propagation
        result.backprop_links.append(
            DiscoveredLink("START", "Limgrave (First Step)", "preexisting")
        )
        result.backprop_links.append(
            DiscoveredLink("Limgrave (First Step)", "Limgrave (Field)", "random")
        )
        # Main link
        result.main_links.append(DiscoveredLink("Limgrave (Field)", "Stormveil Castle", "random"))
        # Forward propagation
        result.forward_links.append(
            DiscoveredLink("Stormveil Castle", "Stormveil Castle (Rampart)", "preexisting")
        )

        summary = format_discovery_summary(result, "mod", total_discovered=15, total_links=180)

        # Check structure
        assert "╭─ Discovery Summary" in summary
        assert "╰─ Total:" in summary

        # Check origin
        assert "Origin:     Limgrave (Field)" in summary

        # Check main link
        assert "Link:       Limgrave (Field) ───> Stormveil Castle" in summary

        # Check back-propagation section
        assert "├─ Back-propagation (2):" in summary
        assert "◂ START ---> Limgrave (First Step)" in summary
        assert "◂ Limgrave (First Step) ───> Limgrave (Field)" in summary

        # Check forward-propagation section
        assert "├─ Forward-propagation (1):" in summary
        assert "▸ Stormveil Castle ---> Stormveil Castle (Rampart)" in summary

        # Check footer
        assert "Total: 4 new links" in summary
        assert "Progress: 15/180 (8.3%)" in summary


class TestFormatUndiscoverySummary:
    """Tests for format_undiscovery_summary function."""

    def test_single_zone_undiscovery(self):
        summary = format_undiscovery_summary("Stormveil Castle", ["Stormveil Castle"])

        assert "Undiscovery Summary" in summary
        assert "Target:     Stormveil Castle" in summary
        assert "Total: 1 zone removed" in summary
        # No cascade section when only the target is removed
        assert "Cascade" not in summary

    def test_undiscovery_with_cascade(self):
        removed = ["Stormveil Castle", "Stormveil Castle (Rampart)", "Stormveil Castle (Hall)"]
        summary = format_undiscovery_summary("Stormveil Castle", removed)

        assert "Target:     Stormveil Castle" in summary
        assert "├─ Cascade (2):" in summary
        assert "✗ Stormveil Castle (Rampart)" in summary
        assert "✗ Stormveil Castle (Hall)" in summary
        assert "Total: 3 zones removed" in summary

    def test_with_progress_stats(self):
        summary = format_undiscovery_summary(
            "Zone A", ["Zone A"], total_discovered=10, total_links=180
        )

        assert "Progress: 10/180 (5.6%)" in summary

    def test_without_progress_stats(self):
        summary = format_undiscovery_summary("Zone A", ["Zone A"])

        assert "Progress:" not in summary

    def test_full_scenario(self):
        """Test a complete undiscovery scenario with cascade."""
        removed = ["Limgrave (Field)", "Stormveil Castle", "Stormveil Castle (Rampart)"]
        summary = format_undiscovery_summary(
            "Limgrave (Field)", removed, total_discovered=5, total_links=180
        )

        # Check structure
        assert "╭─ Undiscovery Summary" in summary
        assert "╰─ Total:" in summary

        # Check target
        assert "Target:     Limgrave (Field)" in summary

        # Check cascade section
        assert "├─ Cascade (2):" in summary
        assert "✗ Stormveil Castle" in summary
        assert "✗ Stormveil Castle (Rampart)" in summary

        # Check footer
        assert "Total: 3 zones removed" in summary
        assert "Progress: 5/180 (2.8%)" in summary
