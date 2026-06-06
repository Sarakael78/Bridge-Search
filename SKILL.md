---
name: windows-search
description: Set up and operate the WSL2-to-Windows search bridge for Everything (`es.exe`), AnyTXT via its HTTP Search Service only, and the `bridge_search` MCP package. Use when working across `/mnt/c` and Windows drive paths such as `C:\`, `D:\`, `E:\`, `F:\`, and `X:\`, when you need fast Windows filename search, full-text file-content search on Windows, or when enabling this repo’s MCP server (`scripts/server.py` wrapper or `python -m bridge_search`). Do not look for or rely on an AnyTXT CLI binary; in this workflow AnyTXT is HTTP-only.
---

# Bridge Search

Use this skill to set up and run the MCP bridge: implementation lives in **`bridge_search/`**; **`scripts/server.py`** is a thin compatibility launcher. This is the **authoritative** bridge for cross-OS search and file management.

**Installation, `mcporter`, troubleshooting, and security:** see **`README.md`** in this repo.

## Files

- `bridge_search/`: authoritative Python package — `server.py` (MCP registration), `search_backends.py` (Everything, AnyTXT, WSL find/grep), `file_ops.py` (guarded I/O), `path_policy.py` (allow/denylist), `config.py` (config loading), `result_models.py` (response helpers), `constants.py` (error codes).
- `scripts/server.py`: compatibility wrapper that adds the repo root to `sys.path` then runs `bridge_search.server`.
- `scripts/rediscover_anytxt_endpoint.py`: standalone runtime discovery command that probes candidate AnyTXT URLs, persists the working endpoint, and prints a concise report.
- `bridge_search/__main__.py`: same MCP stdio entry as the server when run as `python -m bridge_search` (requires package import path).
- `config/bridge-search.config.example.json`: optional JSON policy (copy to `config/bridge-search.config.json`; `BRIDGE_SEARCH_CONFIG` can point elsewhere — see README). Profile examples: **`config/bridge-search.config.everything-only.example.json`**, **`config/bridge-search.config.anytxt-only.example.json`**, **`config/bridge-search.config.everything-and-anytxt.example.json`**. Use **`backends`** for other combinations (e.g. WSL-only).
- `references/install-registration.md`: concise install/registration notes, including the `mcporter` package-name gotcha and verification steps.
- `references/repo-discovery-audio-stem-separation.md`: session notes on finding and validating an audio stem-separation repo across Windows and GitHub.

## Workflow

1. Confirm WSL2 is the current environment.
2. **Directory Naming (MANDATORY for Discovery):** If you have just cloned this repository and the folder is not named **`windows-search`**, you **must** rename it to **`windows-search`** before proceeding. Agent discovery of this skill is tied to the folder name.
3. Verify Python 3.10+ and the `mcp` package are available (prefer **`./install.sh`** from the `windows-search` root on Debian/Ubuntu WSL—it installs missing `python3`/`pip`/`venv` via `apt` when needed, then runs **`setup_skill.py --venv`**; otherwise run **`python3 scripts/setup_skill.py --venv`**; add **`--dev`** as needed; **`--skip-checks`** if backends exclude Windows services). If **`sudo`** prompts for a password, the human must run **`./install.sh`** locally.
4. For rediscovering a previously used Windows repo or app, search by tool/repo name variants first, then verify with `git rev-parse --is-inside-work-tree` and `git remote -v` before treating a folder as canonical. See `references/repo-discovery-audio-stem-separation.md` for a compact example.
5. Confirm Windows-side prerequisites match **`backends`** in **`config/bridge-search.config.json`** (defaults: Everything + AnyTXT):
  - Voidtools Everything is installed and running (if **`backends.everything`**). **`es.exe`** comes from the **Everything CLI** package on [Voidtools downloads](https://www.voidtools.com/downloads/)—it is a separate download from the main GUI installer.
  - `es.exe` resolution order is explicit: first Windows `PATH`; if not found, check the standard install paths `C:\Program Files\Everything\es.exe` and `C:\Program Files (x86)\Everything\es.exe`.
   - AnyTXT Searcher is installed and the HTTP Search Service is enabled on the configured URL (probe the live WSL host gateway; a typical WSL2 URL is `http://<wsl-default-gateway>:9921`, and older sample docs may mention `9920`) if `backends.anytxt`. The bridge talks to the live HTTP search service, and on this host that service is the Wt HTML search UI: fetch the session page, extract the tokenised form controls, and submit the search form when a JSON endpoint is not available. Do not look for an AnyTXT CLI binary.
      - Optional: `curl http://$(ip route show default | awk '{print $3; exit}'):9921/` or rely on **`setup_skill.py`** post-install probes. From WSL, test the Windows host IP if localhost routing fails. Treat the Wt HTML search page returning HTTP 200 without the expected search form as “service reachable, bridge API/UI path not yet compatible/configured”, not as an unreachable service.
      - For endpoint recovery, use `python3 scripts/rediscover_anytxt_endpoint.py` first. It performs a lightweight UI/session probe and persists the working URL; add `--verify-search` only when you need content-search confirmation. The helper first checks `C:\ProgramData\Anytxt\config\config.db` for `HttpSearch`; if that setting is `0`, the HTTP Search Service is disabled and rediscovery cannot succeed until the service is enabled in the AnyTXT app.
5. **Tool-Only Enforcement:**
   - **DO NOT** call `es.exe` or `grep` directly via `run_shell_command` if the MCP server can be started.
   - **DO NOT** search for an AnyTXT executable. It is handled exclusively via HTTP on the configured service port.
6. Use this search order:
   - Everything (`locate_file_or_folder`, default **`target_env=windows`**) for filename/path search. Use **`everywhere`** only when you also need WSL-side `find` (scoped to **`$HOME`** by default; full `/` requires config or `BRIDGE_SEARCH_ALLOW_ROOT_LOCATOR=1`).
   - AnyTXT (`locate_content_inside_files`) for content search.
   - Accept a "zero-hit" from Everything as **no match in Everything’s indexed scope** for that query (usually “not found” unless indexing lag, wrong filters, or path outside indexed locations—see Guardrails).
7. Default search scope should be the current Windows user’s document-style folders, for example under the profile (e.g. `%USERPROFILE%\Documents`, `%USERPROFILE%\Desktop`, `%USERPROFILE%\Downloads`). Adjust to the user’s actual layout when known.
8. For OneDrive searches, start at the configured OneDrive root (for example `D:\OneDrive`) and search the full tree first. Do not split the job into multiple narrower subdirectory searches unless there is a specific reason to isolate a subtree.
9. For large WSL-to-OneDrive backups, use `references/large-archive-onedrive-backup.md`: create/hash the archive on WSL/ext4 first, then copy to OneDrive with temporary names and size verification, because large archive reads or compression directly on `/mnt/<drive>/OneDrive` can fail with transient `Cannot allocate memory` errors.

## Tool selection

- **`locate_file_or_folder`**: filename/path search. Default to **`target_env=windows`** for Windows files. Query text must not be blank.
- **`locate_content_inside_files`**: indexed content search. Use **`target_env=windows`** for AnyTXT-only searches and **`everywhere`** when you intentionally want WSL grep too.
- **`map_directory`**: get scoped structure before broad file operations or when you need pagination through a tree.
- **`manage_file`**: read, write, copy, move, delete, and mkdir with policy checks and explicit mutation semantics.
- **`get_health`**: diagnose backend reachability before inventing workarounds. Successful probes should refresh the last-known-good AnyTXT URL in config.

## Guardrails

- **The Absolute Zero Rule:** If Everything (`es.exe`) returns no hits for a filename query, **STOP**. Do not escalate to a slower brute-force `find` or `grep` on `/mnt/c/`. A zero is a high-signal “no match” for that query in the indexer **unless** the human says Everything is still indexing, the file lives outside indexed paths, or the query/filters were wrong—in those cases, refine the query or scope; still do not brute-force `/mnt/c`.
- **Bridge-Only Execution:** Use `manage_file`, `map_directory`, `locate_file_or_folder`, and `locate_content_inside_files` for all operations. Do not hand-roll path conversions or shell commands.
- **Query validation:** Blank or whitespace-only queries are rejected with **`query_required`**. Do not use empty searches to probe backends.
- **Encoding & Quoting:** The bridge tools handle Windows path quoting and `cp1252` encoding. Manual `run_shell_command` calls are likely to fail on paths with spaces or special characters.
- **AnyTXT is a Service:** Treat AnyTXT as a networked local service. If search fails, debug the live HTTP search service or its configured URL, not the local filesystem.
- **AnyTXT root page caveat:** `http://<host>:9921/` returning HTTP 200 only proves the web UI is reachable. The bridge content backend must be able to drive the live search surface actually exposed by the service (JSON API where present, otherwise the Wt HTML form with its session token and controls); if the page lacks the expected search form or the probe cannot complete a real search, report `anytxt_incompatible_endpoint` rather than treating the service as healthy. Do not equate a reachable root page with bridge-compatible content search. Keep the resolved endpoint in `config/bridge-search.config.json` as the last-known-good value and refresh it if the listener moves; successful health/content searches should write the verified endpoint back into config.
- **Structured results:** All bridge tools return **`success`**, **`results`**, **`errors`**, **`warnings`**, and **`meta`**. Issues include stable machine-readable **`code`** fields. A clean zero-hit search is **not** an error.
- **Partial backend failures:** In multi-backend searches, `success` can still be `true` when one backend returns hits and another errors or times out; always read `errors` and `warnings`. If both `errors` and `results` are non-empty, **`meta.degraded`** is `true`.
- **Privacy & Noise:** Ignore `AppData`, browser profiles, `node_modules`, and caches unless explicitly instructed otherwise.
- **Path policy:** Reads, writes, `map_directory`, and WSL grep roots honor the same **denylist** (resolved paths under `/etc`, `/mnt/c/Windows`, `/usr`, `/var`, etc. are blocked). Optional **`BRIDGE_SEARCH_ALLOWED_PREFIXES`** and config **`allowed_prefixes`** restrict file operations to those prefixes and, when set, filter search tool result rows (Everything/`find`, WSL `grep`, AnyTXT) to matching paths. The env parser accepts `:` or `;`; prefer `;` when any Windows-style `C:\...` path is present. If you want the bridge to search additional Windows volumes, explicitly include their roots, for example `D:\;E:\;F:\;X:\` or `/mnt/d;/mnt/e;/mnt/f;/mnt/x`. Config entries may be WSL or Windows absolute paths.
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
- **AnyTXT** = `locate_content_inside_files` (Indexed Content over AnyTXT’s HTTP Search Service)
- **Diagnostic** = `get_health` (Check connectivity/services)
- **AnyTXT Port** = the configured HTTP service root on the current WSL host gateway (for example `http://<wsl-default-gateway>:9921`). Windows Search itself is not a network service.
- **WSL2 Localhost** = Host discovery uses the WSL default route gateway when `/etc/resolv.conf` is owned by Tailscale or another DNS provider.
- **No hit from Everything** = **No match in the indexer for that query** (treat as “not found” unless indexing/scope/query issues apply). Stop brute-forcing `/mnt/c`.
- If `everything_help_text()` or a Windows filename query hangs inside Python but a shell call to `es.exe` works, suspect a bridge-side deadlock or interop issue rather than Everything itself. In particular, the help-path must not take a non-reentrant lock and then call `resolve_es_exe()` again; use a re-entrant lock or split the cache path from the lookup path.
- Everything execution is intentionally PowerShell-wrapped from WSL. Regression tests should assert against a flattened argv/PowerShell command string, not raw list membership, and `path_policy.resolve_path()` must tolerate mocked `subprocess.run(..., text=True)` returning bytes.
- For a mounted AnyTXT public path, pair the tunnel rule with a local prefix-stripping proxy and keep the upstream listener private; see `references/anytxt-path-prefix-proxy.md`.

## References

- `references/anytxt-http-api-notes.md`: HTTP API/probe caveat and filename-vs-content search distinction.
- `references/anytxt-endpoint-runtime-discovery.md`: last-known-good endpoint persistence and rediscovery notes.
- `references/anytxt-path-prefix-proxy.md`: mounted-path AnyTXT proxy pattern, verification checklist, and pitfalls.

## When details matter

Use **`README.md`** for install, troubleshooting, and security. Implementation details live in the **`bridge_search/`** package (the authoritative source): `server.py`, `search_backends.py`, `file_ops.py`, `path_policy.py`, `config.py`, and `result_models.py`. The `scripts/` directory contains compatibility wrappers and the installer.
