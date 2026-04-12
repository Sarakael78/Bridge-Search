from __future__ import annotations

import os
import re
import subprocess
from typing import List, Optional, Tuple

from config import get_bridge_config

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

_WINDOWS_ABS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


def canonical_path(path: str) -> str:
    """Return a normalized real path when possible."""
    try:
        return os.path.realpath(path)
    except OSError:
        return os.path.normpath(path)


def looks_like_windows_abs_path(path: str) -> bool:
    """Detect Windows absolute paths, including UNC-style paths."""
    return bool(_WINDOWS_ABS_PATH_RE.match(path)) or path.startswith("\\\\") or path.startswith("//")


def auto_target_env(path: str) -> str:
    """Infer the translation direction for a mixed Windows/WSL path input."""
    if looks_like_windows_abs_path(path):
        return "wsl"
    if path.startswith("/mnt/") or (path.startswith("/") and not path.startswith("//")):
        return "windows"
    return "wsl"


def resolve_path(path: str, target_env: str) -> str:
    """Translate between Windows and WSL paths when possible."""
    if not path:
        return ""
    env = auto_target_env(path) if target_env == "auto" else target_env
    if env == "wsl" and looks_like_windows_abs_path(path):
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


def _restricted_prefixes() -> Tuple[str, ...]:
    sec = get_bridge_config().get("security", {})
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
            out.append(canonical_path(exp).lower())
        return tuple(dict.fromkeys(out)) if out else _RESTRICTED_DEFAULT
    return _RESTRICTED_DEFAULT


def parse_allowed_prefixes_env() -> Optional[List[str]]:
    raw = os.environ.get("BRIDGE_SEARCH_ALLOWED_PREFIXES", "").strip()
    if not raw:
        return None
    out: List[str] = []
    for part in raw.split(":"):
        p = part.strip()
        if not p:
            continue
        out.append(canonical_path(os.path.expanduser(p)))
    return out if out else None


def allowed_prefixes_merged() -> Optional[List[str]]:
    raw = get_bridge_config().get("security", {}).get("allowed_prefixes")
    from_file: List[str] = []
    if isinstance(raw, list):
        for p in raw:
            if not isinstance(p, str) or not p.strip():
                continue
            from_file.append(canonical_path(os.path.expanduser(p.strip())))
    env_list = parse_allowed_prefixes_env() or []
    merged: List[str] = []
    for p in from_file + env_list:
        if p and p not in merged:
            merged.append(p)
    return merged if merged else None


def allowlist_filters_search_results() -> bool:
    return allowed_prefixes_merged() is not None


def is_path_allowed(path: str, target_env: str) -> bool:
    """Apply allowlist and denylist policy to a path after canonicalization."""
    if not path or not str(path).strip():
        return False
    resolved = resolve_path(path.strip(), target_env)
    canonical = canonical_path(resolved)
    cl = canonical.lower().replace("\\", "/")
    allowed = allowed_prefixes_merged()
    if allowed is not None:
        ok = False
        for prefix in allowed:
            pl = prefix.lower().replace("\\", "/").rstrip("/")
            if cl == pl or cl.startswith(pl + os.sep):
                ok = True
                break
        if not ok:
            return False
    for p in _restricted_prefixes():
        pl = p.lower().replace("\\", "/").rstrip("/")
        if cl == pl or cl.startswith(pl + "/"):
            return False
    return True


def path_allowed_for_search_result(path_candidate: str) -> bool:
    """Apply file-operation path policy to a path returned by a search backend."""
    pc = path_candidate.strip()
    if not pc:
        return False
    if looks_like_windows_abs_path(pc):
        return is_path_allowed(pc, "wsl")
    if pc.startswith("/") or pc.startswith("\\"):
        return is_path_allowed(pc, "wsl")
    return is_path_allowed(pc, "auto")
