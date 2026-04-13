#!/usr/bin/env python3
"""Install deps, register MCP (mcporter), optional OpenClaw allowlist, post-install health checks."""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
from typing import List, Optional, Sequence

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Safe at module level: bridge_search.health does NOT depend on mcp.
# If that ever changes, defer this import or guard it.
from bridge_search.health import check_health, run_command_capture  # noqa: E402


DEFAULT_ANYTXT_URL = "http://127.0.0.1:9921/search"


def run_command(cmd: Sequence[str], description: str) -> bool:
    print(f"[*] {description}...")
    try:
        subprocess.run(list(cmd), check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        err = e.stderr or e.stdout or str(e)
        print(f"[!] Error: {err}")
        return False


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Install Bridge Search MCP (bridge-search): pip deps, mcporter, OpenClaw allowlist.",
    )
    p.add_argument(
        "--venv",
        action="store_true",
        help="Create or reuse a venv at --venv-path and register that Python with mcporter (recommended for isolation).",
    )
    p.add_argument(
        "--venv-path",
        default=".venv",
        metavar="DIR",
        help="Venv directory relative to repo root (default: .venv).",
    )
    p.add_argument(
        "--dev",
        action="store_true",
        help="Also install requirements-dev.txt (pytest, etc.).",
    )
    p.add_argument(
        "--skip-checks",
        action="store_true",
        help="Skip AnyTXT HTTP and Everything (es.exe) post-install probes.",
    )
    p.add_argument(
        "--anytxt-url",
        default=DEFAULT_ANYTXT_URL,
        metavar="URL",
        help="Runtime/search URL for AnyTXT HTTP (default: http://127.0.0.1:9921/search). Accepts either a base URL or the full /search endpoint.",
    )
    p.add_argument(
        "--restart-gateway",
        action="store_true",
        help="If openclaw is on PATH, run: openclaw gateway restart (may interrupt sessions).",
    )
    p.add_argument(
        "--openclaw-allowlist",
        action="store_true",
        help="Explicitly update ~/.openclaw/openclaw.json to add bridge-search to alsoAllow for the main agent.",
    )
    return p.parse_args()


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ensure_venv(venv_path: str) -> str:
    """Return path to venv python3 executable."""
    root = _repo_root()
    vdir = os.path.join(root, venv_path)
    py = os.path.join(vdir, "bin", "python3")
    if os.path.isfile(py):
        print(f"[*] Using existing venv: {vdir}")
        return py
    print(f"[*] Creating venv: {vdir}")
    if not run_command(
        [sys.executable, "-m", "venv", vdir],
        f"Creating virtual environment at {vdir}",
    ):
        sys.exit(1)
    if not os.path.isfile(py):
        print(f"[!] Expected {py} after venv creation")
        sys.exit(1)
    return py


def _pip_install(
    python_exe: str,
    requirements_txt: Optional[str],
    requirements_dev: Optional[str],
    user: bool,
) -> bool:
    if requirements_txt and os.path.isfile(requirements_txt):
        cmd: List[str] = [python_exe, "-m", "pip", "install", "-r", requirements_txt]
        if user:
            cmd.append("--user")
        if not run_command(cmd, f"Installing dependencies from {requirements_txt}"):
            return False
    else:
        cmd = [python_exe, "-m", "pip", "install", "mcp==1.27.0"]
        if user:
            cmd.append("--user")
        if not run_command(cmd, "Installing mcp Python package (requirements.txt missing)"):
            return False

    if requirements_dev and os.path.isfile(requirements_dev):
        cmd = [python_exe, "-m", "pip", "install", "-r", requirements_dev]
        if user:
            cmd.append("--user")
        if not run_command(cmd, f"Installing dev dependencies from {requirements_dev}"):
            return False
    return True


def _health_checks(anytxt_url: str) -> bool:
    """Return True if all required probes pass."""
    # We override the AnyTXT URL via env for the health check if the user provided one on CLI
    if anytxt_url != DEFAULT_ANYTXT_URL:
        os.environ["BRIDGE_SEARCH_ANYTXT_URL"] = anytxt_url

    results = check_health()
    
    for err in results["errors"]:
        print(f"[!] {err['message']}")
    
    for warn in results["warnings"]:
        print(f"[~] {warn['message']}")
        
    for name, stat in results["backends"].items():
        if stat["enabled"] and stat.get("status") == "ok":
            print(f"[+] {name} backend OK.")

    return results["overall_success"]


def _mcporter_register(python_exe: str, server_path: str, mcporter_config: str) -> bool:
    d = os.path.dirname(mcporter_config)
    if d:
        os.makedirs(d, exist_ok=True)
    cmd = [
        "mcporter",
        "config",
        "add",
        "bridge-search",
        "--command",
        python_exe,
        "--arg",
        server_path,
        "--description",
        "WSL-to-Windows search bridge (Everything/AnyTXT)",
        "--persist",
        mcporter_config,
    ]
    print("[*] Registering MCP server via mcporter...")
    code, out, err = run_command_capture(cmd, timeout=60)
    if code == 0:
        return True
    combined = (err or "") + (out or "")
    if "already exists" in combined.lower() or "duplicate" in combined.lower():
        print("[~] Existing mcporter entry detected, replacing it...")
        rm_code, rm_out, rm_err = run_command_capture(
            ["mcporter", "config", "remove", "bridge-search", "--persist", mcporter_config], timeout=60
        )
        if rm_code == 0:
            code, out, err = run_command_capture(cmd, timeout=60)
            if code == 0:
                return True
            combined = (err or "") + (out or "")
    print(f"[!] mcporter config add failed: {combined.strip()}")
    print(
        "[i] If the server already exists, try:\n"
        "    mcporter config remove bridge-search\n"
        f"    # then re-run this script (config file: {mcporter_config})"
    )
    return False


def _write_runtime_config(repo_root: str, anytxt_url: str) -> str:
    from bridge_search.config import normalize_anytxt_url
    config_dir = os.path.join(repo_root, "config")
    config_path = os.path.join(config_dir, "bridge-search.config.json")
    base = {"version": 1, "service": {"anytxt_url": normalize_anytxt_url(anytxt_url)}}
    os.makedirs(config_dir, exist_ok=True)
    if os.path.isfile(config_path):
        with open(config_path, "r", encoding="utf-8") as handle:
            try:
                current = json.load(handle)
            except json.JSONDecodeError:
                current = {}
        merged = copy.deepcopy(current) if isinstance(current, dict) else {}
        merged.setdefault("service", {})
        merged["service"]["anytxt_url"] = base["service"]["anytxt_url"]
        payload = merged
    else:
        payload = base
    with open(config_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    return config_path


def _openclaw_allowlist(skill_name: str, config_path: str) -> None:
    if not os.path.exists(config_path):
        print("[~] OpenClaw config not found. Skipping OpenClaw-specific setup.")
        return
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
        else:
            print("[~] bridge-search already in alsoAllow for main.")
    except OSError as e:
        print(f"[!] Failed to update openclaw.json: {e}")


def _print_openclaw_manual_steps(skill_name: str, config_path: str) -> None:
    print("[~] OpenClaw auto-allowlist is disabled by default.")
    print(
        f"[i] To enable manually, add `{skill_name}` to the relevant agent tools.alsoAllow in {config_path}, then run `openclaw gateway restart`."
    )


def _openclaw_verify() -> None:
    code, out, err = run_command_capture(["openclaw", "skills", "list"], timeout=45)
    if code != 0:
        print(f"[~] Could not run openclaw skills list: {err or out or code}")
        return
    if "bridge-search" in out:
        print("[+] openclaw skills list includes bridge-search.")
    else:
        print("[~] bridge-search not seen in openclaw skills list output (check config / gateway).")


def _maybe_restart_gateway() -> None:
    code, out, err = run_command_capture(["openclaw", "gateway", "restart"], timeout=120)
    if code == 0:
        print("[+] openclaw gateway restart completed.")
    else:
        print(f"[!] openclaw gateway restart failed: {err or out or code}")


def setup(args: argparse.Namespace) -> None:
    base_dir = _repo_root()
    os.chdir(base_dir)
    skill_name = "bridge-search"
    server_path = os.path.join(base_dir, "scripts", "server.py")
    requirements_txt = os.path.join(base_dir, "requirements.txt")
    requirements_dev = os.path.join(base_dir, "requirements-dev.txt")
    config_path = os.path.expanduser("~/.openclaw/openclaw.json")
    mcporter_config = os.path.expanduser("~/.mcporter/mcporter.json")

    print(f"🚀 Initializing {skill_name} setup (repo: {base_dir})")

    if args.venv:
        python_exe = _ensure_venv(args.venv_path)
        user = False
    else:
        python_exe = sys.executable
        user = True

    if not _pip_install(python_exe, requirements_txt, requirements_dev if args.dev else None, user):
        sys.exit(1)

    runtime_config_path = _write_runtime_config(base_dir, args.anytxt_url)
    print(f"[+] Runtime config updated: {runtime_config_path}")

    if not _mcporter_register(python_exe, server_path, mcporter_config):
        sys.exit(1)

    if args.openclaw_allowlist:
        _openclaw_allowlist(skill_name, config_path)
    else:
        _print_openclaw_manual_steps(skill_name, config_path)

    if not args.skip_checks:
        if not _health_checks(args.anytxt_url):
            print("[!] Health checks reported issues. Fix Windows services or use --skip-checks.")
            sys.exit(1)
    else:
        print("[~] Skipping post-install health checks (--skip-checks).")

    _openclaw_verify()

    if args.restart_gateway:
        _maybe_restart_gateway()

    print("\n✅ Setup complete!")
    print("-" * 30)
    print(f"Server Path: {server_path}")
    print(f"Python: {python_exe}")
    print("-" * 30)
    print("For JSON MCP configs, use command + args array (not a single shell string), especially when paths contain spaces.")
    print("\nFor Claude Desktop / Cursor / Windsurf, add this to your MCP config:")
    print(
        json.dumps(
            {"mcpServers": {"bridge-search": {"command": python_exe, "args": [server_path]}}},
            indent=2,
        )
    )
    print("\nAgents can now use tools from bridge-search.")
    print(
        "Tip: `python3 scripts/setup_skill.py --help` — "
        "--venv, --dev, --skip-checks, --anytxt-url, --restart-gateway, --openclaw-allowlist"
    )


if __name__ == "__main__":
    setup(parse_args())
