#!/usr/bin/env node
/**
 * Camoufox Docker VNC MCP Bridge
 * Connects AI agents directly to the live Camoufox session in Docker (noVNC: http://localhost:5800).
 * Talks to the internal Stealth API at http://127.0.0.1:9377
 */

import fs from "fs";
import path from "path";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

function loadEnvFile() {
  try {
    const envPath = path.resolve(path.dirname(new URL(import.meta.url).pathname), ".env");
    if (fs.existsSync(envPath)) {
      const content = fs.readFileSync(envPath, "utf-8");
      for (const line of content.split("\n")) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith("#")) continue;
        const eqIdx = trimmed.indexOf("=");
        if (eqIdx !== -1) {
          const key = trimmed.slice(0, eqIdx).trim();
          const val = trimmed.slice(eqIdx + 1).trim().replace(/^["']|["']$/g, "");
          if (key && !(key in process.env)) {
            process.env[key] = val;
          }
        }
      }
    }
  } catch (e) {
    // ignore
  }
}
loadEnvFile();

const rawHost = process.env.CAMOUFOX_HOST || process.env.CAMOUFOX_API_URL || "http://127.0.0.1:9377";
const CAMOUFOX_API_URL = rawHost.startsWith("http://") || rawHost.startsWith("https://")
  ? rawHost.replace(/\/$/, "")
  : `http://${rawHost.replace(/\/$/, "")}`;

const CLIENT_ID = process.env.CAMOUFOX_CLIENT_ID ||
  `mcp-${process.env.USER || process.env.USERNAME || "client"}-${process.pid}-${Math.random().toString(36).slice(2, 7)}`;

let localQueue = Promise.resolve();
function runExclusive(fn) {
  const next = localQueue.then(fn, fn);
  localQueue = next;
  return next;
}

const TAB_ISOLATION_PROPS = {
  tab_index: {
    type: "number",
    description: "Optional tab index (0, 1, 2...) to target a specific browser tab so concurrent agents do not overwrite each other's active tab.",
  },
  session_id: {
    type: "string",
    description: "Optional agent/task session ID (e.g. 'agent-sara' or 'task-1'). Automatically assigns and isolates a dedicated tab for this session across calls.",
  },
};

function withTabIsolation(payload = {}, args = {}) {
  const out = { ...payload };
  if (args && args.tab_index !== undefined && args.tab_index !== null) {
    out.tab_index = Number(args.tab_index);
  }
  if (args && args.session_id) {
    out.session_id = String(args.session_id).trim();
  }
  return out;
}

function tabTag(res) {
  if (!res || typeof res !== "object") return "";
  const parts = [];
  if (res.tab_index !== undefined && res.tab_index !== null) parts.push(`Tab ${res.tab_index}`);
  if (res.container) parts.push(`container: ${res.container}`);
  if (res.session_id) parts.push(`session: ${res.session_id}`);
  return parts.length > 0 ? `[${parts.join(" | ")}] ` : "";
}

async function sendCmd(endpoint, data = null, method = "POST") {
  const url = `${CAMOUFOX_API_URL}${endpoint}`;
  const clientIdHeader = (data && data.session_id) ? `${CLIENT_ID}:${data.session_id}` : CLIENT_ID;
  const options = {
    method,
    headers: {
      "Content-Type": "application/json",
      "X-MCP-Client-Id": clientIdHeader,
    },
  };
  if (data !== null) {
    options.body = JSON.stringify(data);
  }

  const timeoutMs = Number(process.env.CAMOUFOX_TIMEOUT_MS || 130000);
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  options.signal = controller.signal;

  try {
    const res = await fetch(url, options);
    clearTimeout(timeoutId);
    const json = await res.json();
    if (!res.ok && json && json.error) {
      return { error: json.error, status: json.status || res.status };
    }
    return json;
  } catch (err) {
    clearTimeout(timeoutId);
    if (err.name === "AbortError") {
      return { error: `Request timed out waiting for Camoufox lock / completion (${CAMOUFOX_API_URL})` };
    }
    return { error: `Failed to reach the Camoufox container (${CAMOUFOX_API_URL}): ${err.message}` };
  }
}

const server = new Server(
  {
    name: "camoufox",
    version: "1.2.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: "browse",
        description: "Navigate to a URL in the Docker VNC browser. Supports tab_index, session_id, or container (Firefox Multi-Account Container) for isolated cookies and per-container proxies.",
        inputSchema: {
          type: "object",
          properties: {
            url: { type: "string", description: "Target URL (e.g. 'https://example.com')" },
            new_tab: { type: "boolean", description: "If true, opens the URL in a new tab inside the current window instead of replacing the active tab." },
            container: { type: "string", description: "Optional Firefox Multi-Account Container name (e.g. 'Personal', 'Work', 'Banking', 'Shopping' or a custom container). Returns an error listing valid containers if not found." },
            ...TAB_ISOLATION_PROPS,
          },
          required: ["url"],
        },
      },
      {
        name: "browse_navigate",
        description: "Navigate the active (or specified tab_index / session_id / container) tab to a URL inside the VNC browser.",
        inputSchema: {
          type: "object",
          properties: {
            url: { type: "string", description: "URL to navigate to" },
            container: { type: "string", description: "Optional Firefox Multi-Account Container name. Opens the URL in that container (error if not found)." },
            ...TAB_ISOLATION_PROPS,
          },
          required: ["url"],
        },
      },
      {
        name: "browse_snapshot",
        description: "Get the title, URL, interactive elements (buttons, links, inputs with CSS selectors and x,y coordinates), visible images, and readable text of the page.",
        inputSchema: {
          type: "object",
          properties: {
            ...TAB_ISOLATION_PROPS,
          },
        },
      },
      {
        name: "browse_click",
        description: "Click a button, link or interactive element on the browser page (CSS selector or exact coordinates).",
        inputSchema: {
          type: "object",
          properties: {
            selector: { type: "string", description: "CSS selector of the element to click (optional if x,y provided)" },
            x: { type: "number", description: "X coordinate in pixels (optional alternative to selector)" },
            y: { type: "number", description: "Y coordinate in pixels (optional alternative to selector)" },
            ...TAB_ISOLATION_PROPS,
          },
        },
      },
      {
        name: "browse_move",
        description: "Move the mouse cursor smoothly to coordinates (x, y) or to a CSS selector with realistic human Bézier motion (hovering).",
        inputSchema: {
          type: "object",
          properties: {
            selector: { type: "string", description: "CSS selector of the element to move/hover to (optional if x,y provided)" },
            x: { type: "number", description: "X coordinate in pixels (optional alternative to selector)" },
            y: { type: "number", description: "Y coordinate in pixels (optional alternative to selector)" },
            ...TAB_ISOLATION_PROPS,
          },
        },
      },
      {
        name: "browse_drag_and_drop",
        description: "Drag and drop an element or coordinate to another element or coordinate with smooth human mouse physics.",
        inputSchema: {
          type: "object",
          properties: {
            source_selector: { type: "string", description: "CSS selector of the element to drag (or use source_x, source_y)" },
            target_selector: { type: "string", description: "CSS selector of the drop target (or use target_x, target_y)" },
            source_x: { type: "number", description: "Start X coordinate in pixels" },
            source_y: { type: "number", description: "Start Y coordinate in pixels" },
            target_x: { type: "number", description: "Target X coordinate in pixels" },
            target_y: { type: "number", description: "Target Y coordinate in pixels" },
            ...TAB_ISOLATION_PROPS,
          },
        },
      },
      {
        name: "browse_type",
        description: "Type text into an input or search field visible in the noVNC browser.",
        inputSchema: {
          type: "object",
          properties: {
            selector: { type: "string", description: "CSS selector of the field" },
            text: { type: "string", description: "Text to type" },
            clear_first: { type: "boolean", description: "Clear the field before typing" },
            ...TAB_ISOLATION_PROPS,
          },
          required: ["selector", "text"],
        },
      },
      {
        name: "browse_upload_file",
        description: "Upload a file from your computer directly to an upload element (<input type='file'>) in the browser.",
        inputSchema: {
          type: "object",
          properties: {
            selector: { type: "string", description: "CSS selector of the <input type='file'> element (e.g. 'input[type=file]')" },
            file_path: { type: "string", description: "Absolute file path on the host (e.g. '/home/user/document.pdf')" },
            ...TAB_ISOLATION_PROPS,
          },
          required: ["selector", "file_path"],
        },
      },
      {
        name: "browse_list_downloads",
        description: "List all files downloaded by the browser in the downloads directory, including file name, size and modification time.",
        inputSchema: { type: "object", properties: {} },
      },
      {
        name: "browse_get_download",
        description: "Retrieve a downloaded file from the Camoufox browser (useful when Docker runs on a remote VPS). Can save to a local path or return Base64.",
        inputSchema: {
          type: "object",
          properties: {
            filename: { type: "string", description: "Name of the file to retrieve (as listed by browse_list_downloads)" },
            save_path: { type: "string", description: "Optional local destination file path on your machine where to save the downloaded file" },
          },
          required: ["filename"],
        },
      },
      {
        name: "browse_press_key",
        description: "Press a key on the browser keyboard (e.g. 'Enter', 'Tab', 'Escape').",
        inputSchema: {
          type: "object",
          properties: {
            key: { type: "string", description: "Key name (e.g. 'Enter', 'Tab')" },
            ...TAB_ISOLATION_PROPS,
          },
          required: ["key"],
        },
      },
      {
        name: "browse_scroll",
        description: "Scroll the browser window down or up.",
        inputSchema: {
          type: "object",
          properties: {
            direction: { type: "string", enum: ["down", "up"], description: "Scroll direction (default: 'down')" },
            amount: { type: "number", description: "Pixels to scroll (default 500)" },
            ...TAB_ISOLATION_PROPS,
          },
        },
      },
      {
        name: "browse_screenshot",
        description: "Capture a screenshot of the browser window open in Docker. Returns a direct HTTP PNG URL (for curl / attach_file) as well as the PNG image.",
        inputSchema: {
          type: "object",
          properties: {
            selector: { type: "string", description: "Optional CSS selector to capture only a specific element" },
            full_page: { type: "boolean", description: "Optional: if true, captures the full scrollable page (default: false)" },
            ...TAB_ISOLATION_PROPS,
          },
        },
      },
      {
        name: "browse_evaluate",
        description: "Execute JavaScript code in the browser page context.",
        inputSchema: {
          type: "object",
          properties: {
            script: { type: "string", description: "JavaScript code to execute" },
            ...TAB_ISOLATION_PROPS,
          },
          required: ["script"],
        },
      },
      {
        name: "browse_new_tab",
        description: "Open a URL in a new tab inside the existing browser window (strictly single-window mode; never opens separate OS windows). Optionally target a Firefox Multi-Account Container.",
        inputSchema: {
          type: "object",
          properties: {
            url: { type: "string", description: "New tab URL (e.g. 'https://duckduckgo.com')" },
            container: { type: "string", description: "Optional Firefox Multi-Account Container name (e.g. 'Work', 'Banking', or custom). Returns an error listing valid containers if not found." },
            session_id: TAB_ISOLATION_PROPS.session_id,
          },
        },
      },
      {
        name: "browse_list_containers",
        description: "List all available Firefox Multi-Account Containers (name, userContextId, cookieStoreId, color, icon, and assigned proxy if any).",
        inputSchema: { type: "object", properties: {} },
      },
      {
        name: "browse_create_container",
        description: "Create a new Firefox Multi-Account Container and optionally assign a dedicated proxy (HTTP, HTTPS, SOCKS5, SOCKS4) to it.",
        inputSchema: {
          type: "object",
          properties: {
            name: { type: "string", description: "Unique container name (e.g. 'Brasil', 'Portugal', 'Cliente-X')" },
            color: {
              type: "string",
              enum: ["blue", "turquoise", "green", "yellow", "orange", "red", "pink", "purple", "toolbar"],
              description: "Optional container tab color (default: 'blue')",
            },
            icon: {
              type: "string",
              enum: ["fingerprint", "briefcase", "dollar", "cart", "vacation", "gift", "food", "fruit", "pet", "tree", "chill", "circle", "fence"],
              description: "Optional container icon (default: 'fingerprint')",
            },
            proxy: {
              type: "string",
              description: "Optional dedicated proxy URL for this container (e.g. 'socks5://100.119.154.4:1080' or 'http://user:pass@host:8080'). Omit to use default routing.",
            },
          },
          required: ["name"],
        },
      },
      {
        name: "browse_set_container_proxy",
        description: "Assign, update, or remove a dedicated proxy (HTTP, HTTPS, SOCKS5, SOCKS4) for an existing Firefox Multi-Account Container.",
        inputSchema: {
          type: "object",
          properties: {
            container: { type: "string", description: "Existing container name, cookieStoreId, or userContextId" },
            proxy: {
              type: "string",
              description: "Proxy URL (e.g. 'socks5://host:1080' or 'http://user:pass@host:8080'). Pass empty string '' or omit to remove the proxy and revert to default routing.",
            },
          },
          required: ["container"],
        },
      },
      {
        name: "browse_delete_container",
        description: "Delete an existing Firefox Multi-Account Container (closes its open tabs, clears its isolated cookies/storage, and removes any assigned proxy).",
        inputSchema: {
          type: "object",
          properties: {
            container: { type: "string", description: "Existing container name, cookieStoreId, or userContextId to delete" },
          },
          required: ["container"],
        },
      },
      {
        name: "browse_close_tab",
        description: "Close a specific browser tab by index (or session_id / active tab if omitted). Strictly enforces single-window mode.",
        inputSchema: {
          type: "object",
          properties: {
            index: { type: "number", description: "Numeric index of tab to close (optional)" },
            ...TAB_ISOLATION_PROPS,
          },
        },
      },
      {
        name: "browse_tabs",
        description: "List all open tabs in the single browser window with their indices, URLs, titles, active status, and assigned session_id.",
        inputSchema: { type: "object", properties: {} },
      },
      {
        name: "browse_switch_tab",
        description: "Switch active tab in the browser window to a specific index.",
        inputSchema: {
          type: "object",
          properties: {
            index: { type: "number", description: "Numeric tab index" },
            session_id: TAB_ISOLATION_PROPS.session_id,
          },
          required: ["index"],
        },
      },
    ],
  };
});

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  return runExclusive(async () => {
    const { name, arguments: args } = request.params;

    try {
      if (name === "browse") {
        let targetUrl = (args?.url || "https://duckduckgo.com").trim();
        if (!targetUrl.startsWith("http://") && !targetUrl.startsWith("https://")) {
          targetUrl = "https://" + targetUrl;
        }
        const navPayload = { url: targetUrl };
        if (args?.container) navPayload.container = String(args.container).trim();

        if (args?.new_tab) {
          const res = await sendCmd("/new_tab", withTabIsolation(navPayload, args));
          if (res.error) {
            return { isError: true, content: [{ type: "text", text: `Failed to open in new tab: ${res.error}` }] };
          }
          return {
            content: [{ type: "text", text: `🌐 ${tabTag(res)}Opened in new tab (index ${res.tab_index}): ${res.url} (IMPORTANT: pass tab_index: ${res.tab_index} in all subsequent tool calls for this page)` }],
          };
        } else {
          const res = await sendCmd("/navigate", withTabIsolation(navPayload, args));
          if (res.error) {
            return { isError: true, content: [{ type: "text", text: `Navigation failed: ${res.error}` }] };
          }
          return {
            content: [{ type: "text", text: `🌐 ${tabTag(res)}Navigated to: ${res.url} (IMPORTANT: pass tab_index: ${res.tab_index} in all subsequent tool calls for this page)` }],
          };
        }
      }

      if (name === "browse_navigate") {
        const navPayload = { url: args.url };
        if (args?.container) navPayload.container = String(args.container).trim();
        const res = await sendCmd("/navigate", withTabIsolation(navPayload, args));
        if (res.error) {
          return { isError: true, content: [{ type: "text", text: `Navigation failed: ${res.error}` }] };
        }
        return {
          content: [{ type: "text", text: `${tabTag(res)}Navigated to: ${res.url} (IMPORTANT: pass tab_index: ${res.tab_index} in all subsequent tool calls for this page)` }],
        };
      }

      if (name === "browse_snapshot") {
        const res = await sendCmd("/snapshot", withTabIsolation({}, args));
        if (res.error) {
          return { isError: true, content: [{ type: "text", text: `Snapshot failed: ${res.error}` }] };
        }
        const sections = [
          `${tabTag(res)}Page Title: ${res.title}`,
          `URL: ${res.url}`,
        ];
        if (res.viewport) {
          sections.push(`Viewport: ${res.viewport.width}x${res.viewport.height} (scroll Y: ${res.viewport.scroll_y}/${res.viewport.scroll_height})`);
        }
        if (res.formatted_elements) {
          sections.push(`\n${res.formatted_elements}`);
        }
        sections.push(`\nVisible Content:\n${res.text}`);
        return {
          content: [
            {
              type: "text",
              text: sections.join("\n"),
            },
          ],
        };
      }

      if (name === "browse_click") {
        const payload = withTabIsolation({}, args);
        if (args.selector) payload.selector = args.selector;
        if (args.x !== undefined) payload.x = Number(args.x);
        if (args.y !== undefined) payload.y = Number(args.y);

        if (!payload.selector && (payload.x === undefined || payload.y === undefined)) {
          return {
            isError: true,
            content: [{ type: "text", text: "Either 'selector' or both 'x' and 'y' coordinates must be provided." }],
          };
        }

        const res = await sendCmd("/click", payload);
        if (res.error) {
          return { isError: true, content: [{ type: "text", text: `Click failed: ${res.error}` }] };
        }
        const targetDesc = payload.selector ? `'${payload.selector}'` : `(${payload.x}, ${payload.y})`;
        return {
          content: [{ type: "text", text: `🖱️ ${tabTag(res)}Successfully clicked ${targetDesc}.` }],
        };
      }

      if (name === "browse_move") {
        const payload = withTabIsolation({}, args);
        if (args.selector) payload.selector = args.selector;
        if (args.x !== undefined) payload.x = Number(args.x);
        if (args.y !== undefined) payload.y = Number(args.y);

        if (!payload.selector && (payload.x === undefined || payload.y === undefined)) {
          return {
            isError: true,
            content: [{ type: "text", text: "Either 'selector' or both 'x' and 'y' coordinates must be provided." }],
          };
        }

        const res = await sendCmd("/move", payload);
        if (res.error) {
          return { isError: true, content: [{ type: "text", text: `Move failed: ${res.error}` }] };
        }
        const targetDesc = payload.selector ? `'${payload.selector}'` : `(${payload.x}, ${payload.y})`;
        return {
          content: [{ type: "text", text: `🖱️ ${tabTag(res)}Mouse cursor smoothly moved to ${targetDesc}.` }],
        };
      }

      if (name === "browse_drag_and_drop") {
        const payload = withTabIsolation({}, args);
        if (args.source_selector) payload.source_selector = args.source_selector;
        if (args.target_selector) payload.target_selector = args.target_selector;
        if (args.source_x !== undefined) payload.source_x = Number(args.source_x);
        if (args.source_y !== undefined) payload.source_y = Number(args.source_y);
        if (args.target_x !== undefined) payload.target_x = Number(args.target_x);
        if (args.target_y !== undefined) payload.target_y = Number(args.target_y);

        const hasSource = payload.source_selector || (payload.source_x !== undefined && payload.source_y !== undefined);
        const hasTarget = payload.target_selector || (payload.target_x !== undefined && payload.target_y !== undefined);

        if (!hasSource || !hasTarget) {
          return {
            isError: true,
            content: [{ type: "text", text: "Both source (selector or x,y) and target (selector or x,y) must be provided for drag and drop." }],
          };
        }

        const res = await sendCmd("/drag_and_drop", payload);
        if (res.error) {
          return { isError: true, content: [{ type: "text", text: `Drag and drop failed: ${res.error}` }] };
        }
        const fromDesc = res.from ? `(${res.from.x}, ${res.from.y})` : payload.source_selector;
        const toDesc = res.to ? `(${res.to.x}, ${res.to.y})` : payload.target_selector;
        return {
          content: [{ type: "text", text: `🖱️ ${tabTag(res)}Successfully dragged from ${fromDesc} to ${toDesc}.` }],
        };
      }

      if (name === "browse_type") {
        const res = await sendCmd("/type", withTabIsolation({
          selector: args.selector,
          text: args.text,
          clear: args.clear_first ?? true,
        }, args));
        if (res.error) {
          return { isError: true, content: [{ type: "text", text: `Type failed: ${res.error}` }] };
        }
        return {
          content: [{ type: "text", text: `⌨️ ${tabTag(res)}Text successfully typed into '${args.selector}'.` }],
        };
      }

      if (name === "browse_upload_file") {
        const filePath = args.file_path;
        if (!fs.existsSync(filePath)) {
          return { isError: true, content: [{ type: "text", text: `File not found on the system: ${filePath}` }] };
        }

        const fileBuffer = fs.readFileSync(filePath);
        const base64Data = fileBuffer.toString("base64");
        const filename = path.basename(filePath);

        const res = await sendCmd("/upload", withTabIsolation({
          selector: args.selector,
          base64_data: base64Data,
          filename: filename,
        }, args));

        if (res.error) {
          return { isError: true, content: [{ type: "text", text: `File upload failed: ${res.error}` }] };
        }

        return {
          content: [{ type: "text", text: `📎 ${tabTag(res)}File '${filename}' (${(fileBuffer.length / 1024).toFixed(1)} KB) successfully uploaded to '${args.selector}'.` }],
        };
      }

      if (name === "browse_list_downloads") {
        const res = await sendCmd("/downloads");
        if (res.error) {
          return { isError: true, content: [{ type: "text", text: `Failed to list downloads: ${res.error}` }] };
        }
        if (!res.files || res.files.length === 0) {
          return {
            content: [{ type: "text", text: `📠 No downloaded files found in ${res.downloads_dir || "/data/downloads"}.` }],
          };
        }
        return {
          content: [{ type: "text", text: JSON.stringify(res.files, null, 2) }],
        };
      }

      if (name === "browse_get_download") {
        const filename = args.filename;
        const res = await sendCmd("/get_download", { filename });
        if (res.error) {
          return { isError: true, content: [{ type: "text", text: `Failed to get download '${filename}': ${res.error}` }] };
        }

        if (args.save_path) {
          try {
            const savePath = path.resolve(args.save_path);
            fs.mkdirSync(path.dirname(savePath), { recursive: true });
            const fileBuf = Buffer.from(res.base64_data, "base64");
            fs.writeFileSync(savePath, fileBuf);
            return {
              content: [{ type: "text", text: `💾 Downloaded file '${filename}' (${(res.size_bytes / 1024).toFixed(1)} KB) successfully saved locally to: ${savePath}` }],
            };
          } catch (saveErr) {
            return { isError: true, content: [{ type: "text", text: `Failed to write file locally: ${saveErr.message}` }] };
          }
        }

        return {
          content: [
            {
              type: "text",
              text: `📄 File: ${res.filename} (${(res.size_bytes / 1024).toFixed(1)} KB)\nBase64 length: ${res.base64_data.length} chars`,
            },
          ],
        };
      }

      if (name === "browse_press_key") {
        const res = await sendCmd("/press_key", withTabIsolation({ key: args.key }, args));
        if (res.error) {
          return { isError: true, content: [{ type: "text", text: `Key press failed: ${res.error}` }] };
        }
        return {
          content: [{ type: "text", text: `⌨️ ${tabTag(res)}Key '${args.key}' pressed successfully.` }],
        };
      }

      if (name === "browse_scroll") {
        const deltaY = args?.direction === "up" ? -(args?.amount || 500) : (args?.amount || 500);
        const res = await sendCmd("/scroll", withTabIsolation({ delta_y: deltaY }, args));
        if (res.error) {
          return { isError: true, content: [{ type: "text", text: `Scroll failed: ${res.error}` }] };
        }
        return {
          content: [{ type: "text", text: `📜 ${tabTag(res)}Scrolled (${args?.direction || "down"}, ${args?.amount || 500}px).` }],
        };
      }

      if (name === "browse_screenshot") {
        const payload = withTabIsolation({}, args);
        if (args?.selector) payload.selector = args.selector;
        if (args?.full_page !== undefined) payload.full_page = Boolean(args.full_page);
        const res = await sendCmd("/screenshot", payload);
        if (res.error) {
          return { isError: true, content: [{ type: "text", text: `Screenshot failed: ${res.error}` }] };
        }
        const fname = res.filename || "screenshot.png";
        const directUrl = res.screenshot_path
          ? `${CAMOUFOX_API_URL}${res.screenshot_path}`
          : `${CAMOUFOX_API_URL}/screenshot.png`;
        const latestUrl = `${CAMOUFOX_API_URL}/screenshot.png`;
        const sizeKb = res.size_bytes ? ` (${(res.size_bytes / 1024).toFixed(1)} KB)` : "";
        const infoText = [
          `📸 ${tabTag(res)}Screenshot captured${sizeKb}: ${fname}`,
          `Direct PNG URL: ${directUrl}`,
          `Latest PNG URL: ${latestUrl}`,
          `To attach or inspect this file locally in a container/shell, run:`,
          `curl -k -sL "${directUrl}" -o /tmp/${fname}`,
        ].join("\n");
        return {
          content: [
            {
              type: "text",
              text: infoText,
            },
            {
              type: "image",
              data: res.image_base64,
              mimeType: "image/png",
            },
          ],
        };
      }

      if (name === "browse_evaluate") {
        const res = await sendCmd("/evaluate", withTabIsolation({ script: args.script }, args));
        if (res.error) {
          return { isError: true, content: [{ type: "text", text: `Script execution failed: ${res.error}` }] };
        }
        return {
          content: [{ type: "text", text: `${tabTag(res)}JS result: ${JSON.stringify(res.result)}` }],
        };
      }

      if (name === "browse_new_tab") {
        const payload = { url: args?.url || "https://duckduckgo.com" };
        if (args?.container) payload.container = String(args.container).trim();
        const res = await sendCmd("/new_tab", withTabIsolation(payload, args));
        if (res.error) {
          return { isError: true, content: [{ type: "text", text: `Failed to open tab: ${res.error}` }] };
        }
        return {
          content: [{ type: "text", text: `📄 ${tabTag(res)}New tab opened in existing window (index ${res.tab_index}): ${res.url}` }],
        };
      }

      if (name === "browse_list_containers") {
        const res = await sendCmd("/containers");
        if (res.error) {
          return { isError: true, content: [{ type: "text", text: `Failed to list containers: ${res.error}` }] };
        }
        return {
          content: [{ type: "text", text: JSON.stringify(res.containers, null, 2) }],
        };
      }

      if (name === "browse_create_container") {
        const payload = { name: args.name };
        if (args.color) payload.color = args.color;
        if (args.icon) payload.icon = args.icon;
        if (args.proxy) payload.proxy = args.proxy;
        const res = await sendCmd("/containers/create", payload);
        if (res.error) {
          return { isError: true, content: [{ type: "text", text: `Failed to create container: ${res.error}` }] };
        }
        const c = res.container || {};
        const proxyInfo = c.proxy ? ` | proxy: ${c.proxy}` : " | proxy: default";
        return {
          content: [{ type: "text", text: `📦 Container '${c.name}' created (${c.cookieStoreId}, color: ${c.color}, icon: ${c.icon}${proxyInfo}).` }],
        };
      }

      if (name === "browse_set_container_proxy") {
        const payload = {
          container: args.container,
          proxy: args.proxy !== undefined ? args.proxy : "",
        };
        const res = await sendCmd("/containers/proxy", payload);
        if (res.error) {
          return { isError: true, content: [{ type: "text", text: `Failed to set container proxy: ${res.error}` }] };
        }
        return {
          content: [{ type: "text", text: `🔌 ${res.message || `Updated proxy for container '${res.container}'.`}` }],
        };
      }

      if (name === "browse_delete_container") {
        const res = await sendCmd("/containers/delete", { container: args.container });
        if (res.error) {
          return { isError: true, content: [{ type: "text", text: `Failed to delete container: ${res.error}` }] };
        }
        return {
          content: [{ type: "text", text: `🗑️ ${res.message || `Container '${res.deleted_container}' deleted.`}` }],
        };
      }

      if (name === "browse_close_tab") {
        const payload = withTabIsolation({}, args);
        if (args?.index !== undefined && args?.index !== null) {
          payload.index = Number(args.index);
        }
        const res = await sendCmd("/close_tab", payload);
        if (res.error) {
          return { isError: true, content: [{ type: "text", text: `Failed to close tab: ${res.error}` }] };
        }
        return {
          content: [
            {
              type: "text",
              text: `🗑️ Tab ${res.closed_index !== undefined ? res.closed_index : ""} closed. Active tab is now index ${res.active_index}: ${res.url} (${res.title}) [${res.remaining_tabs_count} tab(s) open]`,
            },
          ],
        };
      }

      if (name === "browse_tabs") {
        const res = await sendCmd("/tabs");
        if (res.error) {
          return { isError: true, content: [{ type: "text", text: `Failed to list tabs: ${res.error}` }] };
        }
        return {
          content: [{ type: "text", text: JSON.stringify(res.tabs, null, 2) }],
        };
      }

      if (name === "browse_switch_tab") {
        const res = await sendCmd("/switch_tab", withTabIsolation({ index: args.index }, args));
        if (res.error) {
          return { isError: true, content: [{ type: "text", text: `Failed to switch_tab: ${res.error}` }] };
        }
        return {
          content: [{ type: "text", text: `${tabTag(res)}Active tab switched to index ${args.index}: ${res.url} (${res.title})` }],
        };
      }

      throw new Error(`Unknown tool: ${name}`);
    } catch (err) {
      return {
        isError: true,
        content: [{ type: "text", text: `Error processing ${name}: ${err.message}` }],
      };
    }
  });
});

const transport = new StdioServerTransport();
await server.connect(transport);
