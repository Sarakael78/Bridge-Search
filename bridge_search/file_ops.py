from __future__ import annotations

import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

from .config import get_bridge_config, lim
from .constants import Actions, ErrorCodes
from .path_policy import canonical_path, is_path_allowed, resolve_path
from .result_models import error_response, make_issue, success_response

_TEXT_READ_ENCODINGS: Tuple[str, ...] = ("utf-8", "utf-8-sig", "cp1252")
_WRITE_MODES = {"replace", "append"}
_MUTABLE_ACTIONS = {
    Actions.READ,
    Actions.WRITE,
    Actions.COPY,
    Actions.MOVE,
    Actions.DELETE,
    Actions.MKDIR,
}


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


def read_text_with_fallbacks(filepath: str) -> Tuple[bool, str, Optional[str], bool]:
    """Read text using a small set of pragmatic encoding fallbacks."""
    max_bytes = max(1, lim("max_read_bytes"))
    try:
        with open(filepath, "rb") as handle:
            raw = handle.read(max_bytes + 1)
    except OSError:
        return False, "", None, False
    truncated = len(raw) > max_bytes
    if truncated:
        raw = raw[:max_bytes]
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return True, raw.decode("utf-16"), "utf-16", truncated
        except UnicodeDecodeError:
            return False, "", None, truncated
    if b"\x00" in raw and not raw.startswith((b"\xef\xbb\xbf",)):
        return False, "", None, truncated
    for encoding in _TEXT_READ_ENCODINGS:
        try:
            return True, raw.decode(encoding), encoding, truncated
        except UnicodeDecodeError:
            continue
    return False, "", None, truncated


def symlink_policy_error(action: str, path: str) -> Optional[Dict[str, Any]]:
    """Return a standardized error response when symlink policy blocks a mutation."""
    if not path or not os.path.islink(path):
        return None
    if action in ("read", "delete"):
        return None
    return error_response(
        code=ErrorCodes.SYMLINK_BLOCKED,
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
    write_mode: str = "replace",
) -> Dict[str, Any]:
    """Perform guarded file operations and return the standard bridge response shape."""
    src = resolve_path(source_path, target_env)
    dst = resolve_path(destination_path, target_env) if destination_path else ""
    src_canon = canonical_path(src) if src else ""
    dst_canon = canonical_path(dst) if dst else ""
    warnings: List[Dict[str, Any]] = []
    normalized_write_mode = (write_mode or "replace").strip().lower()
    meta = {
        "action": action,
        "target_env": target_env,
        "overwrite": overwrite,
        "write_mode": normalized_write_mode,
    }

    if action == Actions.WRITE and normalized_write_mode not in _WRITE_MODES:
        return error_response(
            code=ErrorCodes.INVALID_WRITE_MODE,
            message="write_mode must be 'replace' or 'append'",
            path=source_path,
            meta=meta,
        )

    if action in _MUTABLE_ACTIONS:
        if not is_path_allowed(source_path, target_env):
            return error_response(code=ErrorCodes.PATH_BLOCKED, message="Access to protected path blocked.", path=source_path, meta=meta)
        if destination_path and action in {Actions.COPY, Actions.MOVE} and not is_path_allowed(destination_path, target_env):
            return error_response(code=ErrorCodes.PATH_BLOCKED, message="Access to protected destination path blocked.", path=destination_path, meta=meta)

    sec = get_bridge_config().get("security", {})
    if action == Actions.WRITE and not is_confirmed and sec.get("require_confirm_for_writes", True):
        return error_response(code=ErrorCodes.WRITE_CONFIRMATION_REQUIRED, message="WRITE BLOCKED. Pass is_confirmed=True after reviewing the target path.", path=source_path, meta=meta)
    if action == Actions.DELETE and not is_confirmed and sec.get("require_confirm_for_deletes", True):
        return error_response(code=ErrorCodes.DELETE_CONFIRMATION_REQUIRED, message="DESTRUCTIVE ACTION BLOCKED. Pass is_confirmed=True to delete.", path=source_path, meta=meta)

    def validate_existing_source() -> Optional[Dict[str, Any]]:
        if not src:
            return error_response(code=ErrorCodes.SOURCE_REQUIRED, message="Source path required", meta=meta)
        if not os.path.lexists(src):
            return error_response(code=ErrorCodes.NOT_FOUND, message="Source path not found", path=source_path, meta=meta)
        return symlink_policy_error(action, src)

    def validate_destination() -> Optional[Dict[str, Any]]:
        if not dst:
            return error_response(code=ErrorCodes.DESTINATION_REQUIRED, message="Destination required", meta=meta)
        if os.path.lexists(dst):
            blocked = symlink_policy_error(action, dst)
            if blocked is not None:
                return blocked
        parent = os.path.dirname(dst_canon) or os.getcwd()
        if not os.path.isdir(parent):
            return error_response(code=ErrorCodes.DESTINATION_PARENT_MISSING, message="Destination parent directory does not exist", path=destination_path, meta=meta)
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

    if action == Actions.READ:
        if not os.path.exists(src):
            return error_response(code=ErrorCodes.NOT_FOUND, message="File not found", path=source_path, meta=meta)
        ok, text, encoding, truncated = read_text_with_fallbacks(src)
        if ok:
            if truncated:
                warnings.append(
                    make_issue(
                        code=ErrorCodes.READ_TRUNCATED,
                        message=f"File size exceeded lim(max_read_bytes) ({lim('max_read_bytes')} bytes); returning truncated content.",
                        path=source_path,
                    )
                )
            return success_response(results=[_file_result("read", src, source_path=source_path, content=text, encoding=encoding)], warnings=warnings, meta=meta)
        if is_binary_file(src):
            return error_response(code=ErrorCodes.BINARY_FILE, message="Cannot read binary file as text.", path=source_path, meta=meta)
        try:
            with open(src, "rb"):
                pass
        except PermissionError:
            return error_response(code=ErrorCodes.PERMISSION_DENIED, message="Permission denied. The file may be locked by another process.", path=source_path, meta=meta)
        return error_response(code=ErrorCodes.DECODE_FAILED, message="Could not decode file as supported text (utf-8, utf-16, cp1252).", path=source_path, meta=meta)

    if action == Actions.WRITE:
        blocked = symlink_policy_error(action, src)
        if blocked is not None:
            return blocked
        parent = os.path.dirname(src_canon) or os.getcwd()
        if not os.path.isdir(parent):
            return error_response(
                code=ErrorCodes.DESTINATION_PARENT_MISSING,
                message="Destination parent directory does not exist",
                path=source_path,
                meta=meta,
            )
        parent_blocked = symlink_policy_error(action, parent)
        if parent_blocked is not None:
            return parent_blocked
        mode = "a" if normalized_write_mode == "append" else "w"
        try:
            with open(src, mode, encoding="utf-8", newline="") as file_handle:
                if content:
                    file_handle.write(content)
            return success_response(
                results=[
                    _file_result(
                        "write",
                        src,
                        bytes_written=len(content or ""),
                        encoding="utf-8",
                        write_mode=normalized_write_mode,
                    )
                ],
                warnings=warnings,
                meta=meta,
            )
        except PermissionError:
            return error_response(code=ErrorCodes.PERMISSION_DENIED, message="Permission denied. File is locked or requires elevated privileges.", path=source_path, meta=meta)
        except FileNotFoundError:
            return error_response(code=ErrorCodes.DESTINATION_PARENT_MISSING, message="Destination parent directory does not exist", path=source_path, meta=meta)
        except OSError as exc:
            return error_response(code=ErrorCodes.WRITE_FAILED, message=str(exc), path=source_path, meta=meta)

    if action == "copy":
        problem = validate_existing_source() or validate_destination()
        if problem:
            return problem
        if paths_conflict():
            return error_response(code=ErrorCodes.SAME_PATH, message="Source and destination resolve to the same path", path=source_path, meta=meta)
        if destination_inside_source():
            return error_response(code=ErrorCodes.RECURSIVE_DESTINATION, message="Refusing to copy a directory into itself", path=destination_path, meta=meta)
        if os.path.exists(dst_canon):
            if not overwrite:
                return error_response(code=ErrorCodes.DESTINATION_EXISTS, message="Destination already exists. Pass overwrite=True to replace it.", path=destination_path, meta=meta)
            try:
                safe_remove(dst_canon)
            except OSError as exc:
                return error_response(code=ErrorCodes.REPLACE_FAILED, message=f"Could not replace existing destination: {exc}", path=destination_path, meta=meta)
        try:
            if os.path.isdir(src_canon) and not os.path.islink(src_canon):
                shutil.copytree(src_canon, dst_canon, symlinks=True)
                kind = "directory"
            else:
                shutil.copy2(src_canon, dst_canon, follow_symlinks=False)
                kind = "file"
            return success_response(results=[_file_result("copy", dst_canon, source_path=src_canon, destination_path=dst_canon, kind=kind)], warnings=warnings, meta=meta)
        except OSError as exc:
            return error_response(code=ErrorCodes.COPY_FAILED, message=str(exc), path=destination_path, meta=meta)

    if action == "move":
        problem = validate_existing_source() or validate_destination()
        if problem:
            return problem
        if paths_conflict():
            return error_response(code=ErrorCodes.SAME_PATH, message="Source and destination resolve to the same path", path=source_path, meta=meta)
        if destination_inside_source():
            return error_response(code=ErrorCodes.RECURSIVE_DESTINATION, message="Refusing to move a directory into itself", path=destination_path, meta=meta)
        if os.path.exists(dst_canon):
            if not overwrite:
                return error_response(code=ErrorCodes.DESTINATION_EXISTS, message="Destination already exists. Pass overwrite=True to replace it.", path=destination_path, meta=meta)
            try:
                safe_remove(dst_canon)
            except OSError as exc:
                return error_response(code=ErrorCodes.REPLACE_FAILED, message=f"Could not replace existing destination: {exc}", path=destination_path, meta=meta)
        try:
            shutil.move(src_canon, dst_canon)
            return success_response(results=[_file_result("move", dst_canon, source_path=src_canon, destination_path=dst_canon)], warnings=warnings, meta=meta)
        except OSError as exc:
            return error_response(code=ErrorCodes.MOVE_FAILED, message=str(exc), path=destination_path, meta=meta)

    if action == "mkdir":
        blocked = symlink_policy_error(action, src)
        if blocked is not None:
            return blocked
        try:
            os.makedirs(src, exist_ok=True)
            return success_response(results=[_file_result("mkdir", src)], warnings=warnings, meta=meta)
        except OSError as exc:
            return error_response(code=ErrorCodes.MKDIR_FAILED, message=str(exc), path=source_path, meta=meta)

    if action == "delete":
        problem = validate_existing_source()
        if problem:
            return problem
        if src_canon.rstrip(os.sep) in ("", os.sep):
            return error_response(code=ErrorCodes.ROOT_DELETE_BLOCKED, message="Refusing to delete filesystem root", path=source_path, meta=meta)
        home = canonical_path(os.path.expanduser("~")).rstrip(os.sep)
        if src_canon.rstrip(os.sep) == home:
            return error_response(code=ErrorCodes.HOME_DELETE_BLOCKED, message="Refusing to delete the home directory", path=source_path, meta=meta)
        try:
            safe_remove(src if os.path.islink(src) else src_canon)
            return success_response(results=[_file_result("delete", source_path, removed_path=src)], warnings=warnings, meta=meta)
        except OSError as exc:
            return error_response(code=ErrorCodes.DELETE_FAILED, message=str(exc), path=source_path, meta=meta)

    return error_response(code=ErrorCodes.INVALID_ACTION, message="Invalid action", path=source_path, meta=meta)


def catalog_directory(
    target_path: str,
    max_depth: int = 2,
    include_extensions: Optional[List[str]] = None,
    exclude_hidden: bool = True,
    target_env: str = "auto",
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """Build a paginated directory map using os.scandir for high performance."""
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
        return error_response(code=ErrorCodes.PATH_BLOCKED, message="Path not allowed for directory mapping.", path=target_path, meta=meta)
    if not os.path.isdir(resolved_path):
        return error_response(code=ErrorCodes.NOT_FOUND, message="Directory not found.", path=target_path, meta=meta)
    
    if include_extensions:
        include_extensions = [ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in include_extensions]

    catalog_output: List[str] = []
    total_lines = 0
    done = False
    hit_catalog_cap = False
    has_more = False
    page_end = offset + limit

    def record_entry(line: str) -> bool:
        nonlocal total_lines, done, hit_catalog_cap, has_more
        if done:
            return False
        total_lines += 1
        if offset < total_lines <= min(page_end, cap_cat):
            catalog_output.append(line)
        if total_lines > page_end:
            has_more = True
        if total_lines > cap_cat:
            hit_catalog_cap = True
        if has_more or hit_catalog_cap:
            done = True
            return False
        return True

    def walk_level(current_path: str, depth: int) -> None:
        nonlocal done
        if done:
            return

        try:
            with os.scandir(current_path) as it:
                entries = sorted(it, key=lambda e: e.name.lower())
                
                dirs_to_process: List[os.DirEntry] = []
                files_to_process: List[os.DirEntry] = []
                for entry in entries:
                    if exclude_hidden and entry.name.startswith("."):
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            dirs_to_process.append(entry)
                        elif entry.is_file(follow_symlinks=False):
                            if include_extensions:
                                _, ext = os.path.splitext(entry.name)
                                if ext.lower() not in include_extensions:
                                    continue
                            files_to_process.append(entry)
                    except OSError:
                        continue

                indent = "  " * depth
                for f in files_to_process:
                    if not record_entry(f"{indent}  📄 {f.name}"):
                        return
                
                if depth < max_depth:
                    for d in dirs_to_process:
                        if not record_entry(f"{indent}  📂 {d.name}/"):
                            return
                        walk_level(d.path, depth + 1)
                        if done:
                            return

        except OSError:
            pass

    try:
        root_name = os.path.basename(resolved_path.rstrip(os.sep)) or resolved_path
        record_entry(f"📂 {root_name}/")
        if not done:
            walk_level(resolved_path, 0)

        meta.update(
            {
                "total_found": total_lines,
                "offset": offset,
                "limit": limit,
                "returned_count": len(catalog_output),
                "has_more": has_more,
            }
        )
        if has_more or hit_catalog_cap:
            meta["truncated"] = True
            meta["total_found_is_lower_bound"] = True
            notes: List[str] = []
            if hit_catalog_cap:
                notes.append(f"Listing capped at {cap_cat} lines; narrow the path or max_depth.")
            if has_more:
                notes.append("Limit reached; increase limit/offset or narrow the path.")
            if notes:
                meta["note"] = " ".join(notes)
        
        return success_response(results=[{"type": "directory_map", "path": resolved_path, "lines": catalog_output, "text": "\n".join(catalog_output)}], meta=meta)
    except OSError as exc:
        return error_response(code=ErrorCodes.CATALOG_FAILED, message=str(exc), path=target_path, meta=meta)
