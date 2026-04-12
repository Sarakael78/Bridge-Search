import json
from typing import Optional, List
from mcp.server.fastmcp import FastMCP
from bridge_tools import hybrid_file_io, catalog_directory, system_locator, content_locator

mcp = FastMCP("OS-Bridge-Manipulator")

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
    mcp.run("stdio")
