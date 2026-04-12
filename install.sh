#!/usr/bin/env bash
set -euo pipefail

echo "Checking system prerequisites..."

# Check if we are on a Debian/Ubuntu based system before trying to use apt
if command -v apt-get &> /dev/null; then
    MISSING_PKGS=""

    if ! command -v python3 &> /dev/null; then MISSING_PKGS="$MISSING_PKGS python3"; fi
    if ! command -v pip3 &> /dev/null; then MISSING_PKGS="$MISSING_PKGS python3-pip"; fi
    if ! python3 -c "import venv" &> /dev/null; then MISSING_PKGS="$MISSING_PKGS python3-venv"; fi

    if [ -n "$MISSING_PKGS" ]; then
        echo "Missing required packages:$MISSING_PKGS"
        echo "Please enter your WSL password to install them."
        sudo apt-get update
        # shellcheck disable=SC2086
        sudo apt-get install -y $MISSING_PKGS
    else
        echo "All core packages are installed."
    fi
else
    echo "Notice: Not on a Debian/Ubuntu system. Skipping apt dependency checks."
    echo "Ensure python3, pip, and venv are installed via your package manager."
fi

# Run the actual setup script (from repo root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "Starting Python setup..."
python3 "$SCRIPT_DIR/scripts/setup_skill.py" --venv
