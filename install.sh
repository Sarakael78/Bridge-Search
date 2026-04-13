#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP_SCRIPT="$SCRIPT_DIR/scripts/setup_skill.py"

if [ ! -f "$SETUP_SCRIPT" ]; then
    echo "Error: setup script not found at $SETUP_SCRIPT"
    echo "Re-clone the repository and try again."
    exit 1
fi

echo "Checking system prerequisites..."

# Check if we are on a Debian/Ubuntu based system before trying to use apt
if command -v apt-get &> /dev/null; then
    MISSING_PKGS=()

    if ! command -v python3 &> /dev/null; then MISSING_PKGS+=("python3"); fi
    if ! command -v pip3 &> /dev/null; then MISSING_PKGS+=("python3-pip"); fi
    if command -v python3 &> /dev/null && ! python3 -c "import venv" &> /dev/null; then MISSING_PKGS+=("python3-venv"); fi

    if [ "${#MISSING_PKGS[@]}" -gt 0 ]; then
        echo "Missing required packages: ${MISSING_PKGS[*]}"
        echo "Please enter your Linux user password (for sudo)."
        if ! command -v sudo &> /dev/null; then
            echo "Error: sudo is required to install missing packages with apt-get."
            echo "Install these packages manually and re-run: ${MISSING_PKGS[*]}"
            exit 1
        fi
        sudo apt-get update
        sudo apt-get install -y "${MISSING_PKGS[@]}"
    else
        echo "All core packages are installed."
    fi
else
    echo "Notice: Not on a Debian/Ubuntu system. Skipping apt dependency checks."
    echo "Ensure python3, pip, and venv are installed via your package manager."
fi

if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is required but was not found on PATH."
    exit 1
fi

if ! python3 -c "import venv" &> /dev/null; then
    echo "Error: Python venv module is missing. Install your distro's venv package and retry."
    exit 1
fi

SETUP_ARGS=("$@")
HAS_VENV=false
for arg in "${SETUP_ARGS[@]}"; do
    if [[ "$arg" == "--venv" ]]; then HAS_VENV=true; break; fi
done
if [[ "$HAS_VENV" == "false" ]]; then
    SETUP_ARGS=(--venv "${SETUP_ARGS[@]}")
fi

echo "Starting Python setup..."
python3 "$SETUP_SCRIPT" "${SETUP_ARGS[@]}"
