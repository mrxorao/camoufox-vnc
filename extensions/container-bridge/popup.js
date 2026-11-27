const COLORS = {
  blue: "#3b82f6",
  turquoise: "#14b8a6",
  green: "#22c55e",
  yellow: "#eab308",
  orange: "#f97316",
  red: "#ef4444",
  pink: "#ec4899",
  purple: "#a855f7",
  toolbar: "#94a3b8",
};

let API_BASE = "http://127.0.0.1:9377";
let API_KEY = "";
let containersCache = [];
let pendingDeleteName = null;

const el = (id) => document.getElementById(id);

async function loadConfig() {
  try {
    const resp = await fetch(browser.runtime.getURL("config.json"));
    if (resp.ok) {
      const cfg = await resp.json();
      if (cfg && cfg.api_port) API_BASE = `http://127.0.0.1:${cfg.api_port}`;
      if (cfg && cfg.api_key) API_KEY = String(cfg.api_key);
    }
  } catch (_) {}
}

async function apiCall(path, method = "GET", body = null) {
  const headers = { "Content-Type": "application/json" };
  if (API_KEY) headers["X-API-Key"] = API_KEY;
  const opts = { method, headers };
  if (body !== null) opts.body = JSON.stringify(body);
  const resp = await fetch(`${API_BASE}${path}`, opts);
  const json = await resp.json().catch(() => ({}));
  if (!resp.ok || json.error) {
    throw new Error(json.error || `HTTP ${resp.status}`);
  }
  return json;
}

function showToast(msg, isError = false) {
  const t = el("toast");
  t.textContent = msg;
  t.className = `toast ${isError ? "err" : "ok"}`;
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => {
    t.className = "toast hidden";
  }, 4000);
}

function buildColorPicker() {
  const picker = el("colorPicker");
  picker.innerHTML = "";
  for (const [name, hex] of Object.entries(COLORS)) {
    const sw = document.createElement("button");
    sw.type = "button";
    sw.className = "color-swatch" + (el("fColor").value === name ? " active" : "");
    sw.style.background = hex;
    sw.title = name;
    sw.addEventListener("click", () => {
      el("fColor").value = name;
      picker.querySelectorAll(".color-swatch").forEach((s) => s.classList.remove("active"));
      sw.classList.add("active");
    });
    picker.appendChild(sw);
  }
}

function showListView() {
  el("formView").classList.add("hidden");
  el("listView").classList.remove("hidden");
  pendingDeleteName = null;
}

function showCreateForm() {
  el("editMode").value = "create";
  el("editOriginalName").value = "";
  el("formTitle").textContent = "Novo Container";
  el("nameField").classList.remove("hidden");
  el("appearanceFields").classList.remove("hidden");
  el("btnRemoveProxy").classList.add("hidden");
  el("fName").required = true;
  el("fName").value = "";
  el("fColor").value = "blue";
  el("fIcon").value = "fingerprint";
  el("fProxy").value = "";
  el("fDataSaver").value = "off";
  el("fAutoGeo").checked = true;
  el("fTimezone").value = "";
  el("fLocale").value = "";
  el("fLat").value = "";
  el("fLon").value = "";
  buildColorPicker();
  el("listView").classList.add("hidden");
  el("formView").classList.remove("hidden");
  el("fName").focus();
}

function showEditForm(c) {
  el("editMode").value = "edit";
  el("editOriginalName").value = c.name;
  el("formTitle").textContent = `Editar: ${c.name}`;
  el("nameField").classList.add("hidden");
  el("appearanceFields").classList.add("hidden");
  el("fName").required = false;
  el("fProxy").value = "";
  el("fProxy").placeholder = c.proxy
    ? `Atual: ${c.proxy} (deixa vazio para manter)`
    : "http://user:pass@host:port ou socks5://host:1080";
  el("fDataSaver").value = c.data_saver || "off";
  el("fAutoGeo").checked = true;
  const g = c.geo || {};
  el("fTimezone").value = g.timezone || "";
  el("fLocale").value = g.locale || "";
  el("fLat").value = typeof g.lat === "number" ? String(g.lat) : "";
  el("fLon").value = typeof g.lon === "number" ? String(g.lon) : "";
  if (c.proxy) {
    el("btnRemoveProxy").classList.remove("hidden");
  } else {
    el("btnRemoveProxy").classList.add("hidden");
  }
  el("listView").classList.add("hidden");
  el("formView").classList.remove("hidden");
}

function renderContainers(list) {
  containersCache = list || [];
  el("statusText").textContent = `${containersCache.length} container(s) ativo(s)`;
  const containerEl = el("containersList");
  containerEl.innerHTML = "";

  if (containersCache.length === 0) {
    el("emptyState").classList.remove("hidden");
    return;
  }
  el("emptyState").classList.add("hidden");

  for (const c of containersCache) {
    const hex = COLORS[c.color] || "#3b82f6";
    const card = document.createElement("div");
    card.className = "card";
    card.style.borderLeftColor = hex;

    const top = document.createElement("div");
    top.className = "card-top";

    const nameDiv = document.createElement("div");
    nameDiv.className = "card-name";
    const dot = document.createElement("span");
    dot.className = "dot";
    dot.style.background = hex;
    nameDiv.appendChild(dot);
    nameDiv.appendChild(document.createTextNode(c.name));

    const badges = document.createElement("div");
    badges.className = "badges";
    if (c.data_saver && c.data_saver !== "off") {
      const bDs = document.createElement("span");
      bDs.className = "badge ds";
      bDs.textContent = `data_saver: ${c.data_saver}`;
      badges.appendChild(bDs);
    }
    if (c.blocked_requests > 0) {
      const bBlk = document.createElement("span");
      bBlk.className = "badge";
      bBlk.textContent = `🛡️ ${c.blocked_requests} bloq.`;
      badges.appendChild(bBlk);
    }

    top.appendChild(nameDiv);
    top.appendChild(badges);
    card.appendChild(top);

    const meta = document.createElement("div");
    meta.className = "meta";

    const proxyLine = document.createElement("div");
    proxyLine.innerHTML = `<strong>Proxy:</strong> `;
    proxyLine.appendChild(document.createTextNode(c.proxy || "Rota padrão (VPN)"));
    meta.appendChild(proxyLine);

    if (c.geo) {
      const g = c.geo;
      const parts = [g.country, g.timezone, g.locale, g.ip].filter(Boolean);
      if (typeof g.lat === "number" && typeof g.lon === "number") {
        parts.push(`${g.lat.toFixed(2)},${g.lon.toFixed(2)}`);
      }
      if (parts.length > 0) {
        const geoLine = document.createElement("div");
        geoLine.innerHTML = `<strong>Geo:</strong> `;
        geoLine.appendChild(document.createTextNode(parts.join(" • ")));
        meta.appendChild(geoLine);
      }
    }
    card.appendChild(meta);

    const actions = document.createElement("div");
    actions.className = "card-actions";

    const btnOpen = document.createElement("button");
    btnOpen.className = "btn-sm open";
    btnOpen.textContent = "+ Tab";
    btnOpen.addEventListener("click", async () => {
      try {
        await browser.tabs.create({ cookieStoreId: c.cookieStoreId, active: true });
        window.close();
      } catch (e) {
        showToast(`Erro ao abrir tab: ${e.message}`, true);
      }
    });

    const btnEdit = document.createElement("button");
    btnEdit.className = "btn-sm";
    btnEdit.textContent = "Editar";
    btnEdit.addEventListener("click", () => showEditForm(c));

    const btnCookies = document.createElement("button");
    btnCookies.className = "btn-sm";
    btnCookies.textContent = "Limpar Cookies";
    btnCookies.addEventListener("click", async () => {
      btnCookies.disabled = true;
      try {
        const res = await apiCall("/cookies", "POST", { action: "clear", container: c.name });
        showToast(`🧹 ${res.removed_count ?? 0} cookie(s) limpo(s) em '${c.name}'.`);
      } catch (e) {
        showToast(`Erro: ${e.message}`, true);
      } finally {
        btnCookies.disabled = false;
      }
    });

    const btnDel = document.createElement("button");
    btnDel.className = "btn-sm danger";
    btnDel.textContent = pendingDeleteName === c.name ? "Confirmar?" : "Apagar";
    btnDel.addEventListener("click", async () => {
      if (pendingDeleteName !== c.name) {
        pendingDeleteName = c.name;
        btnDel.textContent = "Confirmar?";
        return;
      }
      btnDel.disabled = true;
      try {
        await apiCall("/containers/delete", "POST", { container: c.name });
        pendingDeleteName = null;
        showToast(`🗑️ Container '${c.name}' apagado.`);
        await refreshContainers();
      } catch (e) {
        showToast(`Erro ao apagar: ${e.message}`, true);
        btnDel.disabled = false;
      }
    });

    actions.appendChild(btnOpen);
    actions.appendChild(btnEdit);
    actions.appendChild(btnCookies);
    actions.appendChild(btnDel);
    card.appendChild(actions);
    containerEl.appendChild(card);
  }
}

async function refreshContainers() {
  el("statusText").textContent = "A atualizar...";
  try {
    const res = await apiCall("/containers", "GET");
    renderContainers(res.containers || []);
  } catch (e) {
    el("statusText").textContent = "Erro de ligação";
    showToast(`Falha ao comunicar com a API (${API_BASE}): ${e.message}`, true);
  }
}

el("btnRefresh").addEventListener("click", refreshContainers);
el("btnNew").addEventListener("click", showCreateForm);
el("btnCancel").addEventListener("click", showListView);

el("btnRemoveProxy").addEventListener("click", async () => {
  const name = el("editOriginalName").value;
  if (!name) return;
  el("btnRemoveProxy").disabled = true;
  try {
    await apiCall("/containers/proxy", "POST", {
      container: name,
      proxy: "",
      data_saver: el("fDataSaver").value,
    });
    showToast(`🔌 Proxy removido de '${name}'.`);
    showListView();
    await refreshContainers();
  } catch (e) {
    showToast(`Erro: ${e.message}`, true);
  } finally {
    el("btnRemoveProxy").disabled = false;
  }
});

el("containerForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const mode = el("editMode").value;
  const btn = el("btnSubmit");
  btn.disabled = true;
  btn.textContent = "A guardar...";

  try {
    const proxyVal = el("fProxy").value.trim();
    const dsVal = el("fDataSaver").value;
    const autoGeo = el("fAutoGeo").checked;
    const tzVal = el("fTimezone").value.trim();
    const locVal = el("fLocale").value.trim();
    const latStr = el("fLat").value.trim();
    const lonStr = el("fLon").value.trim();

    if ((latStr && !lonStr) || (!latStr && lonStr)) {
      throw new Error("Preenche tanto a Latitude como a Longitude.");
    }

    if (mode === "create") {
      const payload = {
        name: el("fName").value.trim(),
        color: el("fColor").value,
        icon: el("fIcon").value,
        auto_geo: autoGeo,
        data_saver: dsVal,
      };
      if (proxyVal) payload.proxy = proxyVal;
      if (tzVal) payload.timezone = tzVal;
      if (locVal) payload.locale = locVal;
      if (latStr && lonStr) {
        payload.latitude = Number(latStr);
        payload.longitude = Number(lonStr);
      }
      const res = await apiCall("/containers/create", "POST", payload);
      showToast(`📦 Container '${res.container.name}' criado!`);
    } else {
      const origName = el("editOriginalName").value;
      const payload = {
        container: origName,
        auto_geo: autoGeo,
        data_saver: dsVal,
      };
      if (proxyVal) payload.proxy = proxyVal;
      if (tzVal) payload.timezone = tzVal;
      if (locVal) payload.locale = locVal;
      if (latStr && lonStr) {
        payload.latitude = Number(latStr);
        payload.longitude = Number(lonStr);
      }
      await apiCall("/containers/proxy", "POST", payload);
      showToast(`✅ Container '${origName}' atualizado!`);
    }

    showListView();
    await refreshContainers();
  } catch (e) {
    showToast(`Erro: ${e.message}`, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "Guardar";
  }
});

(async () => {
  await loadConfig();
  buildColorPicker();
  await refreshContainers();
})();
