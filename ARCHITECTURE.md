# Bridge Search Architecture

## Purpose

Bridge Search is a small MCP server that gives agents a fast path across the WSL/Windows boundary.
Instead of brute-forcing `/mnt/c` from Linux tools, it routes filename and content queries to native backends on the Windows side and translates paths back into WSL form when possible.

## High-level design

```text
Agent
  -> MCP tool (stdio)
    -> bridge_search.server
      -> bridge_search.bridge_tools
        -> bridge_search.search_backends / file_ops / path_policy / config
          -> Windows backends (Everything, AnyTXT) and WSL backends (find, grep)
```

## Package layout

- `bridge_search/server.py`: MCP tool registration and tool surface
- `bridge_search/bridge_tools.py`: public convenience exports for tests and callers
- `bridge_search/search_backends.py`: Everything, AnyTXT, WSL find, WSL grep orchestration
- `bridge_search/file_ops.py`: guarded read, write, copy, move, delete, mkdir, and directory mapping
- `bridge_search/path_policy.py`: path translation plus allowlist and denylist checks
- `bridge_search/config.py`: merged config loading, env overrides, limits, and timeouts
- `bridge_search/result_models.py`: standardized response shape helpers
- `scripts/server.py`, `scripts/bridge_tools.py`: compatibility wrappers
- `scripts/setup_skill.py`: installer and registration helper

### Caching and performance

- `resolve_path` and `canonical_path` are cached via `lru_cache` to avoid redundant subprocess calls (`wslpath`) and expensive I/O.
- `resolve_es_exe` is cached at the module level after the first successful resolution, and revalidated on each call to avoid stale paths after install/uninstall changes.
- Parallel execution via `ThreadPoolExecutor` ensures that backend delays do not block the entire search when targeting multiple environments.

## Request flow

### Filename search

1. MCP calls `locate_file_or_folder`.
2. `server.py` delegates to `system_locator`.
3. `system_locator` selects enabled backends from config and `target_env`.
4. Windows searches go through Everything (`es.exe`), WSL searches go through `find`.
5. Returned Windows paths are translated with `wslpath` where possible.
6. Every returned path is filtered through the same path policy used for file operations.
7. Results are returned in the standard response envelope.

### Content search

1. MCP calls `locate_content_inside_files`.
2. `content_locator` selects AnyTXT and or WSL grep backends.
3. WSL grep is restricted to safe roots unless explicitly relaxed.
4. AnyTXT results are translated and filtered the same way as filename results.
5. Results are normalized into the shared response contract.

### File operations

1. MCP calls `manage_file`.
2. `hybrid_file_io` resolves source and destination paths.
3. Path policy checks run before mutation.
4. Confirmation gates are enforced for write and delete when enabled.
5. File operations use Python APIs, not shell wrappers.
6. Errors are returned as structured response objects, not raw exceptions.

## Path translation and policy

Bridge Search supports mixed path input.

- Windows absolute paths are converted to WSL when needed.
- WSL paths can be converted to Windows paths when needed.
- Sensitive prefixes are denied by default.
- Optional allowlists can further restrict visible and mutable paths.
- Search results are filtered through policy before being returned, not only before mutation.

This is a guardrail system, not a sandbox.
The process still runs with the host user’s privileges.

## Backend strategy

### Windows filename search: Everything

Everything is the preferred Windows filename backend.

- If the installed `es.exe` supports `-viewport-offset` and `-viewport-count`, Bridge Search uses native paging for Windows-only locator queries.
- If not, it falls back to bounded client-side paging.
- Native paging is detected from the live `es.exe -help` output and exposed in response metadata.

### Windows content search: AnyTXT

AnyTXT is accessed over HTTP.

- Runtime endpoint comes from config or `BRIDGE_SEARCH_ANYTXT_URL`.
- Response size is capped.
- Request timeout is bounded.

### WSL backends

- WSL filename search uses `find`
- WSL content search uses `grep`
- Both are capped by config and protected by timeouts
- Root-wide scanning is blocked by default

## Pagination model

Bridge Search tries to avoid full unbounded result collection.

- WSL backends short-circuit after enough rows for the requested page plus one extra row to determine `has_more`.
- Everything uses native viewport paging when the installed CLI supports it.
- `meta.total_found_is_lower_bound=true` means the current backend intentionally stopped early and the reported total is not exhaustive.

## Timeouts and failure semantics

All critical subprocess and HTTP calls are bounded.

Examples:
- `wslpath`
- `es.exe`
- `cmd.exe /c where es.exe`
- `find`
- `grep`
- AnyTXT HTTP

Timeouts produce structured `backend_timeout` errors instead of hanging the MCP server indefinitely.

## Response contract

All tools return:

- `success`
- `results`
- `errors`
- `warnings`
- `meta`

Important rules:
- zero-hit searches are valid successes
- warnings and errors include stable machine-readable codes
- `success` can be true for partial backend outcomes when at least one backend produced results; inspect `errors` and `warnings` for degraded paths
- file-operation failures should return structured errors instead of propagating raw exceptions

## Installer posture

`setup_skill.py` handles Python deps, mcporter registration, runtime config persistence, and optional health checks.

OpenClaw config edits are opt-in.
The installer no longer mutates `~/.openclaw/openclaw.json` unless `--openclaw-allowlist` is explicitly passed.

## Current tradeoffs

- Native paging is currently strongest on Everything because the CLI exposes viewport flags.
- WSL `find` and `grep` still rely on bounded client-side short-circuiting, not true backend offsets.
- Safety is policy-based and pragmatic, not a hardened isolation boundary.
