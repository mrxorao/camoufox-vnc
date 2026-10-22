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
          const val = trimmed.slice(eqIdx + 1).trim();
          if (process.env[key] === undefined) {
            process.env[key] = val;
          }
        }
      }
    }
  } catch {
    // ignore
  }
}
loadEnvFile();

const rawHost = process.env.CAMOUFOX_HOST || process.env.CAMOUFOX_API_URL || "http://127.0.0.1:9377";
const CAMOUFOX_API_URL = rawHost.startsWith("http://") || rawHost.startsWith("https://")
  ? rawHost.replace(/\/$/, "")
  : `http://${rawHost.replace(/\/$/, "")}`;

function getJevConfig() {
  loadEnvFile();
  const enableJev = (process.env.ENABLE_JEV || "false").trim().toLowerCase() === "true";
  const apiKey = (process.env.OPENROUTER_API_KEY || "").trim();
  const model = (process.env.JEV_MODEL || "typesafe/jev-1.14").trim();
  return {
    enableJev,
    apiKey,
    model,
    isActive: enableJev && Boolean(apiKey),
  };
}

async function callJevDecisions(state, questions) {
  const { apiKey, model } = getJevConfig();
  if (!apiKey) {
    throw new Error("OPENROUTER_API_KEY is not configured in .env or environment.");
  }

  const url = "https://openrouter.ai/api/alpha/decisions";
  const payload = {
    model,
    state,
    questions,
  };

  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${apiKey}`,
      "Content-Type": "application/json",
      "HTTP-Referer": "https://github.com/xorao/camoufox-vnc",
      "X-Title": "Camoufox VNC Bridge",
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`OpenRouter Jev API returned ${res.status}: ${errText}`);
  }

  return await res.json();
}

function getJevChoice(response, questionKey) {
  const q = response?.answers?.[questionKey] || response?.decisions?.[questionKey] || response?.[questionKey];
  if (!q) return null;
  if (typeof q === "string") return q;
  return q.choice || q.value || q.selected || null;
}

function getJevConfidence(response, questionKey) {
  const q = response?.answers?.[questionKey] || response?.decisions?.[questionKey] || response?.[questionKey];
  if (!q) return null;
  return q.confidence !== undefined ? q.confidence : null;
}

async function extractClickableElements() {
  const script = `
(() => {
  const isVisible = (el) => {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 && rect.bottom >= 0 && rect.top <= window.innerHeight;
  };

  const candidates = Array.from(document.querySelectorAll(
    'button, a, input[type="button"], input[type="submit"], [role="button"], [role="link"], [role="tab"], [tabindex]:not([tabindex="-1"])'
  ));

  let counter = 1;
  const list = [];
  for (const el of candidates) {
    if (!isVisible(el)) continue;
    const text = (
      el.innerText ||
      el.textContent ||
      el.value ||
      el.getAttribute('aria-label') ||
      el.getAttribute('title') ||
      ''
    ).trim().replace(/\\s+/g, ' ');

    if (!text && !el.id && !el.className) continue;

    let marker = el.getAttribute('data-mcp-el');
    if (!marker) {
      marker = 'mcp-el-' + (counter++);
      el.setAttribute('data-mcp-el', marker);
    }

    list.push({
      id: marker,
      tag: el.tagName.toLowerCase(),
      text: text.slice(0, 120),
      selector: '[data-mcp-el="' + marker + '"]'
    });

    if (list.length >= 35) break;
  }
  return list;
})()
`;
  const res = await sendCmd("/evaluate", { script });
  return Array.isArray(res?.result) ? res.result : [];
}

async function extractInputElements() {
  const script = `
(() => {
  const isVisible = (el) => {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };

  const candidates = Array.from(document.querySelectorAll(
    'input:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="checkbox"]):not([type="radio"]), textarea, [contenteditable="true"]'
  ));

  let counter = 1;
  const list = [];
  for (const el of candidates) {
    if (!isVisible(el)) continue;
    const placeholder = el.getAttribute('placeholder') || '';
    const name = el.getAttribute('name') || '';
    const ariaLabel = el.getAttribute('aria-label') || '';
    const title = el.getAttribute('title') || '';
    const type = el.getAttribute('type') || 'text';

    let marker = el.getAttribute('data-mcp-in');
    if (!marker) {
      marker = 'mcp-in-' + (counter++);
      el.setAttribute('data-mcp-in', marker);
    }

    list.push({
      id: marker,
      type: type,
      placeholder: placeholder.slice(0, 80),
      name: name.slice(0, 80),
      ariaLabel: (ariaLabel || title).slice(0, 80),
      selector: '[data-mcp-in="' + marker + '"]'
    });

    if (list.length >= 25) break;
  }
  return list;
})()
`;
  const res = await sendCmd("/evaluate", { script });
  return Array.isArray(res?.result) ? res.result : [];
}

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
  const tools = [
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
  ];

  const jev = getJevConfig();
  if (jev.isActive) {
    tools.push(
      {
        name: "browse_smart_click",
        description: "OPTIONAL (Jev AI System-1): Click an interactive element (button, link, tab) matching an intent in natural language (e.g. 'accept cookies', 'proceed to checkout', 'search button'). Powered by TypeSafe Jev 1.14.",
        inputSchema: {
          type: "object",
          properties: {
            intent: {
              type: "string",
              description: "Natural language description of the target element to click (e.g. 'accept cookies', 'login button', 'shopping cart')",
            },
          },
          required: ["intent"],
        },
      },
      {
        name: "browse_smart_type",
        description: "OPTIONAL (Jev AI System-1): Type text into an input field or search bar matching an intent in natural language (e.g. 'search bar', 'email input'). Powered by TypeSafe Jev 1.14.",
        inputSchema: {
          type: "object",
          properties: {
            intent: {
              type: "string",
              description: "Natural language description of the input field (e.g. 'search field', 'username', 'coupon code')",
            },
            text: {
              type: "string",
              description: "Text to type into the field",
            },
            press_enter: {
              type: "boolean",
              description: "If true, press the Enter key immediately after typing (default: false)",
            },
          },
          required: ["intent", "text"],
        },
      },
      {
        name: "browse_decide",
        description: "OPTIONAL (Jev AI System-1): Ask a fast structured question about the active page (yes/no boolean or pick from options) evaluated in real-time by Jev 1.14 without returning large DOM text. Powered by TypeSafe Jev 1.14.",
        inputSchema: {
          type: "object",
          properties: {
            question: {
              type: "string",
              description: "The question to evaluate against the current page state (e.g. 'Is there a captcha displayed on the page?')",
            },
            type: {
              type: "string",
              enum: ["noul", "choice"],
              description: "Decision type: 'noul' (yes/no boolean probability) or 'choice' (choose from options). Default is 'noul'.",
            },
            options: {
              type: "object",
              description: "Map of option keys to criteria descriptions when type='choice' (e.g. {'logged_in': 'User dashboard visible', 'logged_out': 'Login form visible'}).",
            },
          },
          required: ["question"],
        },
      }
    );
  }

  return { tools };
});

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    if (name === "browse") {
      let targetUrl = args?.url || "";
      if (args?.new_tab) {
        const res = await sendCmd("/new_tab", { url: targetUrl });
        if (res.error) {
          return { isError: true, content: [{ type: "text", text: `Failed to open in new tab: ${res.error}` }] };
        }
        const snap = await sendCmd("/snapshot");
        const pageText = snap.text || "";
        return {
          content: [
            {
              type: "text",
              text: `🌐 [Docker noVNC] Opened in new tab (index ${res.tab_index}): ${res.url}\nTitle: ${res.title}\n\nContent summary:\n${pageText.slice(0, 4000)}`,
            },
          ],
        };
      } else {
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
    }

    if (name === "browse_navigate") {
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

    if (name === "browse_smart_click") {
      const jev = getJevConfig();
      if (!jev.isActive) {
        return {
          isError: true,
          content: [
            {
              type: "text",
              text: "⚠️ 'browse_smart_click' requires Jev to be enabled. Set ENABLE_JEV=true and provide OPENROUTER_API_KEY in your .env file, or use the standard 'browse_click' with a CSS selector.",
            },
          ],
        };
      }

      const elements = await extractClickableElements();
      if (!elements || elements.length === 0) {
        return {
          isError: true,
          content: [{ type: "text", text: "No visible clickable elements found in the current viewport." }],
        };
      }

      const criteria = {};
      for (const el of elements) {
        criteria[el.id] = `<${el.tag}> with text: "${el.text}"`;
      }
      criteria["none"] = "None of the visible elements match the user intent.";

      const jevRes = await callJevDecisions(
        {
          intent: args.intent,
          elements: elements.map((e) => ({ id: e.id, tag: e.tag, text: e.text })),
        },
        {
          target_element: {
            type: "choice",
            instructions: `Which element best matches the user intent: "${args.intent}"? If none matches, choose "none".`,
            criteria,
          },
        }
      );

      const chosenId = getJevChoice(jevRes, "target_element");
      const confidence = getJevConfidence(jevRes, "target_element");

      if (!chosenId || chosenId === "none") {
        return {
          content: [
            {
              type: "text",
              text: `ℹ️ [Jev 1.14] Evaluated ${elements.length} clickable elements, but none matched the intent: "${args.intent}".`,
            },
          ],
        };
      }

      const target = elements.find((e) => e.id === chosenId);
      if (!target) {
        return {
          isError: true,
          content: [{ type: "text", text: `Jev chose element ID '${chosenId}', but it could not be resolved.` }],
        };
      }

      const clickRes = await sendCmd("/click", { selector: target.selector });
      if (clickRes.error) {
        return {
          isError: true,
          content: [{ type: "text", text: `Jev selected '${target.text}' (${target.selector}), but click failed: ${clickRes.error}` }],
        };
      }

      const confText = confidence !== null ? ` (confidence: ${(confidence * 100).toFixed(1)}%)` : "";
      return {
        content: [
          {
            type: "text",
            text: `⚡ [Jev 1.14 Smart Click] Intent: "${args.intent}"\nClicked: <${target.tag}> "${target.text}" (${target.selector})${confText}\nCurrent URL: ${clickRes.url || ""} (${clickRes.title || ""})`,
          },
        ],
      };
    }

    if (name === "browse_smart_type") {
      const jev = getJevConfig();
      if (!jev.isActive) {
        return {
          isError: true,
          content: [
            {
              type: "text",
              text: "⚠️ 'browse_smart_type' requires Jev to be enabled. Set ENABLE_JEV=true and provide OPENROUTER_API_KEY in your .env file, or use the standard 'browse_type' with a CSS selector.",
            },
          ],
        };
      }

      const inputs = await extractInputElements();
      if (!inputs || inputs.length === 0) {
        return {
          isError: true,
          content: [{ type: "text", text: "No visible input fields or textareas found in the page." }],
        };
      }

      const criteria = {};
      for (const el of inputs) {
        const desc = [
          el.placeholder ? `placeholder="${el.placeholder}"` : "",
          el.name ? `name="${el.name}"` : "",
          el.ariaLabel ? `label="${el.ariaLabel}"` : "",
          `type="${el.type}"`,
        ].filter(Boolean).join(" ");
        criteria[el.id] = desc || el.id;
      }
      criteria["none"] = "None of the inputs match the user intent.";

      const jevRes = await callJevDecisions(
        {
          intent: args.intent,
          inputs: inputs.map((e) => ({ id: e.id, placeholder: e.placeholder, name: e.name, label: e.ariaLabel })),
        },
        {
          target_input: {
            type: "choice",
            instructions: `Which input field best matches the user intent: "${args.intent}"? If none matches, choose "none".`,
            criteria,
          },
        }
      );

      const chosenId = getJevChoice(jevRes, "target_input");
      const confidence = getJevConfidence(jevRes, "target_input");

      if (!chosenId || chosenId === "none") {
        return {
          content: [
            {
              type: "text",
              text: `ℹ️ [Jev 1.14] Evaluated ${inputs.length} inputs, but none matched the intent: "${args.intent}".`,
            },
          ],
        };
      }

      const target = inputs.find((e) => e.id === chosenId);
      if (!target) {
        return {
          isError: true,
          content: [{ type: "text", text: `Jev chose input ID '${chosenId}', but it could not be resolved.` }],
        };
      }

      const typeRes = await sendCmd("/type", {
        selector: target.selector,
        text: args.text,
        clear: true,
      });
      if (typeRes.error) {
        return {
          isError: true,
          content: [{ type: "text", text: `Jev selected input (${target.selector}), but typing failed: ${typeRes.error}` }],
        };
      }

      let enterNote = "";
      if (args.press_enter) {
        await sendCmd("/press_key", { key: "Enter" });
        enterNote = " (and pressed Enter)";
      }

      const confText = confidence !== null ? ` (confidence: ${(confidence * 100).toFixed(1)}%)` : "";
      return {
        content: [
          {
            type: "text",
            text: `⚡ [Jev 1.14 Smart Type] Intent: "${args.intent}"\nTyped "${args.text}" into ${target.selector}${enterNote}${confText}`,
          },
        ],
      };
    }

    if (name === "browse_decide") {
      const jev = getJevConfig();
      if (!jev.isActive) {
        return {
          isError: true,
          content: [
            {
              type: "text",
              text: "⚠️ 'browse_decide' requires Jev to be enabled. Set ENABLE_JEV=true and provide OPENROUTER_API_KEY in your .env file.",
            },
          ],
        };
      }

      const snap = await sendCmd("/snapshot");
      const pageSummary = (snap.text || "").slice(0, 4000);
      const decType = args.type === "choice" ? "choice" : "noul";

      const questionObj = {
        type: decType,
        instructions: args.question,
      };
      if (decType === "choice" && args.options && typeof args.options === "object") {
        questionObj.criteria = args.options;
      }

      const jevRes = await callJevDecisions(
        {
          url: snap.url || "",
          title: snap.title || "",
          content_summary: pageSummary,
        },
        {
          evaluation: questionObj,
        }
      );

      const decisionData = jevRes?.answers?.evaluation || jevRes?.decisions?.evaluation || jevRes?.evaluation || jevRes;
      return {
        content: [
          {
            type: "text",
            text: `⚡ [Jev 1.14 Decision]\nQuestion: "${args.question}"\nType: ${decType}\nPage: ${snap.url} (${snap.title})\n\nDecision:\n${JSON.stringify(decisionData, null, 2)}`,
          },
        ],
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
