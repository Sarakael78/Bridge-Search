# Bridge Search 🌉

Searching your Windows files (`/mnt/c`) from inside WSL2 is notoriously slow, and AI agents (like OpenClaw, Claude Desktop, Cursor, or Windsurf) often time out, get stuck, or hallucinate when forced to brute-force search across the OS boundary using standard Linux commands.

**Bridge Search** solves this by connecting your AI agents directly to blazing-fast Windows-native search engines. It provides Model Context Protocol (MCP) tools that seamlessly translate paths and query **Voidtools Everything** (for instant file location) and **AnyTXT** (for instant full-text content search) over the host boundary.

---

## ⚡ Quick Start for Humans

### 1. Prerequisites (Windows)
To get blazing-fast search speeds, you need the underlying Windows indexers installed and running. (Defaults assume both are available):
* **[Voidtools Everything](https://www.voidtools.com/):** Install and ensure the background service is running (`es.exe` on PATH or under `C:\Program Files\Everything\`).
* **[AnyTXT Searcher](https://anytxt.net/):** Install it, open the app, navigate to **Tool → HTTP Search Service**, and enable it.

*(Note: If you only want to use one of these, or just want to use WSL native search, Bridge Search is fully configurable. See Advanced Configuration below).*

### 2. Installation (WSL2)
Open your WSL2 terminal and run:

```bash
git clone https://github.com/Sarakael78/Bridge-Search.git
cd Bridge-Search
chmod +x install.sh   # only needed if the executable bit was not preserved
./install.sh
```

`install.sh` is a small bootstrap script: on Debian/Ubuntu-based WSL it can install missing `python3`, `pip`, and `venv` via `apt` (requires your password for `sudo`), then it runs `scripts/setup_skill.py --venv`. On other distros it skips `apt` and expects you to install those tools yourself.

If you already have Python 3.10+ with pip and venv, you can run the setup step directly:

```bash
python3 scripts/setup_skill.py --venv
```

This installs the required Python dependencies, registers the MCP server with `mcporter`, and automatically adds the skill to OpenClaw if it is installed.

---

## 🤖 For AI Agents (OpenClaw, Claude, Cursor)

**If you are an AI assistant reading this**, Bridge Search provides you with specialised MCP tools to navigate the Windows/WSL file system efficiently. Because agents like OpenClaw struggle to search Windows mounts quickly, you must rely on these tools instead of shell commands.

### Zero-Touch Setup Prompt
Human users can copy and paste this exact prompt to their AI agent to get started:
> "I need you to search my Windows files efficiently. Please clone `https://github.com/Sarakael78/Bridge-Search`, run `./install.sh` from the repo root (or `python3 scripts/setup_skill.py --venv` if Python is already set up), and use the `bridge-search` MCP tools for any file or content lookups going forward."

**If `./install.sh` stops for a `sudo` password**, you cannot complete that step autonomously: tell the human to run `./install.sh` manually in their WSL terminal, then continue once setup has finished.

### Agent Guardrails (The "Absolute Zero" Rule)
As an AI using these tools, you **must** obey the following behavioural logic to save time and compute:
1. **Never brute-force `/mnt/c`:** Do not use `find` or `grep` on Windows mounts. Use the `locate_file_or_folder` and `locate_content_inside_files` tools.
2. **The Absolute Zero Rule:** When `target_env` is set to `windows`, if the `locate_file_or_folder` tool (using Everything) returns **zero hits**, you must **STOP**. Do not fall back to slow Linux `find`/`grep` commands on `/mnt/c/`. A zero-hit from the Everything indexer means the file definitively does not exist.
3. **Path Translation:** Use bridge tools or `wslpath` internally; do not hand-roll path conversions.
4. **AnyTXT is HTTP-only:** Requests use the URL pattern in `scripts/bridge_tools.py` (host `127.0.0.1`, port `9921` by default). There is no AnyTXT CLI binary in this workflow.

---

## 🛠️ Provided MCP Tools

Bridge Search equips your AI with the following capabilities:
* **`locate_file_or_folder`**: Instantly finds files by name. Uses `es.exe` on Windows (`target_env=windows`). Use `everywhere` to combine with WSL `find` under `$HOME`.
* **`locate_content_inside_files`**: Instantly searches inside documents (PDFs, Word, text). Uses AnyTXT's HTTP API on Windows and `grep` when targeting WSL paths.
* **`map_directory`**: Generates hierarchical, paginated directory maps to understand project structures.
* **`manage_file`**: Safely read, write, move, or delete files across the OS boundary with automatic path translation and policy checks.

---

## ⚙️ Advanced Configuration & Backends

You do not have to use both Everything and AnyTXT. Set `backends` in `config/bridge-search.config.json` (copy from `config/bridge-search.config.example.json`) or use per-process environment variables (e.g., `BRIDGE_SEARCH_ENABLE_EVERYTHING=1`).

We provide templates in the `config/` directory for common setups:
* `config/bridge-search.config.everything-only.example.json`: Windows filename search only.
* `config/bridge-search.config.anytxt-only.example.json`: Windows content search only.
* `config/bridge-search.config.everything-and-anytxt.example.json`: Both Windows indexers enabled; WSL find/grep off.
* `config/bridge-search.config.relaxed.json`: A deliberately relaxed profile (merge only what you need).

**AnyTXT HTTP Port:** By default, the bridge expects AnyTXT to be broadcasting on `http://127.0.0.1:9921/search`. If your AnyTXT setup uses a different port, you must update this via the `--anytxt-url` flag during setup, or by editing `scripts/bridge_tools.py`.

### Manual MCP Registration
If you cannot run `setup_skill.py`, register stdio yourself with `mcporter` (uses `--persist` for the config file path):
```bash
mcporter config add bridge-search \
  --command python3 \
  --arg /absolute/path/to/Bridge-Search/scripts/server.py \
  --description "WSL-to-Windows search bridge (Everything/AnyTXT)" \
  --persist ~/.mcporter/mcporter.json
```
For OpenClaw, manually add `bridge-search` to `alsoAllow` for your agent, then run `openclaw gateway restart`.

---

## 🛡️ Security Model

**TL;DR:** Bridge Search includes built-in safeguards to prevent your AI from accidentally modifying critical OS files or endlessly scanning your hard drive.

The MCP process runs with your standard user privileges. Controls are **defence in depth**, relying on workflow flags and path resolution.

| Protection Mechanism | Description |
|----------------------|-------------|
| **Path Denylist** | Paths are resolved via `realpath` and checked against a denylist of sensitive prefixes (e.g., `/etc`, `/mnt/c/Windows`, `/usr`). |
| **Optional Allowlist** | Set `BRIDGE_SEARCH_ALLOWED_PREFIXES` (colon-separated absolute paths) in your environment or `security.allowed_prefixes` in config. If set, file operations and search result rows are strictly filtered to these folders. |
| **Confirmation Flags** | All write/delete operations require the `is_confirmed=True` flag from the agent. *(Note: This is a workflow check, not OS-level authorisation).* |
| **Search Root Limits** | WSL content and filename searches default to `$HOME`. Searching from `/` requires explicit opt-in via config keys like `security.allow_grep_from_filesystem_root`. |
| **DoS Caps** | Directory listing, locator hits, and AnyTXT HTTP responses have hard-coded caps (e.g., `limits.max_catalog_lines`, `limits.anytxt_max_response_bytes`). |

⚠️ **Warning:** Each example JSON file includes a `_security_warning` field. Read it before editing. Relaxing these settings (like using `path_denylist: "none"` or disabling confirmation flags) is at your own risk and can expose system files to the AI or allow unintended file modifications.

---

## 📝 Licence

MIT
