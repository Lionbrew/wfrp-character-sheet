#!/bin/bash
# WFRP4e Character Sheet — macOS / Linux Launcher
# Double-click this file (or run: bash "WFRP Character Sheet.command") to start.

# Move to the script's directory so relative paths work
cd "$(dirname "$0")"

echo ""
echo "============================================================"
echo "  WFRP4e Character Sheet — Starting..."
echo "============================================================"
echo ""

# Check Python 3
if ! command -v python3 &>/dev/null; then
    echo "  ERROR: Python 3 is not installed."
    echo ""
    echo "  macOS:  brew install python"
    echo "          or download from https://www.python.org/downloads/"
    echo ""
    echo "  Linux:  sudo apt install python3  (Ubuntu/Debian)"
    echo "          sudo dnf install python3  (Fedora)"
    echo ""
    read -p "  Press Enter to exit..." _
    exit 1
fi

# Install pypdf if missing
python3 -c "import pypdf" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "  Installing required package: pypdf..."
    echo "  (This only happens once)"
    echo ""
    pip3 install pypdf
    if [ $? -ne 0 ]; then
        echo ""
        echo "  ERROR: Failed to install pypdf."
        echo "  Please run:  pip3 install pypdf"
        echo ""
        read -p "  Press Enter to exit..." _
        exit 1
    fi
    echo ""
    echo "  Package installed successfully!"
    echo ""
fi

echo "  Launching WFRP4e Character Sheet..."
echo ""
python3 wfrp_app.py
