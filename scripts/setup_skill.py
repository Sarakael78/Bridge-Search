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
        print("[*] Updating openclaw.json permissions...")
        try:
            with open(config_path, "r") as f:
                data = json.load(f)
            
            # Find the 'main' agent and add to alsoAllow
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
                print("[+] Successfully added skill to 'main' agent allowlist.")
            else:
                print("[~] Skill already allowed in openclaw.json.")
        except Exception as e:
            print(f"[!] Failed to update openclaw.json: {e}")

    print("\n✅ Setup complete!")
    print(f"Agents can now use tools from the '{skill_name}' skill.")
    print("Remember to restart the OpenClaw Gateway if it is currently running.")

if __name__ == "__main__":
    setup()
