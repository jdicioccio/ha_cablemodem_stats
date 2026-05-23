# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2025-05-22

### Added
- **Options / Reconfiguration support**: You can now update the integration settings (host, model, username, password, SSL, scan interval) after the integration has been added. No more need to remove and re-add the integration to change credentials or connection details.
- Full Options Flow UI with live validation (same connection test as initial setup).
- Automatic reload of the integration when options are saved.

### Changed
- Major refactor of the CGM4331COM / CGM4981COM HTML parser:
  - Extracted reusable helper functions for value extraction and "giant concatenated number" handling.
  - Significantly reduced code duplication across downstream, upstream, and error table parsing.
  - Improved maintainability while preserving identical parsing behavior on real modem output.
- Added proper regression test suite using a real modem capture (`tests/fixtures/capture.html`).
- Enhanced CLI tool (`--html-file` and `--save-html` modes):
  - Now works without Home Assistant installed for parser development.
  - Supports self-signed certificates (common on cable modems).
  - Better structured output and HTML analysis.

### Fixed
- Various parser robustness improvements based on real-world modem HTML.

### Notes
- Existing installations will continue to work. After updating, go to the integration's **Configure** button to access the new options.

## [1.0.0] - Initial Release

- Initial public release with support for:
  - Arris/Motorola MB8600
  - Xfinity XB7 (CGM4331COM)
  - Xfinity XB8 (CGM4981COM)
- Config flow with live connection validation
- Downstream and upstream channel sensors
- System uptime parsing (internal)