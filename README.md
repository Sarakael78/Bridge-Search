# WSL Windows Bridge

A high-performance "Nexus" for cross-OS search and file management between WSL2 and Windows. This repository provides a **Skill** for behavioral guardrails and an **MCP Server** for technical execution.

## 🚀 Overview

The **WSL Windows Bridge** solves the 9P filesystem performance bottleneck in WSL2 by leveraging native Windows indexed search tools:
- **Everything (Voidtools)**: Instant filename and path discovery.
- **AnyTXT Searcher**: Full-text content search via HTTP API.

## 🛠️ Features (MCP Tools)

- `locate_file_or_folder`: Rapidly search the entire Windows host using Everything (`es.exe`).
- `locate_content_inside_files`: Search for text inside files using AnyTXT's indexed content search.
- `map_directory`: Generate hierarchical directory maps with pagination.
- `manage_file`: Robust cross-OS file operations (read, write, move, delete) with built-in path translation.

---

### 🚀 Agent-Led Installation (Automated)

**Directive to Agents**: If you are an OpenClaw agent tasked with installing this skill, you can automate the entire setup process by running the following command from the repository root:

```bash
python3 scripts/setup_skill.py
```

This script will:
1.  Install the `mcp` Python package via `pip --user`.
2.  Register the MCP server with your `mcporter` configuration.
3.  Automatically update `~/.openclaw/openclaw.json` to add `wsl-windows-bridge` to the `main` agent's `alsoAllow` list.

---

## 📦 Manual Installation

Follow these steps to establish the bridge between your WSL2 environment and the Windows host.

### 1. Windows Host Setup

#### **A. Voidtools Everything (Filename Search)**
1.  **Download & Install**: Get the [Everything installer](https://www.voidtools.com/downloads/).
2.  **Verify Service**: Ensure the "Everything Service" is running (Tools -> Options -> General -> Everything Service).
3.  **Command-Line Interface**: Ensure `es.exe` is available. The bridge will automatically look in `C:\Program Files\Everything\`, but adding it to your Windows `PATH` is recommended.

#### **B. AnyTXT Searcher (Content Search)**
1.  **Download & Install**: Get [AnyTXT Searcher](https://anytxt.net/).
2.  **Enable HTTP Search Service**:
    *   Open AnyTXT Searcher.
    *   Go to **Tool -> HTTP Search Service**.
    *   Set the **Port** to `9921` (this matches the bridge's default).
    *   Click **Start**.
    *   *Note*: If you use a different port, you must update `scripts/bridge_tools.py`.

---

### 2. WSL2 Setup

#### **A. Clone the Repository**
Clone this repository into your OpenClaw `skills/` directory (or any preferred location):
```bash
cd ~/.openclaw/workspace/skills
git clone https://github.com/Sarakael78/wsl-windows-bridge.git
cd wsl-windows-bridge
```

#### **B. Install Python Dependencies**
The bridge requires Python 3.10+ and the `mcp` package. It is recommended to use a virtual environment or install globally for your user:
```bash
# Using a virtual environment (Recommended)
python3 -m venv venv
source venv/bin/activate
pip install mcp

# OR install globally for your user
pip install mcp --user
```

#### **C. Verify Connectivity**
Test if WSL can reach the Windows AnyTXT service:
```bash
curl http://127.0.0.1:9921/
```

---

### 3. Registering the MCP Server

The bridge tools are exposed via an MCP server (`scripts/server.py`). You can register this with any MCP-compatible host.

#### **Using `mcporter` (OpenClaw Standard)**
Run this command from within the repository to register the server persistently:
```bash
mcporter config add wsl-bridge \
  --command "python3 $(pwd)/scripts/server.py" \
  --description "WSL-to-Windows search bridge (Everything/AnyTXT)"
```

---

### 4. Enabling for OpenClaw Agents

To allow an OpenClaw agent to use this bridge, you must ensure the skill is "allowed" in your `openclaw.json` config.

#### **A. Add to `alsoAllow`**
Find your agent configuration in `~/.openclaw/openclaw.json` and add `wsl-windows-bridge` to the `alsoAllow` list:

```json
{
  "agents": {
    "list": [
      {
        "id": "main",
        "tools": {
          "alsoAllow": [
            "wsl-windows-bridge",
            "..."
          ]
        }
      }
    ]
  }
}
```

#### **B. Verify Skill Availability**
Run the following command to confirm the skill is recognized and enabled:
```bash
openclaw skills list | grep wsl-windows-bridge
```

#### **C. Reload Agent**
If your OpenClaw Gateway is already running, you may need to restart it to pick up the new skill configuration:
```bash
openclaw gateway restart
```

---

### 5. Manual Integration (Claude Desktop / Windsurf)
Add the following to your `mcp_config.json`:
```json
{
  "mcpServers": {
    "wsl-bridge": {
      "command": "python3",
      "args": ["/absolute/path/to/wsl-windows-bridge/scripts/server.py"]
    }
  }
}
```

## ⚖️ Guardrails (The Absolute Zero Rule)

This bridge enforces strict behavioral rules for agents:
1.  **The Absolute Zero Rule**: If Everything (`es.exe`) returns no hits, **STOP**. Do not fallback to a slow brute-force `find` or `grep` on `/mnt/c/`.
2.  **Service-Only Content Search**: AnyTXT is treated as a networked service on port **9921**. Do not search for local binaries.
3.  **Path Translation**: All tools use `wslpath` internally; never hand-roll path conversions.

## 🧩 Integration

This bridge is designed to be the primary Windows-side discovery provider for legal and research workflows (e.g., `legal-local-research`).

## 📜 License
MIT
