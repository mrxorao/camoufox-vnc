#!/usr/bin/env bash
set -e

# Ensure required directories for the profile and downloads
mkdir -p /data/downloads /var/log/supervisor /tmp/.X11-unix /root/profile
rm -rf /root/Downloads
ln -sf /data/downloads /root/Downloads

# Clean up stale X11 and Firefox/Camoufox profile locks
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99
rm -f /root/profile/.parentlock /root/profile/lock /root/profile/.startup-incomplete

# Auto-update on boot: if AUTO_UPDATE=true, update Camoufox and the C++ binaries
if [ "${AUTO_UPDATE:-true}" = "true" ]; then
    echo "============================================================"
    echo "  🔄 [Auto-Update] Checking for the latest Camoufox version..."
    (
        /opt/venv/bin/pip install --upgrade --no-cache-dir "camoufox[geoip]" && \
        /opt/venv/bin/python3 -m camoufox fetch
    ) || echo "  ⚠️ [Auto-Update] Warning: no internet connection, starting with the existing version."
    echo "  ✅ [Auto-Update] Camoufox updated!"
    echo "============================================================"
fi

# Set the default search engine (DuckDuckGo) in the policies.json of every Camoufox version
python3 -c '
import glob, json
for p in glob.glob("/root/.cache/camoufox/browsers/**/distribution/policies.json", recursive=True):
    try:
        with open(p, "r") as f: d = json.load(f)
        d.setdefault("policies", {})["SearchEngines"] = {
            "PreventInstalls": False,
            "Default": "DuckDuckGo",
            "Add": [{
                "Name": "DuckDuckGo",
                "Description": "DuckDuckGo Search",
                "Alias": "@ddg",
                "Method": "GET",
                "URLTemplate": "https://duckduckgo.com/?q={searchTerms}"
            }]
        }
        with open(p, "w") as f: json.dump(d, f, indent=2)
    except Exception: pass
'

echo "============================================================"
echo "  🚀 Camoufox VNC Stealth Browser Server"
echo "  🌐 noVNC Web UI: http://localhost:${PORT_WEB:-5800}"
echo "  🖥️  Direct VNC access: localhost:${PORT_VNC:-5900}"
echo "  🔌 MCP Control API: http://localhost:${PORT_API:-9377}"
echo "  ⚙️  Resolution: ${RESOLUTION_WIDTH:-1366}x${RESOLUTION_HEIGHT:-768}"
echo "  🛡️  Stealth OS emulation: ${OS_SPOOF:-windows}"
echo "============================================================"

exec /usr/bin/supervisord -n -c /etc/supervisor/supervisord.conf
