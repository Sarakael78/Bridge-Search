import os
import json
import subprocess
import sys

def run_command(cmd, description):
    print(f"[*] {description}...")
    try:
        subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"[!] Error: {e.stderr}")
        return False

def setup():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    skill_name = "wsl-windows-bridge"
    server_path = os.path.join(base_dir, "scripts", "server.py")
    config_path = os.path.expanduser("~/.openclaw/openclaw.json")
    mcporter_config = os.path.expanduser("~/.mcporter/mcporter.json")

    print(f"🚀 Initializing {skill_name} setup...")

    # 1. Install Dependencies
    run_command(f"{sys.executable} -m pip install mcp --user", "Installing 'mcp' Python package")

    # 2. Register with mcporter
    mcporter_cmd = (
        f"mcporter config add windows-bridge "
        f"--command \"python3 {server_path}\" "
        f"--description \"WSL-to-Windows search bridge (Everything/AnyTXT)\" "
        f"--config {mcporter_config}"
    )
    # Ensure directory exists
    os.makedirs(os.path.dirname(mcporter_config), exist_ok=True)
    run_command(mcporter_cmd, "Registering MCP server via mcporter")

    # 3. Update openclaw.json
    if os.path.exists(config_path):
        print("[*] OpenClaw detected. Updating openclaw.json permissions...")
        try:
            with open(config_path, "r") as f:
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
                with open(config_path, "w") as f:
                    json.dump(data, f, indent=2)
                print("[+] Successfully added to OpenClaw 'main' agent allowlist.")
        except Exception as e:
            print(f"[!] Failed to update openclaw.json: {e}")
    else:
        print("[~] OpenClaw config not found. Skipping OpenClaw-specific setup.")

    # 4. Final Instructions
    print("\n✅ Setup complete!")
    print("-" * 30)
    print(f"Server Path: {server_path}")
    print("-" * 30)
    print("\nFor Claude Desktop / Cursor / Windsurf, add this to your MCP config:")
    print(json.dumps({
        "mcpServers": {
            "wsl-bridge": {
                "command": "python3",
                "args": [server_path]
            }
        }
    }, indent=2))
    print("\nAgents can now use tools from 'wsl-windows-bridge'.")


if __name__ == "__main__":
    setup()
