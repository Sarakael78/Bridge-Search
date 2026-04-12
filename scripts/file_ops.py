from __future__ import annotations

import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

from config import get_bridge_config, lim
from path_policy import canonical_path, is_path_allowed, resolve_path
from result_models import error_response, success_response

_TEXT_READ_ENCODINGS: Tuple[str, ...] = ("utf-8", "utf-8-sig", "cp1252")


def clamp_int(value: int, low: int, high: int) -> int:
    """Clamp an integer to an inclusive range."""
    return max(low, min(high, int(value)))


def is_binary_file(filepath: str) -> bool:
    """Heuristically detect whether a file should be treated as binary."""
    try:
        with open(filepath, "rb") as check_file:
            chunk = check_file.read(4096)
        if chunk.startswith((b"\xff\xfe", b"\xfe\xff")):
            try:
                chunk.decode("utf-16")
                return False
            except UnicodeDecodeError:
                return True
        if b"\x00" in chunk:
            return True
        for encoding in _TEXT_READ_ENCODINGS:
            try:
                chunk.decode(encoding)
                return False
            except UnicodeDecodeError:
                continue
        return True
    except OSError:
        return False


def read_text_with_fallbacks(filepath: str) -> Tuple[bool, str, Optional[str]]:
    """Read text using a small set of pragmatic encoding fallbacks."""
    try:
        with open(filepath, "rb") as handle:
            raw = handle.read()
    except OSError:
        return False, "", None
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return True, raw.decode("utf-16"), "utf-16"
        except UnicodeDecodeError:
            return False, "", None
    if b"\x00" in raw and not raw.startswith((b"\xef\xbb\xbf",)):
        return False, "", None
    for encoding in _TEXT_READ_ENCODINGS:
        try:
            return True, raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return False, "", None


def symlink_policy_error(action: str, path: str) -> Optional[Dict[str, Any]]:
    """Return a standardized error response when symlink policy blocks a mutation."""
    if not path or not os.path.islink(path):
        return None
    if action in ("read", "delete"):
        return None
    return error_response(
        code="symlink_blocked",
        message="Symlink policy blocked this operation. Use the resolved target path explicitly for write/copy/move/mkdir.",
        path=path,
    )


def _file_result(action: str, path: str, **extra: Any) -> Dict[str, Any]:
    result = {"action": action, "path": path}
    result.update(extra)
    return result


def hybrid_file_io(
    action: str,
    source_path: str,
    destination_path: Optional[str] = None,
    content: Optional[str] = None,
    target_env: str = "wsl",
    overwrite: bool = False,
    is_confirmed: bool = False,
) -> Dict[str, Any]:
    """Perform guarded file operations and return the standard bridge response shape."""
    src = resolve_path(source_path, target_env)
    dst = resolve_path(destination_path, target_env) if destination_path else ""
    src_canon = canonical_path(src) if src else ""
    dst_canon = canonical_path(dst) if dst else ""
    warnings: List[Dict[str, Any]] = []
    meta = {"action": action, "target_env": target_env, "overwrite": overwrite}

    if action in ["read", "write", "copy", "move", "delete", "mkdir"]:
        if not is_path_allowed(source_path, target_env):
            return error_response(code="path_blocked", message="Access to protected path blocked.", path=source_path, meta=meta)
        if destination_path and action in ["copy", "move"] and not is_path_allowed(destination_path, target_env):
            return error_response(code="path_blocked", message="Access to protected destination path blocked.", path=destination_path, meta=meta)

    sec = get_bridge_config().get("security", {})
    if action == "write" and not is_confirmed and sec.get("require_confirm_for_writes", True):
        return error_response(code="write_confirmation_required", message="WRITE BLOCKED. Pass is_confirmed=True after reviewing the target path.", path=source_path, meta=meta)
    if action == "delete" and not is_confirmed and sec.get("require_confirm_for_deletes", True):
        return error_response(code="delete_confirmation_required", message="DESTRUCTIVE ACTION BLOCKED. Pass is_confirmed=True to delete.", path=source_path, meta=meta)

    def validate_existing_source() -> Optional[Dict[str, Any]]:
        if not src:
            return error_response(code="source_required", message="Source path required", meta=meta)
        if not os.path.lexists(src):
            return error_response(code="not_found", message="Source path not found", path=source_path, meta=meta)
        return symlink_policy_error(action, src)

    def validate_destination() -> Optional[Dict[str, Any]]:
        if not dst:
            return error_response(code="destination_required", message="Destination required", meta=meta)
        if os.path.lexists(dst):
            blocked = symlink_policy_error(action, dst)
            if blocked is not None:
                return blocked
        parent = os.path.dirname(dst_canon) or os.getcwd()
        if not os.path.isdir(parent):
            return error_response(code="destination_parent_missing", message="Destination parent directory does not exist", path=destination_path, meta=meta)
        blocked = symlink_policy_error(action, parent)
        if blocked is not None:
            return blocked
        return None

    def paths_conflict() -> bool:
        return bool(src_canon and dst_canon and src_canon == dst_canon)

    def destination_inside_source() -> bool:
        if not src_canon or not dst_canon or not os.path.isdir(src_canon):
            return False
        return dst_canon.startswith(src_canon.rstrip(os.sep) + os.sep)

    def safe_remove(path: str) -> None:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)

    if action == "read":
        if not os.path.exists(src):
            return error_response(code="not_found", message="File not found", path=source_path, meta=meta)
        ok, text, encoding = read_text_with_fallbacks(src)
        if ok:
            return success_response(results=[_file_result("read", src, source_path=source_path, content=text, encoding=encoding)], warnings=warnings, meta=meta)
        if is_binary_file(src):
            return error_response(code="binary_file", message="Cannot read binary file as text.", path=source_path, meta=meta)
        try:
            with open(src, "rb"):
                pass
        except PermissionError:
            return error_response(code="permission_denied", message="Permission denied. The file may be locked by another process.", path=source_path, meta=meta)
        return error_response(code="decode_failed", message="Could not decode file as supported text (utf-8, utf-16, cp1252).", path=source_path, meta=meta)

    if action == "write":
        blocked = symlink_policy_error(action, src)
        if blocked is not None:
            return blocked
        mode = "w" if overwrite else "a"
        try:
            with open(src, mode, encoding="utf-8", newline="") as file_handle:
                if content:
                    file_handle.write(content)
            return success_response(results=[_file_result("write", src, bytes_written=len(content or ""), encoding="utf-8")], warnings=warnings, meta=meta)
        except PermissionError:
            return error_response(code="permission_denied", message="Permission denied. File is locked or requires elevated privileges.", path=source_path, meta=meta)

    if action == "copy":
        problem = validate_existing_source() or validate_destination()
        if problem:
            return problem
        if paths_conflict():
            return error_response(code="same_path", message="Source and destination resolve to the same path", path=source_path, meta=meta)
        if destination_inside_source():
            return error_response(code="recursive_destination", message="Refusing to copy a directory into itself", path=destination_path, meta=meta)
        if os.path.exists(dst_canon):
            if not overwrite:
                return error_response(code="destination_exists", message="Destination already exists. Pass overwrite=True to replace it.", path=destination_path, meta=meta)
            try:
                safe_remove(dst_canon)
            except OSError as exc:
                return error_response(code="replace_failed", message=f"Could not replace existing destination: {exc}", path=destination_path, meta=meta)
        try:
            if os.path.isdir(src_canon) and not os.path.islink(src_canon):
                shutil.copytree(src_canon, dst_canon, symlinks=True)
                kind = "directory"
            else:
                shutil.copy2(src_canon, dst_canon, follow_symlinks=False)
                kind = "file"
            return success_response(results=[_file_result("copy", dst_canon, source_path=src_canon, destination_path=dst_canon, kind=kind)], warnings=warnings, meta=meta)
        except OSError as exc:
            return error_response(code="copy_failed", message=str(exc), path=destination_path, meta=meta)

    if action == "move":
        problem = validate_existing_source() or validate_destination()
        if problem:
            return problem
        if paths_conflict():
            return error_response(code="same_path", message="Source and destination resolve to the same path", path=source_path, meta=meta)
        if destination_inside_source():
            return error_response(code="recursive_destination", message="Refusing to move a directory into itself", path=destination_path, meta=meta)
        if os.path.exists(dst_canon):
            if not overwrite:
                return error_response(code="destination_exists", message="Destination already exists. Pass overwrite=True to replace it.", path=destination_path, meta=meta)
            try:
                safe_remove(dst_canon)
            except OSError as exc:
                return error_response(code="replace_failed", message=f"Could not replace existing destination: {exc}", path=destination_path, meta=meta)
        try:
            shutil.move(src_canon, dst_canon)
            return success_response(results=[_file_result("move", dst_canon, source_path=src_canon, destination_path=dst_canon)], warnings=warnings, meta=meta)
        except OSError as exc:
            return error_response(code="move_failed", message=str(exc), path=destination_path, meta=meta)

    if action == "mkdir":
        blocked = symlink_policy_error(action, src)
        if blocked is not None:
            return blocked
        try:
            os.makedirs(src, exist_ok=True)
            return success_response(results=[_file_result("mkdir", src)], warnings=warnings, meta=meta)
        except OSError as exc:
            return error_response(code="mkdir_failed", message=str(exc), path=source_path, meta=meta)

    if action == "delete":
        problem = validate_existing_source()
        if problem:
            return problem
        if src_canon.rstrip(os.sep) in ("", os.sep):
            return error_response(code="root_delete_blocked", message="Refusing to delete filesystem root", path=source_path, meta=meta)
        home = canonical_path(os.path.expanduser("~")).rstrip(os.sep)
        if src_canon.rstrip(os.sep) == home:
            return error_response(code="home_delete_blocked", message="Refusing to delete the home directory", path=source_path, meta=meta)
        try:
            safe_remove(src if os.path.islink(src) else src_canon)
            return success_response(results=[_file_result("delete", source_path, removed_path=src)], warnings=warnings, meta=meta)
        except OSError as exc:
            return error_response(code="delete_failed", message=str(exc), path=source_path, meta=meta)

    return error_response(code="invalid_action", message="Invalid action", path=source_path, meta=meta)


def catalog_directory(
    target_path: str,
    max_depth: int = 2,
    include_extensions: Optional[List[str]] = None,
    exclude_hidden: bool = True,
    target_env: str = "auto",
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """Build a paginated directory map and return it in the standard response shape."""
    cap_depth = lim("max_depth")
    cap_limit = lim("max_limit")
    cap_offset = lim("max_offset")
    cap_cat = lim("max_catalog_lines")
    max_depth = clamp_int(max_depth, 0, cap_depth)
    limit = clamp_int(limit, 1, cap_limit)
    offset = clamp_int(offset, 0, cap_offset)
    effective_env = "wsl" if target_env == "auto" else target_env
    resolved_path = resolve_path(target_path, effective_env)
    meta: Dict[str, Any] = {"target_path": target_path, "resolved_path": resolved_path}
    if not is_path_allowed(target_path, effective_env):
        return error_response(code="path_blocked", message="Path not allowed for directory mapping.", path=target_path, meta=meta)
    if not os.path.isdir(resolved_path):
        return error_response(code="not_found", message="Directory not found.", path=target_path, meta=meta)
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
        paginated_output = catalog_output[offset : offset + limit]
        meta.update({"total_found": len(catalog_output), "has_more": offset + limit < len(catalog_output), "offset": offset, "limit": limit})
        if truncated:
            meta["truncated"] = True
            meta["note"] = f"Listing capped at {cap_cat} lines; narrow the path or max_depth."
        return success_response(results=[{"type": "directory_map", "path": resolved_path, "lines": paginated_output, "text": "\n".join(paginated_output)}], meta=meta)
    except OSError as exc:
        return error_response(code="catalog_failed", message=str(exc), path=target_path, meta=meta)
