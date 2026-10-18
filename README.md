# 🦊 Camoufox VNC Docker & MCP Bridge (Anti-Detect & Stealth Automation)

Self-contained, ultra-optimized Docker environment running **Camoufox** (a Firefox fork with a C++ stealth anti-detection engine), with real-time web viewing via **noVNC** (port `5800`), direct **VNC** (port `5900`) and full control through **Model Context Protocol (MCP)** for AI agents (OpenCode, Cursor, Claude Desktop, etc.).

---

## ✨ Key Features

* 🛡️ **Maximum-level anti-detection (score 0–3):** `navigator.webdriver = false`, realistic hardware emulation (WebGL, Canvas, Audio, GPU, Windows fonts).
* 🌐 **Live noVNC web UI:** watch in real time every click, search and scroll made by you or the AI agent ([http://localhost:5800](http://localhost:5800)). Opens directly, no "Connect" click needed.
* 🔌 **Built-in MCP bridge:** control the browser with 13+ tools (navigation, clicks, typing, screenshots, tab management, file uploads and JS execution).
* 📎 **File upload & download support:** upload files from your PC straight into `<input type='file'>` elements and keep downloads in `./data/downloads`.
* 🔄 **Auto-update on boot:** on every container start, Camoufox and the C++ binaries update automatically to the latest GitHub/PyPI release.
* 💾 **Session & login persistence:** dedicated Docker volume (`camoufox_profile`) preserving cookies, logins, history and extensions across restarts and image rebuilds.
* 🚀 **VPS-ready:** runs on any remote server with browser viewing and remote MCP control. Public image, no login required.

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
| `browse(url)` | Navigate to a URL and extract a summary of the page content. |
| `browse_navigate(url)` | Direct navigation to a specific URL. |
| `browse_snapshot()` | Get the visible text of the current page without reloading. |
| `browse_click(selector)` | Click a button, link or interactive element via CSS selector. |
| `browse_type(selector, text)` | Type text into form fields and inputs. |
| `browse_upload_file(selector, file_path)` | Upload files from your computer to the web page. |
| `browse_press_key(key)` | Press keyboard keys (`Enter`, `Tab`, `Escape`, etc.). |
| `browse_scroll(direction, amount)` | Scroll the page down or up. |
| `browse_screenshot()` | Capture a high-resolution PNG screenshot of the browser screen. |
| `browse_new_tab(url)` | Open a new tab in the browser (single-window mode enforced). |
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
