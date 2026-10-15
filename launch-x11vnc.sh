#!/usr/bin/env bash
set -e

# Ensure a full keyboard layout for native PT and US support (Shift / Caps / Accents)
if command -v setxkbmap >/dev/null 2>&1; then
    setxkbmap -display :99 -model pc105 -layout pt,us 2>/dev/null || true
fi

X11VNC_ARGS="-display :99 -forever -shared -rfbport 5900 -noxdamage -wait 50 -xkb -capslock -add_keysyms -repeat -clear_mods -clear_keys"

if [ -n "$VNC_PASSWORD" ]; then
    echo "[VNC] Enabling VNC/noVNC password protection..."
    mkdir -p ~/.vnc
    x11vnc -storepasswd "$VNC_PASSWORD" ~/.vnc/passwd
    exec x11vnc $X11VNC_ARGS -rfbauth ~/.vnc/passwd
else
    echo "[VNC] Starting VNC without a password (direct access)."
    exec x11vnc $X11VNC_ARGS -nopw
fi
