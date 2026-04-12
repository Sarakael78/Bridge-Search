# Bridge Search 🌉

[![Licence: MIT](https://img.shields.io/badge/Licence-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP Compatible](https://img.shields.io/badge/MCP-Ready-success.svg)](https://github.com/steipete/mcporter)

## The Problem

The OS boundary is a massive bottleneck. When AI agents (like OpenClaw, Cursor, or Claude) try to search Windows files (`/mnt/c` etc.) from inside WSL2 using standard Linux commands, the results are disastrous. The search takes forever, the agent times out, loses its context window, or simply hallucinates file paths to move on.

## The Solution

Bridge Search bypasses the file system bottleneck entirely. It uses Model Context Protocol (MCP) tools to connect your AI directly to the native, hyper-optimised search engines built for Windows.

It handles all the messy cross-OS path translations automatically, giving your agent two immediate superpowers:

- ⚡ **Voidtools Everything:** Instant, millisecond file and folder lookups.
- 🔎 **AnyTXT:** Lightning-fast full-text search across documents, code, and PDFs.

Stop letting your AI waste tokens and time on brute-force scanning.

## ⚡ Quick Start

### 1. Prerequisites (Windows)

To get blazing-fast search speeds, you need the underlying Windows indexers installed and running. (Defaults assume both are available):

- **[Voidtools Everything](https://www.voidtools.com/):** Install and ensure the background service is running (`es.exe` on PATH or under `C:\Program Files\Everything\`).
- **[AnyTXT Searcher](https://anytxt.net/):** Install it, open the app, then go to **Tool → HTTP Search Service** and enable it.

*(Note: If you only want to use one of these, or just want to use WSL native search, Bridge Search is fully configurable. See Advanced Configuration below).*

### 2. Automated Setup (via AI Agent)

Human users can copy and paste this exact prompt to their AI agent to automate the setup:

> "I need you to search my Windows files efficiently. Please navigate to your designated skills directory, clone `https://github.com/Sarakael78/Bridge-Search`, read **`README.md`** and **`SKILL.md`** in the repo root, then run `./install.sh` from the repo root. **If `./install.sh` stops for a `sudo` password, halt and ask me to run it manually.** Once installed, explicitly ensure the `bridge-search` skill is activated in your environment (for OpenClaw, verify `alsoAllow` and run `openclaw gateway restart`). Use the `bridge-search` MCP tools for all file lookups going forward, obeying the guardrails in **`SKILL.md`**."

### 3. Manual Installation (WSL2)

Open your WSL2 terminal and run:

```bash
git clone https://github.com/Sarakael78/Bridge-Search.git
cd Bridge-Search
chmod +x install.sh
./install.sh
```

The clone directory name is arbitrary (`Bridge-Search` above); the MCP server name used in clients is **`bridge-search`**.

*(Note: `install.sh` is a bootstrap script. On Debian/Ubuntu-based WSL, it will prompt for `sudo` to install missing `python3`, `pip`, and `venv` via `apt`, then run the Python setup. On Fedora/RHEL and other non-`apt` distros, install those packages with your package manager, then run `./install.sh`—it will skip `apt` and run the Python setup only.)*

### 4. MCP client (`mcporter`) on WSL

The bridge exposes MCP over stdio. **`setup_skill.py`** can register it; otherwise you need **[mcporter](https://github.com/steipete/mcporter)** (or another MCP host that launches `scripts/server.py`). Install Node.js, then:

```bash
npm install -g @steipete/mcporter
```

Manual registration is documented under [Manual MCP Registration](#manual-mcp-registration) below.

## 🤖 For AI Agents (OpenClaw, Claude, Cursor)

**If you are an AI assistant reading this**, Bridge Search provides you with specialised MCP tools to navigate the Windows/WSL file system efficiently. Because agents like OpenClaw struggle to search Windows mounts quickly, you must rely on these tools instead of shell commands.

**Before you call these MCP tools**, read **`README.md`** (install, troubleshooting, security overview) **and** **`SKILL.md`** (full guardrails, search order, path policy, `is_confirmed`, integrations). The following is a short summary only; **`SKILL.md` is authoritative** for agent behaviour.

### Agent Guardrails (The "Absolute Zero" Rule)

As an AI using these tools, you **must** obey the following behavioural logic to save time and compute:

1. **Never brute-force `/mnt/c`:** Do not use `find` or `grep` on Windows mounts. Use the `locate_file_or_folder` and `locate_content_inside_files` tools.
2. **The Absolute Zero Rule:** When `target_env` is set to `windows`, if the `locate_file_or_folder` tool (using Everything) returns **zero hits**, you must **STOP**. Do not fall back to slow Linux `find`/`grep` commands on `/mnt/c/`. Treat a zero-hit as **no match for this query in Everything’s indexed scope**—which usually means the file is absent or not yet indexed. **Exceptions:** if the human reports Everything is still indexing, the path is outside indexed locations, or the query/filters were wrong, fix the query or scope first instead of brute-forcing `/mnt/c`.
3. **Path translation:** Use bridge tools or `wslpath` internally; do not hand-roll path conversions.
4. **AnyTXT is HTTP-only:** Requests use the URL pattern in `scripts/bridge_tools.py` (host `127.0.0.1`, port `9921` by default). There is no AnyTXT CLI binary in this workflow.

## 🏗️ Architecture Flow

```mermaid
sequenceDiagram
    participant User
    participant Agent as AI Agent (OpenClaw)
    participant MCP as Bridge Search MCP Server (WSL)
    participant Win as Windows Host

    User->>Agent: "Find the project specification on Windows"
    Agent->>MCP: Call tool: `locate_file_or_folder`
    MCP->>Win: Query Voidtools Everything (es.exe) via OS bridge
    Win-->>MCP: Returns `C:\Users\User\spec.pdf`
    MCP->>MCP: Translates to `/mnt/c/Users/User/spec.pdf` (wslpath)
    MCP-->>Agent: Returns safe, mapped WSL path
    Agent-->>User: "Found it at /mnt/c/Users/User/spec.pdf"
```

## 🛠️ Provided MCP Tools

Bridge Search equips your AI with the following capabilities:

- **`locate_file_or_folder`:** Instantly finds files by name. Uses `es.exe` on Windows (`target_env=windows`). Use `everywhere` to combine with WSL `find` under `$HOME`.
- **`locate_content_inside_files`:** Instantly searches inside documents (PDFs, Word, text). Uses AnyTXT's HTTP API on Windows and `grep` when targeting WSL paths.
- **`map_directory`:** Generates hierarchical, paginated directory maps to understand project structures.
- **`manage_file`:** Safely read, write, move, or delete files across the OS boundary with automatic path translation and policy checks.

### `manage_file` safety rules

`manage_file` is stricter than a raw shell wrapper:

- write and delete still require `is_confirmed=True` when confirmation gates are enabled
- `write` now defaults to **replace**, while append requires `write_mode="append"`
- copy and move will **not** overwrite an existing destination unless `overwrite=True`
- copy and move refuse source and destination paths that resolve to the same location
- copy and move refuse to place a directory inside itself
- delete refuses filesystem root and the current user's home directory
- write returns a structured `destination_parent_missing` error if the parent directory does not exist
- reads try several common text encodings (`utf-8`, `utf-16`, `cp1252`) before giving up
- write/copy/move/mkdir are blocked on symlink paths, while delete removes the symlink itself rather than following it
- file operations use Python filesystem APIs instead of shelling out to `cp`, `mv`, or `rm -rf`

### Unified response contract

All four tools return the same top-level payload shape:

- `success`
- `results`
- `errors`
- `warnings`
- `meta`

Errors and warnings include a stable machine-readable `code`, so callers do not need to parse English prose.

Important:

- a zero-hit search is a valid outcome, so it returns `success: true` with `results: []`
- when Windows paths come back from Everything or AnyTXT, Bridge Search translates them to WSL paths when possible and preserves the original as `raw_path`
- `manage_file(read)` returns decoded text in `results[0].content` and may include `results[0].encoding`

### Concrete response examples

**Successful filename search**

```json
{
  "success": true,
  "results": [
    {
      "type": "search_hit",
      "path": "/mnt/c/Users/david/Documents/spec.pdf",
      "raw_path": "C:\\Users\\david\\Documents\\spec.pdf",
      "source": "windows-everything"
    }
  ],
  "errors": [],
  "warnings": [],
  "meta": {
    "total_found": 1
  }
}
```

**Zero-hit search**

```json
{
  "success": true,
  "results": [],
  "errors": [],
  "warnings": [],
  "meta": {
    "total_found": 0
  }
}
```

**Backend error response**

```json
{
  "success": false,
  "results": [],
  "errors": [
    {
      "code": "backend_unavailable",
      "message": "es.exe not found. Check Everything installation or Windows PATH.",
      "source": "windows-everything"
    }
  ],
  "warnings": [],
  "meta": {}
}
```

**Blocked `manage_file` mutation**

```json
{
  "success": false,
  "results": [],
  "errors": [
    {
      "code": "write_confirmation_required",
      "message": "WRITE BLOCKED. Pass is_confirmed=True after reviewing the target path.",
      "path": "/mnt/c/Users/david/Documents/note.txt"
    }
  ],
  "warnings": [],
  "meta": {
    "action": "write"
  }
}
```

## 🚑 Troubleshooting

- **AnyTXT connection errors/timeouts:** Open AnyTXT → Tool → HTTP Search Service. Ensure it is checked and the URL matches your runtime config (`service.anytxt_url` in `config/bridge-search.config.json` or `BRIDGE_SEARCH_ANYTXT_URL`; default endpoint `http://127.0.0.1:9921/search`). Allow local traffic on port 9921 in your Windows Firewall. **WSL2 localhost quirk:** If your agent still cannot reach AnyTXT from inside WSL, `127.0.0.1` may resolve to the Linux container instead of Windows. Fix this by updating `--anytxt-url` during setup so it is persisted to runtime config, setting `BRIDGE_SEARCH_ANYTXT_URL`, or enabling `networkingMode=mirrored` in `.wslconfig`.
- **Everything returns "es.exe not found":** Ensure Everything is installed, the background service is running, and `es.exe` is in your Windows `PATH`.
- **`mcporter: command not found`:** Node.js or `mcporter` is missing. Install via npm: `npm install -g @steipete/mcporter`.
- **Agent ignores tools:** If the agent drops context and tries to use `find /mnt/c/`, remind it: *"Do not use shell commands to search. Use your `bridge-search` MCP tools."*

## ⚙️ Advanced Configuration & Backends

You do not have to use both Everything and AnyTXT. Set `backends` in `config/bridge-search.config.json` (copy from `config/bridge-search.config.example.json`) or use per-process environment variables (e.g., `BRIDGE_SEARCH_ENABLE_EVERYTHING=1`).

We provide templates in the `config/` directory for common setups:

- `bridge-search.config.everything-only.example.json` — Windows filename search only.
- `bridge-search.config.anytxt-only.example.json` — Windows content search only.
- `bridge-search.config.everything-and-anytxt.example.json` — Both Windows indexers enabled.
- `bridge-search.config.relaxed.json` — A deliberately relaxed profile.

Example configs now also expose:

- `limits.command_timeout_seconds` for subprocess and HTTP timeout tuning
- a `_write_note` reminder that `manage_file(write)` defaults to replace, while append requires `write_mode="append"` per call

**AnyTXT HTTP URL:** By default, the bridge uses `http://127.0.0.1:9921/search`. Update this via the `--anytxt-url` flag during setup, by editing `config/bridge-search.config.json` (`service.anytxt_url`), or by setting `BRIDGE_SEARCH_ANYTXT_URL`.

**Installer note:** `setup_skill.py` persists the AnyTXT runtime URL into `config/bridge-search.config.json`, and if a `bridge-search` mcporter entry already exists it will replace it instead of failing outright.

### Manual MCP Registration

If you cannot run `setup_skill.py`, register stdio yourself with `mcporter`:

```bash
mcporter config add bridge-search \
  --command python3 \
  --arg /absolute/path/to/Bridge-Search/scripts/server.py \
  --description "WSL-to-Windows search bridge (Everything/AnyTXT)" \
  --persist ~/.mcporter/mcporter.json
```

For OpenClaw, manually add `bridge-search` to `alsoAllow` for your agent, then run `openclaw gateway restart`.

Installer note: `setup_skill.py` no longer edits `~/.openclaw/openclaw.json` unless you explicitly pass `--openclaw-allowlist`.

## 🛡️ Security Model

**TL;DR:** Bridge Search includes built-in safeguards to prevent your AI from accidentally modifying critical OS files or endlessly scanning your hard drive. The MCP process runs with your standard user privileges. Controls are **defence in depth**, relying on workflow flags and path resolution.

| **Protection Mechanism** | **Description** |
| ----- | ----- |
| **Path Denylist** | Paths are resolved via `realpath` and checked against a denylist of sensitive prefixes (e.g., `/etc`, `/mnt/c/Windows`, `/usr`). |
| **Optional Allowlist** | Set `BRIDGE_SEARCH_ALLOWED_PREFIXES` (colon-separated absolute paths) in environment or `security.allowed_prefixes` in config. If set, operations and search results are strictly filtered to these folders. |
| **Confirmation Flags** | All write/delete operations require the `is_confirmed=True` flag from the agent by default. *(Note: This is a workflow check, not OS-level authorisation).* |
| **Safer File Ops** | Copy/move require explicit overwrite opt-in, block self-targeting and copy-into-self mistakes, and delete refuses root and home-directory targets. |
| **Encoding & Symlink Policy** | Text reads try common Windows/Unicode encodings before failing. Mutating operations are blocked on symlink paths so the agent must act on the resolved real path explicitly. |
| **Search Root Limits** | WSL content/filename searches default to `$HOME`. Searching from `/` requires explicit opt-in via config keys like `security.allow_grep_from_filesystem_root`. |
| **Timeouts & DoS Caps** | Directory listing, locator hits, AnyTXT HTTP responses, and subprocess calls have caps/timeouts (for example `limits.max_catalog_lines`, `limits.anytxt_max_response_bytes`, `limits.command_timeout_seconds`). |

⚠️ **Warning:** Each example JSON file includes a `_security_warning` field. Read it before editing. Relaxing these settings (like using `path_denylist: "none"` or disabling confirmation flags) is at your own risk.

## 🧱 Architecture Notes

See `ARCHITECTURE.md` for the internal design, backend flow, pagination strategy, timeout model, and installer posture.

## 🤝 Contributing & Support

If you encounter a bug or have a feature request, please [open an issue](https://github.com/Sarakael78/Bridge-Search/issues). To contribute code:

1. Clone the repository.
2. Install developer dependencies: `python3 scripts/setup_skill.py --venv --dev` (requires **Python 3.10+**).
3. Make your changes and run the test suite: `python3 -m pytest`
4. Submit a pull request.

## 📝 Licence

MIT
