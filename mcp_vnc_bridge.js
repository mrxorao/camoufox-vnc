#!/usr/bin/env node
/**
 * Camoufox Docker VNC MCP Bridge
 * Connects AI agents directly to the live Camoufox session in Docker (noVNC: http://localhost:5800).
 * Talks to the internal Stealth API at http://127.0.0.1:9377
 *
 * MODES:
 * 1. Normal Mode: Direct atomic tools (browse_click, browse_type, browse_snapshot, etc.)
 * 2. Fast Mode (browse_fast): Pure TypeSafe Jev 1.14 autonomous agent (~150ms/step, zero LLM reasoning tokens).
 *    Mandatory stop rule: strictly halts when BLOCKED or budget reached without automatic fallback.
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
    const errorBody = await res.text().catch(() => "");
    throw new Error(`OpenRouter Decisions API failed with HTTP ${res.status}: ${errorBody}`);
  }

  return await res.json();
}

function buildActionSpace(actions) {
  const elements = [];
  const targets = {};
  const controls = {};

  for (const action of actions || []) {
    if (action.kind === "scroll" || action.kind === "wait") {
      const op = action.kind === "scroll" ? (action.delta > 0 ? "SCROLL_DOWN" : "SCROLL_UP") : "WAIT";
      controls[op] = action.label || op;
      targets[op] = targets[op] || {};
      targets[op][action.id] = action;
      continue;
    }

    const op = action.kind === "fill" ? "FILL" : action.kind === "select" ? "SELECT" : "CLICK";
    const label = action.label || action.role || action.id;
    const targetKey = String(action.node || action.id);

    elements.push({
      index: targetKey,
      id: action.id,
      role: action.role,
      label: label,
      value: action.value || "",
      operations: [op],
    });

    controls[op] = controls[op] || `Interact via ${op}`;
    targets[op] = targets[op] || {};
    targets[op][targetKey] = action;
  }
  return { elements, targets, controls };
}

function extractFieldText(goal) {
  if (!goal) return "";
  const cleaned = goal
    .replace(/^(pesquisa por|pesquisar por|pesquisa|pesquisar|search for|search|procura por|procura|find|book|type|enter|digita|escreve)\s+/i, "")
    .trim();
  return cleaned || goal.trim();
}

async function waitForPageSettle(lastAction = null, maxWaitMs = 1500) {
  const start = Date.now();
  await new Promise((r) => setTimeout(r, 200));

  while (Date.now() - start < maxWaitMs) {
    try {
      const evalRes = await sendCmd("/evaluate", {
        script: `(() => {
          const ready = document.readyState === 'complete';
          const busy = Boolean(document.querySelector('[aria-busy="true"], .loading, .spinner, .skeleton, [data-loading="true"]'));
          return { ready, busy };
        })()`,
      });
      if (evalRes?.result?.ready && !evalRes?.result?.busy) {
        break;
      }
    } catch (e) {
      // ignore
    }
    await new Promise((r) => setTimeout(r, 150));
  }
}

async function runFastAutonomousLoop(goal, options = {}) {
  const maxSteps = Math.min(Math.max(Number(options.max_steps) || 15, 1), 30);
  const jev = getJevConfig();
  if (!jev.isActive) {
    return {
      status: "error",
      error: "Fast browsing requires Jev to be enabled. Set ENABLE_JEV=true and provide OPENROUTER_API_KEY in .env.",
    };
  }

  if (options.url) {
    let targetUrl = options.url.trim();
    if (!targetUrl.startsWith("http://") && !targetUrl.startsWith("https://")) {
      targetUrl = "https://" + targetUrl;
    }
    await sendCmd("/navigate", { url: targetUrl });
    await waitForPageSettle({ operation: "CLICK", action: "navigate" }, 3000);
  }

  const history = [];
  const startedAt = Date.now();
  let lastFingerprint = null;
  let consecutiveWaits = 0;

  for (let step = 1; step <= maxSteps; step++) {
    let obsRes = await sendCmd("/observe_fast");
    // Ensure the page has had a chance to render actual interactive elements
    for (let retry = 0; retry < 6; retry++) {
      if (obsRes?.state?.actions) {
        const hasInteractive = obsRes.state.actions.some(
          (a) => a.kind === "click" || a.kind === "fill" || a.kind === "select"
        );
        if (hasInteractive && obsRes.state.title) break;
      }
      await new Promise((r) => setTimeout(r, 500));
      obsRes = await sendCmd("/observe_fast");
    }

    if (obsRes.error || !obsRes.state) {
      return {
        status: "error",
        error: `Observation failed at step ${step}: ${obsRes.error || "no state"}`,
        history,
        elapsed_ms: Date.now() - startedAt,
      };
    }

    const state = obsRes.state;

    // Detect DOM stagnation
    if (state.fingerprint && state.fingerprint === lastFingerprint) {
      // Fingerprint unchanged
    } else {
      lastFingerprint = state.fingerprint || null;
    }

    const { elements, targets, controls } = buildActionSpace(state.actions);

    const questions = {
      operation: {
        type: "choice",
        instructions: `Given the user goal "${goal}", choose the single next operation to make progress. If an operation was already attempted and the page did not change, choose a different operation or BLOCKED. If goal is achieved, choose DONE. If blocked or unable to proceed, choose BLOCKED.`,
        criteria: controls,
      },
    };

    let selectedOp = null;
    let opAnswer = null;
    let jevLatency = 0;
    let jevError = null;

    try {
      const qStart = Date.now();
      const jevRes = await callJevDecisions(state, questions);
      jevLatency = Date.now() - qStart;
      opAnswer = jevRes?.answers?.operation || jevRes?.decisions?.operation || jevRes?.operation || jevRes;
      selectedOp = opAnswer?.choice || opAnswer?.id || opAnswer;
    } catch (e) {
      jevError = e.message;
    }

    if (jevError) {
      return {
        status: "error",
        error: `Jev decision request failed at step ${step}: ${jevError}`,
        history,
        elapsed_ms: Date.now() - startedAt,
      };
    }

    if (!selectedOp || typeof selectedOp !== "string") {
      return {
        status: "blocked",
        reason: `Jev did not return a valid operation choice at step ${step}.`,
        goal,
        steps_executed: step,
        history,
        elapsed_ms: Date.now() - startedAt,
        suggestion: "Execution halted. The calling AI must STOP and NOT execute further browser actions without explicit user orders.",
      };
    }

    selectedOp = selectedOp.trim();

    if (selectedOp === "DONE") {
      history.push({
        step,
        engine: "jev",
        operation: "DONE",
        action: "Goal satisfied",
        latency_ms: jevLatency,
      });
      return {
        status: "completed",
        goal,
        steps_executed: step,
        final_url: state.url,
        final_title: state.title,
        history,
        elapsed_ms: Date.now() - startedAt,
      };
    }

    if (selectedOp === "BLOCKED") {
      history.push({
        step,
        engine: "jev",
        operation: "BLOCKED",
        action: "No action can make progress",
        latency_ms: jevLatency,
      });
      return {
        status: "blocked",
        reason: "Fast mode (pure Jev) determined that no supported operation can make progress towards the goal.",
        goal,
        steps_executed: step,
        final_url: state.url,
        history,
        elapsed_ms: Date.now() - startedAt,
        suggestion: "Execution halted strictly in Fast Mode (Pure Jev). The calling AI must STOP and NOT execute further browser actions without explicit user orders.",
      };
    }

    if (selectedOp === "WAIT") {
      consecutiveWaits++;
      if (consecutiveWaits > 4) {
        history.push({
          step,
          engine: "jev",
          operation: "WAIT",
          action: "Max consecutive waits reached",
          latency_ms: jevLatency,
        });
        return {
          status: "blocked",
          reason: "Fast mode reached the consecutive wait limit (page remained loading or unchanged after multiple wait cycles).",
          goal,
          steps_executed: step,
          final_url: state.url,
          history,
          elapsed_ms: Date.now() - startedAt,
          suggestion: "Use Normal Mode to inspect or complete the task.",
        };
      }
    } else {
      consecutiveWaits = 0;
    }

    // Identify candidate target
    let targetAction = null;
    let targetIndex = null;
    let textToType = null;
    const opTargets = targets[selectedOp] || {};
    const targetKeys = Object.keys(opTargets);

    if (targetKeys.length === 1) {
      targetAction = opTargets[targetKeys[0]];
      targetIndex = targetKeys[0];
    } else if (targetKeys.length > 1) {
      const targetQuestions = {
        target: {
          type: "choice",
          instructions: `Goal: "${goal}". For operation "${selectedOp}", select the best target element index to advance towards the goal.`,
          criteria: Object.fromEntries(
            targetKeys.map((k) => [k, `${opTargets[k].label || opTargets[k].role || k}`])
          ),
        },
      };
      try {
        const tStart = Date.now();
        const tRes = await callJevDecisions(state, targetQuestions);
        jevLatency += Date.now() - tStart;
        const chosenTargetKey = tRes?.answers?.target?.choice || tRes?.answers?.target || tRes?.decisions?.target?.choice;
        if (chosenTargetKey && opTargets[chosenTargetKey]) {
          targetAction = opTargets[chosenTargetKey];
          targetIndex = chosenTargetKey;
        } else {
          targetAction = opTargets[targetKeys[0]];
          targetIndex = targetKeys[0];
        }
      } catch (e) {
        targetAction = opTargets[targetKeys[0]];
        targetIndex = targetKeys[0];
      }
    }

    const candidateActionName = targetAction ? targetAction.label || targetAction.id : null;
    const lastAction = history[history.length - 1];
    const isActionLoop = Boolean(
      selectedOp !== "WAIT" &&
      lastAction &&
      candidateActionName &&
      lastAction.action === candidateActionName &&
      lastAction.operation === selectedOp
    );

    if (isActionLoop) {
      history.push({
        step,
        engine: "jev",
        operation: selectedOp,
        action: candidateActionName,
        error: "Action loop detected",
        latency_ms: jevLatency,
      });
      return {
        status: "blocked",
        reason: `Fast mode detected an action loop: '${selectedOp}' on '${candidateActionName}' repeated with no state change.`,
        goal,
        steps_executed: step,
        final_url: state.url,
        history,
        elapsed_ms: Date.now() - startedAt,
        suggestion: "Execution halted strictly in Fast Mode (Pure Jev). The calling AI must STOP and NOT execute further browser actions without explicit user orders.",
      };
    }

    if (!targetAction) {
      return {
        status: "blocked",
        reason: `Target element for operation '${selectedOp}' could not be resolved.`,
        goal,
        steps_executed: step,
        history,
        elapsed_ms: Date.now() - startedAt,
        suggestion: "Execution halted strictly in Fast Mode. The calling AI must STOP and await user instructions.",
      };
    }

    if (targetAction.kind === "fill" && !textToType) {
      textToType = extractFieldText(goal);
    }

    const actStart = Date.now();
    const actRes = await sendCmd("/act_fast", { action: targetAction, text: textToType });
    const actLatency = Date.now() - actStart;

    history.push({
      step,
      engine: "jev",
      operation: selectedOp,
      action: targetAction.label || targetAction.id,
      target_index: targetIndex,
      text: textToType,
      latency_ms: jevLatency + actLatency,
      error: actRes.error || null,
    });

    if (selectedOp === "WAIT") {
      await new Promise((r) => setTimeout(r, 1000));
      await waitForPageSettle(null, 2500);
    } else {
      await waitForPageSettle({
        operation: selectedOp,
        action: targetAction.label || targetAction.id,
      });
    }
  }

  return {
    status: "max_steps_reached",
    reason: `Fast agent reached step limit (${maxSteps}) before reaching DONE.`,
    goal,
    steps_executed: maxSteps,
    history,
    elapsed_ms: Date.now() - startedAt,
    suggestion: "Budget reached strictly in Fast Mode. The calling AI must STOP and NOT execute further browser actions without explicit user orders.",
  };
}

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
  ];

  const jev = getJevConfig();
  if (jev.isActive) {
    tools.push({
      name: "browse_fast",
      description: "FAST AUTONOMOUS BROWSER AGENT (Pure TypeSafe Jev 1.14): Multi-step web task execution strictly using pure Jev (~150ms per step, zero LLM reasoning tokens). Guided by indexed DOM actions and humanized Bézier mouse trajectories. MANDATORY STOP RULE: If BLOCKED, loop detected, or step budget reached, execution HALTS IMMEDIATELY. The calling AI must STOP and NOT execute any further Camoufox or browser commands without explicit user orders.",
      inputSchema: {
        type: "object",
        properties: {
          goal: {
            type: "string",
            description: "The complete natural language goal to accomplish on the current or targeted page (e.g. 'Search for flights from Lisbon to Paris on Google Flights and pick the earliest flight', 'Reject cookies and accept terms')",
          },
          url: {
            type: "string",
            description: "Optional URL to navigate to before beginning the autonomous task. If omitted, continues from the active page.",
          },
          max_steps: {
            type: "number",
            description: "Maximum autonomous steps before returning control (default 15, max 30).",
          },
        },
        required: ["goal"],
      },
    });
  }

  return { tools };
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

    if (name === "browse_fast") {
      const result = await runFastAutonomousLoop(args.goal, {
        url: args.url,
        max_steps: args.max_steps,
      });

      if (result.status === "error") {
        return {
          isError: true,
          content: [{ type: "text", text: `❌ Fast Agent Error: ${result.error}` }],
        };
      }

      const formattedHistory = (result.history || [])
        .map((h) => {
          const detail = h.text ? ` -> typed "${h.text}"` : (h.error ? ` -> error: ${h.error}` : "");
          return `Step ${h.step} [⚡ Jev]: [${h.operation}] ${h.action || ""}${detail} [${h.latency_ms || 0}ms]`;
        })
        .join("\n");

      let statusMsg = "";
      if (result.status === "completed") {
        statusMsg = `⚡ [Fast Agent: COMPLETED in ${result.elapsed_ms}ms]\nGoal: "${args.goal}"\nFinal URL: ${result.final_url} (${result.final_title || ""})\nSteps executed: ${result.steps_executed}\n\nExecution Log:\n${formattedHistory || "Done"}`;
      } else if (result.status === "blocked") {
        statusMsg = `⚠️ [Fast Agent: BLOCKED after ${result.elapsed_ms}ms]\nGoal: "${args.goal}"\nReason: ${result.reason}\nFinal URL: ${result.final_url || ""}\nSteps executed: ${result.steps_executed}\nDirective: ${result.suggestion || "Stop and await instructions."}\n\nExecution Log:\n${formattedHistory || "None"}`;
      } else {
        statusMsg = `⏱️ [Fast Agent: BUDGET REACHED after ${result.elapsed_ms}ms]\nGoal: "${args.goal}"\nSteps executed: ${result.steps_executed}\nDirective: ${result.suggestion || "Stop and await instructions."}\n\nExecution Log:\n${formattedHistory || "None"}`;
      }

      return {
        content: [{ type: "text", text: statusMsg }],
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
