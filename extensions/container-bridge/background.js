/**
 * Camoufox Container & Proxy Bridge (WebExtension MV2)
 *
 * Bridges Camoufox's local HTTP control API (default http://127.0.0.1:9377)
 * with Firefox's native contextualIdentities, tabs, cookies, proxy, and header APIs.
 */

const VALID_COLORS = new Set([
  "blue", "turquoise", "green", "yellow", "orange", "red", "pink", "purple", "toolbar"
]);

const VALID_ICONS = new Set([
  "fingerprint", "briefcase", "dollar", "cart", "vacation",
  "gift", "food", "fruit", "pet", "tree", "chill", "circle", "fence"
]);

let API_BASE = "http://127.0.0.1:9377";

// Map: cookieStoreId -> { type, host, port, username?, password?, proxyDNS?, data_saver?, geo?: { ... } }
let proxyByCookieStoreId = {};

// Count blocked requests per cookieStoreId for observability
const blockedCountByStore = {};

const SECURITY_ALLOWLIST = [
  "challenges.cloudflare.com",
  "hcaptcha.com",
  "recaptcha.net",
  "arkoselabs.com",
  "funcaptcha.com",
  "datadome.co",
];

const TRACKER_DOMAINS = [
  "doubleclick.net",
  "googlesyndication.com",
  "googleadservices.com",
  "google-analytics.com",
  "googletagmanager.com",
  "adservice.google.com",
  "connect.facebook.net",
  "analytics.tiktok.com",
  "hotjar.com",
  "clarity.ms",
  "taboola.com",
  "outbrain.com",
  "criteo.com",
  "criteo.net",
  "adsrvr.org",
  "adnxs.com",
  "rubiconproject.com",
  "pubmatic.com",
  "openx.net",
  "amazon-adsystem.com",
  "scorecardresearch.com",
  "quantserve.com",
  "bing.com/bat",
];

function hostMatchesList(hostname, list) {
  const h = (hostname || "").toLowerCase();
  for (const dom of list) {
    if (h === dom || h.endsWith("." + dom)) return true;
  }
  return false;
}

// Per-container bandwidth / data_saver blocker (cancels before opening proxy connection -> 0 bytes)
browser.webRequest.onBeforeRequest.addListener(
  (details) => {
    if (!details || isLocalUrl(details.url)) return {};
    const storeId = details.cookieStoreId;
    const cfg = storeId ? proxyByCookieStoreId[storeId] : null;
    const mode = cfg && cfg.data_saver ? String(cfg.data_saver).toLowerCase() : "off";
    if (!mode || mode === "off") return {};

    let hostname = "";
    try {
      hostname = new URL(details.url).hostname.toLowerCase();
    } catch (_) {
      return {};
    }

    // Never block anti-bot / CAPTCHA verification domains
    if (hostMatchesList(hostname, SECURITY_ALLOWLIST) || details.url.includes("gstatic.com/recaptcha")) {
      return {};
    }

    const rtype = details.type || "";
    let shouldBlock = false;

    if (mode === "media") {
      shouldBlock = rtype === "media";
    } else if (mode === "smart") {
      shouldBlock =
        rtype === "media" ||
        rtype === "beacon" ||
        rtype === "ping" ||
        hostMatchesList(hostname, TRACKER_DOMAINS);
    } else if (mode === "images") {
      shouldBlock =
        rtype === "image" ||
        rtype === "imageset" ||
        rtype === "media" ||
        rtype === "beacon" ||
        rtype === "ping" ||
        hostMatchesList(hostname, TRACKER_DOMAINS);
    } else if (mode === "aggressive") {
      shouldBlock =
        rtype === "image" ||
        rtype === "imageset" ||
        rtype === "media" ||
        rtype === "font" ||
        rtype === "object" ||
        rtype === "beacon" ||
        rtype === "ping" ||
        hostMatchesList(hostname, TRACKER_DOMAINS);
    }

    if (shouldBlock) {
      blockedCountByStore[storeId] = (blockedCountByStore[storeId] || 0) + 1;
      return { cancel: true };
    }
    return {};
  },
  { urls: ["<all_urls>"] },
  ["blocking"]
);

// Prevent infinite proxy auth retry loops per requestId
const authAttempts = new Map();

async function loadApiConfig() {
  try {
    const resp = await fetch(browser.runtime.getURL("config.json"));
    if (resp.ok) {
      const cfg = await resp.json();
      if (cfg && cfg.api_port) {
        API_BASE = `http://127.0.0.1:${cfg.api_port}`;
      }
    }
  } catch (_) {
    // Fallback to default 9377
  }
}

function isLocalUrl(urlStr) {
  try {
    const u = new URL(urlStr);
    const h = (u.hostname || "").toLowerCase();
    return h === "127.0.0.1" || h === "localhost" || h === "::1";
  } catch (_) {
    return false;
  }
}

// Per-container proxy routing
browser.proxy.onRequest.addListener(
  (details) => {
    if (!details || isLocalUrl(details.url)) {
      return { type: "direct" };
    }
    const storeId = details.cookieStoreId;
    if (!storeId || !proxyByCookieStoreId[storeId]) {
      return { type: "direct" };
    }
    const cfg = proxyByCookieStoreId[storeId];
    if (!cfg || !cfg.host || !cfg.port) {
      return { type: "direct" };
    }

    const proxyInfo = {
      type: cfg.type || "http",
      host: cfg.host,
      port: Number(cfg.port),
    };

    if (proxyInfo.type === "socks" || proxyInfo.type === "socks4") {
      proxyInfo.proxyDNS = cfg.proxyDNS !== false;
      if (cfg.username) proxyInfo.username = cfg.username;
      if (cfg.password) proxyInfo.password = cfg.password;
    }

    return proxyInfo;
  },
  { urls: ["<all_urls>"] }
);

// Per-container Accept-Language header matching proxy geo locale
browser.webRequest.onBeforeSendHeaders.addListener(
  (details) => {
    if (!details || isLocalUrl(details.url)) return {};
    const storeId = details.cookieStoreId;
    const cfg = storeId ? proxyByCookieStoreId[storeId] : null;
    const acceptLang = cfg && cfg.geo && cfg.geo.acceptLanguage;
    if (!acceptLang || !Array.isArray(details.requestHeaders)) return {};

    const headers = details.requestHeaders.filter(
      (h) => (h.name || "").toLowerCase() !== "accept-language"
    );
    headers.push({ name: "Accept-Language", value: acceptLang });
    return { requestHeaders: headers };
  },
  { urls: ["<all_urls>"] },
  ["blocking", "requestHeaders"]
);

// HTTP/HTTPS proxy authentication per container
browser.webRequest.onAuthRequired.addListener(
  (details) => {
    if (!details || !details.isProxy) {
      return {};
    }
    const storeId = details.cookieStoreId;
    const cfg = storeId ? proxyByCookieStoreId[storeId] : null;
    if (!cfg || !cfg.username) {
      return {};
    }

    const prev = authAttempts.get(details.requestId) || 0;
    if (prev >= 2) {
      authAttempts.delete(details.requestId);
      return { cancel: true };
    }
    authAttempts.set(details.requestId, prev + 1);

    return {
      authCredentials: {
        username: cfg.username,
        password: cfg.password || "",
      },
    };
  },
  { urls: ["<all_urls>"] },
  ["blocking"]
);

browser.webRequest.onCompleted.addListener(
  (details) => { authAttempts.delete(details.requestId); },
  { urls: ["<all_urls>"] }
);

browser.webRequest.onErrorOccurred.addListener(
  (details) => { authAttempts.delete(details.requestId); },
  { urls: ["<all_urls>"] }
);

// Content script asks for current tab's container geo profile
browser.runtime.onMessage.addListener((msg, sender) => {
  if (msg && msg.type === "get_tab_geo") {
    const storeId = sender && sender.tab && sender.tab.cookieStoreId;
    const cfg = storeId ? proxyByCookieStoreId[storeId] : null;
    return Promise.resolve({ geo: (cfg && cfg.geo) || null });
  }
  return undefined;
});

function formatIdentity(ident) {
  const match = /^firefox-container-(\d+)$/.exec(ident.cookieStoreId || "");
  return {
    userContextId: match ? Number(match[1]) : null,
    cookieStoreId: ident.cookieStoreId,
    name: ident.name,
    color: ident.color,
    icon: ident.icon,
  };
}

async function syncProxiesFromServer() {
  try {
    const resp = await fetch(`${API_BASE}/_bridge/proxies`, { cache: "no-store" });
    if (resp.ok) {
      const data = await resp.json();
      if (data && typeof data.proxies === "object" && data.proxies !== null) {
        proxyByCookieStoreId = data.proxies;
      }
    }
  } catch (_) {
    // Will retry on next poll
  }
}

async function handleCommand(cmd) {
  const action = cmd && cmd.action;

  if (action === "list_containers") {
    const identities = await browser.contextualIdentities.query({});
    return {
      ok: true,
      containers: identities.map((ident) => ({
        ...formatIdentity(ident),
        blocked_requests: blockedCountByStore[ident.cookieStoreId] || 0,
      })),
    };
  }

  if (action === "list_tabs") {
    const [tabs, identities] = await Promise.all([
      browser.tabs.query({}),
      browser.contextualIdentities.query({}),
    ]);
    const nameByStore = {};
    for (const ident of identities) {
      nameByStore[ident.cookieStoreId] = ident.name;
    }
    return {
      ok: true,
      tabs: tabs.map((t) => ({
        id: t.id,
        index: t.index,
        url: t.url,
        title: t.title,
        active: t.active,
        cookieStoreId: t.cookieStoreId,
        container: nameByStore[t.cookieStoreId] || null,
      })),
    };
  }

  if (action === "create_container") {
    const name = String(cmd.name || "").trim();
    if (!name) {
      return { ok: false, error: "Container 'name' is required." };
    }
    const existing = await browser.contextualIdentities.query({});
    const dup = existing.find((c) => c.name.toLowerCase() === name.toLowerCase());
    if (dup) {
      return {
        ok: false,
        already_exists: true,
        error: `Container '${dup.name}' already exists.`,
        container: formatIdentity(dup),
      };
    }

    const color = VALID_COLORS.has(cmd.color) ? cmd.color : "blue";
    const icon = VALID_ICONS.has(cmd.icon) ? cmd.icon : "fingerprint";
    const created = await browser.contextualIdentities.create({ name, color, icon });
    return {
      ok: true,
      container: formatIdentity(created),
    };
  }

  if (action === "delete_container") {
    const cookieStoreId = String(cmd.cookieStoreId || "").trim();
    if (!cookieStoreId) {
      return { ok: false, error: "Missing cookieStoreId." };
    }
    const removed = await browser.contextualIdentities.remove(cookieStoreId);
    if (!removed) {
      return { ok: false, error: `Container '${cookieStoreId}' could not be removed or does not exist.` };
    }
    delete proxyByCookieStoreId[cookieStoreId];
    return {
      ok: true,
      container: formatIdentity(removed),
    };
  }

  if (action === "sync_proxies") {
    if (cmd.proxies && typeof cmd.proxies === "object") {
      proxyByCookieStoreId = cmd.proxies;
    } else {
      await syncProxiesFromServer();
    }
    return {
      ok: true,
      count: Object.keys(proxyByCookieStoreId).length,
    };
  }

  if (action === "open_tab") {
    const targetUrl = String(cmd.url || "https://duckduckgo.com");
    const cookieStoreId = String(cmd.cookieStoreId || "");
    if (!cookieStoreId) {
      return { ok: false, error: "Missing cookieStoreId." };
    }

    if (cmd.proxies && typeof cmd.proxies === "object") {
      proxyByCookieStoreId = cmd.proxies;
    }

    const tab = await browser.tabs.create({
      url: targetUrl,
      cookieStoreId,
      active: true,
    });
    return {
      ok: true,
      tabId: tab.id,
      cookieStoreId: tab.cookieStoreId,
      url: tab.url || targetUrl,
    };
  }

  if (action === "get_cookies") {
    const storeId = String(cmd.cookieStoreId || "firefox-default");
    const query = { storeId, firstPartyDomain: null };
    if (cmd.domain) query.domain = String(cmd.domain);
    if (cmd.url) query.url = String(cmd.url);
    let cookies = [];
    try {
      cookies = await browser.cookies.getAll({ ...query, partitionKey: {} });
    } catch (_) {
      cookies = await browser.cookies.getAll(query);
    }
    return {
      ok: true,
      cookieStoreId: storeId,
      count: cookies.length,
      cookies: cookies.map((c) => ({
        name: c.name,
        value: c.value,
        domain: c.domain,
        path: c.path,
        secure: c.secure,
        httpOnly: c.httpOnly,
        sameSite: c.sameSite,
        expirationDate: c.expirationDate,
      })),
    };
  }

  if (action === "set_cookie") {
    const storeId = String(cmd.cookieStoreId || "firefox-default");
    const details = {
      storeId,
      url: String(cmd.url || ""),
      name: String(cmd.name || ""),
      value: String(cmd.value || ""),
    };
    if (!details.url || !details.name) {
      return { ok: false, error: "Parameters 'url' and 'name' are required to set a cookie." };
    }
    if (cmd.domain) details.domain = String(cmd.domain);
    if (cmd.path) details.path = String(cmd.path);
    if (cmd.secure !== undefined) details.secure = Boolean(cmd.secure);
    if (cmd.httpOnly !== undefined) details.httpOnly = Boolean(cmd.httpOnly);
    if (cmd.expirationDate !== undefined) details.expirationDate = Number(cmd.expirationDate);
    let setRes = null;
    let lastErr = null;
    const attempts = [
      details,
      { ...details, firstPartyDomain: "" },
    ];
    try {
      const u = new URL(details.url);
      attempts.push({ ...details, firstPartyDomain: u.hostname });
      attempts.push({ ...details, domain: u.hostname, path: details.path || "/", firstPartyDomain: "" });
    } catch (_) {}
    for (const att of attempts) {
      try {
        setRes = await browser.cookies.set(att);
        if (setRes) break;
      } catch (e) {
        lastErr = String(e && e.message ? e.message : e);
      }
    }
    if (!setRes) {
      return { ok: false, error: `Failed to set cookie '${details.name}' for '${details.url}'${lastErr ? `: ${lastErr}` : "."}` };
    }
    return { ok: true, cookie: setRes };
  }

  if (action === "clear_cookies") {
    const storeId = String(cmd.cookieStoreId || "firefox-default");
    const query = { storeId, firstPartyDomain: null };
    if (cmd.domain) query.domain = String(cmd.domain);
    if (cmd.url) query.url = String(cmd.url);
    let cookies = [];
    try {
      cookies = await browser.cookies.getAll({ ...query, partitionKey: {} });
    } catch (_) {
      cookies = await browser.cookies.getAll(query);
    }
    let removedCount = 0;
    for (const c of cookies) {
      const proto = c.secure ? "https://" : "http://";
      const cleanDomain = (c.domain || "").replace(/^\./, "");
      const cookieUrl = `${proto}${cleanDomain}${c.path || "/"}`;
      try {
        const rmOpts = {
          url: cookieUrl,
          name: c.name,
          storeId,
        };
        if (c.firstPartyDomain !== undefined) rmOpts.firstPartyDomain = c.firstPartyDomain;
        if (c.partitionKey !== undefined) rmOpts.partitionKey = c.partitionKey;
        await browser.cookies.remove(rmOpts);
        removedCount++;
      } catch (_) {}
    }
    return {
      ok: true,
      cookieStoreId: storeId,
      removed_count: removedCount,
    };
  }

  return { ok: false, error: `Unknown bridge action: ${action}` };
}

async function pollLoop() {
  await loadApiConfig();
  await syncProxiesFromServer();

  while (true) {
    try {
      const resp = await fetch(`${API_BASE}/_bridge/poll`, { cache: "no-store" });
      if (resp.status === 204) {
        continue;
      }
      if (!resp.ok) {
        await new Promise((r) => setTimeout(r, 1000));
        continue;
      }
      const cmd = await resp.json();
      if (!cmd || !cmd.id) {
        continue;
      }

      let result;
      try {
        result = await handleCommand(cmd);
      } catch (err) {
        result = { ok: false, error: String(err && err.message ? err.message : err) };
      }

      try {
        await fetch(`${API_BASE}/_bridge/result`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: cmd.id, result }),
        });
      } catch (_) {
        // Ignore callback failure
      }
    } catch (_) {
      await new Promise((r) => setTimeout(r, 1000));
    }
  }
}

pollLoop();
