#!/usr/bin/env python3
import os
import sys
import time
import json
import queue
import base64
import signal
import threading
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
        # Force all links, popups and windows into tabs in the existing window (Single Window Mode)
        "browser.link.open_newwindow": 3,
        "browser.link.open_newwindow.restriction": 0,
        "browser.link.open_newwindow.override.external": 3,
        "browser.tabs.closeWindowWithLastTab": False,
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
                            try:
                                curr_page.goto(target_url, timeout=timeout, wait_until="commit")
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
                            text = curr_page.evaluate("() => document.body ? document.body.innerText : ''")
                        except Exception:
                            pass
                        page_title = safe_get_title(curr_page)
                        result_holder["payload"] = {
                            "status": "ok",
                            "url": curr_page.url,
                            "title": page_title,
                            "text": text[:25000]
                        }

                    elif endpoint == '/click':
                        selector = data.get('selector')
                        if not selector:
                            result_holder["http_status"] = 400
                            result_holder["payload"] = {"error": "Parameter 'selector' is required"}
                        else:
                            curr_page.click(selector, timeout=10000)
                            page_title = safe_get_title(curr_page)
                            result_holder["payload"] = {
                                "status": "ok",
                                "url": curr_page.url,
                                "title": page_title
                            }

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
                            # Prevent opening new windows via shortcut; remap to new tab
                            if key in ("Control+n", "Control+N", "Ctrl+n", "Ctrl+N"):
                                key = "Control+t"
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
                        new_p = browser.new_page()
                        url_t = data.get('url', 'https://duckduckgo.com')
                        if url_t and url_t != 'about:blank':
                            try:
                                new_p.goto(url_t, wait_until="commit", timeout=15000)
                            except Exception:
                                pass
                        active_pages = [p for p in browser.pages if not p.is_closed()]
                        active_tab_index = len(active_pages) - 1
                        new_p.bring_to_front()
                        page_title = safe_get_title(new_p)
                        status_cache["url"] = new_p.url
                        status_cache["title"] = page_title
                        status_cache["tabs_count"] = len(active_pages)
                        result_holder["payload"] = {
                            "status": "ok",
                            "tab_index": active_tab_index,
                            "url": new_p.url,
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

                            # If closing the only tab, open a fresh start tab first so the window never closes/crashes
                            if len(active_pages) <= 1:
                                new_p = browser.new_page()
                                try:
                                    new_p.goto(start_url, wait_until="commit", timeout=15000)
                                except Exception:
                                    pass
                                try:
                                    target_page.close()
                                except Exception:
                                    pass
                                active_pages = [p for p in browser.pages if not p.is_closed()]
                                active_tab_index = 0
                                curr_page = active_pages[0]
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
