#!/usr/bin/env bash
set -euo pipefail

echo "=== Blooms in Gnome Installer ==="
echo ""

echo "1. Installing Python package..."
pip install --break-system-packages -e .

echo ""
echo "2. Installing mount helper..."
mkdir -p "$HOME/.local/bin"
cp blooms_in_gnome/mount.sh "$HOME/.local/bin/blooms-mount"
chmod +x "$HOME/.local/bin/blooms-mount"

echo ""
echo "3. Installing systemd user service..."
mkdir -p "$HOME/.config/systemd/user"
cp blooms.service "$HOME/.config/systemd/user/blooms.service"

echo ""
echo "4. Installing desktop autostart..."
mkdir -p "$HOME/.config/autostart"
cp blooms-in-gnome.desktop "$HOME/.config/autostart/blooms-in-gnome.desktop"
chmod +x "$HOME/.config/autostart/blooms-in-gnome.desktop"

echo ""
echo "5. Installing translations..."
make install-locale 2>/dev/null

echo ""
echo "6. Done!"
echo ""
echo "   Configure your keys:"
echo "     blooms-mount --set-nsec nsec1..."
echo "     blooms-mount --set-npub <hex>"
echo ""
echo "   Start tray icon (auto-mounts + sits in panel):"
echo "     blooms-tray"
echo ""
echo "   Or mount via CLI:"
echo "     blooms-mount --foreground &"
echo "     Files at: ~/Blossom/"
echo ""
echo "   The tray icon will start automatically on next login."
echo "   Language: set BLOOMS_LANG or use system LANG"
