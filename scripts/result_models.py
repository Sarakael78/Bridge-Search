from __future__ import annotations

from typing import Any, Dict, List, Optional


def make_issue(*, code: str, message: str, source: Optional[str] = None, path: Optional[str] = None, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build a standardized warning or error object."""
    issue: Dict[str, Any] = {"code": code, "message": message}
    if source is not None:
        issue["source"] = source
    if path is not None:
        issue["path"] = path
    if details:
        issue["details"] = details
    return issue


def success_response(*, results: Optional[List[Dict[str, Any]]] = None, errors: Optional[List[Dict[str, Any]]] = None, warnings: Optional[List[Dict[str, Any]]] = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return the standard top-level response shape for all bridge tools."""
    errs = errors or []
    res = results or []
    return {
        "success": len(errs) == 0 or len(res) > 0,
        "results": res,
        "errors": errs,
        "warnings": warnings or [],
        "meta": meta or {},
    }


def error_response(*, code: str, message: str, source: Optional[str] = None, path: Optional[str] = None, details: Optional[Dict[str, Any]] = None, warnings: Optional[List[Dict[str, Any]]] = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return a standardized response that contains a single structured error."""
    return success_response(
        results=[],
        errors=[make_issue(code=code, message=message, source=source, path=path, details=details)],
        warnings=warnings,
        meta=meta,
    )
