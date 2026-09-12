#!/usr/bin/env bash
# Install and enable the APOLLO session bridge as a user systemd service.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE_SRC="$REPO_DIR/systemd/apollo-bridge.service"
SERVICE_DEST="$HOME/.config/systemd/user/apollo-bridge.service"

echo "→ Installing apollo-bridge.service..."
mkdir -p "$HOME/.config/systemd/user"
cp "$SERVICE_SRC" "$SERVICE_DEST"

echo "→ Reloading systemd user daemon..."
systemctl --user daemon-reload

echo "→ Enabling apollo-bridge to start with graphical session..."
systemctl --user enable apollo-bridge.service

echo "→ Starting apollo-bridge now..."
systemctl --user start apollo-bridge.service

sleep 1
echo ""
echo "Status:"
systemctl --user status apollo-bridge.service --no-pager || true
echo ""
echo "✅ Done. Bridge running on http://127.0.0.1:7734"
echo "   Check health: curl http://127.0.0.1:7734/health"
