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

## 📦 Installation

### 1. Windows Prerequisites
- Install **[Everything](https://www.voidtools.com/)** and ensure it is running.
- Install **[AnyTXT Searcher](https://anytxt.net/)**.
- Enable the **AnyTXT HTTP Search Service** on port **9921**.

### 2. WSL Setup
Clone this repository into your OpenClaw workspace:
```bash
git clone https://github.com/Sarakael78/wsl-windows-bridge.git
```

### 3. Register MCP Server
Register the server with `mcporter` or your preferred MCP host:
```bash
mcporter config add wsl-bridge --command "python3 /path/to/scripts/server.py" --description "WSL-to-Windows search bridge"
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
