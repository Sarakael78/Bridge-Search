# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> The historical `v1.0.0` tag identifies a tree with package version `0.2.0`. The package version in `pyproject.toml` is authoritative for that tree.

## [0.2.2] - 2026-11-22

### Added

- README hero image (`docs/assets/bridge-search-hero.png`) illustrating WSL2 ↔ Windows search via Everything and AnyTXT.
- WSL `locate` filename backend with a Bridge Search-managed database (`~/.cache/bridge-search/wsl-locate.db`) that auto-refreshes once every 24 hours.
- Non-blocking stale-DB behavior for WSL locate: searches serve cached rows immediately and schedule refresh in the background.
- Native Hermes MCP registration and launcher.

### Changed

- Require confirmation for move and copy-overwrite operations under the existing write-confirmation policy.
- Declare read-only `contents` permission for CI jobs.

### Fixed

- Start the Hermes MCP server from the host's working directory.
- Support the current AnyTXT Wt flow, improve endpoint rediscovery and avoid duplicate drive searches.
- Honour legacy security policy aliases and revalidate canonical paths during authorisation.

### Security

- Upgrade the MCP Python SDK to `1.30.0` and use the same dependency pin when setup falls back to package metadata.

## [0.2.1] - 2026-04-13

### Changed

- Skill is now identified as **windows-search** in `SKILL.md` for better agent discovery.
- Branded as **Bridge Search** in documentation and help text.
- Folder must be named `windows-search` for agent discovery.
- Updated documentation and setup prompt with the required folder name.
- **Note:** The underlying Python package name remains `bridge_search` and the MCP server identifier remains `bridge-search`.

## [0.2.0] - 2026-04-13

### Added

- `python -m bridge_search` stdio entry via `bridge_search/__main__.py`.
- `meta.degraded` on tool responses when both `errors` and `results` are non-empty.
- `limits.max_delete_entries` and warnings for large directory deletes (`large_directory_delete`).
- Warning on empty `manage_file(write)` content (`empty_content_write`).
- Content search deduplication across backends when `line_number` is present.
- CI: Ruff and Mypy jobs; CodeQL badge in README.
- Docs: Everything CLI (`es.exe`) as separate Voidtools download; uninstall section; `CHANGELOG.md`.

### Changed

- `clamp_int` moved to `config.py`; `get_effective_anytxt_urls` is public.
- Consistent `ErrorCodes` usage in backends and health checks.
- Path caches: successful-only caching for `resolve_path` / `canonical_path`; lock-held resolution for `es.exe` and Everything help text.
- AnyTXT: URL host/scheme stderr warnings; validated JSON shape (`results` list).
- WSL `find`: escape glob metacharacters in `-iname` patterns.
- Installer: robust `--venv` detection, PEP 668 hint, restored `BRIDGE_SEARCH_ANYTXT_URL` after health checks.

### Fixed

- `_wsl_grep_command` root detection (`canonical_path(root) == "/"`).
- Removed dead branch in Everything worker.

## [0.1.0]

### Added

- Initial MCP bridge: Everything, AnyTXT, WSL find/grep, `manage_file`, `map_directory`, `get_health`, path policy, and JSON config.
