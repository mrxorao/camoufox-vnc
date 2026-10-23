# 🦊 Camoufox VNC & Camoufox MCP — Stealth Browser in Docker with Live noVNC & MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Docker Image](https://img.shields.io/badge/Docker-mrxorao%2Fcamoufox--vnc-blue.svg)](https://hub.docker.com/r/mrxorao/camoufox-vnc)
[![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io)

**Camoufox VNC** meets **Camoufox MCP**: A self-contained, anti-detect Docker stealth browser environment combining live **noVNC** visual streaming (`:5800`) and a native **Model Context Protocol (MCP)** server (14 tools) for AI coding agents (Claude, Cursor, Antigravity, OpenCode, Windsurf).

---

## ✨ Key Features

* 🛡️ **Camoufox Anti-Detect Core:** C++ stealth Firefox fork with fingerprint spoofing (`navigator.webdriver = false`, WebGL, Canvas, Audio, GPU, font randomization).
* 🌐 **Camoufox VNC (Live Visual Stream):** Watch every click, search, and navigation in real time directly in your browser on `http://localhost:5800` (auto-connects with zero clicks).
* 🔌 **Camoufox MCP Server (14 Native Tools):** Complete direct control for AI agents with navigation, typing, Bézier clicks, screenshots, tab management, file uploads and JS execution.
* 🖱️ **Humanized Bézier Mouse Physics:** Smooth cubic Bézier mouse movement with variable acceleration and micro-jitter that bypasses bot movement detectors.
* 📑 **Single-Window Tab Management:** Clean single-window tab workflow (`browse_new_tab`, `browse_tabs`, `browse_switch_tab`, `browse_close_tab`) preventing messy multi-window states.
* 📎 **File Upload & Download Support:** Upload host files straight into `<input type='file'>` elements and keep downloads in `./data/downloads`.
* 🔄 **Auto-Update on Boot:** Automatically fetches and updates the latest Camoufox engine and C++ binaries on container startup.
* 💾 **Session & Login Persistence:** Dedicated Docker volume preserving cookies, logins, history and extensions.

---

## 🚀 Run Locally

### 1. Start the container
```bash
docker compose up -d
```

### 2. Open the visual interface
* **Web browser (noVNC):** [http://localhost:5800](http://localhost:5800)
* **Direct VNC client:** `localhost:5900`

### 3. Stop the container
```bash
docker compose down
```

---

## ☁️ Deploy on a VPS (1 file)

On a remote VPS (Ubuntu, Debian, etc.) you don't need to clone the whole repo or build anything — just use the pre-built public image:

1. Create a folder on the VPS:
   ```bash
   mkdir -p ~/camoufox && cd ~/camoufox
   ```
2. Copy [`docker-compose.vps.example.yml`](./docker-compose.vps.example.yml) to the VPS as `docker-compose.yml`.
3. Start the service (public image, no login required):
   ```bash
   docker compose up -d
   ```
4. Open `http://YOUR_VPS_IP:5800` in your browser.

Or without compose:
```bash
docker run -d --name camoufox-vnc --shm-size=2g \
  -p 5800:5800 -p 5900:5900 -p 9377:9377 \
  -e VNC_PASSWORD=change_this_secure_password \
  -v camoufox_profile:/root/profile \
  xorao/camoufox-vnc:latest
```

---

## 🔌 MCP Setup (OpenCode, Cursor, Claude Desktop)

Add to your MCP config file (`mcp_config.json` or `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "camoufox": {
      "command": "node",
      "args": [
        "/path/to/camoufox-vnc/mcp_vnc_bridge.js"
      ],
      "env": {
        "CAMOUFOX_API_URL": "http://127.0.0.1:9377"
      }
    }
  }
}
```

> **If Docker runs on a remote VPS:**
> Replace `http://127.0.0.1:9377` with `http://YOUR_VPS_IP:9377`.

---

## 🛠️ Available MCP Tools

| Tool | Description |
|---|---|
| `browse(url, new_tab)` | Navigate to a URL in the active tab (or open in a new tab inside the same window if `new_tab: true`) and extract a summary. |
| `browse_navigate(url)` | Direct navigation in the currently active tab. |
| `browse_snapshot()` | Get the visible text of the current page without reloading. |
| `browse_click(selector, x, y)` | Click an element by CSS selector OR exact $(x, y)$ coordinates with realistic human Bezier curve movement. |
| `browse_type(selector, text)` | Type text into form fields and inputs. |
| `browse_upload_file(selector, file_path)` | Upload files from your computer to the web page. |
| `browse_press_key(key)` | Press keyboard keys (`Enter`, `Tab`, `Escape`, etc.). |
| `browse_scroll(direction, amount)` | Scroll the page down or up. |
| `browse_screenshot()` | Capture a high-resolution PNG screenshot of the browser screen. |
| `browse_new_tab(url)` | Open a new tab inside the existing window (strictly single-window mode enforced; never opens new OS windows). |
| `browse_close_tab(index)` | Close a tab by index (or active tab if omitted). |
| `browse_tabs()` | List all open tabs. |
| `browse_switch_tab(index)` | Switch between open tabs by index. |
| `browse_evaluate(script)` | Execute JavaScript directly in the page context. |

---

## ⚙️ Environment Settings (`.env`)

| Variable | Description | Default |
|---|---|---|
| `PORT_WEB` | noVNC web UI port | `5800` |
| `PORT_VNC` | Direct VNC client port | `5900` |
| `PORT_API` | HTTP API / MCP bridge port | `9377` |
| `RESOLUTION_WIDTH` | Virtual screen width | `1366` |
| `RESOLUTION_HEIGHT` | Virtual screen height | `768` |
| `TZ` | System timezone | `Europe/Lisbon` |
| `OS_SPOOF` | Emulated OS for anti-detection (`windows`, `macos`, `linux`) | `windows` |
| `AUTO_UPDATE` | Auto-update Camoufox on boot | `true` |
| `START_URL` | Page opened on startup | `https://duckduckgo.com` |
| `VNC_PASSWORD` | VNC access password (optional) | *(empty)* |

---

## 📁 Project Structure

```text
camoufox-vnc/
├── .github/
│   └── workflows/docker-publish.yml  # CI: build & push to Docker Hub
├── data/
│   └── downloads/                  # Files downloaded by the browser
├── .env                            # Active environment variables (local, git-ignored)
├── .env.example                    # Environment variables example
├── .gitignore                      # Git exclusion rules
├── docker-compose.yml              # Compose for local development
├── docker-compose.vps.example.yml  # Compose ready for VPS deploy
├── Dockerfile                      # Docker image with the Camoufox engine
├── entrypoint.sh                   # Startup and auto-update routine
├── launch-camoufox.py              # Stealth C++ engine and HTTP API
├── launch-x11vnc.sh                # VNC server
├── mcp_vnc_bridge.js               # Universal MCP bridge
├── novnc-index.html                # noVNC landing page (direct auto-connect)
├── openbox-rc.xml                  # Window manager configuration
├── package.json                    # MCP SDK dependencies
├── README.md                       # Full documentation
└── supervisord.conf                # Internal process management
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE) - see the [LICENSE](LICENSE) file for details.

