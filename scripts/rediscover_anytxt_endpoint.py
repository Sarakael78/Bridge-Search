#!/usr/bin/env python3
"""Probe AnyTXT candidate endpoints, persist the working one, and print a concise discovery report.

Usage examples:
  python3 scripts/rediscover_anytxt_endpoint.py
  python3 scripts/rediscover_anytxt_endpoint.py --query "healthcheck" --json
  python3 scripts/rediscover_anytxt_endpoint.py --query "Anytxt" --limit 3
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Sequence, Set

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from bridge_search import config  # noqa: E402
from bridge_search.search_backends import (  # noqa: E402
    AnyTxtEndpointError,
    _extract_anytxt_wt_controls,
    _extract_anytxt_wt_sid,
    _extract_anytxt_wt_token,
    _query_anytxt_hits,
    _record_anytxt_runtime_url,
    get_effective_anytxt_urls,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Rediscover the working AnyTXT endpoint and persist it back into bridge-search.config.json.",
    )
    p.add_argument(
        "--query",
        default="healthcheck",
        help="Primary probe query to confirm the endpoint is bridge-compatible (default: healthcheck).",
    )
    p.add_argument(
        "--fallback-query",
        default="Anytxt",
        help="Secondary probe query to try if the primary one times out or returns an incompatible endpoint (default: Anytxt).",
    )
    p.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="Probe timeout to use for this standalone command by setting BRIDGE_SEARCH_CMD_TIMEOUT_SECONDS (default: 30).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Maximum number of hits to request while probing (default: 1).",
    )
    p.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Hit offset for the probe query (default: 0).",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a human-readable summary.",
    )
    p.add_argument(
        "--verify-search",
        action="store_true",
        help="After the UI probe succeeds, also run a content-search verification query.",
    )
    return p.parse_args()


def _base_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return urllib.parse.urlunparse(parsed._replace(path="", params="", query="", fragment=""))


def _fetch_text(url: str) -> str:
    timeout = float(os.environ.get("BRIDGE_SEARCH_CMD_TIMEOUT_SECONDS", "30") or 30)
    with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "text/html,application/xhtml+xml"}), timeout=timeout) as response:  # nosec B310 (config-controlled local AnyTXT HTTP service)
        return response.read(config.lim("anytxt_max_response_bytes") + 1).decode("utf-8", errors="replace")


def _probe_open_tcp(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _candidate_ports() -> Sequence[int]:
    return (9921, 9920, 9922, 9923, 9924, 9925)


def _candidate_hosts() -> Sequence[str]:
    hosts: List[str] = ["127.0.0.1", "localhost"]
    host_ip = config.get_wsl_host_ip()
    if host_ip and host_ip not in hosts:
        hosts.append(host_ip)
    return hosts


def _anytxt_http_search_enabled() -> Optional[bool]:
    """Read the host-side AnyTXT config DB if it is accessible from WSL.

    Returns True/False when the config is available, otherwise None.
    """
    db_paths = [
        "/mnt/c/ProgramData/Anytxt/config/config.db",
        "/mnt/d/ProgramData/Anytxt/config/config.db",
    ]
    for path in db_paths:
        if not os.path.exists(path):
            continue
        try:
            import sqlite3

            conn = sqlite3.connect(path)
            cur = conn.cursor()
            cur.execute("SELECT value FROM Setting WHERE key='HttpSearch' LIMIT 1")
            row = cur.fetchone()
            conn.close()
            if row is None:
                return None
            return str(row[0]).strip() not in {"0", "false", "False", "no", "off"}
        except Exception:
            return None
    return None


def _expand_scanned_candidates(existing: Sequence[str]) -> List[str]:
    urls: List[str] = list(existing)
    seen: Set[str] = set(urls)
    timeout = max(0.25, min(2.0, float(os.environ.get("BRIDGE_SEARCH_CMD_TIMEOUT_SECONDS", "30") or 30) / 10.0))
    for host in _candidate_hosts():
        for port in _candidate_ports():
            if not _probe_open_tcp(host, port, timeout):
                continue
            candidate = f"http://{host}:{port}"
            if candidate not in seen:
                urls.append(candidate)
                seen.add(candidate)
    return urls


def _probe_ui(url: str) -> Dict[str, Any]:
    base = _base_url(url)
    root_html = _fetch_text(base)
    token = _extract_anytxt_wt_token(root_html)
    if not token:
        raise AnyTxtEndpointError("AnyTXT returned HTML, but the Wt session token could not be determined.")
    sid = _extract_anytxt_wt_sid(root_html)
    if sid:
        session_url = (
            f"{base}?wtd={token}&sid={sid}&scrW=1024&scrH=768&tz=0"
            "&htmlHistory=true&deployPath=/&request=script&rand=123456"
        )
    else:
        session_url = f"{base}?wtd={token}&js=no"
    session_html = _fetch_text(session_url)
    text_input, select_name, search_signal, drive_options = _extract_anytxt_wt_controls(session_html)
    if not text_input or not select_name or not search_signal or not drive_options:
        raise AnyTxtEndpointError("AnyTXT Wt UI controls could not be parsed.")
    return {
        "url": url,
        "base_url": base,
        "token": token,
        "control_count": 3,
        "drive_count": len(drive_options),
        "bootstrap": "request=script" if sid else "js=no",
        "persisted": _record_anytxt_runtime_url(url, source="rediscover-ui", probe_query="ui-surface"),
    }


def _probe_search(url: str, *, query: str, limit: int, offset: int) -> Dict[str, Any]:
    hits = _query_anytxt_hits(
        url,
        query,
        limit=limit,
        offset=offset,
        max_bytes=config.lim("anytxt_max_response_bytes"),
    )
    return {
        "url": url,
        "probe_query": query,
        "hit_count": len(hits),
        "hits": hits,
        "persisted": _record_anytxt_runtime_url(url, source="rediscover-search", probe_query=query),
    }


def discover_anytxt_endpoint(query: str, fallback_query: str, limit: int, offset: int, verify_search: bool) -> Dict[str, Any]:
    config_enabled = _anytxt_http_search_enabled()
    if config_enabled is False:
        return {
            "success": False,
            "working_url": None,
            "probe_query": query,
            "fallback_query": fallback_query,
            "candidate_count": 0,
            "attempted": [
                {
                    "status": "disabled",
                    "error": "AnyTXT HttpSearch=0 in C:\\ProgramData\\Anytxt\\config\\config.db; enable the HTTP Search Service in AnyTXT before rediscovery can work.",
                }
            ],
            "preflight": {"http_search_enabled": False, "config_db_checked": True},
        }
    candidates = _expand_scanned_candidates(get_effective_anytxt_urls())
    attempted: List[Dict[str, Any]] = []
    for url in candidates:
        try:
            report = _probe_ui(url)
            report["status"] = "ok"
            report["candidate_index"] = len(attempted)
            report["candidates"] = candidates
            if verify_search:
                search_queries = [query]
                if fallback_query and fallback_query not in search_queries:
                    search_queries.append(fallback_query)
                search_result = None
                search_errors: List[Dict[str, Any]] = []
                for probe in search_queries:
                    try:
                        search_result = _probe_search(url, query=probe, limit=limit, offset=offset)
                        report["search"] = search_result
                        report["search_query"] = probe
                        break
                    except AnyTxtEndpointError as exc:
                        search_errors.append({"query": probe, "status": "incompatible", "error": str(exc), "code": getattr(exc, "code", None)})
                    except (OSError, TimeoutError, ValueError) as exc:
                        search_errors.append({"query": probe, "status": "error", "error": str(exc)})
                if search_result is None:
                    report["search_attempts"] = search_errors
            return {
                "success": True,
                "working_url": url,
                "candidate_count": len(candidates),
                "attempted": attempted + [report],
                "report": report,
            }
        except AnyTxtEndpointError as exc:
            attempted.append({"url": url, "status": "incompatible", "error": str(exc), "code": getattr(exc, "code", None)})
        except (OSError, TimeoutError, ValueError, urllib.error.URLError) as exc:
            attempted.append({"url": url, "status": "error", "error": str(exc)})
    return {
        "success": False,
        "working_url": None,
        "probe_query": query,
        "fallback_query": fallback_query,
        "candidate_count": len(candidates),
        "attempted": attempted,
    }


def main() -> int:
    args = parse_args()
    if "BRIDGE_SEARCH_CMD_TIMEOUT_SECONDS" not in os.environ and args.timeout_seconds:
        os.environ["BRIDGE_SEARCH_CMD_TIMEOUT_SECONDS"] = str(args.timeout_seconds)
    result = discover_anytxt_endpoint(args.query, args.fallback_query, args.limit, args.offset, args.verify_search)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        if result["success"]:
            report = result["report"]
            print(f"[+] AnyTXT endpoint discovered: {result['working_url']}")
            print(f"[+] UI probe: token={report['token']}  drives={report['drive_count']}")
            if report.get("search_query"):
                search = report.get("search", {})
                print(f"[+] Search verification: {report['search_query']!r} hits={search.get('hit_count', 0)}")
            print(f"[+] Endpoint persisted to config as last-known-good.")
            if report.get("search") and report["search"].get("hits"):
                first = report["search"]["hits"][0]
                path = first.get("path") or first.get("raw_path") or ""
                snippet = (first.get("snippet") or "").strip()
                if path:
                    print(f"[+] First hit: {path}")
                if snippet:
                    print(f"[+] Snippet: {snippet[:200]}")
        else:
            print("[!] No compatible AnyTXT endpoint found.")
            for item in result["attempted"]:
                print(f"    - {item['url']}: {item.get('status')} ({item.get('error', 'no details')})")
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
