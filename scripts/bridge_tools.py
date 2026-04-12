import os
import subprocess
import urllib.request
import urllib.parse
import json
from typing import Optional, Dict, Any, List, Tuple

# --- SECURITY CONSTANTS ---
RESTRICTED_WIN_DIRS = ["c:\\windows", "c:\\program files", "c:\\program files (x86)"]
RESTRICTED_WSL_DIRS = ["/bin", "/sbin", "/etc", "/boot", "/root", "/dev", "/sys"]

def is_path_safe(path: str) -> bool:
    """Blocks modifications to critical OS directories."""
    path_lower = path.lower()
    for restricted in RESTRICTED_WIN_DIRS:
        if restricted in path_lower: return False
    for restricted in RESTRICTED_WSL_DIRS:
        if path_lower.startswith(restricted): return False
    return True

def is_binary_file(filepath: str) -> bool:
    """Heuristic check to prevent UTF-8 crashes on binary files."""
    try:
        with open(filepath, 'tr') as check_file:
            check_file.read(1024)
            return False
    except UnicodeDecodeError:
        return True
    except OSError:
        return False # Fall back to OS error handling later

def resolve_path(path: str, target_env: str) -> str:
    """Translates file paths between WSL and Windows environments."""
    if not path: return ""
    if target_env == "wsl" and path.lower().startswith("c:\\"):
        try:
            result = subprocess.run(["wslpath", "-u", path], capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            pass
    elif target_env == "windows" and (path.startswith("/mnt/") or path.startswith("/")):
        try:
            result = subprocess.run(["wslpath", "-w", path], capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            pass
    return path

def execute_shell(cmd: List[str]) -> Tuple[bool, str]:
    """Safely executes a shell command."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True, result.stdout.strip()
    except subprocess.CalledProcessError as error:
        return False, error.stderr.strip()

def decode_windows_output(raw: bytes) -> str:
    """Decode Windows CLI output robustly across UTF-8 and legacy code pages."""
    for encoding in ("utf-8", "cp1252", "utf-16le"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")

def resolve_es_exe() -> Optional[str]:
    """Find es.exe from WSL even when it is not exposed on the Linux PATH."""
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
                normalized = line.strip().replace('\\', '/')
                if normalized.lower().endswith('/es.exe'):
                    wsl = resolve_path(line.strip(), "wsl")
                    if wsl and os.path.exists(wsl):
                        return wsl
        except Exception:
            pass

    return None

def hybrid_file_io(action: str, source_path: str, destination_path: Optional[str] = None, content: Optional[str] = None, target_env: str = "wsl", overwrite: bool = False, is_confirmed: bool = False) -> Dict[str, Any]:
    """Hardened read/write/move operations with safety checks."""
    src = resolve_path(source_path, target_env)
    dst = resolve_path(destination_path, target_env) if destination_path else ""

    # Security: Path validation
    if action in ["write", "copy", "move", "delete", "mkdir"]:
        if not is_path_safe(src) or (dst and not is_path_safe(dst)):
            return {"success": False, "error": "SECURITY VIOLATION: Access to protected OS directory blocked."}

    # Security: Destructive Action Confirmation
    if action == "delete" or (action == "write" and overwrite):
        if not is_confirmed:
             return {"success": False, "error": "DESTRUCTIVE ACTION BLOCKED. You must review the target path and explicitly pass 'is_confirmed=True' to execute this command."}

    if action == "read":
        if not os.path.exists(src):
            return {"success": False, "error": "File not found"}
        if is_binary_file(src):
            return {"success": False, "error": "Cannot read binary file as text."}
        try:
            with open(src, "r", encoding="utf-8") as file_handle:
                return {"success": True, "data": file_handle.read()}
        except PermissionError:
            return {"success": False, "error": "Permission Denied (Errno 13). If on Windows, the file may be locked by another process."}

    elif action == "write":
        mode = "w" if overwrite else "a"
        try:
            # Preserve existing line endings by not forcing newline translation
            with open(src, mode, encoding="utf-8", newline='') as file_handle:
                if content:
                    file_handle.write(content)
            return {"success": True, "message": "File written successfully"}
        except PermissionError:
            return {"success": False, "error": "Permission Denied. File is locked or requires elevated privileges."}

    elif action == "copy":
        if not dst: return {"success": False, "error": "Destination required"}
        success, output = execute_shell(["cp", "-r", src, dst])
        return {"success": success, "message": output if success else output}

    elif action == "move":
        if not dst: return {"success": False, "error": "Destination required"}
        success, output = execute_shell(["mv", src, dst])
        return {"success": success, "message": output if success else output}

    elif action == "mkdir":
        success, output = execute_shell(["mkdir", "-p", src])
        return {"success": success, "message": "Directory created" if success else output}

    elif action == "delete":
        success, output = execute_shell(["rm", "-rf", src])
        return {"success": success, "message": "Deleted" if success else output}

    return {"success": False, "error": "Invalid action"}

def catalog_directory(target_path: str, max_depth: int = 2, include_extensions: Optional[List[str]] = None, exclude_hidden: bool = True, target_env: str = "auto", limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    """Paginated hierarchical directory mapping."""
    resolved_path = resolve_path(target_path, target_env)
    if not os.path.isdir(resolved_path):
        return {"success": False, "error": "Directory not found."}

    if include_extensions:
        include_extensions = [ext.lower() if ext.startswith('.') else f'.{ext.lower()}' for ext in include_extensions]

    catalog_output = []
    base_level = resolved_path.rstrip(os.sep).count(os.sep)

    try:
        for root, dirs, files in os.walk(resolved_path):
            current_level = root.count(os.sep)
            depth = current_level - base_level
            if depth > max_depth:
                del dirs[:]
                continue
            if exclude_hidden:
                dirs[:] = [d for d in dirs if not d.startswith('.')]

            indent = "  " * depth
            folder_name = os.path.basename(root) or root
            catalog_output.append(f"{indent}📂 {folder_name}/")

            for file in files:
                if exclude_hidden and file.startswith('.'): continue
                if include_extensions:
                    _, ext = os.path.splitext(file)
                    if ext.lower() not in include_extensions: continue
                catalog_output.append(f"{indent}  📄 {file}")

        # Pagination Logic
        total_items = len(catalog_output)
        paginated_output = catalog_output[offset : offset + limit]
        
        return {
            "success": True, 
            "data": "\n".join(paginated_output),
            "meta": {
                "total_found": total_items,
                "showing": f"{offset} to {min(offset+limit, total_items)}",
                "has_more": offset + limit < total_items
            }
        }
    except Exception as e:
         return {"success": False, "error": str(e)}

def system_locator(query: str, target_env: str = "everywhere", exact_match: bool = False, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    """Paginated global search."""
    results = []
    if target_env in ["wsl", "everywhere"]:
        try:
            wsl_cmd = ["find", "/", "-path", "/mnt", "-prune", "-o", "-iname", query if exact_match else f"*{query}*", "-print"]
            process = subprocess.run(wsl_cmd, capture_output=True, text=True)
            if process.stdout: results.extend(process.stdout.strip().split('\n'))
        except Exception as e: results.append(f"[WSL Error]: {str(e)}")

    if target_env in ["windows", "everywhere"]:
        try:
            es_exe = resolve_es_exe()
            if not es_exe:
                results.append("[Windows Error]: es.exe not found. Check Everything installation or Windows PATH.")
            else:
                win_cmd = [es_exe, f'"{query}"' if exact_match else query]
                process = subprocess.run(win_cmd, capture_output=True)
                if process.returncode == 0 and process.stdout:
                    output = decode_windows_output(process.stdout)
                    results.extend([p.strip() for p in output.strip().split('\n') if p.strip()])
                elif process.stderr:
                    results.append(f"[Windows Error]: {decode_windows_output(process.stderr).strip()}")
        except Exception as e: results.append(f"[Windows Error]: {str(e)}")

    if not results: return {"success": False, "message": "No files found."}

    total_items = len(results)
    paginated_results = results[offset : offset + limit]

    return {
        "success": True, 
        "data": "\n".join(paginated_results),
        "meta": {"total_found": total_items, "has_more": offset + limit < total_items}
    }

def content_locator(query: str, target_env: str = "everywhere", wsl_search_path: str = "/", limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    """Paginated deep content search."""
    results = []
    if target_env in ["wsl", "everywhere"]:
        try:
            # grep handles its own limit per file (-m 2), but we capture everything for Python to paginate
            wsl_cmd = ["grep", "-rni", "-m", "2", "--exclude-dir=/mnt", query, wsl_search_path]
            process = subprocess.run(wsl_cmd, capture_output=True, text=True)
            if process.stdout: results.extend([f"WSL: {line}" for line in process.stdout.strip().split('\n')])
        except Exception as e: results.append(f"[WSL Grep Error]: {str(e)}")

    if target_env in ["windows", "everywhere"]:
        try:
            url = f"http://127.0.0.1:9921/search?q={urllib.parse.quote(query)}" 
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    for item in data.get("results", []): 
                        results.append(f"Windows: {item.get('path', '')} | Snippet: {item.get('snippet', '')}")
        except Exception as e: results.append(f"[AnyTXT API Error]: {str(e)}")

    if not results: return {"success": False, "message": "No content found."}
    
    total_items = len(results)
    return {
        "success": True,
        "data": "\n".join(results[offset : offset + limit]),
        "meta": {"total_found": total_items, "has_more": offset + limit < total_items}
    }
