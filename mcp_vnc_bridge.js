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

const CAMOUFOX_API_URL = process.env.CAMOUFOX_API_URL || "http://127.0.0.1:9377";

async function sendCmd(endpoint, data = null, method = "POST") {
  const url = `${CAMOUFOX_API_URL.replace(/\/$/, "")}${endpoint}`;
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
        description: "Navigate to a URL in the Docker VNC browser. Visible live in noVNC (http://localhost:5800).",
        inputSchema: {
          type: "object",
          properties: {
            url: { type: "string", description: "Target URL (e.g. 'https://example.com')" },
          },
          required: ["url"],
        },
      },
      {
        name: "browse_navigate",
        description: "Navigate to a specific URL inside the VNC browser.",
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
        description: "Click a button, link or interactive element on the browser page (CSS selector).",
        inputSchema: {
          type: "object",
          properties: {
            selector: { type: "string", description: "CSS selector of the element to click" },
          },
          required: ["selector"],
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
        description: "Open a new tab in the existing browser window (new OS windows are restricted).",
        inputSchema: {
          type: "object",
          properties: {
            url: { type: "string", description: "New tab URL (e.g. 'https://duckduckgo.com')" },
          },
        },
      },
      {
        name: "browse_close_tab",
        description: "Close a tab in the Docker VNC browser by its numeric index (or the currently active tab if omitted).",
        inputSchema: {
          type: "object",
          properties: {
            index: {
              type: "number",
              description: "Numeric index of the tab to close (0, 1, 2...). If omitted, closes the currently active tab.",
            },
          },
        },
      },
      {
        name: "browse_tabs",
        description: "List all open tabs in the Docker VNC browser.",
        inputSchema: { type: "object", properties: {} },
      },
      {
        name: "browse_switch_tab",
        description: "Switch the active tab by its index (0, 1, 2...).",
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
    if (name === "browse" || name === "browse_navigate") {
      let targetUrl = args?.url || "";
      const res = await sendCmd("/navigate", { url: targetUrl });
      if (res.error) {
        return { isError: true, content: [{ type: "text", text: `Navigation failed: ${res.error}` }] };
      }
      
      const snap = await sendCmd("/snapshot");
      const pageText = snap.text || "";

      return {
        content: [
          {
            type: "text",
            text: `🌐 [Docker noVNC] Successfully navigated to: ${res.url}\nTitle: ${res.title}\n\nContent summary:\n${pageText.slice(0, 4000)}`,
          },
        ],
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
            text: `Current URL: ${res.url}\nTitle: ${res.title}\n\nVisible content:\n${res.text}`,
          },
        ],
      };
    }

    if (name === "browse_click") {
      const res = await sendCmd("/click", { selector: args.selector });
      if (res.error) {
        return { isError: true, content: [{ type: "text", text: `Click failed: ${res.error}` }] };
      }
      return {
        content: [{ type: "text", text: `🖱️ Successfully clicked '${args.selector}'. Current page: ${res.url} (${res.title})` }],
      };
    }

    if (name === "browse_type") {
      const res = await sendCmd("/type", {
        selector: args.selector,
        text: args.text,
        clear: args.clear_first !== false,
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
        content: [{ type: "text", text: `📄 New tab opened (index ${res.tab_index}): ${res.url}` }],
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
