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

async function sendCmd(endpoint, data = null, method = "POST") {
  const url = `${CAMOUFOX_API_URL}${endpoint}`;
  const options = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (data !== null) {
    options.body = JSON.stringify(data);
  }

  try {
    const res = await fetch(url, options);
    const json = await res.json();
    return json;
  } catch (err) {
    return { error: `Failed to reach the Camoufox container (${CAMOUFOX_API_URL}): ${err.message}` };
  }
}

const server = new Server(
  {
    name: "camoufox",
    version: "1.0.0",
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
        description: "Navigate to a URL in the Docker VNC browser. By default navigates the current tab; set new_tab: true to open in a new tab inside the existing window (strictly single-window, no new OS windows are ever opened). Visible live in noVNC (http://localhost:5800).",
        inputSchema: {
          type: "object",
          properties: {
            url: { type: "string", description: "Target URL (e.g. 'https://example.com')" },
            new_tab: { type: "boolean", description: "If true, opens the URL in a new tab inside the current window instead of replacing the active tab." },
          },
          required: ["url"],
        },
      },
      {
        name: "browse_navigate",
        description: "Navigate the active tab to a specific URL inside the VNC browser.",
        inputSchema: {
          type: "object",
          properties: {
            url: { type: "string", description: "URL to navigate to" },
          },
          required: ["url"],
        },
      },
      {
        name: "browse_snapshot",
        description: "Get the title, URL and readable text of the page currently open in Docker noVNC.",
        inputSchema: { type: "object", properties: {} },
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
          },
          required: ["selector", "file_path"],
        },
      },
      {
        name: "browse_press_key",
        description: "Press a key on the browser keyboard (e.g. 'Enter', 'Tab', 'Escape').",
        inputSchema: {
          type: "object",
          properties: {
            key: { type: "string", description: "Key name (e.g. 'Enter', 'Tab')" },
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
          },
        },
      },
      {
        name: "browse_screenshot",
        description: "Capture a screenshot of the browser window open in Docker.",
        inputSchema: { type: "object", properties: {} },
      },
      {
        name: "browse_evaluate",
        description: "Execute JavaScript code in the browser page context.",
        inputSchema: {
          type: "object",
          properties: {
            script: { type: "string", description: "JavaScript code to execute" },
          },
          required: ["script"],
        },
      },
      {
        name: "browse_new_tab",
        description: "Open a URL in a new tab inside the existing browser window (strictly single-window mode; never opens separate OS windows).",
        inputSchema: {
          type: "object",
          properties: {
            url: { type: "string", description: "New tab URL (e.g. 'https://duckduckgo.com')" },
          },
        },
      },
      {
        name: "browse_close_tab",
        description: "Close a specific browser tab by index (or active tab if omitted). Strictly enforces single-window mode and automatically activates the nearest remaining tab.",
        inputSchema: {
          type: "object",
          properties: {
            index: { type: "number", description: "Numeric index of tab to close (optional, defaults to active tab)" },
          },
        },
      },
      {
        name: "browse_tabs",
        description: "List all open tabs in the single browser window with their indices, URLs, titles, and active status.",
        inputSchema: { type: "object", properties: {} },
      },
      {
        name: "browse_switch_tab",
        description: "Switch active tab in the browser window to a specific index.",
        inputSchema: {
          type: "object",
          properties: {
            index: { type: "number", description: "Numeric tab index" },
          },
          required: ["index"],
        },
      },
    ],
  };
});

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    if (name === "browse") {
      let targetUrl = (args.url || "https://duckduckgo.com").trim();
      if (!targetUrl.startsWith("http://") && !targetUrl.startsWith("https://")) {
        targetUrl = "https://" + targetUrl;
      }

      if (args.new_tab) {
        const res = await sendCmd("/new_tab", { url: targetUrl });
        if (res.error) {
          return { isError: true, content: [{ type: "text", text: `Failed to open in new tab: ${res.error}` }] };
        }
        return {
          content: [{ type: "text", text: `🌐 Opened in new tab (index ${res.tab_index}): ${res.url}` }],
        };
      } else {
        const res = await sendCmd("/navigate", { url: targetUrl });
        if (res.error) {
          return { isError: true, content: [{ type: "text", text: `Navigation failed: ${res.error}` }] };
        }
        return {
          content: [{ type: "text", text: `🌐 Navigated to: ${res.url}` }],
        };
      }
    }

    if (name === "browse_navigate") {
      const res = await sendCmd("/navigate", { url: args.url });
      if (res.error) {
        return { isError: true, content: [{ type: "text", text: `Navigation failed: ${res.error}` }] };
      }
      return {
        content: [{ type: "text", text: `Navigated to: ${res.url}` }],
      };
    }

    if (name === "browse_snapshot") {
      const res = await sendCmd("/snapshot");
      if (res.error) {
        return { isError: true, content: [{ type: "text", text: `Snapshot failed: ${res.error}` }] };
      }
      return {
        content: [
          {
            type: "text",
            text: `Page Title: ${res.title}\nURL: ${res.url}\n\nVisible Content:\n${res.text}`,
          },
        ],
      };
    }

    if (name === "browse_click") {
      const payload = {};
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
        content: [{ type: "text", text: `🖱️ Successfully clicked ${targetDesc}.` }],
      };
    }

    if (name === "browse_type") {
      const res = await sendCmd("/type", {
        selector: args.selector,
        text: args.text,
        clear: args.clear_first ?? true,
      });
      if (res.error) {
        return { isError: true, content: [{ type: "text", text: `Type failed: ${res.error}` }] };
      }
      return {
        content: [{ type: "text", text: `⌨️ Text successfully typed into '${args.selector}'.` }],
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

      const res = await sendCmd("/upload", {
        selector: args.selector,
        base64_data: base64Data,
        filename: filename,
      });

      if (res.error) {
        return { isError: true, content: [{ type: "text", text: `File upload failed: ${res.error}` }] };
      }

      return {
        content: [{ type: "text", text: `📎 File '${filename}' (${(fileBuffer.length / 1024).toFixed(1)} KB) successfully uploaded to '${args.selector}'.` }],
      };
    }

    if (name === "browse_press_key") {
      const res = await sendCmd("/press_key", { key: args.key });
      if (res.error) {
        return { isError: true, content: [{ type: "text", text: `Key press failed: ${res.error}` }] };
      }
      return {
        content: [{ type: "text", text: `⌨️ Key '${args.key}' pressed successfully.` }],
      };
    }

    if (name === "browse_scroll") {
      const deltaY = args?.direction === "up" ? -(args?.amount || 500) : (args?.amount || 500);
      const res = await sendCmd("/scroll", { delta_y: deltaY });
      if (res.error) {
        return { isError: true, content: [{ type: "text", text: `Scroll failed: ${res.error}` }] };
      }
      return {
        content: [{ type: "text", text: `📜 Scrolled (${args?.direction || "down"}, ${args?.amount || 500}px).` }],
      };
    }

    if (name === "browse_screenshot") {
      const res = await sendCmd("/screenshot");
      if (res.error) {
        return { isError: true, content: [{ type: "text", text: `Screenshot failed: ${res.error}` }] };
      }
      return {
        content: [
          {
            type: "image",
            data: res.image_base64,
            mimeType: "image/png",
          },
        ],
      };
    }

    if (name === "browse_evaluate") {
      const res = await sendCmd("/evaluate", { script: args.script });
      if (res.error) {
        return { isError: true, content: [{ type: "text", text: `Script execution failed: ${res.error}` }] };
      }
      return {
        content: [{ type: "text", text: `JS result: ${JSON.stringify(res.result)}` }],
      };
    }

    if (name === "browse_new_tab") {
      const res = await sendCmd("/new_tab", { url: args?.url || "https://duckduckgo.com" });
      if (res.error) {
        return { isError: true, content: [{ type: "text", text: `Failed to open tab: ${res.error}` }] };
      }
      return {
        content: [{ type: "text", text: `📄 New tab opened in existing window (index ${res.tab_index}): ${res.url}` }],
      };
    }

    if (name === "browse_close_tab") {
      const payload = {};
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
      const res = await sendCmd("/switch_tab", { index: args.index });
      if (res.error) {
        return { isError: true, content: [{ type: "text", text: `Failed to switch tab: ${res.error}` }] };
      }
      return {
        content: [{ type: "text", text: `Active tab switched to index ${args.index}: ${res.url} (${res.title})` }],
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

const transport = new StdioServerTransport();
await server.connect(transport);
