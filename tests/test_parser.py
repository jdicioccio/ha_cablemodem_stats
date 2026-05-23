"""Regression tests for the CGM HTML parser using a real modem capture.

The capture.html fixture was taken from an actual CGM4331COM/Xfinity XB7 modem.
These tests ensure that any refactoring of parse_cgm4331com_html preserves
exact behavior on real-world (messy) HTML output.
"""

from pathlib import Path
import sys

# Make the custom_components package importable when running tests from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from custom_components.ha_cablemodem_stats.parser import parse_cgm4331com_html


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "capture.html"


@pytest.fixture(scope="module")
def cgm_html() -> str:
    """Load the real modem HTML capture once for all tests."""
    return FIXTURE_PATH.read_text(encoding="utf-8")


def test_parse_cgm_from_capture_produces_expected_structure(cgm_html: str):
    """Basic structural invariants that must hold for this capture."""
    data = parse_cgm4331com_html(cgm_html)

    assert isinstance(data, dict)
    assert "downstream" in data
    assert "upstream" in data
    assert "system_uptime" in data

    assert len(data["downstream"]) == 34, "Expected 34 downstream channels from this capture"
    assert len(data["upstream"]) == 5, "Expected 5 upstream channels from this capture"
    assert isinstance(data["system_uptime"], int)
    assert data["system_uptime"] > 0


def test_parse_cgm_downstream_channel_1_values(cgm_html: str):
    """Spot-check a few known values from downstream channel 1 in this capture."""
    data = parse_cgm4331com_html(cgm_html)
    ch = data["downstream"][1]

    assert ch["channel"] == 1
    assert ch["channel_id"] == 20
    assert ch["frequency"] == 495.0
    assert ch["power"] == -2.4
    assert ch["snr"] == 39.2
    # These large numbers come from the "giant concatenated" error table in the HTML
    assert ch["corrected_errors"] == 3384096150
    assert ch["uncorrected_errors"] == 38


def test_parse_cgm_has_reasonable_upstream_data(cgm_html: str):
    """Basic sanity on upstream channels."""
    data = parse_cgm4331com_html(cgm_html)
    us = data["upstream"]

    # All upstream channels should have the expected keys
    for ch_num, ch in us.items():
        assert "channel" in ch
        assert "frequency" in ch
        assert "power" in ch
        assert "symbol_rate" in ch
        assert ch["lock_status"] in ("Locked", "Not Locked", "")


def test_parser_is_idempotent_on_capture(cgm_html: str):
    """Calling the parser twice on the same HTML should produce identical results."""
    first = parse_cgm4331com_html(cgm_html)
    second = parse_cgm4331com_html(cgm_html)

    assert first == second
