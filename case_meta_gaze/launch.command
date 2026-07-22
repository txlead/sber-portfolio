#!/bin/bash
# ── Meta Orion Gaze Reels — macOS launcher ────────────────────────────────────
# Double-click this file to install dependencies and run the prototype.

cd "$(dirname "$0")"

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║   Meta Orion — Gaze Reels Prototype  ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# ── Check Python 3 ────────────────────────────────────────────────────────────
PYTHON=""
for cmd in python3 python3.12 python3.11 python3.10 python3.9; do
    if command -v "$cmd" &>/dev/null; then
        VER=$("$cmd" -c "import sys; print(sys.version_info.major)")
        if [ "$VER" = "3" ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "  ✗  Python 3 not found."
    echo ""
    echo "  Please install Python 3 from https://www.python.org/downloads/"
    echo "  Then double-click this file again."
    echo ""
    read -p "  Press Enter to close..."
    exit 1
fi

echo "  ✓  Python found: $($PYTHON --version)"

# ── Check webcam permission (macOS) ───────────────────────────────────────────
echo "  →  Note: macOS may ask for Camera permission — please allow it."
echo ""

# ── Install / upgrade dependencies ───────────────────────────────────────────
echo "  →  Installing dependencies (first run may take ~2 minutes)..."
$PYTHON -m pip install --quiet --upgrade pip
$PYTHON -m pip install --quiet -r requirements.txt

if [ $? -ne 0 ]; then
    echo ""
    echo "  ✗  Failed to install dependencies."
    echo "     Try running: pip3 install mediapipe opencv-python numpy Pillow"
    read -p "  Press Enter to close..."
    exit 1
fi

echo "  ✓  Dependencies ready."
echo ""
echo "  ══════════════════════════════════════════"
echo "   Controls:"
echo "   • Look at video  →  Play"
echo "   • Look away      →  Pause"
echo "   • Close eyes 2s  →  Next reel"
echo "   • Gaze down 1.5s →  Like / Save menu"
echo "   • Press Q        →  Quit"
echo "  ══════════════════════════════════════════"
echo ""
echo "  Starting... (calibration takes ~5 seconds)"
echo ""

# ── Launch ────────────────────────────────────────────────────────────────────
$PYTHON main.py

echo ""
read -p "  Closed. Press Enter to exit..."
