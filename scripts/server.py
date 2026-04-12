from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from bridge_tools import hybrid_file_io, catalog_directory, system_locator, content_locator

mcp = FastMCP("wsl-windows-search-bridge")


@mcp.tool()
def manage_file(
    action: str,
    source_path: str,
    destination_path: Optional[str] = None,
    content: Optional[str] = None,
    target_env: str = "wsl",
    overwrite: bool = False,
    is_confirmed: bool = False,
) -> dict[str, Any]:
    """
    Perform robust file operations across NTFS and ext4 filesystems.
    Valid actions: 'read', 'write', 'copy', 'move', 'delete', 'mkdir'.
    is_confirmed is a workflow flag for the agent, not cryptographic proof of human approval.
    Writes (including append) and deletes require is_confirmed=True after path review.
    """
    return hybrid_file_io(action, source_path, destination_path, content, target_env, overwrite, is_confirmed)


@mcp.tool()
def map_directory(
    target_path: str,
    max_depth: int = 2,
    include_extensions: Optional[list[str]] = None,
    exclude_hidden: bool = True,
    target_env: str = "auto",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """
    Generate a hierarchical map of a directory.
    limit is capped (500); use offset to page when has_more is true.
    max_depth is capped (20).
    """
    return catalog_directory(
        target_path, max_depth, include_extensions, exclude_hidden, target_env, limit, offset
    )


@mcp.tool()
def locate_file_or_folder(
    query: str,
    target_env: str = "windows",
    exact_match: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """
    Filename search: Everything (es.exe) on Windows; optional WSL find (HOME by default, not full '/').
    Use target_env 'everywhere' for both, 'wsl' for Linux-side find only, 'windows' for Everything only.
    limit/offset are capped (500 / 50000); results may truncate at a high water mark.
    When allowed_prefixes (config) or WSL_WINDOWS_SEARCH_BRIDGE_ALLOWED_PREFIXES is set, returned path rows are filtered to paths under those prefixes (same policy as file operations).
    is_confirmed on other tools is a workflow flag for the agent, not cryptographic authorization or a substitute for OS-level approval.
    """
    return system_locator(query, target_env, exact_match, limit, offset)


@mcp.tool()
def locate_content_inside_files(
    query: str,
    target_env: str = "everywhere",
    wsl_search_path: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """
    Search for text inside files (grep on WSL, AnyTXT HTTP on Windows).
    Empty wsl_search_path searches under HOME. Grep from '/' requires WSL_WINDOWS_SEARCH_BRIDGE_ALLOW_ROOT_GREP=1 (or legacy WSL_BRIDGE_ALLOW_ROOT_GREP=1).
    When allowed_prefixes (config) or WSL_WINDOWS_SEARCH_BRIDGE_ALLOWED_PREFIXES is set, result lines are filtered to paths under those prefixes (Everything/find rows, WSL grep hits, and AnyTXT rows).
    is_confirmed on other tools is a workflow flag for the agent, not cryptographic authorization or a substitute for OS-level approval.
    """
    return content_locator(query, target_env, wsl_search_path, limit, offset)


if __name__ == "__main__":
    mcp.run("stdio")
