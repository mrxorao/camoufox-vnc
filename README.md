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
| `browse_ultrafast(goal, url, max_steps)` | *(Optional, Jev 1.14)* Autonomous Ultra-Fast multi-step web agent (inspired by `browser-use/jev-ultrafast`). Executes end-to-end tasks in seconds using indexed element tables and Jev decisions. |

---

## ⚡ TypeSafe Jev 1.14 Ultra-Fast Autonomous Mode (Optional)

Inspired by [`browser-use/jev-ultrafast`](https://github.com/browser-use/jev-ultrafast), you can activate the **Ultra-Fast Autonomous Agent Mode** powered by **TypeSafe Jev 1.14** via OpenRouter. 

Instead of waiting for slow multimodal LLMs to analyze heavy screenshots on every step, `browse_ultrafast` uses:
1. **Indexed DOM Action Space:** Extracts all visible interactive controls atomically (`[1..N]`).
2. **System-1 Fast Decisions:** Jev evaluates operations (`CLICK`, `TYPE_TEXT`, `SELECT`, `SCROLL_DOWN`, `WAIT`, `DONE`, `BLOCKED`) in ~150ms.
3. **Selective Text Generation:** Text generation is called strictly when typing is needed.
4. **Humanized Trajectory:** Every action is executed with realistic mouse movement and full noVNC live observability.
5. **System-2 Safe Fallback:** If blocked or if a CAPTCHA appears, the agent safely halts and hands over control with a complete diagnostic report for Normal Mode intervention.

### Configuration (`.env`)
```bash
ENABLE_JEV=true
OPENROUTER_API_KEY=sk-or-v1-your-key-here
JEV_MODEL=typesafe/jev-1.14
JEV_TEXT_MODEL=openai/gpt-4o-mini
```

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
| `ENABLE_JEV` | Enable TypeSafe Jev 1.14 decision tools (`true`/`false`) | `false` |
| `OPENROUTER_API_KEY` | OpenRouter API Key for Jev decisions | *(empty)* |
| `JEV_MODEL` | Jev decision model identifier | `typesafe/jev-1.14` |

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
