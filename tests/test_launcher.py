import shlex
import shutil
import sys
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_launcher_discovers_tools_from_outside_checkout(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1]
    checkout = tmp_path / "windows search"
    interpreter = checkout / ".venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} \"$@\"\n", encoding="utf-8")
    interpreter.chmod(0o755)
    for directory in ("bridge_search", "scripts"):
        (checkout / directory).symlink_to(source / directory, target_is_directory=True)
    launcher = checkout / "start-bridge-search.sh"
    shutil.copy2(source / launcher.name, launcher)

    async def discover() -> None:
        params = StdioServerParameters(
            command=str(launcher),
            cwd=tmp_path,
            env={"PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"},
        )
        with anyio.fail_after(10):
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as client:
                    result = await client.initialize()
                    assert result.serverInfo.name == "bridge-search"
                    tools = await client.list_tools()
                    assert "locate_file_or_folder" in {tool.name for tool in tools.tools}

    anyio.run(discover)
