#!/usr/bin/env bash
set -e

# Assegurar layout e limpar modificadores presos (Caps Lock / Shift)
if command -v setxkbmap >/dev/null 2>&1; then
    setxkbmap -display :99 -layout pt,us -option "" 2>/dev/null || true
fi

X11VNC_ARGS="-display :99 -forever -shared -rfbport 5900 -noxdamage -wait 50 -nomodtweak -skip_lockkeys -clear_mods -clear_keys -repeat"

if [ -n "$VNC_PASSWORD" ]; then
    echo "[VNC] A ativar proteção por palavra-passe para VNC/noVNC..."
    mkdir -p ~/.vnc
    x11vnc -storepasswd "$VNC_PASSWORD" ~/.vnc/passwd
    exec x11vnc $X11VNC_ARGS -rfbauth ~/.vnc/passwd
else
    echo "[VNC] A iniciar VNC sem palavra-passe (acesso direto)."
    exec x11vnc $X11VNC_ARGS -nopw
fi
