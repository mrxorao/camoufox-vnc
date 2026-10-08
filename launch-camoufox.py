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
        self._send_json({"error": "Endpoint não encontrado"}, 404)

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
            return self._send_json({"error": "Timeout a executar comando no browser"}, 504)

def start_api_server(port=9377):
    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer(('0.0.0.0', port), CamoufoxAPIHandler)
    print(f"[Camoufox API] Servidor de controlo HTTP/MCP ativo na porta {port}", flush=True)
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
            with open(pfile, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            print(f"[Camoufox Config] Motor de pesquisa DuckDuckGo configurado em: {pfile}", flush=True)
        except Exception as e:
            print(f"[Camoufox Config Warning] Aviso ao configurar policies.json: {e}", flush=True)

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
    
    print(f"[Camoufox Stealth Engine] A iniciar Camoufox com perfil em: {profile_dir}", flush=True)
    print(f"[Camoufox Stealth Engine] Emulação SO: {os_spoof}", flush=True)

    start_api_server(port=api_port)

    # Assegurar políticas corporativas com suporte a Containers
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
        print(f"[Camoufox] Aviso ao atualizar policies.json: {e}", flush=True)

    # Preferências do Firefox para DuckDuckGo e Multi-Account Containers
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
    }

    # Gravar user.js diretamente no diretório do perfil para persistência imediata
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
        print(f"[Camoufox Stealth Engine] user.js configurado com sucesso no perfil.", flush=True)

        # Assegurar containers.json inicializado
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
            print(f"[Camoufox Stealth Engine] containers.json inicializado com 4 categorias padrão.", flush=True)
    except Exception as e:
        print(f"[Camoufox Stealth Engine] Aviso ao escrever user.js / containers.json: {e}", flush=True)

    proxy_server = os.getenv("PROXY_SERVER", "").strip()
    proxy_config = None
    if proxy_server:
        proxy_config = {"server": proxy_server}
        proxy_user = os.getenv("PROXY_USERNAME", "").strip()
        proxy_pass = os.getenv("PROXY_PASSWORD", "").strip()
        if proxy_user:
            proxy_config["username"] = proxy_user
            proxy_config["password"] = proxy_pass
        print(f"[Camoufox Stealth Engine] A usar Proxy: {proxy_server}", flush=True)

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
        print("[Camoufox] Sinal de encerramento recebido. A fechar...", flush=True)
        running = False
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    try:
        status_cache["status"] = "starting"
        # Iniciar Camoufox com motor C++ Stealth
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
                    print(f"[Camoufox] Aviso ao abrir URL inicial: {e}", flush=True)

            print("[Camoufox Stealth Engine] Browser 100% ativo com score de bot mínimo (0-3)!", flush=True)

            while running:
                if not browser.pages:
                    print("[Camoufox] Janela ou abas fechadas pelo utilizador. A reiniciar...", flush=True)
                    break

                    try:
                        endpoint, data, done_event, result_holder = command_queue.get(timeout=0.2)
                    except queue.Empty:
                        continue

                    if not browser.pages:
                        browser.new_page()
                    if active_tab_index >= len(browser.pages):
                        active_tab_index = len(browser.pages) - 1
                    curr_page = browser.pages[active_tab_index]

                    try:
                        if endpoint == '/navigate':
                            target_url = data.get('url')
                            if not target_url:
                                result_holder["http_status"] = 400
                                result_holder["payload"] = {"error": "Parâmetro 'url' é obrigatório"}
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
                                result_holder["payload"] = {"error": "Parâmetro 'selector' é obrigatório"}
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
                                result_holder["payload"] = {"error": "Parâmetro 'selector' é obrigatório"}
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
                                result_holder["payload"] = {"error": "Parâmetro 'selector' é obrigatório"}
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
                                    result_holder["payload"] = {"error": "É necessário fornecer 'file_path' ou 'base64_data'"}
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
                                result_holder["payload"] = {"error": "Parâmetro 'key' é obrigatório"}
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
                                result_holder["payload"] = {"error": "Parâmetro 'script' é obrigatório"}
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
                            active_tab_index = len(browser.pages) - 1
                            result_holder["payload"] = {
                                "status": "ok",
                                "tab_index": active_tab_index,
                                "url": new_p.url,
                                "title": safe_get_title(new_p)
                            }

                        elif endpoint == '/tabs':
                            tabs_list = []
                            for idx, p in enumerate(browser.pages):
                                tabs_list.append({
                                    "index": idx,
                                    "url": p.url,
                                    "title": safe_get_title(p),
                                    "is_active": idx == active_tab_index
                                })
                            result_holder["payload"] = {"status": "ok", "tabs": tabs_list}

                        elif endpoint == '/switch_tab':
                            idx = int(data.get('index', 0))
                            if 0 <= idx < len(browser.pages):
                                active_tab_index = idx
                                p = browser.pages[idx]
                                p.bring_to_front()
                                result_holder["payload"] = {
                                    "status": "ok",
                                    "active_index": idx,
                                    "url": p.url,
                                    "title": safe_get_title(p)
                                }
                            else:
                                result_holder["http_status"] = 400
                                result_holder["payload"] = {"error": "Índice de aba inválido"}

                        else:
                            result_holder["http_status"] = 404
                            result_holder["payload"] = {"error": f"Endpoint '{endpoint}' desconhecido"}

                    except Exception as ex:
                        result_holder["http_status"] = 500
                        result_holder["payload"] = {"error": str(ex)}

                    finally:
                        done_event.set()

    except Exception as err:
        print(f"[Camoufox] Instância do browser fechada ou terminada: {err}", flush=True)
    finally:
        status_cache["status"] = "restarting"
        print("[Camoufox] Processo a terminar para reinício automático pelo supervisord...", flush=True)
        time.sleep(0.5)
        sys.exit(0)

if __name__ == "__main__":
    main()
