from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import clamp_int, get_bridge_config, lim
from .constants import ErrorCodes
from .path_policy import is_path_allowed, resolve_path
from .result_models import error_response, success_response

_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./:-]*")


def _knowledge_root(root_id: str) -> tuple[Path | None, dict[str, Any]]:
    roots = get_bridge_config().get("knowledge_roots", {})
    item = roots.get(root_id) if isinstance(roots, dict) else None
    if isinstance(item, str):
        item = {"path": item}
    if not isinstance(item, dict):
        return None, {}
    raw_path = str(item.get("path") or "").strip()
    if not raw_path:
        return None, item
    resolved = resolve_path(raw_path, "wsl")
    return Path(resolved).expanduser(), item


def _markdown_files(root: Path, errors: list[OSError]) -> Iterable[Path]:
    resolved_root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root, onerror=errors.append):
        dirnames[:] = sorted(name for name in dirnames if not name.startswith("."))
        for filename in sorted(filenames):
            if filename.startswith(".") or not filename.casefold().endswith(".md"):
                continue
            candidate = Path(dirpath) / filename
            try:
                resolved = candidate.resolve(strict=True)
            except OSError as error:
                errors.append(error)
                continue
            if candidate.is_symlink() or not resolved.is_relative_to(resolved_root):
                continue
            yield candidate


def _query_matches(text: str, query: str) -> bool:
    folded = text.casefold()
    phrase = query.casefold().strip()
    if phrase in folded:
        return True
    terms = [term.casefold() for term in _WORD_RE.findall(query) if len(term) >= 2]
    return bool(terms) and all(term in folded for term in terms)


def _best_line(text: str, query: str) -> tuple[int, str]:
    lines = text.splitlines()
    phrase = query.casefold().strip()
    terms = [term.casefold() for term in _WORD_RE.findall(query) if len(term) >= 2]
    best = (0, "")
    best_score = -1
    for number, line in enumerate(lines, start=1):
        folded = line.casefold()
        score = 1000 if phrase and phrase in folded else sum(term in folded for term in terms)
        if score > best_score:
            best = (number, line.strip())
            best_score = score
    return best


def search_approved_knowledge(
    query: str,
    knowledge_root: str = "hermes_agent_brain",
    limit: int = 20,
) -> dict[str, Any]:
    """Search one configured read-only Markdown root and return source provenance."""
    query = (query or "").strip()
    limit = clamp_int(limit, 1, lim("max_limit"))
    meta: dict[str, Any] = {
        "knowledge_root": knowledge_root,
        "limit": limit,
        "read_only": True,
    }
    if not query:
        return error_response(
            code=ErrorCodes.QUERY_REQUIRED,
            message="Query must not be blank.",
            source="approved-knowledge",
            meta=meta,
        )

    root, root_config = _knowledge_root(knowledge_root)
    if root is None:
        return error_response(
            code=ErrorCodes.BACKEND_UNAVAILABLE,
            message=f"Knowledge root {knowledge_root!r} is not configured.",
            source="approved-knowledge",
            meta=meta,
        )
    meta["root_path"] = str(root)
    meta["classification"] = str(root_config.get("classification") or "derivative")
    if not is_path_allowed(str(root), "wsl"):
        return error_response(
            code=ErrorCodes.PATH_BLOCKED,
            message="Configured knowledge root is blocked by path policy.",
            source="approved-knowledge",
            meta=meta,
        )
    if not root.is_dir():
        return error_response(
            code=ErrorCodes.NOT_FOUND,
            message="Configured knowledge root does not exist or is not a directory.",
            source="approved-knowledge",
            meta=meta,
        )

    results: list[dict[str, Any]] = []
    scanned = 0
    unreadable = 0
    blocked = 0
    enumeration_errors: list[OSError] = []
    for path in _markdown_files(root, enumeration_errors):
        if not is_path_allowed(str(path), "wsl"):
            blocked += 1
            continue
        scanned += 1
        try:
            payload = path.read_bytes()
            text = payload.decode("utf-8")
            stat = path.stat()
        except (OSError, UnicodeDecodeError):
            unreadable += 1
            continue
        if not _query_matches(text, query):
            continue
        line_number, snippet = _best_line(text, query)
        results.append(
            {
                "type": "knowledge_hit",
                "root_id": knowledge_root,
                "path": str(path),
                "raw_path": resolve_path(str(path), "windows"),
                "title": path.stem,
                "line_number": line_number,
                "snippet": snippet,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": stat.st_size,
                "modified_at_utc": datetime.fromtimestamp(
                    stat.st_mtime, timezone.utc
                ).isoformat(),
                "classification": meta["classification"],
                "source": "approved-knowledge",
                "read_only": True,
            }
        )
        if len(results) > limit:
            break

    observed_matches = len(results)
    has_more = observed_matches > limit
    results = results[:limit]
    exact_total = not has_more and unreadable == 0 and not enumeration_errors
    meta.update(
        {
            "files_scanned": scanned,
            "unreadable_files": unreadable,
            "blocked_files": blocked,
            "enumeration_errors": len(enumeration_errors),
            "returned_count": len(results),
            "total_found": observed_matches,
            "has_more": has_more,
            "total_found_exact": exact_total,
            "total_found_is_lower_bound": not exact_total,
        }
    )
    return success_response(results=results, errors=[], warnings=[], meta=meta)
