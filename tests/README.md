# Testing the ha_cablemodem_stats Parser

This directory contains regression tests for the cable modem parsers, especially the complex HTML scraper for Xfinity CGM4331COM / CGM4981COM modems.

## Running the Tests

```bash
# Activate the project's virtual environment (contains all dev dependencies)
source .venv/bin/activate

# Run all tests
python -m pytest

# Run only the parser tests (most useful during development)
python -m pytest tests/test_parser.py -q

# Run with verbose output + show debug logs from the parser
python -m pytest tests/test_parser.py -q --log-cli-level=DEBUG
```

## The `capture.html` Fixture

- Location: `tests/fixtures/capture.html`
- This is a real-world HTML response captured from a CGM4331COM modem using the CLI:
  ```bash
  python -m custom_components.ha_cablemodem_stats --save-html tests/fixtures/capture.html <ip> CGM4331COM <user> <pass>
  ```
- The parser tests assert that `parse_cgm4331com_html()` produces consistent, correct output against this fixture.
- **Always** add or update tests when the parser changes.

## Adding a New Capture

1. Capture fresh HTML from a modem:
   ```bash
   python -m custom_components.ha_cablemodem_stats --save-html /tmp/new-capture.html <ip> CGM4331COM <user> <pass>
   ```
2. Copy it into `tests/fixtures/` with a descriptive name (e.g. `capture-xb8-firmware-2.4.html`).
3. Add a new test case in `test_parser.py` (or extend the existing one).
4. Make sure the new capture still passes all existing tests (behavioral compatibility).

## Why These Tests Matter

The CGM HTML parser is reverse-engineered against undocumented, frequently-changing modem web UIs. Small HTML changes from firmware updates can break parsing. Having real fixtures + automated tests makes regressions obvious immediately.

## Useful Commands

| Command | Description |
|---------|-------------|
| `python -m pytest tests/test_parser.py` | Run parser regression suite |
| `python -m custom_components.ha_cablemodem_stats --html-file tests/fixtures/capture.html CGM4331COM` | Manually inspect parsed output |
| `python -m pytest --log-cli-level=DEBUG` | See detailed parser debug logs during tests |

Happy testing! If the parser ever starts producing different results on `capture.html`, the tests will catch it before it reaches users.