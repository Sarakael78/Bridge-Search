import json
import os
import shlex
import subprocess
import sys
from typing import List


def run_command(cmd: List[str], description: str) -> bool:
    print(f"[*] {description}...")
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        err = e.stderr or e.stdout or str(e)
        print(f"[!] Error: {err}")
        return False


def setup() -> None:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    skill_name = "wsl-windows-search-bridge"
    server_path = os.path.join(base_dir, "scripts", "server.py")
    requirements_txt = os.path.join(base_dir, "requirements.txt")
    config_path = os.path.expanduser("~/.openclaw/openclaw.json")
    mcporter_config = os.path.expanduser("~/.mcporter/mcporter.json")

    print(f"🚀 Initializing {skill_name} setup...")

    if os.path.exists(requirements_txt):
        pip_cmd = [sys.executable, "-m", "pip", "install", "-r", requirements_txt, "--user"]
        desc = f"Installing Python dependencies from {requirements_txt}"
    else:
        pip_cmd = [sys.executable, "-m", "pip", "install", "mcp", "--user"]
        desc = "Installing mcp Python package (requirements.txt missing)"

    if not run_command(pip_cmd, desc):
        return

    os.makedirs(os.path.dirname(mcporter_config), exist_ok=True)

    mcporter_args = [
        "mcporter",
        "config",
        "add",
        "wsl-windows-search-bridge",
        "--command",
        f"python3 {shlex.quote(server_path)}",
        "--description",
        "WSL-to-Windows search bridge (Everything/AnyTXT)",
        "--config",
        mcporter_config,
    ]
    if not run_command(mcporter_args, "Registering MCP server via mcporter"):
        return

    if os.path.exists(config_path):
        print("[*] OpenClaw detected. Updating openclaw.json permissions...")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            updated = False
            for agent in data.get("agents", {}).get("list", []):
                if agent.get("id") == "main":
                    tools = agent.setdefault("tools", {})
                    allow_list = tools.setdefault("alsoAllow", [])
                    if skill_name not in allow_list:
                        allow_list.append(skill_name)
                        updated = True

            if updated:
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                print("[+] Successfully added to OpenClaw 'main' agent allowlist.")
        except OSError as e:
            print(f"[!] Failed to update openclaw.json: {e}")
    else:
        print("[~] OpenClaw config not found. Skipping OpenClaw-specific setup.")

    print("\n✅ Setup complete!")
    print("-" * 30)
    print(f"Server Path: {server_path}")
    print("-" * 30)
    print("For JSON MCP configs, use an args array for the server script path (not a single string), especially when paths contain spaces.")
    print("\nFor Claude Desktop / Cursor / Windsurf, add this to your MCP config:")
    print(
        json.dumps(
            {"mcpServers": {"wsl-windows-search-bridge": {"command": "python3", "args": [server_path]}}},
            indent=2,
        )
    )
    print("\nAgents can now use tools from wsl-windows-search-bridge.")


if __name__ == "__main__":
    setup()
