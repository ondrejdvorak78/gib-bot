#!/usr/bin/env bash
# gib-bot setup script for macOS and Linux.
# Run from the gib-bot folder. Requires Python 3.10+ already installed.

set -e

echo "=== gib-bot setup ==="
echo ""

# Pick the python binary
if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "ERROR: no python interpreter found."
    echo "Install Python 3.12+ from https://www.python.org/downloads/ or your"
    echo "system package manager, then re-run this script."
    exit 1
fi

# Create the virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment (.venv)..."
    "$PY" -m venv .venv
fi

# Install dependencies into the venv
echo "Installing dependencies into .venv..."
.venv/bin/python -m pip install -e .

# Copy .env template if .env doesn't exist (preserves any prior edits)
if [ ! -f ".env" ]; then
    echo "Creating .env from template..."
    cp .env.example .env
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Opening .env. Paste in your Helius API key and your wallet pubkey,"
echo "then save and close."
echo ""

# Open .env in a sensible editor for the platform
if [[ "$OSTYPE" == "darwin"* ]]; then
    open -e .env
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open .env >/dev/null 2>&1 &
else
    echo "Could not auto-open an editor. Edit .env manually:"
    echo "  nano .env   (or vim, code, etc.)"
fi

echo ""
echo "To run the bot:"
echo "  source .venv/bin/activate"
echo "  python cli.py inventory   # or plan / simulate / submit"
echo ""
