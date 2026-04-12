from __future__ import annotations

import copy
import json
import os
import sys
import urllib.parse
from typing import Any, Dict, List, Optional

_DEFAULTS: Dict[str, Any] = {
    "version": 1,
    "service": {"anytxt_url": "http://127.0.0.1:9921/search"},
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
        "command_timeout_seconds": 10,
    },
    "backends": {"everything": True, "anytxt": True, "wsl_find": True, "wsl_grep": True},
}

_BACKEND_ENV = {
    "everything": "BRIDGE_SEARCH_ENABLE_EVERYTHING",
    "anytxt": "BRIDGE_SEARCH_ENABLE_ANYTXT",
    "wsl_find": "BRIDGE_SEARCH_ENABLE_WSL_FIND",
    "wsl_grep": "BRIDGE_SEARCH_ENABLE_WSL_GREP",
}

_cfg_cache: Optional[Dict[str, Any]] = None


def command_timeout_seconds() -> float:
    """Return the default subprocess timeout for backend and path-translation calls."""
    raw = os.environ.get("BRIDGE_SEARCH_CMD_TIMEOUT_SECONDS", "").strip()
    if raw:
        try:
            return max(1.0, float(raw))
        except ValueError:
            pass
    limits = get_bridge_config().get("limits", _DEFAULTS["limits"])
    return float(limits.get("command_timeout_seconds", 10))


def strip_meta(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: strip_meta(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [strip_meta(x) for x in obj]
    return obj


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, val in override.items():
        if str(key).startswith("_"):
            continue
        if key in out and isinstance(out[key], dict) and isinstance(val, dict):
            out[key] = deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def config_paths() -> List[str]:
    env = os.environ.get("BRIDGE_SEARCH_CONFIG", "").strip()
    if env:
        return [os.path.abspath(env)]
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(script_dir, ".."))
    return [os.path.join(root, "config", "bridge-search.config.json")]


def get_bridge_config(reload: bool = False) -> Dict[str, Any]:
    """Load and cache merged bridge configuration from defaults and the first config file found."""
    global _cfg_cache
    if _cfg_cache is not None and not reload:
        return _cfg_cache
    merged = copy.deepcopy(_DEFAULTS)
    for path in config_paths():
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            user = strip_meta(raw) if isinstance(raw, dict) else {}
            merged = deep_merge(merged, user)
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            print(f"bridge-search: warning: could not load {path}: {exc}", file=sys.stderr)
        break
    _cfg_cache = merged
    return _cfg_cache


def lim(key: str) -> int:
    """Read an integer limit value from config with fallback to defaults."""
    limits = get_bridge_config().get("limits", _DEFAULTS["limits"])
    return int(limits.get(key, _DEFAULTS["limits"][key]))


def normalize_anytxt_url(raw: str) -> str:
    """Normalize a base AnyTXT URL or endpoint into a canonical `/search` endpoint."""
    url = raw.strip()
    if not url:
        return _DEFAULTS["service"]["anytxt_url"]
    parsed = urllib.parse.urlparse(url)
    path = parsed.path or ""
    if path.rstrip("/").endswith("/search"):
        clean_path = path.rstrip("/")
        return urllib.parse.urlunparse(parsed._replace(path=clean_path, query="", fragment=""))
    return f"{url.rstrip('/')}/search"


def anytxt_search_url() -> str:
    """Return the effective runtime AnyTXT search URL from env or config."""
    env = os.environ.get("BRIDGE_SEARCH_ANYTXT_URL", "").strip()
    if env:
        return normalize_anytxt_url(env)
    svc = get_bridge_config().get("service", _DEFAULTS["service"])
    raw = str(svc.get("anytxt_url", _DEFAULTS["service"]["anytxt_url"]))
    return normalize_anytxt_url(raw)


def backend_enabled(name: str) -> bool:
    """Check whether a backend is enabled after applying env overrides."""
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
