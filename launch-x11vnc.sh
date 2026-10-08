#!/usr/bin/env bash
set -e

if [ -n "$VNC_PASSWORD" ]; then
    echo "[VNC] A ativar proteção por palavra-passe para VNC/noVNC..."
    mkdir -p ~/.vnc
    x11vnc -storepasswd "$VNC_PASSWORD" ~/.vnc/passwd
    exec x11vnc -display :99 -forever -shared -rfbauth ~/.vnc/passwd -rfbport 5900 -noxdamage -wait 50
else
    echo "[VNC] A iniciar VNC sem palavra-passe (acesso direto)."
    exec x11vnc -display :99 -forever -shared -nopw -rfbport 5900 -noxdamage -wait 50
fi
