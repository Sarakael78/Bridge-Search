# Bridge Search

Fast **filename** and **full-text** search across WSL2 and Windows without crawling `/mnt/c` like it’s 1999. This repo ships a **Skill** (behavioral guardrails) and an **MCP server** (`scripts/server.py`) that talks to **Voidtools Everything** and **AnyTXT** over the host boundary.

**Repository:** [`Sarakael78/Bridge-Search`](https://github.com/Sarakael78/Bridge-Search) — MCP / skill id **`bridge-search`**, optional policy file **`bridge-search.config.json`** (default checkout folder **`Bridge-Search`**).

---

## Why use it

WSL2’s Plan 9–style `/mnt/c` access is fine for occasional files but painful for “find every PDF mentioning X.” Bridge Search hands that work to **Windows-native indexers**: instant path lookup via **Everything** (`es.exe`) and indexed content search via **AnyTXT’s HTTP API** (default port **9921**). Your agent gets stable MCP tools with **`wslpath`**-aware path handling instead of brittle shell pipelines.

---

## Search backends (Everything, AnyTXT, WSL)

You can run **only** what you need. Set **`backends`** in **`bridge-search.config.json`** (copy from **`bridge-search.config.example.json`**) or use per-process env vars.

| Goal | Config hint |
|------|----------------|
| Everything filename search only | `backends.everything: true`, `backends.wsl_find: false` — `locate_file_or_folder` with **`target_env: "windows"`** |
| WSL filename (`find`) only | `backends.wsl_find: true`, `backends.everything: false` — **`target_env: "wsl"`** |
| Both filename engines | Defaults (`everything` + `wsl_find` true) and **`target_env: "everywhere"`** |
| AnyTXT content search only | `backends.anytxt: true`, `backends.wsl_grep: false` — **`target_env: "windows"`** with `locate_content_inside_files` |
| WSL grep content only | `backends.wsl_grep: true`, `backends.anytxt: false` — **`target_env: "wsl"`** |
| Both content engines | Defaults and **`target_env: "everywhere"`** |

**Env overrides:** **`BRIDGE_SEARCH_ENABLE_EVERYTHING`**, **`BRIDGE_SEARCH_ENABLE_ANYTXT`**, **`BRIDGE_SEARCH_ENABLE_WSL_FIND`**, **`BRIDGE_SEARCH_ENABLE_WSL_GREP`** — `1`/`0`, `true`/`false`, or `on`/`off`.

The install script’s post-checks **respect these flags** (e.g. it won’t insist on AnyTXT if `backends.anytxt` is false).

---

## Prerequisites (Windows)

Install only what matches your **`backends`** (defaults expect **both** Windows indexers):

1. **[Everything](https://www.voidtools.com/)** — service running; **`es.exe`** on PATH or under `C:\Program Files\Everything\`.
2. **[AnyTXT Searcher](https://anytxt.net/)** — **Tool → HTTP Search Service** on port **9921** (bridge default; change both the app and your workflow if you use another port).

---

## Install (recommended)

```bash
git clone https://github.com/Sarakael78/Bridge-Search.git
cd Bridge-Search
python3 scripts/setup_skill.py
```

The script **installs** Python deps (`requirements.txt`, or `mcp` if missing), **registers** the MCP server with **`mcporter`** (`command` + `args`, written to `~/.mcporter/mcporter.json`), **adds** **`bridge-search`** to OpenClaw **`alsoAllow`** for the **`main`** agent when `~/.openclaw/openclaw.json` exists, runs **health probes** (AnyTXT HTTP + `es.exe -version` when those backends are enabled), runs **`openclaw skills list`** if available, prints a **JSON snippet** for Claude Desktop / Cursor / Windsurf, and exits **non-zero** if a required probe fails (unless you opt out).

| Flag | Purpose |
|------|---------|
| `--venv` | Create or reuse **`.venv`** and register that interpreter (recommended; avoids `--user` site-packages). |
| `--venv-path DIR` | Venv location relative to repo root (default `.venv`). |
| `--dev` | Also install **`requirements-dev.txt`** (e.g. pytest). |
| `--skip-checks` | Skip AnyTXT / Everything post-install probes (CI or WSL-only backends). |
| `--anytxt-url URL` | AnyTXT base URL for the HTTP probe (default `http://127.0.0.1:9921/`). |
| `--restart-gateway` | Run **`openclaw gateway restart`** after setup (optional; can interrupt sessions). |

**Examples**

```bash
python3 scripts/setup_skill.py --venv --dev
python3 scripts/setup_skill.py --skip-checks
```

---

## Zero-touch (any MCP agent)

1. Complete **Windows** prerequisites for the backends you use (see above).
2. Tell your agent: clone **`https://github.com/Sarakael78/Bridge-Search`** and run **`python3 scripts/setup_skill.py`** (add flags as needed).

---

## Features (MCP tools)

- **`locate_file_or_folder`**: Everything (`es.exe`) on Windows by default (`target_env=windows`). Use **`everywhere`** to combine with WSL **`find`** under **`$HOME`** (full-root WSL find is opt-in via config or **`BRIDGE_SEARCH_ALLOW_ROOT_LOCATOR`**). Partial filename matches add `*wildcards*` for `es.exe` unless **`exact_match`**.
- **`locate_content_inside_files`**: AnyTXT HTTP on Windows; WSL **`grep`** when targeting WSL paths.
- **`map_directory`**: Hierarchical directory maps with pagination.
- **`manage_file`**: Cross-OS read / write / move / delete with path translation and policy checks.

---

## Security at a glance

- **Path denylist** (and optional **allowlist**) on resolved paths; search **result rows** can be filtered when an allowlist is set.
- **`is_confirmed`** is a workflow flag for writes/deletes—not OS-level authorization.
- **Resource caps** limit listing, locator hits, and AnyTXT response size (see `scripts/bridge_tools.py`).
- **`setup_skill.py`** runs subprocesses with **argument lists** (no shell) where possible.

Full detail, relax/tighten guidance, and config keys are in the next section.

---

## Security model (full)

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
| Search result row filtering | When an allowlist is active (env and/or config), `locate_file_or_folder` and `locate_content_inside_files` drop result lines whose paths are outside allowed prefixes (Everything/`find`, WSL `grep`, AnyTXT). |

### Configuration file (relax or tighten policy)

Place **`bridge-search.config.json`** in the **repository root** (next to `README.md`), or set **`BRIDGE_SEARCH_CONFIG`** to an absolute path. Copy from **`bridge-search.config.example.json`** (defaults match built-in behavior). For a deliberately **relaxed** profile, see **`bridge-search.config.relaxed.json`** and merge only the keys you need.

Alternate config locations (optional): **`wsl-windows-search-bridge.config.json`**, **`WSL_WINDOWS_SEARCH_BRIDGE_CONFIG`**, **`wsl-bridge.config.json`**, **`WSL_BRIDGE_CONFIG`**.

Each example JSON file includes a **`_security_warning`** field: read it before editing. **Changing security-related settings is at your own risk.** This project and its maintainers are **not responsible** for data loss, leaked secrets, account compromise, or unstable systems.

If you relax the defaults, realistic outcomes include:

- **Privacy and secrets:** Broader reads or searches can surface SSH private keys, API tokens, mail, synced cloud folders, or browser data into the agent context or logs.
- **Integrity and availability:** Turning off confirmation flags lets an agent (or a poisoned prompt) write, append, or delete files without a separate explicit approval step.
- **Resource abuse:** Higher limits or whole-filesystem search roots can cause high CPU, memory, or disk load, or lock up a session.
- **System exposure:** Weakening path denylists or using `path_denylist: "none"` can expose OS and application directories that the stricter defaults would block.

Only relax settings on machines and user accounts you trust; prefer tightening with **`allowed_prefixes`** when possible.

### Pinned dependencies

Runtime dependencies are pinned in **`requirements.txt`**. For reproducible deployments you can snapshot with `pip freeze > requirements.lock` and install from that file in controlled environments.

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
| `backends.everything` | If `false`, skip Voidtools **`es.exe`** in `locate_file_or_folder` (see Search backends above). |
| `backends.anytxt` | If `false`, skip AnyTXT HTTP in `locate_content_inside_files`. |
| `backends.wsl_find` | If `false`, skip WSL **`find`** in `locate_file_or_folder`. |
| `backends.wsl_grep` | If `false`, skip WSL **`grep`** in `locate_content_inside_files`. |

Keys whose names start with `_` are ignored (documentation only).

---

## Advanced (manual MCP registration)

If you cannot run **`setup_skill.py`**, register stdio yourself with **`mcporter`** (uses **`--persist`** for the config file path):

```bash
mcporter config add bridge-search \
  --command python3 \
  --arg /absolute/path/to/Bridge-Search/scripts/server.py \
  --description "WSL-to-Windows search bridge (Everything/AnyTXT)" \
  --persist ~/.mcporter/mcporter.json
```

Or add to **`mcp_config.json`** / host UI:

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

**OpenClaw:** add **`bridge-search`** to **`alsoAllow`** for your agent, then **`openclaw gateway restart`** if needed.

### Developers

```bash
python3 scripts/setup_skill.py --venv --dev
python3 -m pytest
```

---

## Guardrails (Absolute Zero)

1. **The Absolute Zero Rule:** If **Everything** is enabled and returns no hits for a filename query, **STOP**. Do not fall back to slow **`find`** / **`grep`** on `/mnt/c/`.
2. **AnyTXT is HTTP-only:** Port **9921** by default; no AnyTXT CLI binary in this workflow.
3. **Path translation:** Use bridge tools / **`wslpath`** internally; do not hand-roll conversions.

## License

MIT
