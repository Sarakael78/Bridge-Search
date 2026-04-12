**Canonical source:** The maintained implementation is `scripts/bridge_tools.py` and `scripts/server.py` in this repository (plus `wsl-windows-search-bridge.config.example.json`). The material below is historical reference; when they disagree with the scripts, trust the scripts.

---

### File 1: `SETUP_DIRECTIVE.md` (Give this to OpenClaw)

```markdown
# OPENCLAW INITIALISATION DIRECTIVE: wsl-windows-search-bridge
**Target Environment:** WSL2 (Ubuntu/Debian) bridged to Windows Host.

## System Objective
You must install, configure, and initialise the **wsl-windows-search-bridge** Model Context Protocol (MCP) server. This server grants you high-performance, cross-environment filesystem manipulation, directory indexing, and instantaneous full-text search capabilities.

## Execution Steps

### Phase 1: Dependency Verification
1. Ensure you are operating within a WSL2 environment.
2. Verify Python 3.10+ is installed.
3. Install the standard MCP Python SDK: run `pip install mcp`.

### Phase 2: File Creation
1. Create `bridge_tools.py` and populate it with the provided logic file.
2. Create `server.py` and populate it with the provided MCP wrapper file.

### Phase 3: Host Configuration Check (User Assistance Required)
For `system_locator` and `content_locator` to function, the Windows host requires specific binaries. **You must stop and ask the user to confirm the following are installed and running on their Windows machine:**
* **Voidtools 'Everything':** The GUI must be running, and the CLI binary (`es.exe`) must be added to the Windows System `PATH`.
* **AnyTXT Searcher:** The application must be installed, and the HTTP Search Service must be enabled (usually on port 9921).
* **wsl.conf Metadata:** Ask the user to confirm if `[automount] options = "metadata"` is set in `/etc/wsl.conf` to ensure file permissions are retained across environments.

### Phase 4: Initialisation
Once the user confirms Phase 3 is complete, execute `python server.py` to start the standard input/output MCP server.

## Operational Parameters
* **Pathing:** Always utilise the `bridge_tools.py` logic to translate paths between `C:\` and `/mnt/c/`.
* **Context Safety:** Do not bypass the truncation limits set in the indexing and search tools; they are designed to protect your context window from saturation.
```

---

File 1: bridge_tools.py (The Hardened Engine)
Replace your existing file with this updated logic.

Python
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
            win_cmd = ["es.exe", f'"{query}"' if exact_match else query]
            process = subprocess.run(win_cmd, capture_output=True, text=True)
            if process.returncode == 0 and process.stdout:
                results.extend([p.strip() for p in process.stdout.strip().split('\n') if p.strip()])
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


    
File 2: server.py (The Updated MCP Interface)
This updates the FastMCP server schema so OpenClaw automatically understands the new confirmation flags and pagination limits.

Python
import json
from typing import Optional, List
from mcp.server.fastmcp import FastMCP
from bridge_tools import hybrid_file_io, catalog_directory, system_locator, content_locator

mcp = FastMCP("wsl-windows-search-bridge")

@mcp.tool()
def manage_file(action: str, source_path: str, destination_path: str = None, content: str = None, target_env: str = "wsl", overwrite: bool = False, is_confirmed: bool = False) -> str:
    """
    Perform robust file operations across NTFS and ext4 filesystems.
    Valid actions: 'read', 'write', 'copy', 'move', 'delete', 'mkdir'.
    SECURITY NOTE: 'delete' and 'overwrite' actions will be BLOCKED unless you explicitly set is_confirmed=True.
    """
    result = hybrid_file_io(action, source_path, destination_path, content, target_env, overwrite, is_confirmed)
    return json.dumps(result, indent=2)

@mcp.tool()
def map_directory(target_path: str, max_depth: int = 2, include_extensions: list[str] = None, exclude_hidden: bool = True, target_env: str = "auto", limit: int = 100, offset: int = 0) -> str:
    """
    Generate a hierarchical map of a directory. 
    Use 'offset' to page through results if 'has_more' returns True.
    """
    result = catalog_directory(target_path, max_depth, include_extensions, exclude_hidden, target_env, limit, offset)
    return json.dumps(result, indent=2)

@mcp.tool()
def locate_file_or_folder(query: str, target_env: str = "everywhere", exact_match: bool = False, limit: int = 100, offset: int = 0) -> str:
    """
    Rapidly search the entire computer. 
    Use 'offset' to page through results if 'has_more' returns True.
    """
    result = system_locator(query, target_env, exact_match, limit, offset)
    return json.dumps(result, indent=2)

@mcp.tool()
def locate_content_inside_files(query: str, target_env: str = "everywhere", wsl_search_path: str = "/", limit: int = 50, offset: int = 0) -> str:
    """
    Search for specific text INSIDE files.
    Use 'offset' to page through results if 'has_more' returns True.
    """
    result = content_locator(query, target_env, wsl_search_path, limit, offset)
    return json.dumps(result, indent=2)

if __name__ == "__main__":
    mcp.run_stdio()