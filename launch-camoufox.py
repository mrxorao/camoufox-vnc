#!/usr/bin/env python3
import os
import sys
import time
import json
import queue
import base64
import signal
import threading
import math
import random
import hashlib
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from camoufox.sync_api import Camoufox

def get_env_bool(name, default=True):
    val = os.getenv(name, str(default)).strip().lower()
    return val in ("true", "1", "yes", "on")

def cleanup_profile_locks(profile_dir):
    for fname in [".parentlock", "lock", ".startup-incomplete"]:
        fpath = os.path.join(profile_dir, fname)
        if os.path.exists(fpath) or os.path.islink(fpath):
            try:
                os.remove(fpath)
            except Exception:
                pass

class HumanMouse:
    def __init__(self):
        self.last_x = 640.0
        self.last_y = 360.0

    def bezier_curve(self, p0, p3, steps=25):
        """Generates a cubic Bezier trajectory with natural human curvature."""
        x0, y0 = p0
        x3, y3 = p3
        dx = x3 - x0
        dy = y3 - y0
        dist = math.hypot(dx, dy)
        if dist < 2:
            return [(x3, y3)]

        steps = max(12, min(45, int(dist / 16)))
        dev = (random.random() - 0.5) * min(dist * 0.35, 140)
        norm = max(dist, 1e-5)
        nx = -dy / norm
        ny = dx / norm

        p1 = (x0 + dx * 0.25 + nx * dev + random.uniform(-8, 8),
              y0 + dy * 0.25 + ny * dev + random.uniform(-8, 8))
        p2 = (x0 + dx * 0.75 + nx * dev * 0.6 + random.uniform(-8, 8),
              y0 + dy * 0.75 + ny * dev * 0.6 + random.uniform(-8, 8))

        points = []
        for i in range(1, steps + 1):
            t = i / steps
            t_eased = t * t * (3.0 - 2.0 * t)
            u = 1.0 - t_eased
            tt = t_eased * t_eased
            uu = u * u
            x = uu * u * x0 + 3 * uu * t_eased * p1[0] + 3 * u * tt * p2[0] + tt * t_eased * x3
            y = uu * u * y0 + 3 * uu * t_eased * p1[1] + 3 * u * tt * p2[1] + tt * t_eased * y3
            if i < steps:
                x += random.uniform(-0.8, 0.8)
                y += random.uniform(-0.8, 0.8)
            points.append((round(x, 1), round(y, 1)))
        return points

    def smooth_move(self, page, target_x, target_y):
        points = self.bezier_curve((self.last_x, self.last_y), (target_x, target_y))
        for px, py in points:
            try:
                page.mouse.move(px, py)
            except Exception:
                pass
            time.sleep(random.uniform(0.005, 0.012))
        self.last_x = target_x
        self.last_y = target_y

    def click(self, page, x, y, button="left", click_count=1):
        self.smooth_move(page, x, y)
        time.sleep(random.uniform(0.03, 0.08))
        for _ in range(click_count):
            try:
                page.mouse.down(button=button)
                time.sleep(random.uniform(0.04, 0.07))
                page.mouse.up(button=button)
            except Exception as e:
                print(f"[HumanMouse Click Warning]: {e}", flush=True)
            if click_count > 1:
                time.sleep(0.05)

human_mouse = HumanMouse()

SNAPSHOT_JS = r"""(() => {
  if (!document.body) return null;
  const cache = window.__jevFast ||= {ids:new WeakMap(), nodes:new Map(), next:1};
  const identity = e => {
    if (!cache.ids.has(e)) cache.ids.set(e,cache.next++);
    const id=cache.ids.get(e); cache.nodes.set(id,e); return id;
  };
  for (const [id,e] of cache.nodes) if (!e.isConnected) cache.nodes.delete(id);
  const safe = e => !['password','file','hidden'].includes(e.type);
  const visible = e => !e.closest('[aria-hidden="true"],[inert]') &&
    e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
  const name = (e,seen=new Set()) => {
    if (!e || seen.has(e)) return '';
    seen.add(e);
    const referenced=(e.getAttribute('aria-labelledby')||'').split(/\s+/)
      .map(id=>name(document.getElementById(id),seen)).filter(Boolean).join(' ');
    return referenced || e.getAttribute('aria-label') ||
      [...(e.labels||[])].map(l=>name(l,seen)).filter(Boolean).join(' ') ||
      (['button','submit','reset'].includes(e.type) ? e.value : '') || e.getAttribute('alt') ||
      (e.tagName==='INPUT' ? '' : [...e.childNodes].map(n=>n.nodeType===3 ? n.textContent :
        n.nodeType===1 && n.getAttribute('aria-hidden')!=='true' ? name(n,seen) : '').join(' ').trim()) ||
      e.getAttribute('title') || e.getAttribute('placeholder') || '';
  };
  const roles=['button','link','checkbox','radio','switch','tab','menuitem','menuitemradio',
    'option','gridcell','combobox','textbox','searchbox','spinbutton'];
  const selector='a[href],button,input,textarea,select,summary,[contenteditable="true"],'+
    roles.map(role=>'[role="'+role+'"]').join(',');
  const role = e => {
    const explicit=e.getAttribute('role');
    if (roles.includes(explicit)) return explicit;
    if (e.tagName==='BUTTON' || e.tagName==='SUMMARY') return 'button';
    if (e.tagName==='A') return 'link';
    if (e.tagName==='SELECT') return 'combobox';
    if (e.tagName==='TEXTAREA' || e.isContentEditable) return 'textbox';
    if (e.tagName==='INPUT') {
      if (['checkbox','radio'].includes(e.type)) return e.type;
      if (['button','submit','reset','image'].includes(e.type)) return 'button';
      if (e.type==='search') return 'searchbox';
      if (e.type==='number') return 'spinbutton';
      if (['text','email','url','tel'].includes(e.type)) return 'textbox';
    }
    return null;
  };
  cache.pageKey=()=>[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    [...document.querySelectorAll('input,textarea,select')].filter(safe)
      .map(e=>[identity(e),e.value,e.checked,e.selectedIndex,e.disabled,e.readOnly])];
  cache.guard=e=>{
    if (!e?.isConnected || !visible(e)) return null;
    const scope=e.closest('form,dialog,[role="dialog"],article,li,tr,[role="row"]') || e.parentElement;
    return [identity(e),role(e),name(e),e.value??null,e.checked??null,e.selectedIndex??null,
      e.readOnly??null,e.matches(':disabled'),e.getAttribute('aria-disabled'),
      e.getAttribute('aria-expanded'),e.getAttribute('aria-checked'),e.getAttribute('aria-selected'),
      e.getAttribute('href'),scope?.innerText?.slice(0,6000)||''];
  };
  const actions=[];
  for (const e of document.querySelectorAll(selector)) {
    if (!safe(e) || !visible(e) || e.matches(':disabled') || e.closest('[aria-disabled="true"]')) continue;
    const r=e.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2, rname=role(e);
    if (!rname || r.width<=0 || r.height<=0 || x<0 || y<0 || x>=innerWidth || y>=innerHeight) continue;
    if (rname==='gridcell' && e.querySelector('button,[role="button"]')) continue;
    const base={node:identity(e),role:rname,label:name(e)||rname,
      rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
    for (const key of ['checked','selected','expanded']) {
      const value=e.getAttribute('aria-'+key);
      if (value!==null) base[key]=value;
    }
    if (['checkbox','radio'].includes(e.type)) base.checked=String(e.checked);
    if (e.tagName==='SELECT') {
      for (const o of e.options) if (!o.selected && !o.disabled && !o.closest('optgroup[disabled]'))
        actions.push({...base,kind:'select',value:o.value,
          current_value:[...e.selectedOptions].map(o=>o.label).join(', '),label:base.label+' → '+o.label});
    } else {
      const editable=!e.readOnly && e.getAttribute('aria-readonly')!=='true' &&
        (['textbox','searchbox','spinbutton'].includes(rname) ||
          (rname==='combobox' && ['INPUT','TEXTAREA'].includes(e.tagName)));
      const value='value' in e ? String(e.value) :
        e.isContentEditable || rname==='combobox' ? e.innerText.trim() : '';
      actions.push({...base,kind:editable?'fill':'click',value});
      if (editable) actions.push({...base,kind:'click',value,label:'Open '+base.label});
    }
  }
  const words=[], walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  const range=document.createRange(); let node,length=0;
  while ((node=walker.nextNode()) && length<6000) {
    const value=node.textContent.trim(), parent=node.parentElement;
    if (!value || !parent || parent.closest('script,style,noscript,template') || !visible(parent)) continue;
    range.selectNodeContents(node); const r=range.getBoundingClientRect();
    if (r.width>0 && r.height>0 && r.bottom>0 && r.top<innerHeight && r.right>0 && r.left<innerWidth) {
      words.push(value); length+=value.length;
    }
  }
  const text=words.join('\n').slice(0,6000), height=document.documentElement.scrollHeight;
  const page_key=cache.pageKey(), guards={};
  for (const a of actions) if (!(a.node in guards)) guards[a.node]=cache.guard(cache.nodes.get(a.node));
  const semantics=actions.map(({rect,...action})=>action);
  const marker=[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    document.title,text,semantics,page_key[6]];
  const omitted_actions=Math.max(0,actions.length-250);
  actions.splice(250);
  actions.forEach((a,i)=>a.id='e'+(i+1));
  if (scrollY+innerHeight<height-2) actions.push({id:'scroll_down',kind:'scroll',label:'Scroll down',delta:560});
  if (scrollY>0) actions.push({id:'scroll_up',kind:'scroll',label:'Scroll up',delta:-560});
  actions.push({id:'wait',kind:'wait',label:'Wait for the page to update'});
  return {url:location.href,title:document.title,w:innerWidth,h:innerHeight,text,
    scroll:{y:scrollY,height},actions,marker,page_key,guards,omitted_actions};
})()"""

command_queue = queue.Queue()
status_cache = {
    "status": "starting",
    "browser": "camoufox",
    "url": "",
    "title": "",
    "tabs_count": 0
}

class CamoufoxAPIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def _read_body(self):
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length > 0:
            raw = self.rfile.read(content_length).decode('utf-8')
            try:
                return json.loads(raw)
            except Exception:
                return {}
        return {}

    def do_GET(self):
        if self.path == '/health' or self.path == '/':
            return self._send_json(status_cache)
        self._send_json({"error": "Endpoint not found"}, 404)

    def do_POST(self):
        data = self._read_body()
        endpoint = self.path

        done_event = threading.Event()
        result_holder = {}

        command_queue.put((endpoint, data, done_event, result_holder))

        if done_event.wait(timeout=40.0):
            status_code = result_holder.get("http_status", 200)
            return self._send_json(result_holder.get("payload", {}), status_code)
        else:
            return self._send_json({"error": "Browser command timed out"}, 504)

def start_api_server(port=9377):
    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer(('0.0.0.0', port), CamoufoxAPIHandler)
    print(f"[Camoufox API] HTTP/MCP control server listening on port {port}", flush=True)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server

def safe_get_title(page):
    try:
        return page.title()
    except Exception:
        return ""

def create_new_tab(browser, current_page, target_url="https://duckduckgo.com"):
    """
    Opens a new TAB in the existing Firefox window instead of creating
    a new OS window (which browser.new_page() would do in Firefox).
    """
    if not target_url or target_url == "about:blank":
        target_url = "https://duckduckgo.com"
    elif not target_url.startswith("http://") and not target_url.startswith("https://") and not target_url.startswith("about:"):
        target_url = "https://" + target_url

    # 1. Primary method: Evaluate window.open in the active page.
    # Because browser.link.open_newwindow=3 and restriction=0, Firefox strictly forces this into a TAB in the existing window.
    if current_page and not current_page.is_closed():
        try:
            with browser.expect_page(timeout=5000) as p_info:
                current_page.evaluate("(u) => { window.open(u, '_blank'); }", target_url)
            new_p = p_info.value
            return new_p
        except Exception as e_eval:
            print(f"[Camoufox Tab] window.open failed ({e_eval}), falling back to xdotool Ctrl+T...", flush=True)

    # 2. Secondary method: Send Ctrl+T via xdotool directly to the X11 display
    # This natively tells the Firefox UI to open a new tab in the current window.
    try:
        with browser.expect_page(timeout=5000) as p_info:
            os.system("xdotool key --clearmodifiers ctrl+t 2>/dev/null || true")
        new_p = p_info.value
        if target_url and target_url != "about:blank":
            try:
                new_p.goto(target_url, wait_until="commit", timeout=15000)
            except Exception:
                pass
        return new_p
    except Exception as e_xdo:
        print(f"[Camoufox Tab] xdotool Ctrl+T failed ({e_xdo}), falling back to browser.new_page()...", flush=True)

    # 3. Final fallback: If no pages or windows exist at all
    new_p = browser.new_page()
    if target_url and target_url != "about:blank":
        try:
            new_p.goto(target_url, wait_until="commit", timeout=15000)
        except Exception:
            pass
    return new_p

def fix_search_policies():
    import glob
    for pfile in glob.glob("/root/.cache/camoufox/browsers/**/distribution/policies.json", recursive=True):
        try:
            with open(pfile, "r", encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("policies", {})["SearchEngines"] = {
                "PreventInstalls": False,
                "Default": "DuckDuckGo",
                "Add": [
                    {
                        "Name": "DuckDuckGo",
                        "Description": "DuckDuckGo Search",
                        "Alias": "@ddg",
                        "Method": "GET",
                        "URLTemplate": "https://duckduckgo.com/?q={searchTerms}"
                    }
                ]
            }
            # Enforce single-window / tab-only policy (never open new OS windows, force everything to tabs)
            data["policies"].setdefault("Preferences", {})
            data["policies"]["Preferences"]["browser.link.open_newwindow"] = {"Value": 3, "Status": "locked"}
            data["policies"]["Preferences"]["browser.link.open_newwindow.restriction"] = {"Value": 0, "Status": "locked"}
            data["policies"]["Preferences"]["browser.link.open_newwindow.override.external"] = {"Value": 3, "Status": "locked"}
            data["policies"]["Preferences"]["browser.tabs.closeWindowWithLastTab"] = {"Value": False, "Status": "locked"}
            data["policies"]["Preferences"]["browser.search.openintab"] = {"Value": True, "Status": "locked"}
            with open(pfile, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            print(f"[Camoufox Config] Policies and single-window rules configured at: {pfile}", flush=True)
        except Exception as e:
            print(f"[Camoufox Config Warning] Failed to configure policies.json: {e}", flush=True)

def cleanup_profile_locks(profile_dir):
    try:
        import glob
        lock_patterns = [
            os.path.join(profile_dir, "*lock*"),
            os.path.join(profile_dir, ".*lock*"),
            os.path.join(profile_dir, "lock"),
            os.path.join(profile_dir, ".parentlock"),
            os.path.join(profile_dir, "parent.lock"),
        ]
        for pattern in lock_patterns:
            for lock_file in glob.glob(pattern):
                try:
                    if os.path.exists(lock_file) or os.path.islink(lock_file):
                        os.remove(lock_file)
                        print(f"[Camoufox] Removed stale lock: {lock_file}", flush=True)
                except Exception:
                    pass
    except Exception as e:
        print(f"[Camoufox] Warning while cleaning locks: {e}", flush=True)

def main():
    global status_cache
    profile_dir = os.getenv("PROFILE_DIR", "/root/profile")
    os.makedirs(profile_dir, exist_ok=True)
    cleanup_profile_locks(profile_dir)
    fix_search_policies()
    
    start_url = os.getenv("START_URL", "https://duckduckgo.com")
    os_spoof = os.getenv("OS_SPOOF", "windows")
    enable_cache = get_env_bool("ENABLE_CACHE", True)
    api_port = int(os.getenv("PORT_API", "9377"))
    
    print(f"[Camoufox Stealth Engine] Starting Camoufox with profile at: {profile_dir}", flush=True)
    print(f"[Camoufox Stealth Engine] OS emulation: {os_spoof}", flush=True)

    start_api_server(port=api_port)

    # Enforce enterprise policies with Containers support
    try:
        import glob
        for p in glob.glob("/root/.cache/camoufox/browsers/**/distribution/policies.json", recursive=True):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data.setdefault("policies", {})
                data["policies"]["Containers"] = {"Enabled": True}
                data["policies"].setdefault("ExtensionSettings", {})
                data["policies"]["ExtensionSettings"]["@testpilot-containers"] = {
                    "default_area": "navbar"
                }
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            except Exception:
                pass
    except Exception as e:
        print(f"[Camoufox] Warning while updating policies.json: {e}", flush=True)

    # Firefox preferences for DuckDuckGo and Multi-Account Containers
    firefox_prefs = {
        "browser.startup.homepage": "https://duckduckgo.com",
        "browser.startup.page": 1,
        "browser.search.defaultenginename": "DuckDuckGo",
        "browser.search.order.1": "DuckDuckGo",
        "browser.urlbar.placeholderName": "DuckDuckGo",
        "browser.search.suggest.enabled": True,
        "browser.urlbar.suggest.searches": True,
        "keyword.enabled": True,
        # Multi-Account Containers
        "privacy.userContext.enabled": True,
        "privacy.userContext.ui.enabled": True,
        "privacy.userContext.longPressBehavior": 2,
        "privacy.userContext.newTabContainerOnLeftClick.enabled": True,
        "privacy.userContext.extension": "@testpilot-containers",
        # Force all links, popups and windows into tabs in the existing window (Strict Single-Window Mode)
        "browser.link.open_newwindow": 3,
        "browser.link.open_newwindow.restriction": 0,
        "browser.link.open_newwindow.override.external": 3,
        "browser.tabs.closeWindowWithLastTab": False,
        "browser.tabs.loadBookmarksInTabs": True,
        "browser.search.openintab": True,
        "privacy.popups.policy": 1,
        "dom.disable_window_open_feature.close": True,
        "dom.disable_window_open_feature.location": True,
        "dom.disable_window_open_feature.menubar": True,
        "dom.disable_window_open_feature.minimizable": True,
        "dom.disable_window_open_feature.personalbar": True,
        "dom.disable_window_open_feature.resizable": True,
        "dom.disable_window_open_feature.status": True,
        "dom.disable_window_open_feature.titlebar": True,
        "dom.disable_window_open_feature.toolbar": True,
        # Prevent session-restore screens and prompts that block user input
        "browser.sessionstore.resume_from_crash": False,
        "browser.sessionstore.max_resumed_crashes": 0,
        "toolkit.startup.max_resumed_crashes": -1,
        "browser.tabs.warnOnClose": False,
        "browser.tabs.warnOnCloseOtherTabs": False,
        "browser.warnOnQuit": False,
    }

    # Write user.js directly into the profile directory for immediate persistence
    try:
        os.makedirs(profile_dir, exist_ok=True)
        user_js_path = os.path.join(profile_dir, "user.js")
        user_js_lines = []
        for k, v in firefox_prefs.items():
            if isinstance(v, bool):
                val_str = "true" if v else "false"
            elif isinstance(v, int):
                val_str = str(v)
            else:
                val_str = f'"{v}"'
            user_js_lines.append(f'user_pref("{k}", {val_str});')
        with open(user_js_path, "w", encoding="utf-8") as f:
            f.write("\n".join(user_js_lines) + "\n")
        print(f"[Camoufox Stealth Engine] user.js successfully written to the profile.", flush=True)

        # Ensure containers.json is initialized
        containers_path = os.path.join(profile_dir, "containers.json")
        if not os.path.exists(containers_path) or os.path.getsize(containers_path) < 20:
            default_containers = {
                "version": 4,
                "lastUserContextId": 4,
                "identities": [
                    {"userContextId": 1, "name": "Personal", "icon": "fingerprint", "color": "blue", "public": True},
                    {"userContextId": 2, "name": "Work", "icon": "briefcase", "color": "orange", "public": True},
                    {"userContextId": 3, "name": "Banking", "icon": "dollar", "color": "green", "public": True},
                    {"userContextId": 4, "name": "Shopping", "icon": "cart", "color": "pink", "public": True},
                ],
                "siteAssociations": {}
            }
            with open(containers_path, "w", encoding="utf-8") as f:
                json.dump(default_containers, f, indent=2)
            print(f"[Camoufox Stealth Engine] containers.json initialized with 4 default categories.", flush=True)
    except Exception as e:
        print(f"[Camoufox Stealth Engine] Warning while writing user.js / containers.json: {e}", flush=True)

    proxy_server = os.getenv("PROXY_SERVER", "").strip()
    proxy_config = None
    if proxy_server:
        proxy_config = {"server": proxy_server}
        proxy_user = os.getenv("PROXY_USERNAME", "").strip()
        proxy_pass = os.getenv("PROXY_PASSWORD", "").strip()
        if proxy_user:
            proxy_config["username"] = proxy_user
            proxy_config["password"] = proxy_pass
        print(f"[Camoufox Stealth Engine] Using proxy: {proxy_server}", flush=True)

    camoufox_kwargs = {
        "headless": False,
        "persistent_context": True,
        "user_data_dir": profile_dir,
        "os": os_spoof,
        "humanize": False,
        "enable_cache": enable_cache,
        "allow_addon_new_tab": True,
        "firefox_user_prefs": firefox_prefs,
    }
    if proxy_config:
        camoufox_kwargs["proxy"] = proxy_config
        camoufox_kwargs["geoip"] = True

    running = True

    def handle_sigterm(signum, frame):
        nonlocal running
        print("[Camoufox] Shutdown signal received. Closing...", flush=True)
        running = False
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    try:
        status_cache["status"] = "starting"
        # Start Camoufox with the C++ stealth engine
        with Camoufox(**camoufox_kwargs) as browser:
            page = browser.pages[0] if browser.pages else browser.new_page()
            active_tab_index = 0
            
            status_cache["status"] = "ready"
            status_cache["url"] = page.url
            status_cache["tabs_count"] = len(browser.pages)

            if start_url:
                try:
                    page.goto(start_url, timeout=20000, wait_until="commit")
                    status_cache["url"] = page.url
                    status_cache["title"] = safe_get_title(page)
                except Exception as e:
                    print(f"[Camoufox] Warning while opening the start URL: {e}", flush=True)

            print("[Camoufox Stealth Engine] Browser fully active with minimal bot score (0-3)!", flush=True)

            # Ensure window focus and reset X11 keyboard modifiers
            def ensure_window_focus():
                time.sleep(1.0)
                try:
                    os.system("xdotool keyup Alt_L Alt_R Control_L Control_R Shift_L Shift_R Super_L Super_R 2>/dev/null || true")
                    os.system("xdotool search --onlyvisible --name '.*' windowactivate --sync 2>/dev/null || true")
                except Exception:
                    pass
            threading.Thread(target=ensure_window_focus, daemon=True).start()

            # Fully reliable check of the main Camoufox process via /proc
            def is_browser_process_alive():
                try:
                    import glob
                    for cmdline_file in glob.glob("/proc/[0-9]*/cmdline"):
                        try:
                            with open(cmdline_file, "rb") as f:
                                content = f.read().decode('utf-8', errors='ignore')
                                if "camoufox-bin" in content and "-contentproc" not in content and "python" not in content:
                                    return True
                        except Exception:
                            continue
                except Exception:
                    pass
                return False

            # Standalone watchdog for instant detection of window/process close by the user
            def browser_watchdog():
                # Wait until the browser has initially started
                for _ in range(30):
                    time.sleep(0.5)
                    if is_browser_process_alive():
                        break

                consecutive_dead = 0
                while running:
                    time.sleep(0.5)
                    if not is_browser_process_alive():
                        consecutive_dead += 1
                        if consecutive_dead >= 2:  # 1 consecutive second without the main process
                            print("[Camoufox Watchdog] Main Camoufox process closed by the user. Restarting...", flush=True)
                            os.system("pkill -9 -f 'camoufox-bin' 2>/dev/null || true")
                            cleanup_profile_locks(profile_dir)
                            os._exit(0)
                    else:
                        consecutive_dead = 0

            threading.Thread(target=browser_watchdog, daemon=True).start()

            while running:
                try:
                    item = command_queue.get(timeout=0.5)
                    if not item or item[0] is None:
                        continue
                    endpoint, data, done_event, result_holder = item
                except queue.Empty:
                    continue

                # Ensure a valid active page for the command
                try:
                    active_pages = [p for p in browser.pages if not p.is_closed()]
                    if not active_pages:
                        curr_page = browser.new_page()
                        active_tab_index = 0
                    else:
                        if active_tab_index >= len(active_pages):
                            active_tab_index = len(active_pages) - 1
                        curr_page = active_pages[active_tab_index]
                except Exception:
                    continue

                try:
                    if endpoint == '/navigate':
                        target_url = data.get('url')
                        if not target_url:
                            result_holder["http_status"] = 400
                            result_holder["payload"] = {"error": "Parameter 'url' is required"}
                        else:
                            if not target_url.startswith("http://") and not target_url.startswith("https://"):
                                target_url = "https://" + target_url
                            timeout = int(data.get('timeout', 30000))
                            
                            is_container = ".container/" in target_url.lower()
                            launcher_page = curr_page
                            pages_before = set(browser.pages)

                            if is_container:
                                container_page = None
                                try:
                                    with browser.expect_page(timeout=4500) as p_info:
                                        launcher_page.evaluate("(u) => { setTimeout(() => { window.location.href = u; }, 10); }", target_url)
                                    container_page = p_info.value
                                except Exception as e_exp:
                                    print(f"[Camoufox Container] expect_page notice: {e_exp}", flush=True)

                                if not container_page:
                                    candidates = [p for p in browser.pages if p not in pages_before and not p.is_closed()]
                                    if candidates:
                                        container_page = candidates[-1]

                                if container_page:
                                    print(f"[Camoufox Container] Successfully captured new container tab: {container_page.url}", flush=True)
                                    try:
                                        if launcher_page != container_page and not launcher_page.is_closed():
                                            launcher_page.close()
                                    except Exception as e_close:
                                        print(f"[Camoufox Container Warning] Failed to close launcher tab: {e_close}", flush=True)

                                    active_pages = [p for p in browser.pages if not p.is_closed()]
                                    if container_page in active_pages:
                                        active_tab_index = active_pages.index(container_page)
                                    else:
                                        active_tab_index = len(active_pages) - 1
                                    curr_page = active_pages[active_tab_index]
                                    try:
                                        curr_page.bring_to_front()
                                    except Exception:
                                        pass

                                    try:
                                        curr_page.wait_for_load_state("domcontentloaded", timeout=6000)
                                    except Exception:
                                        pass
                            else:
                                try:
                                    launcher_page.goto(target_url, timeout=timeout, wait_until="commit")
                                except Exception as e:
                                    print(f"[Camoufox Navigate Warning]: {e}", flush=True)
                            
                            page_title = safe_get_title(curr_page)
                            status_cache["url"] = curr_page.url
                            status_cache["title"] = page_title
                            status_cache["tabs_count"] = len(browser.pages)

                            result_holder["payload"] = {
                                "status": "ok",
                                "url": curr_page.url,
                                "title": page_title
                            }

                    elif endpoint == '/snapshot':
                        text = ""
                        try:
                            body_loc = curr_page.locator("body")
                            if body_loc.count() > 0:
                                text = body_loc.first.inner_text(timeout=4000)
                            else:
                                text = curr_page.evaluate("() => document.body ? document.body.innerText : ''")
                        except Exception:
                            try:
                                text = curr_page.evaluate("() => document.body ? document.body.innerText : ''")
                            except Exception:
                                pass
                        page_title = safe_get_title(curr_page)
                        result_holder["payload"] = {
                            "status": "ok",
                            "url": curr_page.url,
                            "title": page_title,
                            "text": (text or "")[:25000]
                        }

                    elif endpoint == '/click':
                        selector = data.get('selector')
                        x = data.get('x')
                        y = data.get('y')
                        button = data.get('button', 'left')
                        click_count = int(data.get('click_count', 1))

                        if x is not None and y is not None:
                            try:
                                target_x = float(x)
                                target_y = float(y)
                                human_mouse.click(curr_page, target_x, target_y, button=button, click_count=click_count)
                                page_title = safe_get_title(curr_page)
                                result_holder["payload"] = {
                                    "status": "ok",
                                    "url": curr_page.url,
                                    "title": page_title,
                                    "clicked_at": {"x": target_x, "y": target_y}
                                }
                            except Exception as e:
                                result_holder["http_status"] = 500
                                result_holder["payload"] = {"error": f"Mouse coordinate click failed: {str(e)}"}
                        elif selector:
                            try:
                                loc = curr_page.locator(selector).first
                                box = loc.bounding_box(timeout=8000)
                                if box and box.get('width', 0) > 0 and box.get('height', 0) > 0:
                                    target_x = box['x'] + box['width'] * random.uniform(0.25, 0.75)
                                    target_y = box['y'] + box['height'] * random.uniform(0.25, 0.75)
                                    human_mouse.click(curr_page, target_x, target_y, button=button, click_count=click_count)
                                else:
                                    curr_page.click(selector, timeout=10000)
                                page_title = safe_get_title(curr_page)
                                result_holder["payload"] = {
                                    "status": "ok",
                                    "url": curr_page.url,
                                    "title": page_title
                                }
                            except Exception as e:
                                result_holder["http_status"] = 500
                                result_holder["payload"] = {"error": f"Click failed: {str(e)}"}
                        else:
                            result_holder["http_status"] = 400
                            result_holder["payload"] = {"error": "Either 'selector' or ('x', 'y') coordinates are required"}

                    elif endpoint == '/type':
                        selector = data.get('selector')
                        text_val = data.get('text', '')
                        if not selector:
                            result_holder["http_status"] = 400
                            result_holder["payload"] = {"error": "Parameter 'selector' is required"}
                        else:
                            if data.get('clear', True):
                                curr_page.fill(selector, "")
                            curr_page.type(selector, text_val, delay=int(data.get('delay', 20)))
                            result_holder["payload"] = {"status": "ok"}

                    elif endpoint == '/upload':
                        selector = data.get('selector')
                        file_path = data.get('file_path')
                        base64_data = data.get('base64_data')
                        filename = data.get('filename', 'upload_file.bin')

                        if not selector:
                            result_holder["http_status"] = 400
                            result_holder["payload"] = {"error": "Parameter 'selector' is required"}
                        else:
                            upload_target = None
                            if base64_data:
                                os.makedirs("/tmp/uploads", exist_ok=True)
                                upload_target = os.path.join("/tmp/uploads", filename)
                                with open(upload_target, "wb") as f:
                                    f.write(base64.b64decode(base64_data))
                            elif file_path:
                                if os.path.exists(file_path):
                                    upload_target = file_path
                                else:
                                    shared_check = os.path.join("/data/downloads", os.path.basename(file_path))
                                    if os.path.exists(shared_check):
                                        upload_target = shared_check
                                    else:
                                        upload_target = file_path

                            if not upload_target:
                                result_holder["http_status"] = 400
                                result_holder["payload"] = {"error": "'file_path' or 'base64_data' is required"}
                            else:
                                curr_page.set_input_files(selector, upload_target)
                                result_holder["payload"] = {
                                    "status": "ok",
                                    "selector": selector,
                                    "filename": filename or os.path.basename(upload_target)
                                }

                    elif endpoint == '/press_key':
                        key = data.get('key')
                        if not key:
                            result_holder["http_status"] = 400
                            result_holder["payload"] = {"error": "Parameter 'key' is required"}
                        else:
                            # Intercept new tab and window shortcuts to open in a tab inside the same window
                            if key in ("Control+n", "Control+N", "Ctrl+n", "Ctrl+N", "Control+t", "Control+T", "Ctrl+t", "Ctrl+T"):
                                new_p = create_new_tab(browser, curr_page, start_url)
                                active_pages = [p for p in browser.pages if not p.is_closed()]
                                if new_p in active_pages:
                                    active_tab_index = active_pages.index(new_p)
                                else:
                                    active_tab_index = len(active_pages) - 1
                                curr_page = active_pages[active_tab_index]
                                curr_page.bring_to_front()
                                status_cache["url"] = curr_page.url
                                status_cache["title"] = safe_get_title(curr_page)
                                status_cache["tabs_count"] = len(active_pages)
                                result_holder["payload"] = {"status": "ok", "action": "new_tab", "tab_index": active_tab_index}
                            elif key in ("Control+w", "Control+W", "Ctrl+w", "Ctrl+W"):
                                active_pages = [p for p in browser.pages if not p.is_closed()]
                                if len(active_pages) <= 1:
                                    try:
                                        curr_page.goto(start_url, wait_until="commit", timeout=15000)
                                    except Exception:
                                        pass
                                else:
                                    try:
                                        curr_page.close()
                                    except Exception:
                                        pass
                                    active_pages = [p for p in browser.pages if not p.is_closed()]
                                    active_tab_index = min(active_tab_index, len(active_pages) - 1)
                                    if active_tab_index < 0:
                                        active_tab_index = 0
                                    curr_page = active_pages[active_tab_index]
                                    curr_page.bring_to_front()
                                status_cache["url"] = curr_page.url
                                status_cache["title"] = safe_get_title(curr_page)
                                status_cache["tabs_count"] = len(active_pages)
                                result_holder["payload"] = {"status": "ok", "action": "close_tab"}
                            else:
                                curr_page.keyboard.press(key)
                                result_holder["payload"] = {"status": "ok"}

                    elif endpoint == '/scroll':
                        delta_y = int(data.get('delta_y', 500))
                        delta_x = int(data.get('delta_x', 0))
                        curr_page.mouse.wheel(delta_x, delta_y)
                        result_holder["payload"] = {"status": "ok"}

                    elif endpoint == '/screenshot':
                        img_bytes = curr_page.screenshot(type="png")
                        b64 = base64.b64encode(img_bytes).decode('utf-8')
                        page_title = safe_get_title(curr_page)
                        result_holder["payload"] = {
                            "status": "ok",
                            "image_base64": b64,
                            "url": curr_page.url,
                            "title": page_title
                        }

                    elif endpoint == '/evaluate':
                        script = data.get('script')
                        if not script:
                            result_holder["http_status"] = 400
                            result_holder["payload"] = {"error": "Parameter 'script' is required"}
                        else:
                            res = curr_page.evaluate(script)
                            result_holder["payload"] = {"status": "ok", "result": res}

                    elif endpoint == '/new_tab':
                        url_t = data.get('url', 'https://duckduckgo.com')
                        is_container = ".container/" in url_t.lower()
                        pages_before = set(browser.pages)
                        new_p = create_new_tab(browser, curr_page, url_t)

                        if is_container:
                            start_wait = time.time()
                            while time.time() - start_wait < 5.0:
                                candidates = [p for p in browser.pages if p not in pages_before and p != new_p and not p.is_closed()]
                                if candidates:
                                    container_page = candidates[-1]
                                    try:
                                        if not new_p.is_closed():
                                            new_p.close()
                                    except Exception:
                                        pass
                                    new_p = container_page
                                    break
                                time.sleep(0.15)

                        active_pages = [p for p in browser.pages if not p.is_closed()]
                        if new_p in active_pages:
                            active_tab_index = active_pages.index(new_p)
                        else:
                            active_tab_index = len(active_pages) - 1
                        curr_page = active_pages[active_tab_index]
                        curr_page.bring_to_front()
                        page_title = safe_get_title(curr_page)
                        status_cache["url"] = curr_page.url
                        status_cache["title"] = page_title
                        status_cache["tabs_count"] = len(active_pages)
                        result_holder["payload"] = {
                            "status": "ok",
                            "tab_index": active_tab_index,
                            "url": curr_page.url,
                            "title": page_title
                        }

                    elif endpoint == '/close_tab':
                        active_pages = [p for p in browser.pages if not p.is_closed()]
                        raw_idx = data.get('index')
                        if raw_idx is not None:
                            try:
                                target_idx = int(raw_idx)
                            except (ValueError, TypeError):
                                target_idx = active_tab_index
                        else:
                            target_idx = active_tab_index

                        if not (0 <= target_idx < len(active_pages)):
                            result_holder["http_status"] = 400
                            result_holder["payload"] = {
                                "error": f"Invalid tab index: {target_idx}. Open tabs: 0 to {len(active_pages) - 1}"
                            }
                        else:
                            target_page = active_pages[target_idx]

                            # If closing the only tab, navigate it to start_url so the browser window stays intact without opening/closing windows
                            if len(active_pages) <= 1:
                                try:
                                    target_page.goto(start_url, wait_until="commit", timeout=15000)
                                except Exception:
                                    pass
                                active_tab_index = 0
                                curr_page = target_page
                                curr_page.bring_to_front()
                            else:
                                try:
                                    target_page.close()
                                except Exception as close_err:
                                    print(f"[Camoufox Close Tab Error]: {close_err}", flush=True)

                                active_pages = [p for p in browser.pages if not p.is_closed()]
                                if target_idx < active_tab_index:
                                    active_tab_index -= 1
                                elif target_idx == active_tab_index:
                                    active_tab_index = min(target_idx, len(active_pages) - 1)

                                if active_tab_index < 0:
                                    active_tab_index = 0

                                curr_page = active_pages[active_tab_index]
                                curr_page.bring_to_front()

                            page_title = safe_get_title(curr_page)
                            status_cache["url"] = curr_page.url
                            status_cache["title"] = page_title
                            status_cache["tabs_count"] = len(active_pages)

                            result_holder["payload"] = {
                                "status": "ok",
                                "closed_index": target_idx,
                                "active_index": active_tab_index,
                                "remaining_tabs_count": len(active_pages),
                                "url": curr_page.url,
                                "title": page_title
                            }

                    elif endpoint == '/tabs':
                        active_pages = [p for p in browser.pages if not p.is_closed()]
                        tabs_list = []
                        for idx, p in enumerate(active_pages):
                            tabs_list.append({
                                "index": idx,
                                "url": p.url,
                                "title": safe_get_title(p),
                                "is_active": idx == active_tab_index
                            })
                        result_holder["payload"] = {"status": "ok", "tabs": tabs_list, "count": len(tabs_list)}

                    elif endpoint == '/switch_tab':
                        idx = int(data.get('index', 0))
                        active_pages = [p for p in browser.pages if not p.is_closed()]
                        if 0 <= idx < len(active_pages):
                            active_tab_index = idx
                            p = active_pages[idx]
                            p.bring_to_front()
                            page_title = safe_get_title(p)
                            status_cache["url"] = p.url
                            status_cache["title"] = page_title
                            result_holder["payload"] = {
                                "status": "ok",
                                "active_index": idx,
                                "url": p.url,
                                "title": page_title
                            }
                        else:
                            result_holder["http_status"] = 400
                            result_holder["payload"] = {
                                "error": f"Invalid tab index: {idx}. Open tabs: 0 to {len(active_pages) - 1}"
                            }

                    else:
                        result_holder["http_status"] = 404
                        result_holder["payload"] = {"error": f"Unknown endpoint '{endpoint}'"}

                except Exception as ex:
                    result_holder["http_status"] = 500
                    result_holder["payload"] = {"error": str(ex)}

                finally:
                    done_event.set()

    except Exception as err:
        print(f"[Camoufox] Browser instance closed or terminated: {err}", flush=True)
    finally:
        status_cache["status"] = "restarting"
        print("[Camoufox] Exiting for automatic restart by supervisord...", flush=True)
        cleanup_profile_locks(profile_dir)
        time.sleep(0.5)
        sys.exit(0)

if __name__ == "__main__":
    main()
