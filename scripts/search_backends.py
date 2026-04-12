from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from config import anytxt_search_url, backend_enabled, get_bridge_config, lim
from file_ops import clamp_int
from path_policy import allowlist_filters_search_results, canonical_path, is_path_allowed, looks_like_windows_abs_path, path_allowed_for_search_result, resolve_path
from result_models import error_response, make_issue, success_response

_GREP_LINE_RE = re.compile(r"^(.+?):(\d+):(.*)$", re.DOTALL)


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


def resolve_es_exe() -> Optional[str]:
    """Locate Everything's `es.exe` from standard paths or Windows PATH."""
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


def _everything_search_arg(query: str, exact_match: bool) -> str:
    if exact_match:
        return query
    q = query.strip()
    if not q:
        return q
    if any(c in q for c in ("*", "?", '"')):
        return q
    return f"*{q}*"


def _wsl_locator_full_root_allowed() -> bool:
    sec = get_bridge_config().get("security", {})
    if bool(sec.get("allow_wsl_locator_from_filesystem_root", False)):
        return True
    return os.environ.get("BRIDGE_SEARCH_ALLOW_ROOT_LOCATOR", "").strip() == "1"


def _wsl_filename_find_root() -> str:
    return "/" if _wsl_locator_full_root_allowed() else os.path.expanduser("~")


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
    wants_win = target_env in ("windows", "everywhere")
    wants_wsl = target_env in ("wsl", "everywhere")
    run_everything = wants_win and backend_enabled("everything")
    run_wsl_find = wants_wsl and backend_enabled("wsl_find")
    meta: Dict[str, Any] = {"filename_backends": {"everything": run_everything, "wsl_find": run_wsl_find}, "offset": offset, "limit": limit}
    if not run_everything and not run_wsl_find:
        return error_response(code="backend_disabled", message="No filename search backend enabled for this target_env.", source="locator", meta=meta)
    results: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    truncated = False

    def append_result(item: Dict[str, Any]) -> None:
        nonlocal truncated
        if len(results) >= cap_loc:
            truncated = True
            return
        results.append(item)

    if run_everything:
        try:
            es_exe = resolve_es_exe()
            if not es_exe:
                errors.append(make_issue(code="backend_unavailable", message="es.exe not found. Check Everything installation or Windows PATH.", source="windows-everything"))
            else:
                process = subprocess.run([es_exe, _everything_search_arg(query, exact_match)], capture_output=True)
                if process.returncode == 0 and process.stdout:
                    output = decode_windows_output(process.stdout)
                    for line in output.strip().split("\n"):
                        if truncated:
                            break
                        raw_path = line.strip()
                        if not raw_path:
                            continue
                        mapped = resolve_path(raw_path, "wsl") if looks_like_windows_abs_path(raw_path) else raw_path
                        if not path_allowed_for_search_result(mapped):
                            continue
                        if mapped == raw_path and looks_like_windows_abs_path(raw_path):
                            warnings.append(make_issue(code="path_translation_failed", message=f"Could not translate Windows path to WSL form: {raw_path}", source="windows-everything", path=raw_path))
                        append_result({"type": "search_hit", "path": mapped, "raw_path": raw_path, "source": "windows-everything"})
                elif process.stderr:
                    errors.append(make_issue(code="backend_error", message=decode_windows_output(process.stderr).strip(), source="windows-everything"))
        except OSError as exc:
            errors.append(make_issue(code="backend_error", message=str(exc), source="windows-everything"))

    if run_wsl_find and len(results) < cap_loc:
        try:
            pattern = query if exact_match else f"*{query}*"
            search_root = _wsl_filename_find_root()
            cmd = ["find", "/", "-path", "/mnt", "-prune", "-o", "-iname", pattern, "-print"] if search_root == "/" else ["find", search_root, "-iname", pattern, "-print"]
            process = subprocess.run(cmd, capture_output=True, text=True)
            if process.stdout:
                for line in process.stdout.strip().split("\n"):
                    if truncated:
                        break
                    path = line.strip()
                    if not path or not path_allowed_for_search_result(path):
                        continue
                    append_result({"type": "search_hit", "path": path, "raw_path": path, "source": "wsl-find"})
            if process.returncode not in (0, 1) and process.stderr:
                errors.append(make_issue(code="backend_error", message=process.stderr.strip(), source="wsl-find"))
        except OSError as exc:
            errors.append(make_issue(code="backend_error", message=str(exc), source="wsl-find"))

    meta["total_found"] = len(results)
    meta["has_more"] = offset + limit < len(results)
    if truncated or len(results) >= cap_loc:
        meta["truncated"] = True
        meta["note"] = f"Combined results capped at {cap_loc} paths."
    if allowlist_filters_search_results():
        meta["allowlist_filtered_search_results"] = True
    return success_response(results=results[offset : offset + limit], errors=errors, warnings=warnings, meta=meta)


def content_locator(query: str, target_env: str = "everywhere", wsl_search_path: str = "", limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    """Search file contents via AnyTXT and optional WSL grep backends."""
    cap_limit = lim("max_limit")
    cap_offset = lim("max_offset")
    cap_loc = lim("max_locator_results")
    cap_anytxt = lim("anytxt_max_response_bytes")
    limit = clamp_int(limit, 1, cap_limit)
    offset = clamp_int(offset, 0, cap_offset)
    eff_root = wsl_search_path.strip() or os.path.expanduser("~")
    wants_wsl = target_env in ("wsl", "everywhere")
    wants_anytxt = target_env in ("windows", "everywhere")
    run_wsl = wants_wsl and backend_enabled("wsl_grep")
    run_anytxt = wants_anytxt and backend_enabled("anytxt")
    meta: Dict[str, Any] = {"content_backends": {"wsl_grep": run_wsl, "anytxt": run_anytxt}, "offset": offset, "limit": limit, "anytxt_url": anytxt_search_url() if run_anytxt else None}
    if not run_wsl and not run_anytxt:
        return error_response(code="backend_disabled", message="No content-search backend enabled for this target_env.", source="content-locator", meta=meta)
    results: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    if run_wsl:
        try:
            ok, root = _wsl_grep_root_allowed(eff_root)
            if not ok:
                errors.append(make_issue(code="search_root_blocked", message=root, source="wsl-grep", path=eff_root))
            else:
                cmd = ["grep", "-rni", "-m", "2", "--exclude-dir=/mnt", "-F", "-e", query, "--", root]
                process = subprocess.run(cmd, capture_output=True, text=True)
                if process.stdout:
                    for line in process.stdout.strip().split("\n"):
                        if len(results) >= cap_loc:
                            break
                        path_g = grep_line_file_path(line)
                        match = _GREP_LINE_RE.match(line)
                        if path_g is None or match is None or not path_allowed_for_search_result(path_g):
                            continue
                        results.append({"type": "content_hit", "path": path_g, "raw_path": path_g, "line_number": int(match.group(2)), "snippet": match.group(3), "source": "wsl-grep"})
                if process.returncode not in (0, 1) and process.stderr:
                    errors.append(make_issue(code="backend_error", message=process.stderr.strip(), source="wsl-grep"))
        except OSError as exc:
            errors.append(make_issue(code="backend_error", message=str(exc), source="wsl-grep"))

    if run_anytxt:
        try:
            base = anytxt_search_url()
            sep = "&" if urllib.parse.urlparse(base).query else "?"
            req = urllib.request.Request(f"{base}{sep}q={urllib.parse.quote(query)}")
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    raw = response.read(cap_anytxt + 1)
                    if len(raw) > cap_anytxt:
                        errors.append(make_issue(code="response_too_large", message=f"Response exceeded {cap_anytxt} bytes; raise anytxt_max_response_bytes if needed.", source="windows-anytxt"))
                    else:
                        data = json.loads(raw.decode("utf-8"))
                        for item in data.get("results", []):
                            if len(results) >= cap_loc:
                                break
                            raw_path = str(item.get("path", "")).strip()
                            if not raw_path:
                                continue
                            mapped = resolve_path(raw_path, "wsl") if looks_like_windows_abs_path(raw_path) else raw_path
                            if not path_allowed_for_search_result(mapped):
                                continue
                            if mapped == raw_path and looks_like_windows_abs_path(raw_path):
                                warnings.append(make_issue(code="path_translation_failed", message=f"Could not translate Windows path to WSL form: {raw_path}", source="windows-anytxt", path=raw_path))
                            results.append({"type": "content_hit", "path": mapped, "raw_path": raw_path, "snippet": item.get("snippet", ""), "source": "windows-anytxt"})
        except OSError as exc:
            errors.append(make_issue(code="backend_error", message=str(exc), source="windows-anytxt"))
        except json.JSONDecodeError as exc:
            errors.append(make_issue(code="invalid_response", message=f"Invalid JSON ({exc})", source="windows-anytxt"))

    meta["total_found"] = len(results)
    meta["has_more"] = offset + limit < len(results)
    if len(results) >= cap_loc:
        meta["truncated"] = True
        meta["note"] = f"Results capped at {cap_loc} lines."
    if allowlist_filters_search_results():
        meta["allowlist_filtered_search_results"] = True
    return success_response(results=results[offset : offset + limit], errors=errors, warnings=warnings, meta=meta)
