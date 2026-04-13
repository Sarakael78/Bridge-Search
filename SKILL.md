---
name: bridge-search
description: Set up and operate the WSL2-to-Windows search bridge for Everything (`es.exe`), AnyTXT via its HTTP Search Service only, and `bridge_tools.py`. Use when working across `/mnt/c` and `C:\` paths, when you need fast Windows filename search, full-text file-content search on Windows, or when enabling the bundled `bridge_tools.py` and `server.py` MCP pair as a reusable bridge skill. Do not look for or rely on an AnyTXT CLI binary; in this workflow AnyTXT is HTTP-only.
---

# Bridge Search

Use this skill to set up and run the MCP bridge stored in this skill's `scripts/` folder. This is the **authoritative** bridge for cross-OS search and file management.

**Installation, `mcporter`, troubleshooting, and security:** see **`README.md`** in this repo.

## Files

- `scripts/bridge_tools.py`: path translation, safe file operations, directory cataloging, filename search, and content search helpers.
- `scripts/server.py`: FastMCP wrapper exposing the bridge tools over stdio.
- `config/bridge-search.config.example.json`: optional JSON policy (copy to `config/bridge-search.config.json`; `BRIDGE_SEARCH_CONFIG` can point elsewhere — see README). Profile examples: **`config/bridge-search.config.everything-only.example.json`**, **`config/bridge-search.config.anytxt-only.example.json`**, **`config/bridge-search.config.everything-and-anytxt.example.json`**. Use **`backends`** for other combinations (e.g. WSL-only).

## Workflow

1. Confirm WSL2 is the current environment.
2. Verify Python 3.10+ and the `mcp` package are available (prefer **`./install.sh`** from the repo root on Debian/Ubuntu WSL—it installs missing `python3`/`pip`/`venv` via `apt` when needed, then runs **`setup_skill.py --venv`**; otherwise run **`python3 scripts/setup_skill.py --venv`**; add **`--dev`** as needed; **`--skip-checks`** if backends exclude Windows services). If **`sudo`** prompts for a password, the human must run **`./install.sh`** locally.
3. Confirm Windows-side prerequisites match **`backends`** in **`config/bridge-search.config.json`** (defaults: Everything + AnyTXT):
   - Voidtools Everything is installed and running (if **`backends.everything`**).
   - AnyTXT Searcher is installed and the **HTTP Search Service** is enabled on the configured URL (default **`http://127.0.0.1:9921/search`**) if **`backends.anytxt`**.
   - Optional: `curl http://127.0.0.1:9921/` or rely on **`setup_skill.py`** post-install probes.
4. **Tool-Only Enforcement:**
   - **DO NOT** call `es.exe` or `grep` directly via `run_shell_command` if the MCP server can be started.
   - **DO NOT** search for an AnyTXT executable. It is handled exclusively via HTTP on port **9921**.
5. Use this search order:
   - Everything (`locate_file_or_folder`, default **`target_env=windows`**) for filename/path search. Use **`everywhere`** only when you also need WSL-side `find` (scoped to **`$HOME`** by default; full `/` requires config or `BRIDGE_SEARCH_ALLOW_ROOT_LOCATOR=1`).
   - AnyTXT (`locate_content_inside_files`) for content search.
   - Accept a "zero-hit" from Everything as **no match in Everything’s indexed scope** for that query (usually “not found” unless indexing lag, wrong filters, or path outside indexed locations—see Guardrails).
6. Default search scope should be the current Windows user’s document-style folders, for example under the profile (e.g. `%USERPROFILE%\Documents`, `%USERPROFILE%\Desktop`, `%USERPROFILE%\Downloads`). Adjust to the user’s actual layout when known.

## Tool selection

- **`locate_file_or_folder`**: filename/path search. Default to **`target_env=windows`** for Windows files. Query text must not be blank.
- **`locate_content_inside_files`**: indexed content search. Use **`target_env=windows`** for AnyTXT-only searches and **`everywhere`** when you intentionally want WSL grep too. Query text must not be blank.
- **`map_directory`**: get scoped structure before broad file operations or when you need pagination through a tree.
- **`manage_file`**: read, write, copy, move, delete, and mkdir with policy checks and explicit mutation semantics.
- **`get_health`**: diagnose backend reachability before inventing workarounds.

## Guardrails

- **The Absolute Zero Rule:** If Everything (`es.exe`) returns no hits for a filename query, **STOP**. Do not escalate to a slower brute-force `find` or `grep` on `/mnt/c/`. A zero is a high-signal “no match” for that query in the indexer **unless** the human says Everything is still indexing, the file lives outside indexed paths, or the query/filters were wrong—in those cases, refine the query or scope; still do not brute-force `/mnt/c`.
- **Bridge-Only Execution:** Use `manage_file`, `map_directory`, `locate_file_or_folder`, and `locate_content_inside_files` for all operations. Do not hand-roll path conversions or shell commands.
- **Query validation:** Blank or whitespace-only queries are rejected with **`query_required`**. Do not use empty searches to probe backends.
- **Encoding & Quoting:** The bridge tools handle Windows path quoting and `cp1252` encoding. Manual `run_shell_command` calls are likely to fail on paths with spaces or special characters.
- **AnyTXT is a Service:** Treat AnyTXT as a networked local service. If search fails, debug the service state or port **9921**, not the local filesystem.
- **Structured results:** All bridge tools return **`success`**, **`results`**, **`errors`**, **`warnings`**, and **`meta`**. Issues include stable machine-readable **`code`** fields. A clean zero-hit search is **not** an error.
- **Partial backend failures:** In multi-backend searches, `success` can still be `true` when one backend returns hits and another errors or times out; always read `errors` and `warnings`.
- **Privacy & Noise:** Ignore `AppData`, browser profiles, `node_modules`, and caches unless explicitly instructed otherwise.
- **Path policy:** Reads, writes, `map_directory`, and WSL grep roots honor the same **denylist** (resolved paths under `/etc`, `/mnt/c/Windows`, `/usr`, `/var`, etc. are blocked). Optional **`BRIDGE_SEARCH_ALLOWED_PREFIXES`** and config **`allowed_prefixes`** restrict file operations to those prefixes and, when set, **filter search tool result rows** (Everything/`find`, WSL `grep`, AnyTXT) to matching paths. The env parser accepts `:` or `;`; prefer `;` when any Windows-style `C:\...` path is present. Config entries may be WSL or Windows absolute paths.
- **Confirmation flag:** `is_confirmed` is an **agent workflow** toggle—not authorization, not cryptographic proof of human approval, and **not a substitute for OS-level approval**. All **writes** and **deletes** still require it so the model explicitly opts in.
- **Safer file mutations:** `manage_file` will not overwrite existing destinations on copy/move unless `overwrite=True`, refuses source==destination and directory-into-itself operations, and refuses deletion of filesystem root or the current home directory.
- **Encoding & symlinks:** `manage_file(read)` tries common text encodings (`utf-8`, BOM variants, `utf-16`, `cp1252`) before failing. Mutating operations (`write`, `copy`, `move`, `mkdir`) are blocked on symlink paths; if you really mean the target, resolve and pass the real path explicitly. `delete` removes the symlink itself.
- **WSL grep default root:** Empty `wsl_search_path` uses **`$HOME`**. Grep from **`/`** needs **`allow_grep_from_filesystem_root`** in `config/bridge-search.config.json` or **`BRIDGE_SEARCH_ALLOW_ROOT_GREP=1`**. When root grep is allowed, the bridge still avoids traversing `/mnt`.
- **Config file:** Optional **`config/bridge-search.config.json`** (see `config/bridge-search.config.example.json`) adjusts denylist strength, confirmation flags, grep-from-root, and resource caps without editing Python. Example files include **`_security_warning`**: relaxing settings is **at your own risk** (see README for what can go wrong).

## Integration: Legal Research

- **Primary Provider:** This skill (`bridge-search`) is the **sole provider** of Windows-side file discovery for the `legal-local-research` skill.
- **Cross-Matter Context:** When `legal-local-research` needs to check for prior matters or precedents stored on the Windows host, it **must** call this bridge.

## Fast mental model

- **Everything** = `locate_file_or_folder` (Fastest)
- **AnyTXT** = `locate_content_inside_files` (Indexed Content)
- **Diagnostic** = `get_health` (Check connectivity/services)
- **Bridge Port** = **9921**
- **WSL2 Localhost** = Automatic host discovery (from `/etc/resolv.conf`) is enabled.
- **No hit from Everything** = **No match in the indexer for that query** (treat as “not found” unless indexing/scope/query issues apply). Stop brute-forcing `/mnt/c`.

If you catch yourself looking for an AnyTXT CLI, or repeating a slower search after a clean Everything zero, you are already off the rails.

## When details matter

Use **`README.md`** for install, troubleshooting, and security. Implementation details live in the **`bridge_search/`** package (the authoritative source): `server.py`, `search_backends.py`, `file_ops.py`, `path_policy.py`, `config.py`, and `result_models.py`. The `scripts/` directory contains compatibility wrappers and the installer.
