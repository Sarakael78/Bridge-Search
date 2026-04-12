---
name: bridge-search
description: Set up and operate the WSL2-to-Windows search bridge for Everything (`es.exe`), AnyTXT via its HTTP Search Service only, and `bridge_tools.py`. Use when working across `/mnt/c` and `C:\` paths, when you need fast Windows filename search, full-text file-content search on Windows, or when enabling the bundled `bridge_tools.py` and `server.py` MCP pair as a reusable bridge skill. Do not look for or rely on an AnyTXT CLI binary; in this workflow AnyTXT is HTTP-only.
---

# Bridge Search

Use this skill to set up and run the MCP bridge stored in this skill's `scripts/` folder. This is the **authoritative** bridge for cross-OS search and file management.

## Files

- `scripts/bridge_tools.py`: path translation, safe file operations, directory cataloging, filename search, and content search helpers.
- `scripts/server.py`: FastMCP wrapper exposing the bridge tools over stdio.
- `config/bridge-search.config.example.json`: optional JSON policy (copy to `config/bridge-search.config.json`; `BRIDGE_SEARCH_CONFIG` can point elsewhere — see README). Profile examples: **`config/bridge-search.config.everything-only.example.json`**, **`config/bridge-search.config.anytxt-only.example.json`**, **`config/bridge-search.config.everything-and-anytxt.example.json`**. Use **`backends`** for other combinations (e.g. WSL-only).
- `references/setup_directive.md`: original full setup directive and source material.

## Workflow

1. Confirm WSL2 is the current environment.
2. Verify Python 3.10+ and the `mcp` package are available (prefer **`./install.sh`** from the repo root on Debian/Ubuntu WSL—it installs missing `python3`/`pip`/`venv` via `apt` when needed, then runs **`setup_skill.py --venv`**; otherwise run **`python3 scripts/setup_skill.py --venv`**; add **`--dev`** as needed; **`--skip-checks`** if backends exclude Windows services). If **`sudo`** prompts for a password, the human must run **`./install.sh`** locally.
3. Confirm Windows-side prerequisites match **`backends`** in **`config/bridge-search.config.json`** (defaults: Everything + AnyTXT):
   - Voidtools Everything is installed and running (if **`backends.everything`**).
   - AnyTXT Searcher is installed and the **HTTP Search Service** is enabled on port **9921** (if **`backends.anytxt`**; see `bridge_tools.py` for the request URL).
   - Optional: `curl http://127.0.0.1:9921/` or rely on **`setup_skill.py`** post-install probes.
4. **Tool-Only Enforcement:**
   - **DO NOT** call `es.exe` or `grep` directly via `run_shell_command` if the MCP server can be started.
   - **DO NOT** search for an AnyTXT executable. It is handled exclusively via HTTP on port **9921**.
5. Use this search order:
   - Everything (`locate_file_or_folder`, default **`target_env=windows`**) for filename/path search. Use **`everywhere`** only when you also need WSL-side `find` (scoped to **`$HOME`** by default; full `/` requires config or `BRIDGE_SEARCH_ALLOW_ROOT_LOCATOR=1`).
   - AnyTXT (`locate_content_inside_files`) for content search.
   - Accept a "zero-hit" from Everything as a definitive "File Not Found" for the requested scope.
6. Default search scope should be user-document areas:
   - `C:\Users\david\Documents`
   - `C:\Users\david\Desktop`
   - `C:\Users\david\Downloads`

## Guardrails

- **The Absolute Zero Rule:** If Everything (`es.exe`) returns no hits for a filename query, **STOP**. Do not escalate to a slower brute-force `find` or `grep` on `/mnt/c/`. A zero from Everything is a high-signal "No" in this workspace.
- **Bridge-Only Execution:** Use `manage_file`, `map_directory`, `locate_file_or_folder`, and `locate_content_inside_files` for all operations. Do not hand-roll path conversions or shell commands.
- **Encoding & Quoting:** The bridge tools handle Windows path quoting and `cp1252` encoding. Manual `run_shell_command` calls are likely to fail on paths with spaces or special characters.
- **AnyTXT is a Service:** Treat AnyTXT as a networked local service. If search fails, debug the service state or port **9921**, not the local filesystem.
- **Privacy & Noise:** Ignore `AppData`, browser profiles, `node_modules`, and caches unless explicitly instructed otherwise.
- **Path policy:** Reads, writes, `map_directory`, and WSL grep roots honor the same **denylist** (resolved paths under `/etc`, `/mnt/c/Windows`, `/usr`, `/var`, etc. are blocked). Optional **`BRIDGE_SEARCH_ALLOWED_PREFIXES`** (`:`-separated) and config **`allowed_prefixes`** restrict file operations to those prefixes and, when set, **filter search tool result rows** (Everything/`find`, WSL `grep`, AnyTXT) to matching paths.
- **Confirmation flag:** `is_confirmed` is an **agent workflow** toggle—not authorization, not cryptographic proof of human approval, and **not a substitute for OS-level approval**. All **writes** and **deletes** still require it so the model explicitly opts in.
- **WSL grep default root:** Empty `wsl_search_path` uses **`$HOME`**. Grep from **`/`** needs **`allow_grep_from_filesystem_root`** in `config/bridge-search.config.json` or **`BRIDGE_SEARCH_ALLOW_ROOT_GREP=1`**.
- **Config file:** Optional **`config/bridge-search.config.json`** (see `config/bridge-search.config.example.json`) adjusts denylist strength, confirmation flags, grep-from-root, and resource caps without editing Python. Example files include **`_security_warning`**: relaxing settings is **at your own risk** (see README for what can go wrong).

## Integration: Legal Research

- **Primary Provider:** This skill (`bridge-search`) is the **sole provider** of Windows-side file discovery for the `legal-local-research` skill.
- **Cross-Matter Context:** When `legal-local-research` needs to check for prior matters or precedents stored on the Windows host, it **must** call this bridge.

## Fast mental model

- **Everything** = `locate_file_or_folder` (Fastest)
- **AnyTXT** = `locate_content_inside_files` (Indexed Content)
- **Bridge Port** = **9921**
- **No hit from Everything** = **The file does not exist.** Stop searching.

If you catch yourself looking for an AnyTXT CLI, or repeating a slower search after a clean Everything zero, you are already off the rails.

## When details matter

Read `references/setup_directive.md` for the full original implementation notes and the embedded source copies of both Python files.
