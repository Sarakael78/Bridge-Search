from __future__ import annotations

import functools
import os
import re
import subprocess
from typing import List, Optional, Tuple

from .config import command_timeout_seconds, get_bridge_config

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


@functools.lru_cache(maxsize=4096)
def canonical_path(path: str) -> str:
    """Return a normalized real path when possible."""
    try:
        return os.path.realpath(path)
    except OSError:
        return os.path.normpath(path)


def looks_like_windows_abs_path(path: str) -> bool:
    """Detect Windows absolute paths, including UNC-style paths."""
    return bool(_WINDOWS_ABS_PATH_RE.match(path)) or path.startswith("\\\\") or path.startswith("//")


def _split_prefix_blob(raw: str) -> List[str]:
    """Split an env prefix list on ':' or ';' without breaking Windows drive letters."""
    parts: List[str] = []
    current: List[str] = []
    for idx, ch in enumerate(raw):
        if ch in ":;":
            next_ch = raw[idx + 1] if idx + 1 < len(raw) else ""
            current_text = "".join(current).strip()
            is_drive_colon = ch == ":" and len(current_text) == 1 and current_text.isalpha() and next_ch in ("\\", "/")
            if is_drive_colon:
                current.append(ch)
                continue
            part = current_text
            if part:
                parts.append(part)
            current = []
            continue
        current.append(ch)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def normalize_policy_prefix(path: str) -> Optional[str]:
    """Normalize allowlist and denylist prefixes into the same path form used at runtime."""
    if not isinstance(path, str) or not path.strip():
        return None
    raw = os.path.expanduser(path.strip())
    translated = resolve_path(raw, "wsl") if looks_like_windows_abs_path(raw) else raw
    return canonical_path(translated)


def auto_target_env(path: str) -> str:
    """Infer the translation direction for a mixed Windows/WSL path input."""
    if looks_like_windows_abs_path(path):
        return "wsl"
    if path.startswith("/mnt/") or (path.startswith("/") and not path.startswith("//")):
        return "windows"
    return "wsl"


@functools.lru_cache(maxsize=4096)
def resolve_path(path: str, target_env: str) -> str:
    """Translate between Windows and WSL paths when possible."""
    if not path:
        return ""
    env = auto_target_env(path) if target_env == "auto" else target_env
    if env == "wsl" and looks_like_windows_abs_path(path):
        try:
            result = subprocess.run(
                ["wslpath", "-u", path],
                capture_output=True,
                text=True,
                check=True,
                timeout=command_timeout_seconds(),
            )
            return result.stdout.strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            pass
    elif env == "windows" and (path.startswith("/mnt/") or path.startswith("/")):
        try:
            result = subprocess.run(
                ["wslpath", "-w", path],
                capture_output=True,
                text=True,
                check=True,
                timeout=command_timeout_seconds(),
            )
            return result.stdout.strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
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
            normalized = normalize_policy_prefix(p)
            if normalized is None:
                continue
            out.append(normalized.lower())
        return tuple(dict.fromkeys(out)) if out else _RESTRICTED_DEFAULT
    return _RESTRICTED_DEFAULT


def parse_allowed_prefixes_env() -> Optional[List[str]]:
    raw = os.environ.get("BRIDGE_SEARCH_ALLOWED_PREFIXES", "").strip()
    if not raw:
        return None
    out: List[str] = []
    for part in _split_prefix_blob(raw):
        normalized = normalize_policy_prefix(part)
        if normalized is None:
            continue
        out.append(normalized)
    return out if out else None


def allowed_prefixes_merged() -> Optional[List[str]]:
    raw = get_bridge_config().get("security", {}).get("allowed_prefixes")
    from_file: List[str] = []
    if isinstance(raw, list):
        for p in raw:
            normalized = normalize_policy_prefix(p)
            if normalized is None:
                continue
            from_file.append(normalized)
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
