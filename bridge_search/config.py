from __future__ import annotations

import copy
import functools
import json
import os
import sys
import ipaddress
import subprocess
import tempfile
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

_DEFAULTS: Dict[str, Any] = {
    "version": 1,
    "service": {"anytxt_url": "http://127.0.0.1:9920", "last_known_good_anytxt_url": ""},
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
        "max_read_bytes": 1048576,
        "max_delete_entries": 1000,
    },
    "backends": {"everything": True, "anytxt": True, "wsl_locate": True, "wsl_find": True, "wsl_grep": True},
}

_BACKEND_ENV = {
    "everything": "BRIDGE_SEARCH_ENABLE_EVERYTHING",
    "anytxt": "BRIDGE_SEARCH_ENABLE_ANYTXT",
    "wsl_locate": "BRIDGE_SEARCH_ENABLE_WSL_LOCATE",
    "wsl_find": "BRIDGE_SEARCH_ENABLE_WSL_FIND",
    "wsl_grep": "BRIDGE_SEARCH_ENABLE_WSL_GREP",
}

def _is_probable_wsl_host_ip(value: str) -> bool:
    """Return True for private IPv4 gateways that can plausibly be the WSL host."""
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    if ip.version != 4:
        return False
    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        return False
    # Tailscale DNS (100.100.100.100 / 100.64.0.0/10) can own resolv.conf and is not
    # the Windows host gateway. Prefer RFC1918 WSL/Hyper-V gateway addresses.
    if ip in ipaddress.ip_network("100.64.0.0/10"):
        return False
    return ip.is_private


def _first_nameserver_from_resolv_conf() -> Optional[str]:
    if not os.path.exists("/etc/resolv.conf"):
        return None
    try:
        with open("/etc/resolv.conf", "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("nameserver"):
                    parts = line.split()
                    if len(parts) >= 2 and _is_probable_wsl_host_ip(parts[1]):
                        return parts[1]
    except OSError:
        pass
    return None


def _default_gateway_ip() -> Optional[str]:
    try:
        result = subprocess.run(
            ["ip", "route", "show", "default"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "default" and parts[1] == "via":
            if _is_probable_wsl_host_ip(parts[2]):
                return parts[2]
    return None


def get_wsl_host_ip() -> Optional[str]:
    """Auto-discover the Windows host IP from WSL2 resolver/route state."""
    env = os.environ.get("BRIDGE_SEARCH_WSL_HOST_IP", "").strip()
    if env and _is_probable_wsl_host_ip(env):
        return env
    # Classic WSL writes the host gateway into resolv.conf; VPN/Tailscale setups may
    # replace it with their own DNS, so fall back to the default route gateway.
    return _first_nameserver_from_resolv_conf() or _default_gateway_ip()


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


def _load_bridge_config(paths: Tuple[str, ...]) -> Dict[str, Any]:
    merged = copy.deepcopy(_DEFAULTS)
    for path in paths:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            user = strip_meta(raw) if isinstance(raw, dict) else {}
            merged = deep_merge(merged, user)
            break
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            print(f"bridge-search: warning: could not load {path}: {exc}", file=sys.stderr)
    return merged


@functools.lru_cache(maxsize=None)
def _cached_bridge_config(paths: Tuple[str, ...]) -> Dict[str, Any]:
    return _load_bridge_config(paths)


def get_bridge_config(reload: bool = False) -> Dict[str, Any]:
    """Load and cache merged bridge configuration from defaults and the first config file found."""
    if reload:
        _cached_bridge_config.cache_clear()
    return _cached_bridge_config(tuple(config_paths()))


def lim(key: str) -> int:
    """Read an integer limit value from config with fallback to defaults."""
    limits = get_bridge_config().get("limits", _DEFAULTS["limits"])
    return int(limits.get(key, _DEFAULTS["limits"][key]))


_PRIVATE_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _is_private_host(hostname: Optional[str]) -> bool:
    if not hostname:
        return False
    h = hostname.lower()
    if h in _PRIVATE_HOSTS:
        return True
    if h.startswith("10.") or h.startswith("172.") or h.startswith("192.168."):
        return True
    return False


def normalize_anytxt_url(raw: str) -> str:
    """Normalize an AnyTXT HTTP endpoint.

    The bridge supports both the newer JSON-RPC API root (default, e.g. `http://127.0.0.1:9920`)
    and the older `/search` style endpoint when explicitly configured.

    Emits a stderr warning if the resulting URL points to a non-private host
    (potential SSRF risk).
    """
    url = raw.strip()
    if not url:
        return str(_DEFAULTS["service"]["anytxt_url"])
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme and parsed.scheme not in ("http", "https"):
        print(
            f"bridge-search: warning: AnyTXT URL uses unexpected scheme '{parsed.scheme}'; only http/https are supported",
            file=sys.stderr,
        )
    if parsed.hostname and not _is_private_host(parsed.hostname):
        print(
            f"bridge-search: warning: AnyTXT URL points to non-private host '{parsed.hostname}'; "
            "AnyTXT should run on localhost or a private network",
            file=sys.stderr,
        )
    return urllib.parse.urlunparse(parsed._replace(query="", fragment=""))


def anytxt_search_url() -> str:
    """Return the effective runtime AnyTXT search URL from env or config."""
    env = os.environ.get("BRIDGE_SEARCH_ANYTXT_URL", "").strip()
    if env:
        return normalize_anytxt_url(env)
    svc = get_bridge_config().get("service", _DEFAULTS["service"])
    raw = str(svc.get("anytxt_url", _DEFAULTS["service"]["anytxt_url"]))
    return normalize_anytxt_url(raw)


def should_persist_anytxt_url(url: str) -> bool:
    """Return True when a verified AnyTXT URL differs from current runtime state."""
    normalized = normalize_anytxt_url(url)
    svc = get_bridge_config().get("service", _DEFAULTS["service"])
    current = anytxt_search_url()
    if normalized != current:
        return True
    known_good = str(svc.get("last_known_good_anytxt_url", "")).strip()
    if known_good and normalize_anytxt_url(known_good) != normalized:
        return True
    return False


def persist_anytxt_url(url: str, *, source: str = "", probe_query: str = "", force: bool = False) -> str:
    """Persist a working AnyTXT URL back into the runtime config file.

    The current live endpoint is written to `service.anytxt_url`. The same value
    is also mirrored into `service.last_known_good_anytxt_url` and a `_meta`
    audit block so the last verified URL remains easy to inspect even if later
    sessions override the live endpoint via environment variables.

    Routine health/search success paths call this only when the verified URL has
    changed. The idempotence guard below is a second line of defence for direct
    callers, avoiding unnecessary disk I/O, config-cache reloads, and warnings on
    read-only installs when the on-disk runtime config is already stable.
    """
    normalized = normalize_anytxt_url(url)
    config_path = config_paths()[0]
    try:
        if os.path.isfile(config_path):
            with open(config_path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            payload = raw if isinstance(raw, dict) else {}
        else:
            payload = {}
        service = payload.setdefault("service", {})
        env_override = bool(os.environ.get("BRIDGE_SEARCH_ANYTXT_URL", "").strip())
        current_url = str(service.get("anytxt_url", "")).strip()
        current_known_good = str(service.get("last_known_good_anytxt_url", "")).strip()
        current_runtime = payload.get("_meta", {}).get("anytxt_runtime", {}) if isinstance(payload.get("_meta"), dict) else {}
        current_runtime_url = str(current_runtime.get("last_known_good_url", "")).strip() if isinstance(current_runtime, dict) else ""
        already_stable = (
            current_known_good
            and normalize_anytxt_url(current_known_good) == normalized
            and (env_override or (current_url and normalize_anytxt_url(current_url) == normalized))
            and (not current_runtime_url or normalize_anytxt_url(current_runtime_url) == normalized)
        )
        if already_stable and not force:
            return normalized

        service["last_known_good_anytxt_url"] = normalized
        service["last_known_good_anytxt_url_updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        if source:
            service["last_known_good_anytxt_url_source"] = source
        if probe_query:
            service["last_known_good_anytxt_probe_query"] = probe_query
        if not env_override:
            service["anytxt_url"] = normalized
        meta = payload.setdefault("_meta", {})
        runtime = meta.setdefault("anytxt_runtime", {})
        runtime["last_known_good_url"] = normalized
        runtime["last_verified_at"] = service["last_known_good_anytxt_url_updated_at"]
        if source:
            runtime["last_verified_source"] = source
        if probe_query:
            runtime["last_probe_query"] = probe_query
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".bridge-search.", suffix=".json", dir=os.path.dirname(config_path))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
                handle.write("\n")
            os.replace(tmp_path, config_path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        get_bridge_config(reload=True)
    except Exception as exc:
        print(f"bridge-search: warning: could not persist AnyTXT URL to {config_path}: {exc}", file=sys.stderr)
    return normalized


def clamp_int(value: int, low: int, high: int) -> int:
    """Clamp an integer to an inclusive range."""
    return max(low, min(high, int(value)))


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
