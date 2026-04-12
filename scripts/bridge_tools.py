import copy
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

# --- JSON config: config/bridge-search.config.json (preferred), or repo-root legacy filenames, or BRIDGE_SEARCH_CONFIG ---
# Legacy env: WSL_WINDOWS_SEARCH_BRIDGE_CONFIG, WSL_BRIDGE_CONFIG.
# Legacy paths: bridge-search.config.json et al. in repo root still honored if config/ file is absent.
_DEFAULTS: Dict[str, Any] = {
    "version": 1,
    "security": {
        "path_denylist": "default",
        "custom_restricted_prefixes": [],
        "allowed_prefixes": [],
        "allow_grep_from_filesystem_root": False,
        "allow_wsl_locator_from_filesystem_root": False,
        "require_confirm_for_writes": True,
        "require_confirm_for_deletes": True,
    },
    "limits": {
        "max_limit": 500,
        "max_offset": 50000,
        "max_depth": 20,
        "max_catalog_lines": 10000,
        "max_locator_results": 5000,
        "anytxt_max_response_bytes": 2097152,
    },
    "backends": {
        "everything": True,
        "anytxt": True,
        "wsl_find": True,
        "wsl_grep": True,
    },
}

_RESTRICTED_DEFAULT: Tuple[str, ...] = (
    "/bin",
    "/sbin",
    "/etc",
    "/boot",
    "/root",
    "/dev",
    "/sys",
    "/usr",
    "/var",
    "/proc",
    "/mnt/c/windows",
    "/mnt/c/program files",
    "/mnt/c/program files (x86)",
)

_RESTRICTED_MINIMAL: Tuple[str, ...] = (
    "/mnt/c/windows",
    "/mnt/c/program files",
    "/mnt/c/program files (x86)",
    "/proc",
    "/sys",
)

_cfg_cache: Optional[Dict[str, Any]] = None


def _strip_meta(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_meta(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [_strip_meta(x) for x in obj]
    return obj


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, val in override.items():
        if str(key).startswith("_"):
            continue
        if key in out and isinstance(out[key], dict) and isinstance(val, dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def _config_paths() -> List[str]:
    for key in ("BRIDGE_SEARCH_CONFIG", "WSL_WINDOWS_SEARCH_BRIDGE_CONFIG", "WSL_BRIDGE_CONFIG"):
        env = os.environ.get(key, "").strip()
        if env:
            return [os.path.abspath(env)]
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(script_dir, ".."))
    cfg = os.path.join(root, "config")
    return [
        os.path.join(cfg, "bridge-search.config.json"),
        os.path.join(root, "bridge-search.config.json"),
        os.path.join(cfg, "wsl-windows-search-bridge.config.json"),
        os.path.join(root, "wsl-windows-search-bridge.config.json"),
        os.path.join(cfg, "wsl-bridge.config.json"),
        os.path.join(root, "wsl-bridge.config.json"),
    ]


def get_bridge_config(reload: bool = False) -> Dict[str, Any]:
    """Merged defaults + first existing config file (see _config_paths)."""
    global _cfg_cache
    if _cfg_cache is not None and not reload:
        return _cfg_cache
    merged = copy.deepcopy(_DEFAULTS)
    for path in _config_paths():
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            user = _strip_meta(raw) if isinstance(raw, dict) else {}
            merged = _deep_merge(merged, user)
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            print(f"bridge-search: warning: could not load {path}: {exc}", file=sys.stderr)
        break
    _cfg_cache = merged
    return _cfg_cache


def _lim(key: str) -> int:
    lim = get_bridge_config().get("limits", _DEFAULTS["limits"])
    return int(lim.get(key, _DEFAULTS["limits"][key]))


_BACKEND_ENV: Dict[str, str] = {
    "everything": "BRIDGE_SEARCH_ENABLE_EVERYTHING",
    "anytxt": "BRIDGE_SEARCH_ENABLE_ANYTXT",
    "wsl_find": "BRIDGE_SEARCH_ENABLE_WSL_FIND",
    "wsl_grep": "BRIDGE_SEARCH_ENABLE_WSL_GREP",
}


def _backend_enabled(name: str) -> bool:
    """Config backends.* with optional env override (BRIDGE_SEARCH_ENABLE_* = 1/0, true/false, on/off)."""
    env_key = _BACKEND_ENV.get(name)
    if env_key:
        raw = os.environ.get(env_key, "").strip().lower()
        if raw in ("0", "false", "no", "off"):
            return False
        if raw in ("1", "true", "yes", "on"):
            return True
    defaults = _DEFAULTS.get("backends", {})
    cfg = get_bridge_config().get("backends", defaults)
    return bool(cfg.get(name, defaults.get(name, True)))


def _restricted_prefixes() -> Tuple[str, ...]:
    sec = get_bridge_config().get("security", _DEFAULTS["security"])
    mode = str(sec.get("path_denylist") or "default").lower()
    if mode == "none":
        return ()
    if mode == "minimal":
        return _RESTRICTED_MINIMAL
    if mode == "custom":
        extra = sec.get("custom_restricted_prefixes") or []
        out: List[str] = []
        for p in extra:
            if not isinstance(p, str) or not p.strip():
                continue
            exp = os.path.expanduser(p.strip())
            try:
                out.append(os.path.realpath(exp).lower())
            except OSError:
                out.append(os.path.normpath(exp).lower())
        return tuple(dict.fromkeys(out)) if out else _RESTRICTED_DEFAULT
    return _RESTRICTED_DEFAULT


def _parse_allowed_prefixes_env() -> Optional[List[str]]:
    raw = (
        os.environ.get("BRIDGE_SEARCH_ALLOWED_PREFIXES", "").strip()
        or os.environ.get("WSL_WINDOWS_SEARCH_BRIDGE_ALLOWED_PREFIXES", "").strip()
        or os.environ.get("WSL_BRIDGE_ALLOWED_PREFIXES", "").strip()
    )
    if not raw:
        return None
    out: List[str] = []
    for part in raw.split(":"):
        p = part.strip()
        if not p:
            continue
        expanded = os.path.expanduser(p)
        try:
            out.append(os.path.realpath(expanded))
        except OSError:
            out.append(os.path.normpath(expanded))
    return out if out else None


def _allowed_prefixes_merged() -> Optional[List[str]]:
    raw = get_bridge_config().get("security", _DEFAULTS["security"]).get("allowed_prefixes")
    from_file: List[str] = []
    if isinstance(raw, list):
        for p in raw:
            if not isinstance(p, str) or not p.strip():
                continue
            exp = os.path.expanduser(p.strip())
            try:
                from_file.append(os.path.realpath(exp))
            except OSError:
                from_file.append(os.path.normpath(exp))
    env_list = _parse_allowed_prefixes_env() or []
    merged: List[str] = []
    for p in from_file + env_list:
        if p and p not in merged:
            merged.append(p)
    return merged if merged else None



def _allowlist_filters_search_results() -> bool:
    """When set, Everything / find / grep / AnyTXT rows are filtered to paths under allowed_prefixes."""
    return _allowed_prefixes_merged() is not None


def _path_allowed_for_search_result(path_candidate: str) -> bool:
    """Same path policy as file ops for a filesystem path string from search tools."""
    pc = path_candidate.strip()
    if not pc:
        return False
    if _looks_like_windows_abs_path(pc):
        return is_path_allowed(pc, "wsl")
    if pc.startswith("/") or pc.startswith("\\"):
        return is_path_allowed(pc, "wsl")
    return is_path_allowed(pc, "auto")


_GREP_LINE_RE = re.compile(r"^(.+?):(\d+):(.*)$", re.DOTALL)


def _grep_line_file_path(grep_line: str) -> Optional[str]:
    m = _GREP_LINE_RE.match(grep_line)
    return m.group(1) if m else None


def _system_locator_line_kept(line: str) -> bool:
    if not _allowlist_filters_search_results():
        return True
    s = line.strip()
    if not s:
        return False
    if s.startswith("["):
        return True
    return _path_allowed_for_search_result(s)


def _wsl_prefixed_grep_line_kept(prefixed_line: str) -> bool:
    if not _allowlist_filters_search_results():
        return True
    if not prefixed_line.startswith("WSL: "):
        return True
    rest = prefixed_line[5:].strip()
    path_g = _grep_line_file_path(rest)
    if path_g is None:
        return False
    return _path_allowed_for_search_result(path_g)


def _anytxt_result_line_kept(line: str) -> bool:
    if not _allowlist_filters_search_results():
        return True
    if not line.startswith("Windows: "):
        return True
    rest = line[len("Windows: ") :]
    path_part = rest.split(" | Snippet: ", 1)[0].strip()
    if not path_part:
        return False
    return _path_allowed_for_search_result(path_part)

def _clamp_int(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def _canonical_path(path: str) -> str:
    try:
        return os.path.realpath(path)
    except OSError:
        return os.path.normpath(path)


def _looks_like_windows_abs_path(path: str) -> bool:
    low = path.lower()
    return low.startswith("c:\\") or low.startswith("c:/")


def _auto_target_env(path: str) -> str:
    """Pick wslpath direction: Windows-looking paths -> wsl; Unix/WSL paths -> windows."""
    if _looks_like_windows_abs_path(path):
        return "wsl"
    if path.startswith("/mnt/") or (path.startswith("/") and not path.startswith("//")):
        return "windows"
    return "wsl"


def resolve_path(path: str, target_env: str) -> str:
    """Translates file paths between WSL and Windows environments."""
    if not path:
        return ""
    env = _auto_target_env(path) if target_env == "auto" else target_env
    if env == "wsl" and _looks_like_windows_abs_path(path):
        try:
            result = subprocess.run(["wslpath", "-u", path], capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            pass
    elif env == "windows" and (path.startswith("/mnt/") or path.startswith("/")):
        try:
            result = subprocess.run(["wslpath", "-w", path], capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            pass
    return path


def is_path_allowed(path: str, target_env: str) -> bool:
    """
    True if path may be used for read/write/map/search roots.
    Uses realpath; optional allowlist (config + BRIDGE_SEARCH_ALLOWED_PREFIXES); denylist from config path_denylist.
    """
    if not path or not str(path).strip():
        return False
    resolved = resolve_path(path.strip(), target_env)
    canonical = _canonical_path(resolved)
    cl = canonical.lower()

    allowed = _allowed_prefixes_merged()
    if allowed is not None:
        ok = False
        for prefix in allowed:
            pl = prefix.lower().rstrip(os.sep)
            if not pl:
                continue
            if cl == pl or cl.startswith(pl + os.sep):
                ok = True
                break
        if not ok:
            return False

    for p in _restricted_prefixes():
        pl = p.rstrip(os.sep).lower()
        if cl == pl or cl.startswith(pl + os.sep):
            return False
    return True


def is_binary_file(filepath: str) -> bool:
    """Heuristic check to prevent UTF-8 crashes on binary files."""
    try:
        with open(filepath, "rt") as check_file:
            check_file.read(1024)
            return False
    except UnicodeDecodeError:
        return True
    except OSError:
        return False


def execute_shell(cmd: List[str]) -> Tuple[bool, str]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True, result.stdout.strip()
    except subprocess.CalledProcessError as error:
        return False, error.stderr.strip()


def decode_windows_output(raw: bytes) -> str:
    for encoding in ("utf-8", "cp1252", "utf-16le"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def resolve_es_exe() -> Optional[str]:
    candidates = [
        "/mnt/c/Program Files/Everything/es.exe",
        "/mnt/c/Program Files (x86)/Everything/es.exe",
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate

    cmd_exe = "/mnt/c/Windows/System32/cmd.exe"
    if os.path.exists(cmd_exe):
        try:
            result = subprocess.run([cmd_exe, "/c", "where", "es.exe"], capture_output=True)
            output = decode_windows_output(result.stdout)
            for line in output.splitlines():
                if line.strip().lower().endswith("es.exe"):
                    wsl = resolve_path(line.strip(), "wsl")
                    if wsl and os.path.exists(wsl):
                        return wsl
        except OSError:
            pass

    return None


def hybrid_file_io(
    action: str,
    source_path: str,
    destination_path: Optional[str] = None,
    content: Optional[str] = None,
    target_env: str = "wsl",
    overwrite: bool = False,
    is_confirmed: bool = False,
) -> Dict[str, Any]:
    """Hardened read/write/move operations with safety checks."""
    src = resolve_path(source_path, target_env)
    dst = resolve_path(destination_path, target_env) if destination_path else ""

    if action in ["read", "write", "copy", "move", "delete", "mkdir"]:
        if not is_path_allowed(source_path, target_env):
            return {"success": False, "error": "SECURITY VIOLATION: Access to protected path blocked."}
        if destination_path and action in ["copy", "move"] and not is_path_allowed(destination_path, target_env):
            return {"success": False, "error": "SECURITY VIOLATION: Access to protected path blocked."}

    sec = get_bridge_config().get("security", _DEFAULTS["security"])
    if action == "write" and not is_confirmed and sec.get("require_confirm_for_writes", True):
        return {
            "success": False,
            "error": "WRITE BLOCKED. Pass is_confirmed=True after reviewing the target path (create, append, or overwrite), or relax require_confirm_for_writes in config/bridge-search.config.json.",
        }

    if action == "delete" and not is_confirmed and sec.get("require_confirm_for_deletes", True):
        return {
            "success": False,
            "error": "DESTRUCTIVE ACTION BLOCKED. Pass is_confirmed=True to delete, or relax require_confirm_for_deletes in config/bridge-search.config.json.",
        }

    if action == "read":
        if not os.path.exists(src):
            return {"success": False, "error": "File not found"}
        if is_binary_file(src):
            return {"success": False, "error": "Cannot read binary file as text."}
        try:
            with open(src, "r", encoding="utf-8") as file_handle:
                return {"success": True, "data": file_handle.read()}
        except PermissionError:
            return {"success": False, "error": "Permission Denied (Errno 13). If on Windows, the file may be locked by another process."}

    elif action == "write":
        mode = "w" if overwrite else "a"
        try:
            with open(src, mode, encoding="utf-8", newline="") as file_handle:
                if content:
                    file_handle.write(content)
            return {"success": True, "message": "File written successfully"}
        except PermissionError:
            return {"success": False, "error": "Permission Denied. File is locked or requires elevated privileges."}

    elif action == "copy":
        if not dst:
            return {"success": False, "error": "Destination required"}
        success, output = execute_shell(["cp", "-r", src, dst])
        return {"success": success, "message": output if success else output}

    elif action == "move":
        if not dst:
            return {"success": False, "error": "Destination required"}
        success, output = execute_shell(["mv", src, dst])
        return {"success": success, "message": output if success else output}

    elif action == "mkdir":
        success, output = execute_shell(["mkdir", "-p", src])
        return {"success": success, "message": "Directory created" if success else output}

    elif action == "delete":
        success, output = execute_shell(["rm", "-rf", src])
        return {"success": success, "message": "Deleted" if success else output}

    return {"success": False, "error": "Invalid action"}


def catalog_directory(
    target_path: str,
    max_depth: int = 2,
    include_extensions: Optional[List[str]] = None,
    exclude_hidden: bool = True,
    target_env: str = "auto",
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """Paginated hierarchical directory mapping."""
    cap_depth = _lim("max_depth")
    cap_limit = _lim("max_limit")
    cap_offset = _lim("max_offset")
    cap_cat = _lim("max_catalog_lines")
    max_depth = _clamp_int(max_depth, 0, cap_depth)
    limit = _clamp_int(limit, 1, cap_limit)
    offset = _clamp_int(offset, 0, cap_offset)

    resolved_path = resolve_path(target_path, target_env)
    if not is_path_allowed(target_path, target_env):
        return {"success": False, "error": "SECURITY VIOLATION: Path not allowed for directory mapping."}
    if not os.path.isdir(resolved_path):
        return {"success": False, "error": "Directory not found."}

    if include_extensions:
        include_extensions = [ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in include_extensions]

    catalog_output: List[str] = []
    base_level = resolved_path.rstrip(os.sep).count(os.sep)
    truncated = False

    try:
        for root, dirs, files in os.walk(resolved_path):
            if len(catalog_output) >= cap_cat:
                truncated = True
                break
            current_level = root.count(os.sep)
            depth = current_level - base_level
            if depth > max_depth:
                dirs[:] = []
                continue
            if exclude_hidden:
                dirs[:] = [d for d in dirs if not d.startswith(".")]

            indent = "  " * depth
            folder_name = os.path.basename(root) or root
            catalog_output.append(f"{indent}📂 {folder_name}/")

            for file in files:
                if len(catalog_output) >= cap_cat:
                    truncated = True
                    break
                if exclude_hidden and file.startswith("."):
                    continue
                if include_extensions:
                    _, ext = os.path.splitext(file)
                    if ext.lower() not in include_extensions:
                        continue
                catalog_output.append(f"{indent}  📄 {file}")

        total_items = len(catalog_output)
        paginated_output = catalog_output[offset : offset + limit]

        meta: Dict[str, Any] = {
            "total_found": total_items,
            "showing": f"{offset} to {min(offset + limit, total_items)}",
            "has_more": offset + limit < total_items,
        }
        if truncated:
            meta["truncated"] = True
            meta["note"] = f"Listing capped at {cap_cat} lines; narrow the path or max_depth."

        return {"success": True, "data": "\n".join(paginated_output), "meta": meta}
    except OSError as e:
        return {"success": False, "error": str(e)}


def _wsl_locator_full_root_allowed() -> bool:
    sec = get_bridge_config().get("security", _DEFAULTS["security"])
    if bool(sec.get("allow_wsl_locator_from_filesystem_root", False)):
        return True
    return (
        os.environ.get("BRIDGE_SEARCH_ALLOW_ROOT_LOCATOR", "").strip() == "1"
        or os.environ.get("WSL_WINDOWS_SEARCH_BRIDGE_ALLOW_ROOT_LOCATOR", "").strip() == "1"
        or os.environ.get("WSL_BRIDGE_ALLOW_ROOT_LOCATOR", "").strip() == "1"
    )


def _wsl_filename_find_root() -> str:
    if _wsl_locator_full_root_allowed():
        return "/"
    return os.path.expanduser("~")


def _everything_search_arg(query: str, exact_match: bool) -> str:
    """Build Voidtools Everything CLI search string (partial match uses * wildcards)."""
    if exact_match:
        return query
    q = query.strip()
    if not q:
        return q
    if any(c in q for c in ("*", "?", '"')):
        return q
    return f"*{q}*"


def system_locator(
    query: str,
    target_env: str = "windows",
    exact_match: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """Paginated filename search: Everything on Windows; WSL uses find under HOME unless opted into full root."""
    cap_limit = _lim("max_limit")
    cap_offset = _lim("max_offset")
    cap_loc = _lim("max_locator_results")
    limit = _clamp_int(limit, 1, cap_limit)
    offset = _clamp_int(offset, 0, cap_offset)

    wants_win = target_env in ("windows", "everywhere")
    wants_wsl = target_env in ("wsl", "everywhere")
    run_everything = wants_win and _backend_enabled("everything")
    run_wsl_find = wants_wsl and _backend_enabled("wsl_find")
    if not run_everything and not run_wsl_find:
        return {
            "success": False,
            "message": "No filename search backend enabled for this target_env. "
            "Set backends.everything and/or backends.wsl_find in config/bridge-search.config.json, "
            "or BRIDGE_SEARCH_ENABLE_EVERYTHING / BRIDGE_SEARCH_ENABLE_WSL_FIND. "
            "Use target_env 'windows' for Everything-only, 'wsl' for WSL find-only, 'everywhere' for both.",
        }

    results: List[str] = []
    truncated = False

    def _append_lines(lines: List[str]) -> None:
        nonlocal truncated
        for line in lines:
            if len(results) >= cap_loc:
                truncated = True
                return
            if not _system_locator_line_kept(line):
                continue
            s = line.strip()
            if s:
                results.append(s)

    # Prefer Windows (Everything) first when searching both — matches skill workflow.
    if run_everything:
        try:
            es_exe = resolve_es_exe()
            if not es_exe:
                results.append("[Windows Error]: es.exe not found. Check Everything installation or Windows PATH.")
            else:
                win_arg = _everything_search_arg(query, exact_match)
                win_cmd = [es_exe, win_arg]
                process = subprocess.run(win_cmd, capture_output=True)
                if process.returncode == 0 and process.stdout:
                    output = decode_windows_output(process.stdout)
                    _append_lines(output.strip().split("\n"))
                elif process.stderr:
                    results.append(f"[Windows Error]: {decode_windows_output(process.stderr).strip()}")
        except OSError as e:
            results.append(f"[Windows Error]: {str(e)}")

    if run_wsl_find and len(results) < cap_loc:
        try:
            pattern = query if exact_match else f"*{query}*"
            search_root = _wsl_filename_find_root()
            if search_root == "/":
                wsl_cmd = ["find", "/", "-path", "/mnt", "-prune", "-o", "-iname", pattern, "-print"]
            else:
                wsl_cmd = ["find", search_root, "-iname", pattern, "-print"]
            process = subprocess.run(wsl_cmd, capture_output=True, text=True)
            if process.stdout:
                _append_lines(process.stdout.strip().split("\n"))
        except OSError as e:
            results.append(f"[WSL Error]: {str(e)}")

    if not results:
        return {"success": False, "message": "No files found."}

    total_items = len(results)
    paginated_results = results[offset : offset + limit]
    meta: Dict[str, Any] = {
        "total_found": total_items,
        "has_more": offset + limit < total_items,
        "filename_backends": {"everything": run_everything, "wsl_find": run_wsl_find},
    }
    if truncated or total_items >= cap_loc:
        meta["truncated"] = True
        meta["note"] = f"Combined results capped at {cap_loc} paths."
    if _allowlist_filters_search_results():
        meta["allowlist_filtered_search_results"] = True

    return {"success": True, "data": "\n".join(paginated_results), "meta": meta}


def _wsl_grep_root_allowed(wsl_search_path: str) -> Tuple[bool, str]:
    """Avoid grep-from-root unless explicitly opted in."""
    canon = _canonical_path(resolve_path(wsl_search_path, "wsl"))
    cfg_allow = bool(get_bridge_config().get("security", _DEFAULTS["security"]).get("allow_grep_from_filesystem_root", False))
    env_allow = (
        os.environ.get("BRIDGE_SEARCH_ALLOW_ROOT_GREP", "").strip() == "1"
        or os.environ.get("WSL_WINDOWS_SEARCH_BRIDGE_ALLOW_ROOT_GREP", "").strip() == "1"
        or os.environ.get("WSL_BRIDGE_ALLOW_ROOT_GREP", "").strip() == "1"
    )
    if canon.rstrip(os.sep) == "/" and not cfg_allow and not env_allow:
        return (
            False,
            "Refusing grep from '/'. Set allow_grep_from_filesystem_root in config/bridge-search.config.json, or BRIDGE_SEARCH_ALLOW_ROOT_GREP=1 (legacy: WSL_WINDOWS_SEARCH_BRIDGE_ALLOW_ROOT_GREP=1), or use a narrower wsl_search_path.",
        )
    if not is_path_allowed(wsl_search_path, "wsl"):
        return False, "SECURITY VIOLATION: Search root path not allowed."
    if not os.path.isdir(canon):
        return False, "wsl_search_path must be an existing directory."
    return True, canon


def content_locator(
    query: str,
    target_env: str = "everywhere",
    wsl_search_path: str = "",
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """Paginated deep content search. Empty wsl_search_path defaults to the invoking user's HOME."""
    cap_limit = _lim("max_limit")
    cap_offset = _lim("max_offset")
    cap_loc = _lim("max_locator_results")
    cap_anytxt = _lim("anytxt_max_response_bytes")
    limit = _clamp_int(limit, 1, cap_limit)
    offset = _clamp_int(offset, 0, cap_offset)

    eff_root = wsl_search_path.strip() or os.path.expanduser("~")

    wants_wsl_grep = target_env in ("wsl", "everywhere")
    wants_anytxt = target_env in ("windows", "everywhere")
    run_wsl_grep = wants_wsl_grep and _backend_enabled("wsl_grep")
    run_anytxt_http = wants_anytxt and _backend_enabled("anytxt")
    if not run_wsl_grep and not run_anytxt_http:
        return {
            "success": False,
            "message": "No content-search backend enabled for this target_env. "
            "Set backends.wsl_grep and/or backends.anytxt in config/bridge-search.config.json, "
            "or BRIDGE_SEARCH_ENABLE_WSL_GREP / BRIDGE_SEARCH_ENABLE_ANYTXT. "
            "Use target_env 'windows' for AnyTXT-only, 'wsl' for WSL grep-only, 'everywhere' for both.",
        }

    results: List[str] = []
    if run_wsl_grep:
        try:
            ok, msg_or_canon = _wsl_grep_root_allowed(eff_root)
            if not ok:
                results.append(f"[WSL Grep Error]: {msg_or_canon}")
            else:
                search_root = msg_or_canon
                wsl_cmd = [
                    "grep",
                    "-rni",
                    "-m",
                    "2",
                    "--exclude-dir=/mnt",
                    "-F",
                    "-e",
                    query,
                    "--",
                    search_root,
                ]
                process = subprocess.run(wsl_cmd, capture_output=True, text=True)
                if process.stdout:
                    for line in process.stdout.strip().split("\n"):
                        if len(results) >= cap_loc:
                            break
                        prefixed = f"WSL: {line}"
                        if _wsl_prefixed_grep_line_kept(prefixed):
                            results.append(prefixed)
        except OSError as e:
            results.append(f"[WSL Grep Error]: {str(e)}")

    if run_anytxt_http:
        try:
            url = f"http://127.0.0.1:9921/search?q={urllib.parse.quote(query)}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    raw = response.read(cap_anytxt + 1)
                    if len(raw) > cap_anytxt:
                        results.append(
                            f"[AnyTXT API Error]: Response exceeded {cap_anytxt} bytes; raise anytxt_max_response_bytes in config/bridge-search.config.json if needed."
                        )
                    else:
                        data = json.loads(raw.decode("utf-8"))
                        for item in data.get("results", []):
                            if len(results) >= cap_loc:
                                break
                            row = f"Windows: {item.get('path', '')} | Snippet: {item.get('snippet', '')}"
                            if _anytxt_result_line_kept(row):
                                results.append(row)
        except OSError as e:
            results.append(f"[AnyTXT API Error]: {str(e)}")
        except json.JSONDecodeError as e:
            results.append(f"[AnyTXT API Error]: Invalid JSON ({e})")

    if not results:
        return {"success": False, "message": "No content found."}

    total_items = len(results)
    meta: Dict[str, Any] = {
        "total_found": total_items,
        "has_more": offset + limit < total_items,
        "content_backends": {"wsl_grep": run_wsl_grep, "anytxt": run_anytxt_http},
    }
    if total_items >= cap_loc:
        meta["truncated"] = True
        meta["note"] = f"Results capped at {cap_loc} lines."
    if _allowlist_filters_search_results():
        meta["allowlist_filtered_search_results"] = True

    return {"success": True, "data": "\n".join(results[offset : offset + limit]), "meta": meta}
