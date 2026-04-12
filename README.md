# Bridge Search

A high-performance bridge for cross-OS search and file management between WSL2 and Windows. This repository provides a **Skill** for behavioral guardrails and an **MCP Server** for technical execution.

**GitHub:** [`Sarakael78/wsl-windows-search`](https://github.com/Sarakael78/wsl-windows-search) — rename the repository on GitHub to **`Bridge-Search`** when you want the URL and default clone folder to match that name; then update `git remote` and any bookmarks.

---

## ⚡ Zero-Touch Installation (Any MCP Agent)

If you are using **OpenClaw, Claude Desktop, Cursor, or Windsurf**, you can automate the setup.

1.  **Windows Setup**: Ensure [Everything](https://www.voidtools.com/) and [AnyTXT](https://anytxt.net/) (port 9921) are running on Windows.
2.  **Tell your Agent**: Give it this link: **`https://github.com/Sarakael78/wsl-windows-search`** and say:
    **"Clone this and run `python3 scripts/setup_skill.py` to install."**

The agent will autonomously:
-   Clone the repository.
-   Install Python dependencies.
-   Register the server.
-   Auto-configure the environment.

---

## 🚀 Overview

**Bridge Search** solves the 9P filesystem performance bottleneck in WSL2 by leveraging native Windows indexed search tools:
- **Everything (Voidtools)**: Instant filename and path discovery.
- **AnyTXT Searcher**: Full-text content search via HTTP API.

## 🛠️ Features (MCP Tools)

- `locate_file_or_folder`: Search with Everything (`es.exe`) by default (`target_env=windows`). Use `everywhere` to add WSL `find` under **`$HOME`** (full-root WSL find is opt-in via config or `BRIDGE_SEARCH_ALLOW_ROOT_LOCATOR`). Partial filename matches pass `*wildcards*` to `es.exe` automatically.
- `locate_content_inside_files`: Search for text inside files using AnyTXT's indexed content search.
- `map_directory`: Generate hierarchical directory maps with pagination.
- `manage_file`: Robust cross-OS file operations (read, write, move, delete) with built-in path translation.

---

## Security model

The MCP process runs with your user privileges. Controls are **defense in depth**, not a substitute for host trust and agent policy.

| Mechanism | Behavior |
|-----------|----------|
| Path policy | After `wslpath` where needed, paths are checked with `os.path.realpath` against a **denylist** of sensitive prefixes (for example `/etc`, `/mnt/c/Windows`, `/mnt/c/Program Files`, `/usr`, `/var`). |
| Optional allowlist | Set **`BRIDGE_SEARCH_ALLOWED_PREFIXES`** to a colon-separated list of absolute path prefixes (or non-empty **`allowed_prefixes`** in config). When set, **file operations** must fall under one of these prefixes after resolution; **search tools** also filter **returned result rows** to matching paths (strongest lock-down). Legacy: **`WSL_WINDOWS_SEARCH_BRIDGE_ALLOWED_PREFIXES`**. |
| `is_confirmed` | A **workflow flag** for the agent—not cryptographic authorization and **not a substitute for OS-level approval** or host policy. **All writes** and **deletes** require `is_confirmed=True`. |
| WSL content search root | Empty `wsl_search_path` defaults to **`$HOME`**. Searching from **`/`** requires **`BRIDGE_SEARCH_ALLOW_ROOT_GREP=1`** or **`allow_grep_from_filesystem_root`** in config. Legacy: **`WSL_WINDOWS_SEARCH_BRIDGE_ALLOW_ROOT_GREP`**. |
| WSL filename search root | By default, `find` for WSL filename search runs under **`$HOME`** only. Full **`find /`** (with `/mnt` pruned) requires **`allow_wsl_locator_from_filesystem_root`** in config or **`BRIDGE_SEARCH_ALLOW_ROOT_LOCATOR=1`**. Legacy: **`WSL_WINDOWS_SEARCH_BRIDGE_ALLOW_ROOT_LOCATOR`**. |
| Grep safety | WSL grep uses **`-F`**, **`-e`**, and **`--`** so patterns and paths are not treated as options. |
| DoS limits | Catalog listing, locator hits, and AnyTXT HTTP responses are **capped** (see `scripts/bridge_tools.py` constants). |
| Setup script | `setup_skill.py` runs subprocesses with **argument lists** (no shell) where possible. |
| Search result row filtering | When an allowlist is active (env and/or config), `locate_file_or_folder` and `locate_content_inside_files` drop result lines whose paths are outside allowed prefixes (Everything/`find`, WSL `grep`, AnyTXT). |

### Configuration file (relax or tighten policy)

Place **`bridge-search.config.json`** in the **repository root** (next to `README.md`), or set **`BRIDGE_SEARCH_CONFIG`** to an absolute path. Copy from **`bridge-search.config.example.json`** (defaults match built-in behavior). For a deliberately **relaxed** profile, see **`bridge-search.config.relaxed.json`** and merge only the keys you need.

Legacy filenames and env vars still work when canonical ones are unset: **`wsl-windows-search-bridge.config.json`**, **`WSL_WINDOWS_SEARCH_BRIDGE_CONFIG`**, **`wsl-bridge.config.json`**, **`WSL_BRIDGE_CONFIG`**.

Each example JSON file includes a **`_security_warning`** field: read it before editing. **Changing security-related settings is at your own risk.** This project and its maintainers are **not responsible** for data loss, leaked secrets, account compromise, or unstable systems.

If you relax the defaults, realistic outcomes include:

- **Privacy and secrets:** Broader reads or searches can surface SSH private keys, API tokens, mail, synced cloud folders, or browser data into the agent context or logs.
- **Integrity and availability:** Turning off confirmation flags lets an agent (or a poisoned prompt) write, append, or delete files without a separate explicit approval step.
- **Resource abuse:** Higher limits or whole-filesystem search roots can cause high CPU, memory, or disk load, or lock up a session.
- **System exposure:** Weakening path denylists or using `path_denylist: "none"` can expose OS and application directories that the stricter defaults would block.

Only relax settings on machines and user accounts you trust; prefer tightening with **`allowed_prefixes`** when possible.

### Pinned dependencies

Runtime dependencies are pinned in **`requirements.txt`** (used by `setup_skill.py` and recommended manual installs). For reproducible deployments you can snapshot your environment with `pip freeze > requirements.lock` and install from that file in controlled environments.

---

| Key | Purpose |
|-----|---------|
| `security.path_denylist` | `"default"` \| `"minimal"` \| `"none"` \| `"custom"` — controls blocked path prefixes (`none` removes the denylist; allowlist still applies if set). |
| `security.custom_restricted_prefixes` | Used when `path_denylist` is `"custom"`: list of absolute path prefixes to block (after `realpath`). |
| `security.allowed_prefixes` | If non-empty, paths must lie under one of these (merged with `BRIDGE_SEARCH_ALLOWED_PREFIXES`). |
| `security.allow_grep_from_filesystem_root` | If `true`, allows `wsl_search_path` `/` without `BRIDGE_SEARCH_ALLOW_ROOT_GREP=1`. |
| `security.allow_wsl_locator_from_filesystem_root` | If `true`, WSL `locate_file_or_folder` may use `find /` (expensive). Default is HOME-scoped only; same opt-in as **`BRIDGE_SEARCH_ALLOW_ROOT_LOCATOR=1`**. |
| `security.require_confirm_for_writes` / `require_confirm_for_deletes` | Set to `false` only on trusted hosts to skip `is_confirmed` checks. |
| `limits.*` | Raise or lower caps (`max_limit`, `max_offset`, `max_depth`, `max_catalog_lines`, `max_locator_results`, `anytxt_max_response_bytes`). |

Keys whose names start with `_` are ignored (documentation only).

---

### 🚀 Agent-Led Installation (Automated)

**Directive to Agents**: If you are a coding assistant (Claude, Cursor, Codex, Windsurf, or OpenClaw), you can perform the entire setup by executing:

```bash
python3 scripts/setup_skill.py
```

This script will:
1.  Install dependencies from `requirements.txt` (or `mcp` if that file is missing).
2.  Register the MCP server via `mcporter`.
3.  Auto-configure OpenClaw (`openclaw.json`) if detected.
4.  Provide a JSON snippet for manual addition to other agent configs (Claude/Cursor/Windsurf).

---

## 📦 Manual Installation

Follow these steps to establish the bridge between your WSL2 environment and the Windows host.

### 1. Windows Host Setup

#### **A. Voidtools Everything (Filename Search)**
1.  **Download & Install**: Get the [Everything installer](https://www.voidtools.com/downloads/).
2.  **Verify Service**: Ensure the "Everything Service" is running (Tools -> Options -> General -> Everything Service).
3.  **Command-Line Interface**: Ensure `es.exe` is available. The bridge will automatically look in `C:\Program Files\Everything\`, but adding it to your Windows `PATH` is recommended.

#### **B. AnyTXT Searcher (Content Search)**
1.  **Download & Install**: Get [AnyTXT Searcher](https://anytxt.net/).
2.  **Enable HTTP Search Service**:
    *   Open AnyTXT Searcher.
    *   Go to **Tool -> HTTP Search Service**.
    *   Set the **Port** to `9921` (this matches the bridge's default).
    *   Click **Start**.
    *   *Note*: If you use a different port, you must update `scripts/bridge_tools.py`.

---

### 2. WSL2 Setup

#### **A. Clone the Repository**
Clone this repository into your OpenClaw `skills/` directory (or any preferred location). The default checkout folder follows the GitHub repo name (currently **`wsl-windows-search`**). You may rename the folder to **`Bridge-Search`** locally or after renaming the repo on GitHub.
```bash
cd ~/.openclaw/workspace/skills
git clone https://github.com/Sarakael78/wsl-windows-search.git
cd wsl-windows-search
```

#### **B. Install Python Dependencies**
The bridge requires Python 3.10+ and the dependencies pinned in **`requirements.txt`** (also declared under `[project]` in `pyproject.toml`). For running tests, install **`requirements-dev.txt`**. It is recommended to use a virtual environment or install globally for your user:
```bash
# Using a virtual environment (Recommended)
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt

# OR install globally for your user
pip install -r requirements.txt --user
pip install -r requirements-dev.txt --user
```

Run tests from the repo root: `python3 -m pytest` (see `[tool.pytest.ini_options]` in `pyproject.toml`).

#### **C. Verify Connectivity**
Test if WSL can reach the Windows AnyTXT service:
```bash
curl http://127.0.0.1:9921/
```

---

### 3. Registering the MCP Server

The bridge tools are exposed via an MCP server (`scripts/server.py`). You can register this with any MCP-compatible host.

#### **Using `mcporter` (OpenClaw Standard)**
Run this command from within the repository to register the server persistently:
```bash
mcporter config add bridge-search \
  --command "python3 $(pwd)/scripts/server.py" \
  --description "WSL-to-Windows search bridge (Everything/AnyTXT)"
```

If you previously registered **`wsl-windows-search-bridge`**, remove or replace that entry so only **`bridge-search`** is active.

---

### 4. Enabling for OpenClaw Agents

To allow an OpenClaw agent to use this bridge, you must ensure the skill is "allowed" in your `openclaw.json` config.

#### **A. Add to `alsoAllow`**
Find your agent configuration in `~/.openclaw/openclaw.json` and add **`bridge-search`** to the `alsoAllow` list (replace **`wsl-windows-search-bridge`** if present):

```json
{
  "agents": {
    "list": [
      {
        "id": "main",
        "tools": {
          "alsoAllow": [
            "bridge-search",
            "..."
          ]
        }
      }
    ]
  }
}
```

#### **B. Verify Skill Availability**
Run the following command to confirm the skill is recognized and enabled:
```bash
openclaw skills list | grep bridge-search
```

#### **C. Reload Agent**
If your OpenClaw Gateway is already running, you may need to restart it to pick up the new skill configuration:
```bash
openclaw gateway restart
```

---

### 5. Manual Integration (Claude Desktop / Windsurf)
Add the following to your `mcp_config.json`:
```json
{
  "mcpServers": {
    "bridge-search": {
      "command": "python3",
      "args": ["/absolute/path/to/Bridge-Search/scripts/server.py"]
    }
  }
}
```

## ⚖️ Guardrails (The Absolute Zero Rule)

This bridge enforces strict behavioral rules for agents:
1.  **The Absolute Zero Rule**: If Everything (`es.exe`) returns no hits, **STOP**. Do not fallback to a slow brute-force `find` or `grep` on `/mnt/c/`.
2.  **Service-Only Content Search**: AnyTXT is treated as a networked service on port **9921**. Do not search for local binaries.
3.  **Path Translation**: All tools use `wslpath` internally; never hand-roll path conversions.

## 📜 License
MIT
