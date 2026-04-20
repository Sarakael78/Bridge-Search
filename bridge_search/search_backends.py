from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from .config import anytxt_search_url, backend_enabled, clamp_int, command_timeout_seconds, get_bridge_config, get_wsl_host_ip, lim
from .constants import ErrorCodes
from .path_policy import allowlist_filters_search_results, canonical_path, is_path_allowed, looks_like_windows_abs_path, path_allowed_for_search_result, resolve_path
from .result_models import error_response, make_issue, success_response

_GREP_LINE_RE = re.compile(r"^(.+?):(\d+):(.*)$", re.DOTALL)
_EVERYTHING_HELP_CACHE: Optional[str] = None
_CACHE_LOCK = threading.Lock()
_WSL_LOCATE_REFRESH_LOCK = threading.Lock()
_WSL_LOCATE_REFRESH_IN_FLIGHT: set[str] = set()


def get_effective_anytxt_urls() -> List[str]:
    """Return a list of URLs to try for AnyTXT, with WSL2 host IP fallback if localhost is configured."""
    primary = anytxt_search_url()
    urls = [primary]
    parsed = urllib.parse.urlparse(primary)
    if parsed.hostname in ("127.0.0.1", "localhost"):
        host_ip = get_wsl_host_ip()
        if host_ip and host_ip != "127.0.0.1":
            # Attempt to rebuild URL with the host IP. 
            # If no port is in primary, it might be 9921 or 80 depending on scheme.
            netloc = f"{host_ip}:{parsed.port}" if parsed.port else host_ip
            fallback = urllib.parse.urlunparse(parsed._replace(netloc=netloc))
            if fallback not in urls:
                urls.append(fallback)
    return urls


def _subprocess_timeout() -> float:
    return command_timeout_seconds()


def _normalized_query(query: str) -> str:
    return (query or "").strip()


def _query_required_response(*, source: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    return error_response(
        code=ErrorCodes.QUERY_REQUIRED,
        message="Query must not be blank.",
        source=source,
        meta=meta,
    )


def _wsl_grep_command(query: str, root: str) -> List[str]:
    # -m 2: limit to 2 matches per file to keep results concise and fast
    cmd = ["grep", "-rni", "-m", "2"]
    # grep matches --exclude-dir against basenames, so use `mnt` when searching from `/`.
    if canonical_path(root) == "/":
        cmd.append("--exclude-dir=mnt")
    cmd.extend(["-F", "-e", query, "--", root])
    return cmd


def _is_timeout_error(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, TimeoutError):
            return True
        return "timed out" in str(reason).lower()
    return "timed out" in str(exc).lower()


def grep_line_file_path(grep_line: str) -> Optional[str]:
    """Extract the file path from a standard grep result line."""
    m = _GREP_LINE_RE.match(grep_line)
    return m.group(1) if m else None


def decode_windows_output(raw: bytes) -> str:
    """Decode Windows CLI output with pragmatic fallback encodings."""
    for encoding in ("utf-8", "cp1252", "utf-16le"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


_ES_EXE_CACHE: Optional[str] = None


def resolve_es_exe() -> Optional[str]:
    """Locate Everything's `es.exe` from standard paths or Windows PATH.

    The entire resolution runs under ``_CACHE_LOCK`` to prevent redundant
    subprocess spawns from concurrent threads.
    """
    global _ES_EXE_CACHE
    with _CACHE_LOCK:
        if _ES_EXE_CACHE is not None and os.path.exists(_ES_EXE_CACHE):
            return _ES_EXE_CACHE
        _ES_EXE_CACHE = None
        candidates = [
            "/mnt/c/Program Files/Everything/es.exe",
            "/mnt/c/Program Files (x86)/Everything/es.exe",
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                _ES_EXE_CACHE = candidate
                return candidate
        cmd_exe = "/mnt/c/Windows/System32/cmd.exe"
        if os.path.exists(cmd_exe):
            try:
                result = subprocess.run([cmd_exe, "/c", "where", "es.exe"], capture_output=True, timeout=_subprocess_timeout())
                output = decode_windows_output(result.stdout)
                for line in output.splitlines():
                    if line.strip().lower().endswith("es.exe"):
                        wsl = resolve_path(line.strip(), "wsl")
                        if wsl and os.path.exists(wsl):
                            _ES_EXE_CACHE = wsl
                            return wsl
            except (OSError, subprocess.TimeoutExpired):
                pass
        return None


def everything_help_text(force_reload: bool = False) -> str:
    global _EVERYTHING_HELP_CACHE
    with _CACHE_LOCK:
        if _EVERYTHING_HELP_CACHE is not None and not force_reload:
            return _EVERYTHING_HELP_CACHE
        es_exe = resolve_es_exe()
        if not es_exe:
            _EVERYTHING_HELP_CACHE = ""
            return ""
        try:
            result = subprocess.run(
                [es_exe, "-help"],
                capture_output=True,
                timeout=_subprocess_timeout(),
            )
        except (OSError, subprocess.TimeoutExpired):
            _EVERYTHING_HELP_CACHE = ""
            return ""
        payload = result.stdout or result.stderr or b""
        text = decode_windows_output(payload)
        _EVERYTHING_HELP_CACHE = text
        return text


def everything_supports_native_paging() -> bool:
    help_text = everything_help_text()
    return "-viewport-offset" in help_text and "-viewport-count" in help_text


def _everything_command(
    es_exe: str,
    query: str,
    exact_match: bool,
    limit: int,
    offset: int,
    *,
    allow_native_paging: bool,
) -> Tuple[List[str], bool]:
    supports_paging = allow_native_paging and everything_supports_native_paging()
    cmd = [es_exe]
    if supports_paging:
        cmd.extend(["-json", "-full-path-and-name", "-viewport-offset", str(offset), "-viewport-count", str(limit + 1)])
    cmd.append(_everything_search_arg(query, exact_match))
    return cmd, supports_paging


def _parse_everything_results(raw: bytes, *, native_paging: bool) -> List[str]:
    if not raw:
        return []
    output = decode_windows_output(raw)
    if not native_paging:
        return [line.strip() for line in output.strip().splitlines() if line.strip()]
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return []
    rows: List[str] = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            filename = str(item.get("filename", "")).strip()
            if filename:
                rows.append(filename)
    return rows


def _everything_search_arg(query: str, exact_match: bool) -> str:
    if exact_match:
        return query
    q = query.strip()
    if not q:
        return q
    if any(c in q for c in ("*", "?", '"')):
        return q
    return f"*{q}*"


def _escape_find_glob(query: str) -> str:
    """Escape characters that ``find -iname`` interprets as glob metacharacters."""
    for ch in ("\\", "[", "]"):
        query = query.replace(ch, f"\\{ch}")
    return query


def _wsl_locator_full_root_allowed() -> bool:
    sec = get_bridge_config().get("security", {})
    if bool(sec.get("allow_wsl_locator_from_filesystem_root", False)):
        return True
    return os.environ.get("BRIDGE_SEARCH_ALLOW_ROOT_LOCATOR", "").strip() == "1"


def _wsl_filename_find_root() -> str:
    return "/" if _wsl_locator_full_root_allowed() else os.path.expanduser("~")


def _wsl_locate_db_path() -> str:
    override = os.environ.get("BRIDGE_SEARCH_LOCATE_DB_PATH", "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))
    return os.path.join(os.path.expanduser("~"), ".cache", "bridge-search", "wsl-locate.db")


def _parse_locate_db_header(header_line: str) -> Tuple[float, str]:
    ts = 0.0
    root = ""
    # Use partition to handle spaces in root path correctly
    if "generated_at=" in header_line:
        ts_part = header_line.partition("generated_at=")[2].split(None, 1)[0]
        try:
            ts = float(ts_part)
        except ValueError:
            ts = 0.0
    if "root=" in header_line:
        root = header_line.partition("root=")[2].strip()
    return ts, root


def _wsl_locate_db_is_stale(db_path: str, search_root: str, max_age_seconds: float = 86400.0) -> bool:
    if not os.path.isfile(db_path):
        return True
    try:
        with open(db_path, "r", encoding="utf-8") as handle:
            header = handle.readline()
    except OSError:
        return True
    if not header.startswith("# "):
        return True
    generated_at, indexed_root = _parse_locate_db_header(header[2:])
    if generated_at <= 0:
        return True
    if canonical_path(indexed_root or "") != canonical_path(search_root):
        return True
    return (time.time() - generated_at) >= max_age_seconds


def _build_wsl_locate_db(db_path: str, search_root: str) -> None:
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    tmp_path = f"{db_path}.tmp"
    root_is_fs = canonical_path(search_root) == "/"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(f"# generated_at={time.time()} root={search_root}\n")
        for current_root, dirs, files in os.walk(search_root, onerror=lambda _err: None):
            if root_is_fs:
                dirs[:] = [d for d in dirs if d not in ("mnt", "proc", "sys", "dev", "run")]
            if path_allowed_for_search_result(current_root):
                handle.write(f"{current_root}\n")
            for name in files:
                full_path = os.path.join(current_root, name)
                if path_allowed_for_search_result(full_path):
                    handle.write(f"{full_path}\n")
    os.replace(tmp_path, db_path)


def _schedule_wsl_locate_refresh(db_path: str, search_root: str) -> bool:
    """Schedule a non-blocking locate DB refresh; returns True when a new job starts."""
    with _WSL_LOCATE_REFRESH_LOCK:
        if db_path in _WSL_LOCATE_REFRESH_IN_FLIGHT:
            return False
        _WSL_LOCATE_REFRESH_IN_FLIGHT.add(db_path)

    def _worker() -> None:
        try:
            _build_wsl_locate_db(db_path, search_root)
        except OSError:
            # Best-effort async refresh; query path should continue with stale data.
            pass
        finally:
            with _WSL_LOCATE_REFRESH_LOCK:
                _WSL_LOCATE_REFRESH_IN_FLIGHT.discard(db_path)

    t = threading.Thread(
        target=_worker,
        name="bridge-search-wsl-locate-refresh",
        daemon=True,
    )
    t.start()
    return True


def _wsl_locate_search(
    query: str,
    search_root: str,
    exact_match: bool,
    page_cap: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], bool, bool]:
    l_results: List[Dict[str, Any]] = []
    l_errors: List[Dict[str, Any]] = []
    l_warnings: List[Dict[str, Any]] = []
    truncated = False
    refresh_scheduled = False
    db_path = _wsl_locate_db_path()
    stale = _wsl_locate_db_is_stale(db_path, search_root)
    if stale:
        started = _schedule_wsl_locate_refresh(db_path, search_root)
        with _WSL_LOCATE_REFRESH_LOCK:
            refresh_scheduled = db_path in _WSL_LOCATE_REFRESH_IN_FLIGHT
        if started:
            l_warnings.append(
                make_issue(
                    code=ErrorCodes.BACKEND_UNAVAILABLE,
                    message="WSL locate database is stale or missing; background refresh scheduled. Serving cached results when available.",
                    source="wsl-locate",
                )
            )

    needle = query.lower()
    if not os.path.isfile(db_path):
        return l_results, l_errors, l_warnings, truncated, refresh_scheduled

    try:
        with open(db_path, "r", encoding="utf-8") as handle:
            # Skip metadata header line.
            handle.readline()
            for raw in handle:
                if len(l_results) >= page_cap:
                    truncated = True
                    break
                path = raw.strip()
                if not path or not path_allowed_for_search_result(path):
                    continue
                name = os.path.basename(path)
                matched = name.lower() == needle if exact_match else needle in path.lower()
                if not matched:
                    continue
                l_results.append(
                    {
                        "type": "search_hit",
                        "path": path,
                        "raw_path": path,
                        "source": "wsl-locate",
                    }
                )
    except OSError as exc:
        issue = make_issue(
            code=ErrorCodes.BACKEND_UNAVAILABLE if stale else ErrorCodes.BACKEND_ERROR,
            message=f"WSL locate database read failed: {exc}",
            source="wsl-locate",
        )
        if stale:
            l_warnings.append(issue)
        else:
            l_errors.append(issue)
            return l_results, l_errors, l_warnings, truncated, refresh_scheduled

    return l_results, l_errors, l_warnings, truncated, refresh_scheduled


def _wsl_grep_root_allowed(wsl_search_path: str) -> Tuple[bool, str]:
    canon = canonical_path(resolve_path(wsl_search_path, "wsl"))
    cfg_allow = bool(get_bridge_config().get("security", {}).get("allow_grep_from_filesystem_root", False))
    env_allow = os.environ.get("BRIDGE_SEARCH_ALLOW_ROOT_GREP", "").strip() == "1"
    if canon.rstrip(os.sep) == "/" and not cfg_allow and not env_allow:
        return False, "Refusing grep from '/'. Set allow_grep_from_filesystem_root in config/bridge-search.config.json, or BRIDGE_SEARCH_ALLOW_ROOT_GREP=1, or use a narrower wsl_search_path."
    if not is_path_allowed(wsl_search_path, "wsl"):
        return False, "Search root path not allowed."
    if not os.path.isdir(canon):
        return False, "wsl_search_path must be an existing directory."
    return True, canon


def system_locator(query: str, target_env: str = "windows", exact_match: bool = False, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    """Search for files and folders via Everything and optional WSL find backends."""
    cap_limit = lim("max_limit")
    cap_offset = lim("max_offset")
    cap_loc = lim("max_locator_results")
    limit = clamp_int(limit, 1, cap_limit)
    offset = clamp_int(offset, 0, cap_offset)
    page_cap = min(cap_loc, offset + limit + 1)
    wants_win = target_env in ("windows", "everywhere")
    wants_wsl = target_env in ("wsl", "everywhere")
    run_everything = wants_win and backend_enabled("everything")
    run_wsl_locate = wants_wsl and backend_enabled("wsl_locate")
    run_wsl_find = wants_wsl and backend_enabled("wsl_find")
    meta: Dict[str, Any] = {
        "filename_backends": {
            "everything": run_everything,
            "wsl_locate": run_wsl_locate,
            "wsl_find": run_wsl_find,
        },
        "offset": offset,
        "limit": limit,
    }
    if run_wsl_locate:
        meta["wsl_locate_refresh_scheduled"] = False
    query = _normalized_query(query)
    if not query:
        return _query_required_response(source="locator", meta=meta)
    if not run_everything and not run_wsl_locate and not run_wsl_find:
        return error_response(code=ErrorCodes.BACKEND_DISABLED, message="No filename search backend enabled for this target_env.", source="locator", meta=meta)
    results: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    truncated = False

    def append_result(item: Dict[str, Any]) -> None:
        nonlocal truncated
        if len(results) >= page_cap:
            truncated = True
            return
        results.append(item)

    def everything_worker() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], bool, bool]:
        e_results: List[Dict[str, Any]] = []
        e_errors: List[Dict[str, Any]] = []
        e_warnings: List[Dict[str, Any]] = []
        e_truncated = False
        native_paging = False
        try:
            es_exe = resolve_es_exe()
            if not es_exe:
                e_errors.append(make_issue(code=ErrorCodes.BACKEND_UNAVAILABLE, message="es.exe not found. Check Everything installation or Windows PATH.", source="windows-everything"))
            else:
                cmd, native_paging = _everything_command(
                    es_exe,
                    query,
                    exact_match,
                    limit,
                    offset,
                    allow_native_paging=not run_wsl_find,
                )
                process = subprocess.run(cmd, capture_output=True, timeout=_subprocess_timeout())
                if process.returncode == 0 and process.stdout:
                    lines = _parse_everything_results(process.stdout, native_paging=native_paging)
                    for line in lines:
                        if len(e_results) >= page_cap:
                            e_truncated = True
                            break
                        raw_path = line.strip()
                        if not raw_path:
                            continue
                        mapped = resolve_path(raw_path, "wsl") if looks_like_windows_abs_path(raw_path) else raw_path
                        if not path_allowed_for_search_result(mapped):
                            continue
                        if mapped == raw_path and looks_like_windows_abs_path(raw_path):
                            e_warnings.append(make_issue(code=ErrorCodes.PATH_TRANSLATION_FAILED, message=f"Could not translate Windows path to WSL form: {raw_path}", source="windows-everything", path=raw_path))
                        e_results.append({"type": "search_hit", "path": mapped, "raw_path": raw_path, "source": "windows-everything"})
                        if native_paging and len(e_results) >= limit + 1:
                            break
                elif process.stderr:
                    e_errors.append(make_issue(code=ErrorCodes.BACKEND_ERROR, message=decode_windows_output(process.stderr).strip(), source="windows-everything"))
        except subprocess.TimeoutExpired:
            e_errors.append(make_issue(code=ErrorCodes.BACKEND_TIMEOUT, message="Everything query timed out.", source="windows-everything"))
        except OSError as exc:
            e_errors.append(make_issue(code=ErrorCodes.BACKEND_ERROR, message=str(exc), source="windows-everything"))
        return e_results, e_errors, e_warnings, e_truncated, native_paging

    def wsl_find_worker() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], bool]:
        f_results: List[Dict[str, Any]] = []
        f_errors: List[Dict[str, Any]] = []
        f_warnings: List[Dict[str, Any]] = []
        f_truncated = False
        try:
            escaped = _escape_find_glob(query)
            pattern = escaped if exact_match else f"*{escaped}*"
            search_root = _wsl_filename_find_root()
            cmd = ["find", "/", "-path", "/mnt", "-prune", "-o", "-iname", pattern, "-print"] if search_root == "/" else ["find", search_root, "-iname", pattern, "-print"]
            process = subprocess.run(cmd, capture_output=True, text=True, timeout=_subprocess_timeout())
            if process.stdout:
                for line in process.stdout.strip().split("\n"):
                    if len(f_results) >= page_cap:
                        f_truncated = True
                        break
                    path = line.strip()
                    if not path or not path_allowed_for_search_result(path):
                        continue
                    f_results.append({"type": "search_hit", "path": path, "raw_path": path, "source": "wsl-find"})
            if process.returncode not in (0, 1) and process.stderr:
                f_errors.append(make_issue(code=ErrorCodes.BACKEND_ERROR, message=process.stderr.strip(), source="wsl-find"))
        except subprocess.TimeoutExpired:
            f_errors.append(make_issue(code=ErrorCodes.BACKEND_TIMEOUT, message="WSL find query timed out.", source="wsl-find"))
        except OSError as exc:
            f_errors.append(make_issue(code=ErrorCodes.BACKEND_ERROR, message=str(exc), source="wsl-find"))
        return f_results, f_errors, f_warnings, f_truncated

    with ThreadPoolExecutor(max_workers=3) as executor:
        e_future = executor.submit(everything_worker) if run_everything else None
        l_future = None
        if run_wsl_locate:
            search_root = _wsl_filename_find_root()
            l_future = executor.submit(_wsl_locate_search, query, search_root, exact_match, page_cap)
        f_future = executor.submit(wsl_find_worker) if run_wsl_find else None

        if e_future:
            e_results, e_errors, e_warnings, e_truncated, native_paging = e_future.result()
            meta["everything_native_paging"] = native_paging
            errors.extend(e_errors)
            warnings.extend(e_warnings)
            for r in e_results:
                append_result(r)
            if e_truncated:
                truncated = True

        if l_future and not truncated and len(results) < page_cap:
            l_results, l_errors, l_warnings, l_truncated, l_refresh_scheduled = l_future.result()
            errors.extend(l_errors)
            warnings.extend(l_warnings)
            if l_refresh_scheduled:
                meta["wsl_locate_refresh_scheduled"] = True
            for r in l_results:
                append_result(r)
            if l_truncated:
                truncated = True

        if f_future and not truncated and len(results) < page_cap:
            f_results, f_errors, f_warnings, f_truncated = f_future.result()
            # If we already have results but wsl_find timed out, demote the error to a warning
            if results and any(e["code"] == ErrorCodes.BACKEND_TIMEOUT for e in f_errors):
                for e in f_errors:
                    if e["code"] == ErrorCodes.BACKEND_TIMEOUT:
                        warnings.append(make_issue(code=ErrorCodes.BACKEND_TIMEOUT_PARTIAL, message=f"WSL find timed out, results may be incomplete. {e['message']}", source="wsl-find"))
                    else:
                        errors.append(e)
            else:
                errors.extend(f_errors)
            
            warnings.extend(f_warnings)
            for r in f_results:
                append_result(r)
            if f_truncated:
                truncated = True

    # Deduplicate results (Everything + WSL find can return the same path)
    deduped_results: List[Dict[str, Any]] = []
    seen_paths: Dict[str, str] = {}
    duplicates_skipped = 0
    for row in results:
        norm = canonical_path(row["path"])
        seen_source = seen_paths.get(norm)
        if seen_source is not None and seen_source != row.get("source"):
            duplicates_skipped += 1
            continue
        seen_paths.setdefault(norm, row.get("source", ""))
        deduped_results.append(row)
    results = deduped_results
    if duplicates_skipped:
        meta["duplicate_hits_ignored"] = duplicates_skipped

    meta["has_more"] = len(results) > limit if meta.get("everything_native_paging") else len(results) > offset + limit
    if truncated or meta.get("everything_native_paging"):
        meta["total_found_is_lower_bound"] = True
    if truncated or len(results) >= cap_loc:
        meta["truncated"] = True
        meta["note"] = f"Combined results capped at {cap_loc} paths."
    if allowlist_filters_search_results():
        meta["allowlist_filtered_search_results"] = True
    page_results = results[:limit] if meta.get("everything_native_paging") else results[offset : offset + limit]
    if meta.get("everything_native_paging"):
        meta["total_found"] = offset + len(page_results)
        meta["returned_count"] = len(page_results)
        meta["total_found_exact"] = False
        meta["note"] = (
            meta.get("note", "") + (" " if meta.get("note") else "") +
            "Everything native paging reports a lower-bound total_found, not an exact total."
        )
    else:
        meta["total_found"] = len(results)
        meta["returned_count"] = len(page_results)
        meta["total_found_exact"] = not meta.get("total_found_is_lower_bound", False)
    return success_response(results=page_results, errors=errors, warnings=warnings, meta=meta)


def content_locator(query: str, target_env: str = "everywhere", wsl_search_path: str = "", limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    """Search file contents via AnyTXT and optional WSL grep backends."""
    cap_limit = lim("max_limit")
    cap_offset = lim("max_offset")
    cap_loc = lim("max_locator_results")
    cap_anytxt = lim("anytxt_max_response_bytes")
    limit = clamp_int(limit, 1, cap_limit)
    offset = clamp_int(offset, 0, cap_offset)
    page_cap = min(cap_loc, offset + limit + 1)
    eff_root = wsl_search_path.strip() or os.path.expanduser("~")
    wants_wsl = target_env in ("wsl", "everywhere")
    wants_anytxt = target_env in ("windows", "everywhere")
    run_wsl = wants_wsl and backend_enabled("wsl_grep")
    run_anytxt = wants_anytxt and backend_enabled("anytxt")
    meta: Dict[str, Any] = {"content_backends": {"wsl_grep": run_wsl, "anytxt": run_anytxt}, "offset": offset, "limit": limit, "anytxt_url": anytxt_search_url() if run_anytxt else None}
    query = _normalized_query(query)
    if not query:
        return _query_required_response(source="content-locator", meta=meta)
    if not run_wsl and not run_anytxt:
        return error_response(code=ErrorCodes.BACKEND_DISABLED, message="No content-search backend enabled for this target_env.", source="content-locator", meta=meta)
    results: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    def anytxt_worker() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], str]:
        a_results: List[Dict[str, Any]] = []
        a_errors: List[Dict[str, Any]] = []
        a_warnings: List[Dict[str, Any]] = []
        used_url = ""
        last_err = None
        anytxt_ok = False
        effective_urls = get_effective_anytxt_urls()
        for url in effective_urls:
            try:
                sep = "&" if urllib.parse.urlparse(url).query else "?"
                req = urllib.request.Request(f"{url}{sep}q={urllib.parse.quote(query)}")
                with urllib.request.urlopen(req, timeout=_subprocess_timeout()) as response:  # nosec B310 (config-controlled local AnyTXT HTTP service)
                    if response.status == 200:
                        raw = response.read(cap_anytxt + 1)
                        if len(raw) > cap_anytxt:
                            a_errors.append(make_issue(code=ErrorCodes.RESPONSE_TOO_LARGE, message=f"Response exceeded {cap_anytxt} bytes; raise anytxt_max_response_bytes if needed.", source="windows-anytxt"))
                        else:
                            data = json.loads(raw.decode("utf-8"))
                            if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                                a_errors.append(make_issue(code=ErrorCodes.INVALID_RESPONSE, message="AnyTXT response has unexpected structure (expected {\"results\": [...]})", source="windows-anytxt"))
                                continue
                            for item in data.get("results", []):
                                if len(a_results) >= cap_loc:
                                    break
                                raw_path = str(item.get("path", "")).strip()
                                if not raw_path:
                                    continue
                                mapped = resolve_path(raw_path, "wsl") if looks_like_windows_abs_path(raw_path) else raw_path
                                if not path_allowed_for_search_result(mapped):
                                    continue
                                if mapped == raw_path and looks_like_windows_abs_path(raw_path):
                                    a_warnings.append(make_issue(code=ErrorCodes.PATH_TRANSLATION_FAILED, message=f"Could not translate Windows path to WSL form: {raw_path}", source="windows-anytxt", path=raw_path))
                                a_results.append({"type": "content_hit", "path": mapped, "raw_path": raw_path, "snippet": item.get("snippet", ""), "source": "windows-anytxt"})
                        used_url = url
                        anytxt_ok = True
                        break
            except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
                last_err = exc
                continue
        
        if not anytxt_ok and last_err:
            if isinstance(last_err, json.JSONDecodeError):
                a_errors.append(make_issue(code=ErrorCodes.INVALID_RESPONSE, message=f"Invalid JSON ({last_err})", source="windows-anytxt"))
            elif _is_timeout_error(last_err):
                a_errors.append(make_issue(code=ErrorCodes.BACKEND_TIMEOUT, message="AnyTXT query timed out.", source="windows-anytxt"))
            else:
                a_errors.append(make_issue(code=ErrorCodes.BACKEND_ERROR, message=str(last_err), source="windows-anytxt"))
        return a_results, a_errors, a_warnings, used_url

    def wsl_grep_worker() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        g_results: List[Dict[str, Any]] = []
        g_errors: List[Dict[str, Any]] = []
        g_warnings: List[Dict[str, Any]] = []
        try:
            ok, root = _wsl_grep_root_allowed(eff_root)
            if not ok:
                g_errors.append(make_issue(code=ErrorCodes.SEARCH_ROOT_BLOCKED, message=root, source="wsl-grep", path=eff_root))
            else:
                cmd = _wsl_grep_command(query, root)
                process = subprocess.run(cmd, capture_output=True, text=True, timeout=_subprocess_timeout())
                if process.stdout:
                    for line in process.stdout.strip().split("\n"):
                        if len(g_results) >= cap_loc:
                            break
                        path_g = grep_line_file_path(line)
                        match = _GREP_LINE_RE.match(line)
                        if path_g is None or match is None or not path_allowed_for_search_result(path_g):
                            continue
                        g_results.append({"type": "content_hit", "path": path_g, "raw_path": path_g, "line_number": int(match.group(2)), "snippet": match.group(3), "source": "wsl-grep"})
                if process.returncode not in (0, 1) and process.stderr:
                    g_errors.append(make_issue(code=ErrorCodes.BACKEND_ERROR, message=process.stderr.strip(), source="wsl-grep"))
        except subprocess.TimeoutExpired:
            g_errors.append(make_issue(code=ErrorCodes.BACKEND_TIMEOUT, message="WSL grep query timed out.", source="wsl-grep"))
        except OSError as exc:
            g_errors.append(make_issue(code=ErrorCodes.BACKEND_ERROR, message=str(exc), source="wsl-grep"))
        return g_results, g_errors, g_warnings

    with ThreadPoolExecutor(max_workers=2) as executor:
        a_future = executor.submit(anytxt_worker) if run_anytxt else None
        g_future = executor.submit(wsl_grep_worker) if run_wsl else None

        if a_future:
            a_results, a_errors, a_warnings, used_url = a_future.result()
            results.extend(a_results)
            if results and any(e["code"] == ErrorCodes.BACKEND_TIMEOUT for e in a_errors):
                for e in a_errors:
                    if e["code"] == ErrorCodes.BACKEND_TIMEOUT:
                        warnings.append(make_issue(code=ErrorCodes.BACKEND_TIMEOUT_PARTIAL, message=f"AnyTXT timed out, results may be incomplete. {e['message']}", source="windows-anytxt"))
                    else:
                        errors.append(e)
            else:
                errors.extend(a_errors)
            
            warnings.extend(a_warnings)
            if used_url:
                meta["anytxt_url_used"] = used_url

        if g_future and len(results) < page_cap:
            g_results, g_errors, g_warnings = g_future.result()
            if results and any(e["code"] == ErrorCodes.BACKEND_TIMEOUT for e in g_errors):
                for e in g_errors:
                    if e["code"] == ErrorCodes.BACKEND_TIMEOUT:
                        warnings.append(make_issue(code=ErrorCodes.BACKEND_TIMEOUT_PARTIAL, message=f"WSL grep timed out, results may be incomplete. {e['message']}", source="wsl-grep"))
                    else:
                        errors.append(e)
            else:
                errors.extend(g_errors)

            warnings.extend(g_warnings)
            results.extend(g_results)

    # Deduplicate across backends keyed on (canonical_path, line_number)
    deduped: List[Dict[str, Any]] = []
    seen_keys: set = set()
    duplicates_skipped = 0
    for row in results:
        line_num = row.get("line_number")
        key = (canonical_path(row["path"]), line_num)
        if line_num is not None and key in seen_keys:
            duplicates_skipped += 1
            continue
        if line_num is not None:
            seen_keys.add(key)
        deduped.append(row)
    results = deduped
    if duplicates_skipped:
        meta["duplicate_content_hits_ignored"] = duplicates_skipped

    meta["total_found"] = len(results)
    meta["has_more"] = len(results) > offset + limit
    if len(results) >= page_cap:
        meta["total_found_is_lower_bound"] = True
    meta["returned_count"] = len(results[offset : offset + limit])
    meta["total_found_exact"] = not meta.get("total_found_is_lower_bound", False)
    if len(results) >= cap_loc:
        meta["truncated"] = True
        meta["note"] = f"Results capped at {cap_loc} lines."
    if allowlist_filters_search_results():
        meta["allowlist_filtered_search_results"] = True
    return success_response(results=results[offset : offset + limit], errors=errors, warnings=warnings, meta=meta)
