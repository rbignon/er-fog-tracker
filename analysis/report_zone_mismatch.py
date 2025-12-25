#!/usr/bin/env python3
"""
Generate a Claude prompt for reporting zone resolution mismatches.

This script:
1. Takes a server log excerpt (pasted interactively)
2. Runs baseline test on the seed to get current success rate
3. Generates a formatted prompt with raw log and context for debugging

Usage:
    # Interactive - paste log excerpt when prompted:
    ./report_zone_mismatch.py --seed seeds/1567343926 --expected "Siofra River -> Crystal Tunnel"

    # Skip baseline test (faster):
    ./report_zone_mismatch.py --seed seeds/1567343926 --expected "Zone A -> Zone B" --no-baseline

The generated prompt includes:
- The expected link that should have been resolved
- The raw server log showing the full resolution strategy
- Current baseline stats (1-link %, not found count)
- Instructions for fixing and testing
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path


def run_baseline_test(seed_path: Path) -> dict | None:
    """Run test_fog_resolution.py and capture results."""
    script_dir = Path(__file__).parent
    test_script = script_dir / "test_fog_resolution.py"

    if not test_script.exists():
        return None

    try:
        result = subprocess.run(
            [sys.executable, str(test_script), str(seed_path)],
            capture_output=True,
            text=True,
            cwd=script_dir,
            timeout=60,
        )

        # Parse summary from output
        output = result.stdout + result.stderr

        stats = {}
        if match := re.search(r"1 link:\s+(\d+)\s+\(\s*([\d.]+)%\)", output):
            stats["1_link_count"] = int(match.group(1))
            stats["1_link_pct"] = float(match.group(2))
        if match := re.search(r"Not found:\s+(\d+)\s+\(\s*([\d.]+)%\)", output):
            stats["not_found_count"] = int(match.group(1))
            stats["not_found_pct"] = float(match.group(2))
        if match := re.search(r"Total random links tested:\s+(\d+)", output):
            stats["total"] = int(match.group(1))

        return stats if stats else None

    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        return None


def generate_prompt(
    expected_link: str | None,
    raw_log: str | None,
    seed_path: str,
    baseline_stats: dict | None,
) -> str:
    """Generate a formatted prompt for Claude."""

    lines = ["# Zone Resolution Issue Report", ""]

    # Expected link
    if expected_link:
        lines.append("## Expected Link (not found)")
        lines.append(f"```")
        lines.append(expected_link)
        lines.append(f"```")
        lines.append("")

    # Raw server log - shows full resolution strategy
    if raw_log:
        lines.append("## Server Log (resolution attempt)")
        lines.append("```")
        lines.append(raw_log.strip())
        lines.append("```")
        lines.append("")

    # Seed info
    lines.append("## Seed Data")
    lines.append(f"Path: `analysis/{seed_path}`")
    lines.append("")

    # Baseline stats
    if baseline_stats:
        lines.append("## Current Baseline (test_fog_resolution.py)")
        lines.append(f"- Total links: {baseline_stats.get('total', '?')}")
        lines.append(
            f"- 1-link perfect: {baseline_stats.get('1_link_count', '?')} ({baseline_stats.get('1_link_pct', '?')}%)"
        )
        lines.append(
            f"- Not found: {baseline_stats.get('not_found_count', '?')} ({baseline_stats.get('not_found_pct', '?')}%)"
        )
        lines.append("")

    # Instructions
    lines.append("## Instructions")
    lines.append("")
    lines.append("Investigate and fix this zone resolution issue. The expected link should be")
    lines.append("discovered when the mod sends the discovery data shown in the log.")
    lines.append("")
    lines.append("**Before and after your fix:**")
    lines.append("")
    lines.append("1. Run the baseline test:")
    lines.append(f"   ```bash")
    lines.append(f"   cd analysis && ./test_fog_resolution.py {seed_path}")
    lines.append(f"   ```")
    lines.append("")
    lines.append("2. After fixing, verify:")
    lines.append("   - The specific case is now resolved")
    lines.append("   - No regression: 1-link % stays same or improves")
    lines.append("   - No new 'not found' cases")
    lines.append("")
    lines.append("3. Add a unit test in `server/tests/unit/test_zone_resolver.py`")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Generate Claude prompt for zone mismatch issues",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive - paste log excerpt, specify expected link:
  %(prog)s --seed seeds/1567343926 --expected "Siofra River -> Crystal Tunnel"

  # Skip baseline test (faster):
  %(prog)s --seed seeds/1567343926 --expected "Zone A -> Zone B" --no-baseline
""",
    )
    parser.add_argument("--seed", type=Path, required=True, help="Seed folder path")
    parser.add_argument("--expected", help="Expected link: 'Source Zone -> Target Zone'")
    parser.add_argument("--no-baseline", action="store_true", help="Skip baseline test")

    args = parser.parse_args()

    # Interactive mode - read log from stdin
    print("Paste server log excerpt (Ctrl+D when done):", file=sys.stderr)
    try:
        log_content = sys.stdin.read()
    except KeyboardInterrupt:
        sys.exit(1)

    if not log_content.strip():
        print("Error: No log content provided", file=sys.stderr)
        sys.exit(1)

    # Run baseline test
    baseline_stats = None
    if not args.no_baseline and args.seed.exists():
        print("Running baseline test...", file=sys.stderr)
        baseline_stats = run_baseline_test(args.seed)

    # Generate prompt with raw log
    prompt = generate_prompt(
        expected_link=args.expected,
        raw_log=log_content,
        seed_path=str(args.seed),
        baseline_stats=baseline_stats,
    )

    print(prompt)
    print("\n---", file=sys.stderr)
    print("Prompt generated. Copy and paste into Claude.", file=sys.stderr)


if __name__ == "__main__":
    main()
