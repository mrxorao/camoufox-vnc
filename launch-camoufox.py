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
import uuid
from urllib.parse import urlparse
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

    def move(self, page, x, y):
        self.smooth_move(page, x, y)

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

    def drag_and_drop(self, page, start_x, start_y, end_x, end_y, button="left"):
        # 1. Smoothly move to start coordinates
        self.smooth_move(page, start_x, start_y)
        time.sleep(random.uniform(0.06, 0.12))
        # 2. Press mouse button down
        page.mouse.down(button=button)
        time.sleep(random.uniform(0.08, 0.15))
        # 3. Smooth drag with bezier movement under load
        points = self.bezier_curve((start_x, start_y), (end_x, end_y))
        for px, py in points:
            try:
                page.mouse.move(px, py)
            except Exception:
                pass
            time.sleep(random.uniform(0.008, 0.020))
        self.last_x = end_x
        self.last_y = end_y
        time.sleep(random.uniform(0.08, 0.15))
        # 4. Release mouse button at destination
        page.mouse.up(button=button)
        time.sleep(random.uniform(0.05, 0.10))

human_mouse = HumanMouse()

def get_element_coords(page, selector):
    try:
        loc = page.locator(selector).first
        box = loc.bounding_box(timeout=8000)
        if box and box.get('width', 0) > 0 and box.get('height', 0) > 0:
            tx = box['x'] + box['width'] * random.uniform(0.3, 0.7)
            ty = box['y'] + box['height'] * random.uniform(0.3, 0.7)
            return round(tx, 1), round(ty, 1)
    except Exception:
        pass
    return None, None

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

class CommandRequest:
    """Represents a queued command from an MCP client awaiting exclusive access."""
    def __init__(self, endpoint, data, client_id="anonymous", queue_timeout=120.0, exec_timeout=60.0):
        self.id = str(random.randint(100000, 999999))
        self.endpoint = endpoint
        self.data = data
        self.client_id = client_id
        self.created_at = time.time()
        self.started_at = None
        self.finished_at = None
        self.started_event = threading.Event()
        self.done_event = threading.Event()
        self.cancelled = threading.Event()
        self.result_holder = {}
        self.queue_timeout = queue_timeout
        self.exec_timeout = exec_timeout

command_queue = queue.Queue()
bridge_cmd_queue = queue.Queue()
bridge_pending_lock = threading.Lock()
bridge_pending = {}  # cmd_id -> {"event": threading.Event(), "result": None}
container_proxies_lock = threading.Lock()

VALID_CONTAINER_COLORS = {"blue", "turquoise", "green", "yellow", "orange", "red", "pink", "purple", "toolbar"}
VALID_CONTAINER_ICONS = {"fingerprint", "briefcase", "dollar", "cart", "vacation", "gift", "food", "fruit", "pet", "tree", "chill", "circle", "fence"}
VALID_DATA_SAVER_MODES = {"off", "smart", "media", "images", "aggressive"}


def get_proxies_file(profile_dir=None):
    pdir = profile_dir or os.getenv("PROFILE_DIR", "/root/profile")
    return os.path.join(pdir, "container_proxies.json")


def load_container_proxies(profile_dir=None):
    fpath = get_proxies_file(profile_dir)
    with container_proxies_lock:
        if not os.path.exists(fpath):
            return {}
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


def save_container_proxies(proxies_dict, profile_dir=None):
    fpath = get_proxies_file(profile_dir)
    with container_proxies_lock:
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(proxies_dict, f, indent=2)


def parse_proxy_url(proxy_url):
    """Parse proxy URL (http, https, socks5, socks, socks4) into Firefox proxyInfo dict."""
    raw = str(proxy_url or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "http://" + raw
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    scheme_map = {
        "http": "http",
        "https": "https",
        "socks": "socks",
        "socks5": "socks",
        "socks5h": "socks",
        "socks4": "socks4",
        "socks4a": "socks4",
    }
    if scheme not in scheme_map:
        raise ValueError(f"Unsupported proxy scheme '{scheme}'. Use http://, https://, socks5://, or socks4://")
    if not parsed.hostname:
        raise ValueError("Proxy URL must include a valid host")
    if not parsed.port:
        raise ValueError("Proxy URL must include a valid port (e.g. socks5://host:1080)")

    cfg = {
        "type": scheme_map[scheme],
        "host": parsed.hostname,
        "port": int(parsed.port),
    }
    if cfg["type"] in ("socks", "socks4"):
        cfg["proxyDNS"] = True
    if parsed.username is not None:
        cfg["username"] = parsed.username
    if parsed.password is not None:
        cfg["password"] = parsed.password
    return cfg


def mask_proxy_config(cfg):
    if not isinstance(cfg, dict) or not cfg.get("host"):
        return None
    scheme = "socks5" if cfg.get("type") == "socks" else cfg.get("type", "http")
    auth = ""
    if cfg.get("username"):
        auth = f"{cfg['username']}:***@" if cfg.get("password") else f"{cfg['username']}@"
    return f"{scheme}://{auth}{cfg['host']}:{cfg['port']}"


COUNTRY_TO_LOCALE = {
    "PT": "pt-PT", "BR": "pt-BR", "ES": "es-ES", "AR": "es-AR", "MX": "es-MX",
    "CO": "es-CO", "CL": "es-CL", "US": "en-US", "GB": "en-GB", "UK": "en-GB",
    "CA": "en-CA", "AU": "en-AU", "IE": "en-IE", "FR": "fr-FR", "BE": "fr-BE",
    "CH": "de-CH", "DE": "de-DE", "AT": "de-AT", "IT": "it-IT", "NL": "nl-NL",
    "PL": "pl-PL", "SE": "sv-SE", "NO": "nb-NO", "DK": "da-DK", "FI": "fi-FI",
    "JP": "ja-JP", "KR": "ko-KR", "CN": "zh-CN", "IN": "en-IN", "RU": "ru-RU",
    "TR": "tr-TR", "ZA": "en-ZA", "AO": "pt-AO", "MZ": "pt-MZ",
}


def build_accept_language(locale_str):
    if not locale_str:
        return None
    loc = str(locale_str).strip()
    base = loc.split("-")[0]
    if base.lower() == "en":
        return f"{loc},{base};q=0.9"
    return f"{loc},{base};q=0.9,en-US;q=0.8,en;q=0.7"


def build_requests_proxy_url(cfg):
    if not isinstance(cfg, dict) or not cfg.get("host"):
        return None
    ptype = cfg.get("type", "http")
    scheme = "socks5h" if ptype == "socks" else ("socks4a" if ptype == "socks4" else ptype)
    auth = ""
    if cfg.get("username"):
        auth = f"{cfg['username']}:{cfg.get('password', '')}@"
    return f"{scheme}://{auth}{cfg['host']}:{cfg['port']}"


def detect_proxy_geo(proxy_cfg, explicit_timezone=None, explicit_locale=None, auto_geo=True, explicit_lat=None, explicit_lon=None):
    """Auto-detect IP, country, timezone, locale and coordinates through the container's proxy."""
    geo = {}
    if auto_geo and isinstance(proxy_cfg, dict) and proxy_cfg.get("host"):
        try:
            import requests
            purl = build_requests_proxy_url(proxy_cfg)
            proxies_arg = {"http": purl, "https": purl}
            info = None
            try:
                r = requests.get(
                    "http://ip-api.com/json/?fields=status,country,countryCode,regionName,city,lat,lon,timezone,query",
                    proxies=proxies_arg,
                    timeout=10,
                )
                if r.ok:
                    j = r.json()
                    if j.get("status") == "success":
                        info = {
                            "ip": j.get("query"),
                            "country": j.get("country"),
                            "countryCode": (j.get("countryCode") or "").upper(),
                            "city": j.get("city"),
                            "timezone": j.get("timezone"),
                            "lat": j.get("lat"),
                            "lon": j.get("lon"),
                        }
            except Exception as e1:
                print(f"[Camoufox GeoIP] ip-api.com failed ({e1}), trying ipwho.is...", flush=True)

            if not info:
                try:
                    r2 = requests.get("https://ipwho.is/", proxies=proxies_arg, timeout=10)
                    if r2.ok:
                        j2 = r2.json()
                        if j2.get("success", True):
                            tz_obj = j2.get("timezone")
                            tz_id = tz_obj.get("id") if isinstance(tz_obj, dict) else tz_obj
                            info = {
                                "ip": j2.get("ip"),
                                "country": j2.get("country"),
                                "countryCode": (j2.get("country_code") or "").upper(),
                                "city": j2.get("city"),
                                "timezone": tz_id,
                                "lat": j2.get("latitude"),
                                "lon": j2.get("longitude"),
                            }
                except Exception as e2:
                    print(f"[Camoufox GeoIP] ipwho.is failed: {e2}", flush=True)

            if info:
                geo.update({k: v for k, v in info.items() if v is not None})
                cc = info.get("countryCode", "")
                if cc and cc in COUNTRY_TO_LOCALE:
                    geo["locale"] = COUNTRY_TO_LOCALE[cc]
        except Exception as ge:
            print(f"[Camoufox GeoIP Warning] Could not auto-detect geo for proxy: {ge}", flush=True)

    if explicit_timezone:
        geo["timezone"] = str(explicit_timezone).strip()
    if explicit_locale:
        geo["locale"] = str(explicit_locale).strip()
    if explicit_lat is not None and explicit_lon is not None:
        lat_f = float(explicit_lat)
        lon_f = float(explicit_lon)
        if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0):
            raise ValueError("latitude must be between -90 and 90, and longitude between -180 and 180.")
        geo["lat"] = lat_f
        geo["lon"] = lon_f

    if geo.get("locale"):
        loc = geo["locale"]
        base = loc.split("-")[0]
        geo["languages"] = [loc, base] if base != loc else [loc]
        geo["acceptLanguage"] = build_accept_language(loc)

    return geo if geo else None


def build_geo_init_script(geo):
    if not isinstance(geo, dict):
        return None
    if not (geo.get("timezone") or geo.get("locale") or isinstance(geo.get("lat"), (int, float))):
        return None
    payload = json.dumps({
        "timezone": geo.get("timezone"),
        "locale": geo.get("locale"),
        "languages": geo.get("languages") or ([geo["locale"], geo["locale"].split("-")[0]] if geo.get("locale") else None),
        "lat": geo.get("lat") if isinstance(geo.get("lat"), (int, float)) else None,
        "lon": geo.get("lon") if isinstance(geo.get("lon"), (int, float)) else None,
    })
    return f"""(() => {{
  try {{
    const cfg = {payload};
    window.__camoufoxGeoApplied = true;
    if (cfg.locale) {{
      Object.defineProperty(Navigator.prototype, "language", {{
        get: () => cfg.locale,
        configurable: true
      }});
    }}
    if (Array.isArray(cfg.languages) && cfg.languages.length > 0) {{
      const langs = Object.freeze([...cfg.languages]);
      Object.defineProperty(Navigator.prototype, "languages", {{
        get: () => langs,
        configurable: true
      }});
    }}
    if (cfg.timezone) {{
      const tz = cfg.timezone;
      const OrigDTF = Intl.DateTimeFormat;
      const PatchedDTF = function DateTimeFormat(locales, options) {{
        const opts = Object.assign({{}}, options || {{}});
        if (!opts.timeZone) opts.timeZone = tz;
        const loc = locales !== undefined ? locales : (cfg.locale || undefined);
        return new OrigDTF(loc, opts);
      }};
      PatchedDTF.prototype = OrigDTF.prototype;
      PatchedDTF.supportedLocalesOf = OrigDTF.supportedLocalesOf.bind(OrigDTF);
      Intl.DateTimeFormat = PatchedDTF;

      const origResolved = OrigDTF.prototype.resolvedOptions;
      OrigDTF.prototype.resolvedOptions = function () {{
        const res = origResolved.call(this);
        if (res && !res.timeZone) res.timeZone = tz;
        return res;
      }};

      const computeOffset = (date) => {{
        try {{
          const parts = new OrigDTF("en-US", {{
            timeZone: tz,
            year: "numeric", month: "2-digit", day: "2-digit",
            hour: "2-digit", minute: "2-digit", second: "2-digit",
            hour12: false
          }}).formatToParts(date);
          const map = {{}};
          for (const p of parts) map[p.type] = p.value;
          const h = map.hour === "24" ? "00" : map.hour;
          const asUtc = Date.UTC(
            Number(map.year), Number(map.month) - 1, Number(map.day),
            Number(h), Number(map.minute), Number(map.second)
          );
          return Math.round((date.getTime() - asUtc) / 60000);
        }} catch (_) {{ return 0; }}
      }};
      Date.prototype.getTimezoneOffset = function () {{ return computeOffset(this); }};
    }}
    if (typeof cfg.lat === "number" && typeof cfg.lon === "number" && navigator.geolocation) {{
      const mockPos = () => ({{
        coords: {{ latitude: cfg.lat, longitude: cfg.lon, accuracy: 35, altitude: null, altitudeAccuracy: null, heading: null, speed: null }},
        timestamp: Date.now()
      }});
      navigator.geolocation.getCurrentPosition = (cb) => {{ if (typeof cb === "function") setTimeout(() => cb(mockPos()), 10); }};
      navigator.geolocation.watchPosition = (cb) => {{ if (typeof cb === "function") setTimeout(() => cb(mockPos()), 10); return 1; }};
    }}
  }} catch (_) {{}}
}})();"""


def cleanup_old_screenshots(d_dir, max_files=None):
    try:
        limit = max_files if max_files is not None else int(os.getenv("SCREENSHOT_MAX_FILES", "50"))
        if limit <= 0:
            return
        shots = [
            os.path.join(d_dir, f)
            for f in os.listdir(d_dir)
            if f.startswith("screenshot_") and f.endswith(".png")
        ]
        if len(shots) <= limit:
            return
        shots.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        for old_p in shots[limit:]:
            try:
                os.remove(old_p)
            except Exception:
                pass
    except Exception:
        pass


def call_container_bridge(action, payload=None, timeout=10.0):
    """Send a command to the internal container-bridge WebExtension and await its response."""
    cmd_id = uuid.uuid4().hex
    evt = threading.Event()
    entry = {"event": evt, "result": None}
    with bridge_pending_lock:
        bridge_pending[cmd_id] = entry

    cmd = {"id": cmd_id, "action": action}
    if isinstance(payload, dict):
        cmd.update(payload)
    bridge_cmd_queue.put(cmd)

    if not evt.wait(timeout=timeout):
        with bridge_pending_lock:
            bridge_pending.pop(cmd_id, None)
        return {"ok": False, "error": f"Container bridge timed out waiting for '{action}' (is the extension loaded?)"}

    with bridge_pending_lock:
        bridge_pending.pop(cmd_id, None)
    return entry.get("result") or {"ok": False, "error": "Empty response from container bridge"}


def get_containers_list(profile_dir=None):
    """Return list of containers from live Firefox extension (fallback to containers.json) enriched with proxy info."""
    pdir = profile_dir or os.getenv("PROFILE_DIR", "/root/profile")
    proxies = load_container_proxies(pdir)
    containers = None

    bridge_res = call_container_bridge("list_containers", timeout=5.0)
    if bridge_res.get("ok") and isinstance(bridge_res.get("containers"), list):
        containers = bridge_res["containers"]
    else:
        containers_path = os.path.join(pdir, "containers.json")
        containers = []
        if os.path.exists(containers_path):
            try:
                with open(containers_path, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                for ident in cdata.get("identities", []):
                    if not ident.get("public", True):
                        continue
                    uid = ident.get("userContextId")
                    name = ident.get("name") or ident.get("l10nId") or f"Container {uid}"
                    containers.append({
                        "userContextId": uid,
                        "cookieStoreId": f"firefox-container-{uid}",
                        "name": name,
                        "color": ident.get("color", "blue"),
                        "icon": ident.get("icon", "fingerprint"),
                    })
            except Exception:
                pass

    enriched = []
    for c in containers:
        store_id = c.get("cookieStoreId")
        pcfg = proxies.get(store_id)
        c_copy = dict(c)
        c_copy["proxy"] = mask_proxy_config(pcfg)
        c_copy["data_saver"] = (pcfg.get("data_saver") or "off") if isinstance(pcfg, dict) else "off"
        c_copy["geo"] = pcfg.get("geo") if isinstance(pcfg, dict) else None
        enriched.append(c_copy)
    return enriched


def resolve_container(container_query, profile_dir=None):
    """Find a container by name (case-insensitive), cookieStoreId, or userContextId."""
    q = str(container_query or "").strip()
    containers = get_containers_list(profile_dir)
    q_low = q.lower()
    for c in containers:
        if str(c.get("name", "")).lower() == q_low:
            return c, containers
        if str(c.get("cookieStoreId", "")).lower() == q_low:
            return c, containers
        if c.get("userContextId") is not None and str(c.get("userContextId")) == q:
            return c, containers
    return None, containers


status_cache = {
    "status": "starting",
    "browser": "camoufox",
    "url": "",
    "title": "",
    "tabs_count": 0,
    "is_busy": False,
    "active_client": None,
    "active_command": None,
    "queue_length": 0
}

class CamoufoxAPIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-MCP-Client-Id')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-MCP-Client-Id, Authorization, X-API-Key')
        self.end_headers()

    def _is_authorized(self, clean_path):
        api_key = os.getenv("CAMOUFOX_API_KEY", "").strip()
        if not api_key:
            return True
        if clean_path in ('/health', '/'):
            return True
        if clean_path.startswith('/_bridge/') and self.client_address[0] in ('127.0.0.1', '::1'):
            return True
        req_key = (self.headers.get('X-API-Key') or '').strip()
        auth_hdr = (self.headers.get('Authorization') or '').strip()
        if auth_hdr.lower().startswith('bearer '):
            req_key = auth_hdr[7:].strip()
        return req_key == api_key

    def _read_body(self):
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length > 0:
            raw = self.rfile.read(content_length).decode('utf-8')
            try:
                return json.loads(raw)
            except Exception:
                return {}
        return {}

    def _send_binary(self, data_bytes, content_type='image/png', status=200, filename=None, head_only=False):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data_bytes)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        if filename:
            self.send_header('Content-Disposition', f'inline; filename="{filename}"')
        self.end_headers()
        if not head_only:
            self.wfile.write(data_bytes)

    def do_HEAD(self):
        return self._handle_get_or_head(head_only=True)

    def do_GET(self):
        return self._handle_get_or_head(head_only=False)

    def _handle_get_or_head(self, head_only=False):
        clean_path = self.path.split('?')[0]
        if not self._is_authorized(clean_path):
            return self._send_json({"error": "Unauthorized: invalid or missing API key"}, 401)
        if clean_path in ('/health', '/', '/status'):
            status_copy = dict(status_cache)
            status_copy["queue_length"] = command_queue.qsize()
            return self._send_json(status_copy)
        if clean_path == '/_bridge/proxies':
            return self._send_json({"proxies": load_container_proxies()})
        if clean_path == '/_bridge/poll':
            try:
                cmd = bridge_cmd_queue.get(timeout=20.0)
                return self._send_json(cmd)
            except queue.Empty:
                self.send_response(204)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                return
        if clean_path == '/containers':
            containers = get_containers_list()
            return self._send_json({"status": "ok", "containers": containers, "count": len(containers)})
        if clean_path in ('/screenshot.png', '/screenshot', '/latest_screenshot.png'):
            d_dir = os.getenv("DOWNLOADS_DIR", "/data/downloads")
            latest_fpath = os.path.join(d_dir, "latest_screenshot.png")
            force_live = 'live=1' in self.path or 'fresh=1' in self.path
            if not force_live and os.path.exists(latest_fpath) and os.path.isfile(latest_fpath):
                try:
                    with open(latest_fpath, "rb") as f:
                        return self._send_binary(f.read(), 'image/png', 200, 'screenshot.png', head_only=head_only)
                except Exception as e:
                    return self._send_json({"error": f"Failed to read screenshot: {str(e)}"}, 500)
            req = CommandRequest(endpoint='/screenshot', data={}, client_id='http-get-screenshot')
            command_queue.put(req)
            if not req.started_event.wait(timeout=req.queue_timeout):
                req.cancelled.set()
                return self._send_json({"error": "Queue timeout"}, 503)
            if req.done_event.wait(timeout=req.exec_timeout):
                payload = req.result_holder.get("payload", {})
                b64 = payload.get("image_base64")
                if b64:
                    return self._send_binary(base64.b64decode(b64), 'image/png', 200, 'screenshot.png', head_only=head_only)
                return self._send_json(payload, req.result_holder.get("http_status", 500))
            return self._send_json({"error": "Execution timeout"}, 504)
        if clean_path.startswith('/screenshots/'):
            fname = os.path.basename(clean_path[len('/screenshots/'):].strip())
            d_dir = os.getenv("DOWNLOADS_DIR", "/data/downloads")
            fpath = os.path.join(d_dir, fname)
            if fname and os.path.exists(fpath) and os.path.isfile(fpath):
                try:
                    with open(fpath, "rb") as f:
                        return self._send_binary(f.read(), 'image/png', 200, fname, head_only=head_only)
                except Exception as e:
                    return self._send_json({"error": f"Failed to read screenshot: {str(e)}"}, 500)
            return self._send_json({"error": f"Screenshot '{fname}' not found"}, 404)
        self._send_json({"error": "Endpoint not found"}, 404)

    def do_POST(self):
        clean_path = self.path.split('?')[0]
        if not self._is_authorized(clean_path):
            return self._send_json({"error": "Unauthorized: invalid or missing API key"}, 401)
        data = self._read_body()
        endpoint = clean_path
        if endpoint == '/_bridge/result':
            cmd_id = data.get("id")
            res = data.get("result")
            if cmd_id:
                with bridge_pending_lock:
                    entry = bridge_pending.get(cmd_id)
                if entry:
                    entry["result"] = res
                    entry["event"].set()
            return self._send_json({"ok": True})

        client_id = self.headers.get('X-MCP-Client-Id') or data.get('_client_id')
        if not client_id:
            client_id = f"client-{self.client_address[0]}:{self.client_address[1]}"

        queue_timeout = float(os.getenv("QUEUE_TIMEOUT", "120.0"))
        exec_timeout = float(os.getenv("EXEC_TIMEOUT", "60.0"))

        req = CommandRequest(
            endpoint=endpoint,
            data=data,
            client_id=client_id,
            queue_timeout=queue_timeout,
            exec_timeout=exec_timeout
        )

        curr_q = command_queue.qsize()
        if curr_q > 0 or status_cache.get("is_busy"):
            print(f"[Camoufox Queue] ⏳ Client '{client_id}' queued '{endpoint}' (position in line: {curr_q + 1})", flush=True)

        command_queue.put(req)

        # 1. Wait to acquire the exclusive execution lock from queue
        if not req.started_event.wait(timeout=req.queue_timeout):
            req.cancelled.set()
            print(f"[Camoufox Queue] ⚠️ Queue wait timeout ({req.queue_timeout}s) for client '{client_id}' ({endpoint})", flush=True)
            return self._send_json({
                "error": "Server busy: queue wait timeout exceeded (another client is using Camoufox)",
                "status": "queue_timeout"
            }, 503)

        # 2. Wait for command execution to complete
        if req.done_event.wait(timeout=req.exec_timeout):
            status_code = req.result_holder.get("http_status", 200)
            return self._send_json(req.result_holder.get("payload", {}), status_code)
        else:
            print(f"[Camoufox Queue] ⚠️ Execution timeout ({req.exec_timeout}s) for client '{client_id}' ({endpoint})", flush=True)
            return self._send_json({
                "error": "Browser command execution timed out",
                "status": "exec_timeout"
            }, 504)

def start_api_server(port=9377):
    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer(('0.0.0.0', port), CamoufoxAPIHandler)
    print(f"[Camoufox API] HTTP/MCP control server listening on port {port}", flush=True)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server

def safe_get_title(page):
    if not page:
        return ""
    try:
        if page.is_closed():
            return ""
        return page.locator("title").first.inner_text(timeout=500)
    except Exception:
        return ""

def safe_get_text(page):
    if not page:
        return ""
    try:
        if page.is_closed():
            return ""
        return page.locator("body").inner_text(timeout=3000)
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

        sc_dir = os.path.join(profile_dir, "startupCache")
        if os.path.exists(sc_dir):
            import shutil
            shutil.rmtree(sc_dir, ignore_errors=True)
            print(f"[Camoufox] Cleared startupCache to reload updated browser scripts", flush=True)
    except Exception as e:
        print(f"[Camoufox] Warning while cleaning locks: {e}", flush=True)

def ensure_container_juggler_support():
    """
    Patches Firefox Juggler's TargetRegistry.js and BrowserHandler.js inside omni.ja so that tabs
    opened in container contexts (e.g. Multi-Account Containers for Portugal/Brasil proxies)
    fall back to the default automation context and attach to Juggler sessions.
    This guarantees full Playwright / MCP control over container tabs.
    Runs automatically on startup, making it 100% persistent across any Camoufox browser updates.
    """
    import glob
    import zipfile
    import shutil

    search_dirs = [
        "/root/.cache/camoufox/browsers/**/omni.ja",
        "/root/.cache/ms-playwright/firefox-*/**/omni.ja",
        "/opt/camoufox/**/omni.ja"
    ]
    omni_files = []
    for pattern in search_dirs:
        omni_files.extend(glob.glob(pattern, recursive=True))

    for omni_path in set(omni_files):
        try:
            if not os.path.isfile(omni_path):
                continue
            needs_patch = False
            target_reg_entry = None
            browser_handler_entry = None
            with zipfile.ZipFile(omni_path, "r") as zin:
                for fname in zin.namelist():
                    if fname.endswith("/TargetRegistry.js") and "juggler" in fname:
                        target_reg_entry = fname
                    elif fname.endswith("/BrowserHandler.js") and "juggler" in fname:
                        browser_handler_entry = fname

                if target_reg_entry:
                    data = zin.read(target_reg_entry).decode("utf-8")
                    if "[JUGGLER DUMP]" not in data:
                        needs_patch = True
                if browser_handler_entry:
                    b_data = zin.read(browser_handler_entry).decode("utf-8")
                    if "_shouldAttachToTarget(target) {\n    if (this._createdBrowserContextIds" in b_data:
                        needs_patch = True

            if not needs_patch:
                continue

            print(f"[Camoufox Container Support] Patching Juggler container support in: {omni_path} ({target_reg_entry}, {browser_handler_entry})", flush=True)
            bak_path = omni_path + ".bak"
            if not os.path.exists(bak_path):
                shutil.copy2(omni_path, bak_path)

            tmp_path = omni_path + ".tmp"
            with zipfile.ZipFile(omni_path, "r") as zin:
                with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_STORED) as zout:
                    for item in zin.infolist():
                        file_data = zin.read(item.filename)
                        if target_reg_entry and item.filename == target_reg_entry:
                            text = file_data.decode("utf-8")
                            old_const = "const userContextId = tab.userContextId;\n      const browserContext = this._userContextIdToBrowserContext.get(userContextId);"
                            new_const = 'const userContextId = tab.userContextId;\n      dump("[JUGGLER DUMP] onTabOpen userContextId=" + userContextId + "\\n");\n      const browserContext = this._userContextIdToBrowserContext.get(userContextId) || this._defaultContext || this._userContextIdToBrowserContext.get(0);'
                            old_err1 = "if (!browserContext)\n        throw new Error(`Internal error: cannot find context for userContextId=${userContextId}`);"
                            old_err2 = "if (!browserContext)\n        browserContext = this._defaultContext || this._userContextIdToBrowserContext.get(0);"
                            old_err3 = "if (!browserContext)\n        browserContext = this._userContextIdToBrowserContext.get(0) || this._defaultContext;"
                            old_net = "return this._userContextIdToBrowserContext.get(userContextId);"
                            new_net = "return this._userContextIdToBrowserContext.get(userContextId) || this._defaultContext || this._userContextIdToBrowserContext.get(0);"
                            text = text.replace(old_const, new_const)
                            text = text.replace(old_err1, "// container resolved")
                            text = text.replace(old_err2, "// container resolved")
                            text = text.replace(old_err3, "// container resolved")
                            text = text.replace(old_net, new_net)
                            file_data = text.encode("utf-8")
                        elif browser_handler_entry and item.filename == browser_handler_entry:
                            text = file_data.decode("utf-8")
                            old_should = "_shouldAttachToTarget(target) {\n    if (this._createdBrowserContextIds"
                            new_should = "_shouldAttachToTarget(target) {\n    return true;\n    if (this._createdBrowserContextIds"
                            text = text.replace(old_should, new_should)
                            file_data = text.encode("utf-8")
                        zout.writestr(item, file_data)
            shutil.move(tmp_path, omni_path)
            shutil.rmtree("/root/profile/startupCache", ignore_errors=True)
            print(f"[Camoufox Container Support] Successfully activated container automation support! Cleared startupCache.", flush=True)
        except Exception as e:
            print(f"[Camoufox Container Support Warning] Could not patch {omni_path}: {e}", flush=True)

def main():
    global status_cache
    profile_dir = os.getenv("PROFILE_DIR", "/root/profile")
    os.makedirs(profile_dir, exist_ok=True)
    cleanup_profile_locks(profile_dir)
    fix_search_policies()
    ensure_container_juggler_support()
    
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
                data["policies"]["ExtensionSettings"]["container-bridge@camoufox.local"] = {
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
        "browser.dom.window.dump.enabled": True,
        "browser.startup.homepage": "https://duckduckgo.com",
        "browser.startup.page": 1,
        "browser.search.defaultenginename": "DuckDuckGo",
        "browser.search.order.1": "DuckDuckGo",
        "browser.urlbar.placeholderName": "DuckDuckGo",
        "browser.search.suggest.enabled": True,
        "browser.urlbar.suggest.searches": True,
        "keyword.enabled": True,
        # Multi-Account Containers & WebRTC leak protection
        "privacy.userContext.enabled": True,
        "privacy.userContext.ui.enabled": True,
        "privacy.userContext.longPressBehavior": 2,
        "privacy.userContext.newTabContainerOnLeftClick.enabled": True,
        "privacy.userContext.extension": "@testpilot-containers",
        "xpinstall.signatures.required": False,
        "media.peerconnection.ice.default_address_only": True,
        "media.peerconnection.ice.proxy_only_if_behind_proxy": True,
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
        proxy_config = {
            "server": proxy_server,
            "bypass": os.getenv("PROXY_BYPASS", "0.0.4.0,localhost,127.0.0.1"),
        }
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
        "canvas_noise": get_env_bool("CANVAS_NOISE", False),
        "i_know_what_im_doing": True,
    }
    bridge_ext_dir = os.getenv("CONTAINER_BRIDGE_EXT_DIR", "/opt/camoufox-extensions/container-bridge")
    if os.path.isdir(bridge_ext_dir):
        try:
            ext_cfg = {"api_port": api_port}
            if os.getenv("CAMOUFOX_API_KEY", "").strip():
                ext_cfg["api_key"] = os.getenv("CAMOUFOX_API_KEY", "").strip()
            with open(os.path.join(bridge_ext_dir, "config.json"), "w", encoding="utf-8") as cfg_f:
                json.dump(ext_cfg, cfg_f)
        except Exception as e_cfg:
            print(f"[Camoufox Container Bridge] Warning writing config.json: {e_cfg}", flush=True)
        camoufox_kwargs["addons"] = [bridge_ext_dir]
        print(f"[Camoufox Container Bridge] Loaded internal extension from: {bridge_ext_dir}", flush=True)
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

            session_tabs = {}
            page_last_touch = {}
            page_containers = {}

            while running:
                try:
                    req = command_queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                if not req:
                    continue

                if req.cancelled.is_set():
                    print(f"[Camoufox Lock] Skipping cancelled/timed-out request {req.id} from '{req.client_id}' ({req.endpoint})", flush=True)
                    continue

                req.started_at = time.time()
                wait_time = req.started_at - req.created_at
                req.started_event.set()

                status_cache["is_busy"] = True
                status_cache["active_client"] = req.client_id
                status_cache["active_command"] = req.endpoint
                status_cache["queue_length"] = command_queue.qsize()

                print(f"[Camoufox Lock] 🔒 Lock acquired by '{req.client_id}' for '{req.endpoint}' (waited: {wait_time:.2f}s, in queue: {command_queue.qsize()})", flush=True)

                endpoint = req.endpoint
                data = req.data
                result_holder = req.result_holder

                try:
                    # Ensure a valid active page for the command (with per-agent tab_index / session_id isolation)
                    req_tab_index = data.get("tab_index") if isinstance(data, dict) else None
                    req_session_id = (str(data.get("session_id") or "").strip() or None) if isinstance(data, dict) else None
                    try:
                        active_pages = [p for p in browser.pages if not p.is_closed()]
                        if not active_pages:
                            curr_page = browser.new_page()
                            active_pages = [curr_page]
                            active_tab_index = 0

                        for sid_k, sp in list(session_tabs.items()):
                            if sp not in active_pages:
                                del session_tabs[sid_k]

                        prev_page = active_pages[active_tab_index] if 0 <= active_tab_index < len(active_pages) else active_pages[-1]

                        if req_tab_index is not None and endpoint not in ('/close_tab', '/switch_tab'):
                            t_idx = int(req_tab_index)
                            if not (0 <= t_idx < len(active_pages)):
                                result_holder["http_status"] = 400
                                result_holder["payload"] = {
                                    "error": f"Invalid tab_index {t_idx}. Open tabs: 0 to {len(active_pages) - 1}"
                                }
                                continue
                            active_tab_index = t_idx
                            curr_page = active_pages[active_tab_index]
                            if req_session_id:
                                session_tabs[req_session_id] = curr_page
                        elif req_session_id and endpoint not in ('/new_tab', '/close_tab', '/switch_tab'):
                            if req_session_id in session_tabs and session_tabs[req_session_id] in active_pages:
                                curr_page = session_tabs[req_session_id]
                                active_tab_index = active_pages.index(curr_page)
                            else:
                                assigned_p = None
                                owned_pages = set(session_tabs.values())
                                now_ts = time.time()
                                for candidate_p in active_pages:
                                    if candidate_p in owned_pages:
                                        continue
                                    last_owner, last_ts = page_last_touch.get(candidate_p, (None, 0.0))
                                    if last_owner is None or last_owner == req_session_id or (now_ts - last_ts > 180.0):
                                        assigned_p = candidate_p
                                        break
                                if assigned_p is None:
                                    assigned_p = create_new_tab(browser, prev_page, start_url)
                                    active_pages = [p for p in browser.pages if not p.is_closed()]
                                    if assigned_p not in active_pages:
                                        assigned_p = active_pages[-1]
                                session_tabs[req_session_id] = assigned_p
                                curr_page = assigned_p
                                active_tab_index = active_pages.index(curr_page)
                        else:
                            if active_tab_index >= len(active_pages):
                                active_tab_index = len(active_pages) - 1
                            curr_page = active_pages[active_tab_index]
                            if endpoint == '/navigate' and isinstance(data, dict) and data.get('url'):
                                raw_u = str(data.get('url')).strip()
                                if not raw_u.startswith("http://") and not raw_u.startswith("https://"):
                                    raw_u = "https://" + raw_u
                                try:
                                    from urllib.parse import urlparse
                                    t_dom = urlparse(raw_u).netloc.lower().lstrip("www.")
                                    c_dom = urlparse(curr_page.url or "").netloc.lower().lstrip("www.")
                                except Exception:
                                    t_dom, c_dom = "", ""
                                now_ts = time.time()
                                owned_pages = set(session_tabs.values())
                                _, c_last_ts = page_last_touch.get(curr_page, (None, 0.0))
                                c_busy = (curr_page in owned_pages) or (c_last_ts > 0 and (now_ts - c_last_ts <= 180.0))
                                if c_busy and c_dom and t_dom and c_dom != t_dom:
                                    chosen_p = None
                                    for cand_p in active_pages:
                                        if cand_p in owned_pages:
                                            continue
                                        _, cand_ts = page_last_touch.get(cand_p, (None, 0.0))
                                        try:
                                            cand_dom = urlparse(cand_p.url or "").netloc.lower().lstrip("www.")
                                        except Exception:
                                            cand_dom = ""
                                        if cand_p.url in ("", "about:blank") or (cand_ts == 0.0) or (now_ts - cand_ts > 180.0):
                                            chosen_p = cand_p
                                            break
                                    if chosen_p is None:
                                        chosen_p = create_new_tab(browser, curr_page, "about:blank")
                                        active_pages = [p for p in browser.pages if not p.is_closed()]
                                        if chosen_p not in active_pages:
                                            chosen_p = active_pages[-1]
                                    curr_page = chosen_p
                                    active_tab_index = active_pages.index(curr_page)

                        if curr_page != prev_page and endpoint not in ('/tabs', '/downloads', '/list_downloads', '/get_download'):
                            try:
                                curr_page.bring_to_front()
                            except Exception:
                                pass
                    except Exception as pe:
                        result_holder["http_status"] = 500
                        result_holder["payload"] = {"error": f"Failed to get active page: {str(pe)}"}
                        continue
                    if endpoint == '/navigate':
                        target_url = data.get('url')
                        req_container = str(data.get('container') or '').strip()
                        if not target_url:
                            result_holder["http_status"] = 400
                            result_holder["payload"] = {"error": "Parameter 'url' is required"}
                        else:
                            if not target_url.startswith("http://") and not target_url.startswith("https://"):
                                target_url = "https://" + target_url
                            timeout = int(data.get('timeout', 30000))

                            if req_container:
                                ident, all_containers = resolve_container(req_container, profile_dir)
                                if not ident:
                                    avail = [c.get("name") for c in all_containers]
                                    result_holder["http_status"] = 400
                                    result_holder["payload"] = {
                                        "error": f"Container '{req_container}' not found. Available containers: {', '.join(avail) if avail else '(none)'}. Use browse_create_container to create one.",
                                        "available_containers": all_containers
                                    }
                                    continue

                                launcher_page = curr_page
                                pages_before = set(browser.pages)
                                container_page = None
                                bridge_open_res = None
                                proxies_snapshot = load_container_proxies(profile_dir)
                                try:
                                    with browser.expect_page(timeout=15000) as p_info:
                                        bridge_open_res = call_container_bridge(
                                            "open_tab",
                                            {
                                                "cookieStoreId": ident["cookieStoreId"],
                                                "url": target_url,
                                                "proxies": proxies_snapshot,
                                            },
                                            timeout=10.0
                                        )
                                    if bridge_open_res and bridge_open_res.get("ok"):
                                        cand = p_info.value
                                        new_pages = [p for p in browser.pages if p not in pages_before and not p.is_closed()]
                                        target_host = (urlparse(target_url).hostname or "").lower()
                                        matched = next((p for p in reversed(new_pages) if target_host and target_host in (p.url or "").lower()), None)
                                        container_page = matched or (new_pages[-1] if new_pages else cand)
                                except Exception as e_exp:
                                    print(f"[Camoufox Container] expect_page notice: {e_exp}", flush=True)

                                if bridge_open_res and not bridge_open_res.get("ok"):
                                    result_holder["http_status"] = 500
                                    result_holder["payload"] = {
                                        "error": f"Failed to open tab in container '{ident['name']}': {bridge_open_res.get('error', 'unknown error')}"
                                    }
                                    continue

                                if not container_page:
                                    for _ in range(15):
                                        candidates = [p for p in browser.pages if p not in pages_before and not p.is_closed()]
                                        if candidates:
                                            container_page = candidates[-1]
                                            break
                                        time.sleep(0.2)

                                if not container_page:
                                    result_holder["http_status"] = 500
                                    result_holder["payload"] = {
                                        "error": f"Opened tab in container '{ident['name']}', but Playwright could not attach to the new tab."
                                    }
                                    continue

                                page_containers[container_page] = ident["name"]
                                geo_js = build_geo_init_script(ident.get("geo"))
                                if geo_js:
                                    try:
                                        container_page.add_init_script(geo_js)
                                    except Exception:
                                        pass
                                try:
                                    if launcher_page != container_page and not launcher_page.is_closed() and len([p for p in browser.pages if not p.is_closed()]) > 1:
                                        launcher_page.close(run_before_unload=False)
                                except Exception as e_close:
                                    print(f"[Camoufox Container Warning] Failed to close previous tab: {e_close}", flush=True)

                                active_pages = [p for p in browser.pages if not p.is_closed()]
                                active_tab_index = active_pages.index(container_page) if container_page in active_pages else len(active_pages) - 1
                                curr_page = active_pages[active_tab_index]
                                try:
                                    curr_page.bring_to_front()
                                except Exception:
                                    pass
                                try:
                                    curr_page.wait_for_load_state("domcontentloaded", timeout=min(timeout, 15000))
                                except Exception:
                                    pass
                                if geo_js:
                                    try:
                                        curr_page.evaluate(geo_js)
                                    except Exception:
                                        pass

                                page_title = safe_get_title(curr_page)
                                status_cache["url"] = curr_page.url
                                status_cache["title"] = page_title
                                status_cache["tabs_count"] = len(active_pages)
                                if req_session_id:
                                    session_tabs[req_session_id] = curr_page
                                page_last_touch[curr_page] = (req_session_id or req.client_id, time.time())
                                result_holder["payload"] = {
                                    "status": "ok",
                                    "tab_index": active_tab_index,
                                    "session_id": req_session_id,
                                    "container": ident["name"],
                                    "cookieStoreId": ident["cookieStoreId"],
                                    "proxy": ident.get("proxy"),
                                    "url": curr_page.url,
                                    "title": page_title
                                }
                                continue

                            is_container = ".container/" in target_url.lower()
                            launcher_page = curr_page
                            pages_before = set(browser.pages)

                            if is_container:
                                container_page = None
                                try:
                                    with browser.expect_page(timeout=15000) as p_info:
                                        try:
                                            launcher_page.goto(target_url, timeout=3000, wait_until="commit")
                                        except Exception:
                                            pass
                                    container_page = p_info.value
                                except Exception as e_exp:
                                    print(f"[Camoufox Container] expect_page notice: {e_exp}", flush=True)

                                if not container_page:
                                    for _ in range(8):
                                        candidates = [p for p in browser.pages if p != launcher_page and not p.is_closed()]
                                        if candidates:
                                            container_page = candidates[-1]
                                            break
                                        try:
                                            if not launcher_page.is_closed():
                                                launcher_page.wait_for_timeout(500)
                                            else:
                                                time.sleep(0.5)
                                        except Exception:
                                            time.sleep(0.5)

                                if container_page:
                                    print(f"[Camoufox Container] Successfully captured container tab: {container_page.url}", flush=True)
                                    try:
                                        if launcher_page != container_page and not launcher_page.is_closed():
                                            launcher_page.close(run_before_unload=False)
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
                                        curr_page.wait_for_load_state("domcontentloaded", timeout=15000)
                                    except Exception:
                                        pass
                                else:
                                    print("[Camoufox Container Warning] No container tab found, staying on launcher page", flush=True)
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
                        text = safe_get_text(curr_page)
                        page_title = safe_get_title(curr_page)
                        elements_info = []
                        images_info = []
                        viewport_info = None
                        formatted_lines = []
                        try:
                            rich_js = r'''(() => {
                              const cssEsc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : String(s).replace(/([!"#$%&'()*+,./:;<=>?@[\\\]^`{|}~])/g, '\\$1');
                              const buildSelector = (el) => {
                                if (!el || el.nodeType !== 1) return '';
                                if (el.id) return '#' + cssEsc(el.id);
                                const tag = el.tagName.toLowerCase();
                                const nameAttr = el.getAttribute('name');
                                if (nameAttr && document.querySelectorAll(tag + '[name="' + nameAttr.replace(/"/g, '\\"') + '"]').length === 1) {
                                  return tag + '[name="' + nameAttr.replace(/"/g, '\\"') + '"]';
                                }
                                const ph = el.getAttribute('placeholder');
                                if (ph && document.querySelectorAll(tag + '[placeholder="' + ph.replace(/"/g, '\\"') + '"]').length === 1) {
                                  return tag + '[placeholder="' + ph.replace(/"/g, '\\"') + '"]';
                                }
                                const alt = el.getAttribute('alt');
                                if (alt && document.querySelectorAll(tag + '[alt="' + alt.replace(/"/g, '\\"') + '"]').length === 1) {
                                  return tag + '[alt="' + alt.replace(/"/g, '\\"') + '"]';
                                }
                                const aria = el.getAttribute('aria-label');
                                if (aria && document.querySelectorAll(tag + '[aria-label="' + aria.replace(/"/g, '\\"') + '"]').length === 1) {
                                  return tag + '[aria-label="' + aria.replace(/"/g, '\\"') + '"]';
                                }
                                const parts = [];
                                let cur = el;
                                while (cur && cur.nodeType === 1 && cur !== document.body && parts.length < 4) {
                                  let p = cur.tagName.toLowerCase();
                                  if (cur.id) {
                                    parts.unshift('#' + cssEsc(cur.id));
                                    break;
                                  }
                                  const parent = cur.parentElement;
                                  if (parent) {
                                    const siblings = [...parent.children].filter(c => c.tagName === cur.tagName);
                                    if (siblings.length > 1) {
                                      p += ':nth-of-type(' + (siblings.indexOf(cur) + 1) + ')';
                                    }
                                  }
                                  parts.unshift(p);
                                  cur = parent;
                                }
                                return parts.join(' > ');
                              };
                              const visible = (e) => !e.closest('[aria-hidden="true"],[inert]') &&
                                (typeof e.checkVisibility === 'function' ? e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true}) : true);
                              const getLabel = (e) => {
                                return (e.getAttribute('aria-label') ||
                                  [...(e.labels || [])].map(l => l.innerText.trim()).filter(Boolean).join(' ') ||
                                  (['button','submit','reset'].includes(e.type) ? e.value : '') ||
                                  e.getAttribute('placeholder') ||
                                  e.getAttribute('alt') ||
                                  e.getAttribute('title') ||
                                  (e.tagName === 'INPUT' ? '' : (e.innerText || e.textContent || '').trim()) ||
                                  e.getAttribute('name') ||
                                  '').replace(/\s+/g, ' ').trim().slice(0, 120);
                              };
                              const roles = ['button','link','checkbox','radio','switch','tab','menuitem','option','combobox','textbox','searchbox','spinbutton'];
                              const sel = 'a[href],button,input,textarea,select,summary,[contenteditable="true"],' + roles.map(r => '[role="' + r + '"]').join(',');
                              const getRole = (e) => {
                                const ex = e.getAttribute('role');
                                if (roles.includes(ex)) return ex;
                                if (e.tagName === 'BUTTON' || e.tagName === 'SUMMARY') return 'button';
                                if (e.tagName === 'A') return 'link';
                                if (e.tagName === 'SELECT') return 'combobox';
                                if (e.tagName === 'TEXTAREA' || e.isContentEditable) return 'textbox';
                                if (e.tagName === 'INPUT') {
                                  if (['checkbox','radio'].includes(e.type)) return e.type;
                                  if (['button','submit','reset','image'].includes(e.type)) return 'button';
                                  if (e.type === 'search') return 'searchbox';
                                  if (e.type === 'number') return 'spinbutton';
                                  if (!['hidden'].includes(e.type)) return 'textbox';
                                }
                                return 'element';
                              };
                              const elements = [];
                              let idx = 1;
                              for (const e of document.querySelectorAll(sel)) {
                                if (e.type === 'hidden' || !visible(e) || e.matches(':disabled')) continue;
                                const r = e.getBoundingClientRect();
                                if (r.width <= 1 || r.height <= 1) continue;
                                const cx = Math.round(r.x + r.width / 2);
                                const cy = Math.round(r.y + r.height / 2);
                                if (r.bottom < 0 || r.top > window.innerHeight * 2) continue;
                                const role = getRole(e);
                                const label = getLabel(e);
                                const selector = buildSelector(e);
                                const val = ('value' in e && e.type !== 'password') ? String(e.value || '').slice(0, 80) : '';
                                const href = e.tagName === 'A' ? (e.getAttribute('href') || '').slice(0, 120) : '';
                                elements.push({
                                  id: 'e' + (idx++),
                                  role,
                                  tag: e.tagName.toLowerCase(),
                                  type: e.type || '',
                                  label,
                                  selector,
                                  x: cx,
                                  y: cy,
                                  w: Math.round(r.width),
                                  h: Math.round(r.height),
                                  value: val,
                                  href
                                });
                                if (elements.length >= 120) break;
                              }
                              const images = [];
                              let imgIdx = 1;
                              for (const im of document.querySelectorAll('img,canvas')) {
                                if (!visible(im)) continue;
                                const r = im.getBoundingClientRect();
                                if (r.width < 16 || r.height < 16) continue;
                                if (r.bottom < 0 || r.top > window.innerHeight * 2) continue;
                                const cx = Math.round(r.x + r.width / 2);
                                const cy = Math.round(r.y + r.height / 2);
                                const rawSrc = im.tagName === 'IMG' ? (im.currentSrc || im.src || '') : '';
                                const src = rawSrc.startsWith('data:') ? rawSrc.slice(0, 64) + '...' : rawSrc.slice(0, 200);
                                images.push({
                                  id: 'img' + (imgIdx++),
                                  tag: im.tagName.toLowerCase(),
                                  alt: (im.getAttribute('alt') || im.getAttribute('title') || im.getAttribute('aria-label') || '').trim().slice(0, 100),
                                  selector: buildSelector(im),
                                  x: cx,
                                  y: cy,
                                  w: Math.round(r.width),
                                  h: Math.round(r.height),
                                  src
                                });
                                if (images.length >= 40) break;
                              }
                              return {
                                viewport: {
                                  width: window.innerWidth,
                                  height: window.innerHeight,
                                  scroll_y: Math.round(window.scrollY),
                                  scroll_height: Math.round(document.documentElement.scrollHeight || document.body.scrollHeight || window.innerHeight)
                                },
                                elements,
                                images
                              };
                            })()'''
                            snap_data = curr_page.evaluate(rich_js)
                            if isinstance(snap_data, dict):
                                elements_info = snap_data.get("elements") or []
                                images_info = snap_data.get("images") or []
                                viewport_info = snap_data.get("viewport")
                                if elements_info:
                                    formatted_lines.append("Interactive Elements (use 'selector' or 'x','y' with browse_click / browse_type):")
                                    for el in elements_info:
                                        lbl = f' "{el["label"]}"' if el.get("label") else ""
                                        val_s = f' | value: "{el["value"]}"' if el.get("value") else ""
                                        href_s = f' | href: {el["href"]}' if el.get("href") else ""
                                        formatted_lines.append(
                                            f'  [{el["id"]}] {el["role"]} (<{el["tag"]}>){lbl} | selector: {el["selector"]} | center: (x: {el["x"]}, y: {el["y"]}, size: {el["w"]}x{el["h"]}){val_s}{href_s}'
                                        )
                                if images_info:
                                    formatted_lines.append("Visible Images / Canvas:")
                                    for im in images_info:
                                        alt_s = f' "{im["alt"]}"' if im.get("alt") else ""
                                        src_s = f' | src: {im["src"]}' if im.get("src") else ""
                                        formatted_lines.append(
                                            f'  [{im["id"]}] <{im["tag"]}>{alt_s} | selector: {im["selector"]} | center: (x: {im["x"]}, y: {im["y"]}, size: {im["w"]}x{im["h"]}){src_s}'
                                        )
                        except Exception as snap_err:
                            print(f"[Camoufox Snapshot Warning] Rich snapshot evaluation failed: {snap_err}", flush=True)
                        result_holder["payload"] = {
                            "status": "ok",
                            "url": curr_page.url,
                            "title": page_title,
                            "viewport": viewport_info,
                            "elements": elements_info,
                            "images": images_info,
                            "formatted_elements": "\n".join(formatted_lines),
                            "text": (text or "")[:25000]
                        }

                    elif endpoint == '/click':
                        selector = data.get('selector')
                        x = data.get('x')
                        y = data.get('y')
                        button = data.get('button', 'left')
                        click_count = int(data.get('click_count', 1))
                        action_timeout = int(data.get('timeout_ms') or data.get('timeout') or 8000)

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
                                box = loc.bounding_box(timeout=action_timeout)
                                if box and box.get('width', 0) > 0 and box.get('height', 0) > 0:
                                    target_x = box['x'] + box['width'] * random.uniform(0.25, 0.75)
                                    target_y = box['y'] + box['height'] * random.uniform(0.25, 0.75)
                                    human_mouse.click(curr_page, target_x, target_y, button=button, click_count=click_count)
                                else:
                                    curr_page.click(selector, timeout=action_timeout)
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

                    elif endpoint == '/move':
                        selector = data.get('selector')
                        x = data.get('x')
                        y = data.get('y')

                        if x is not None and y is not None:
                            try:
                                target_x = float(x)
                                target_y = float(y)
                                human_mouse.move(curr_page, target_x, target_y)
                                page_title = safe_get_title(curr_page)
                                result_holder["payload"] = {
                                    "status": "ok",
                                    "url": curr_page.url,
                                    "title": page_title,
                                    "moved_to": {"x": target_x, "y": target_y}
                                }
                            except Exception as e:
                                result_holder["http_status"] = 500
                                result_holder["payload"] = {"error": f"Mouse move failed: {str(e)}"}
                        elif selector:
                            try:
                                tx, ty = get_element_coords(curr_page, selector)
                                if tx is not None and ty is not None:
                                    human_mouse.move(curr_page, tx, ty)
                                else:
                                    curr_page.hover(selector, timeout=8000)
                                    tx, ty = human_mouse.last_x, human_mouse.last_y
                                page_title = safe_get_title(curr_page)
                                result_holder["payload"] = {
                                    "status": "ok",
                                    "url": curr_page.url,
                                    "title": page_title,
                                    "moved_to": {"x": tx, "y": ty, "selector": selector}
                                }
                            except Exception as e:
                                result_holder["http_status"] = 500
                                result_holder["payload"] = {"error": f"Move to selector failed: {str(e)}"}
                        else:
                            result_holder["http_status"] = 400
                            result_holder["payload"] = {"error": "Either 'selector' or ('x', 'y') coordinates are required"}

                    elif endpoint == '/drag_and_drop':
                        source_sel = data.get('source_selector') or data.get('source')
                        target_sel = data.get('target_selector') or data.get('target')
                        source_x = data.get('source_x') if data.get('source_x') is not None else data.get('from_x')
                        source_y = data.get('source_y') if data.get('source_y') is not None else data.get('from_y')
                        target_x = data.get('target_x') if data.get('target_x') is not None else data.get('to_x')
                        target_y = data.get('target_y') if data.get('target_y') is not None else data.get('to_y')
                        button = data.get('button', 'left')

                        start_x, start_y = None, None
                        end_x, end_y = None, None

                        if source_x is not None and source_y is not None:
                            start_x, start_y = float(source_x), float(source_y)
                        elif source_sel:
                            start_x, start_y = get_element_coords(curr_page, source_sel)

                        if target_x is not None and target_y is not None:
                            end_x, end_y = float(target_x), float(target_y)
                        elif target_sel:
                            end_x, end_y = get_element_coords(curr_page, target_sel)

                        if start_x is not None and start_y is not None and end_x is not None and end_y is not None:
                            try:
                                human_mouse.drag_and_drop(curr_page, start_x, start_y, end_x, end_y, button=button)
                                page_title = safe_get_title(curr_page)
                                result_holder["payload"] = {
                                    "status": "ok",
                                    "from": {"x": start_x, "y": start_y},
                                    "to": {"x": end_x, "y": end_y},
                                    "url": curr_page.url,
                                    "title": page_title
                                }
                            except Exception as e:
                                result_holder["http_status"] = 500
                                result_holder["payload"] = {"error": f"Human drag and drop failed: {str(e)}"}
                        elif source_sel and target_sel:
                            try:
                                curr_page.drag_and_drop(source_sel, target_sel, timeout=12000)
                                page_title = safe_get_title(curr_page)
                                result_holder["payload"] = {
                                    "status": "ok",
                                    "source": source_sel,
                                    "target": target_sel,
                                    "url": curr_page.url,
                                    "title": page_title
                                }
                            except Exception as e:
                                result_holder["http_status"] = 500
                                result_holder["payload"] = {"error": f"Playwright drag_and_drop failed: {str(e)}"}
                        else:
                            result_holder["http_status"] = 400
                            result_holder["payload"] = {"error": "Both source (selector or x,y) and target (selector or x,y) are required"}

                    elif endpoint == '/type':
                        selector = data.get('selector')
                        text_val = data.get('text', '')
                        action_timeout = int(data.get('timeout_ms') or data.get('timeout') or 8000)
                        if not selector:
                            result_holder["http_status"] = 400
                            result_holder["payload"] = {"error": "Parameter 'selector' is required"}
                        else:
                            if data.get('clear', True):
                                curr_page.fill(selector, "", timeout=action_timeout)
                            curr_page.type(selector, text_val, delay=int(data.get('delay', 20)), timeout=action_timeout)
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

                    elif endpoint == '/downloads' or endpoint == '/list_downloads':
                        d_dir = os.getenv("DOWNLOADS_DIR", "/data/downloads")
                        files_list = []
                        if os.path.exists(d_dir):
                            for fname in os.listdir(d_dir):
                                fpath = os.path.join(d_dir, fname)
                                if os.path.isfile(fpath):
                                    try:
                                        stat = os.stat(fpath)
                                        size_bytes = stat.st_size
                                        if size_bytes < 1024:
                                            size_fmt = f"{size_bytes} B"
                                        elif size_bytes < 1024 * 1024:
                                            size_fmt = f"{size_bytes / 1024:.1f} KB"
                                        else:
                                            size_fmt = f"{size_bytes / (1024 * 1024):.2f} MB"
                                        
                                        files_list.append({
                                            "name": fname,
                                            "size_bytes": size_bytes,
                                            "size": size_fmt,
                                            "modified_at": stat.st_mtime
                                        })
                                    except Exception:
                                        pass
                        files_list.sort(key=lambda x: x["modified_at"], reverse=True)
                        result_holder["payload"] = {
                            "status": "ok",
                            "downloads_dir": d_dir,
                            "count": len(files_list),
                            "files": files_list
                        }

                    elif endpoint == '/get_download':
                        filename = data.get('filename') or data.get('name')
                        if not filename:
                            result_holder["http_status"] = 400
                            result_holder["payload"] = {"error": "Parameter 'filename' is required"}
                        else:
                            clean_name = os.path.basename(filename.strip())
                            d_dir = os.getenv("DOWNLOADS_DIR", "/data/downloads")
                            fpath = os.path.join(d_dir, clean_name)
                            if not os.path.exists(fpath) or not os.path.isfile(fpath):
                                result_holder["http_status"] = 404
                                result_holder["payload"] = {"error": f"File '{clean_name}' not found in {d_dir}"}
                            else:
                                try:
                                    stat = os.stat(fpath)
                                    with open(fpath, "rb") as f:
                                        content_bytes = f.read()
                                    b64 = base64.b64encode(content_bytes).decode('utf-8')
                                    result_holder["payload"] = {
                                        "status": "ok",
                                        "filename": clean_name,
                                        "size_bytes": stat.st_size,
                                        "base64_data": b64
                                    }
                                except Exception as fe:
                                    result_holder["http_status"] = 500
                                    result_holder["payload"] = {"error": f"Failed to read file: {str(fe)}"}

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
                        full_page = bool(data.get('full_page') or data.get('fullPage') or False)
                        selector = data.get('selector')
                        if selector:
                            loc = curr_page.locator(selector).first
                            img_bytes = loc.screenshot(type="png", timeout=10000)
                        else:
                            img_bytes = curr_page.screenshot(type="png", full_page=full_page)
                        d_dir = os.getenv("DOWNLOADS_DIR", "/data/downloads")
                        os.makedirs(d_dir, exist_ok=True)
                        ts_ms = int(time.time() * 1000)
                        shot_filename = f"screenshot_{ts_ms}.png"
                        shot_path = os.path.join(d_dir, shot_filename)
                        latest_path = os.path.join(d_dir, "latest_screenshot.png")
                        try:
                            with open(shot_path, "wb") as sf:
                                sf.write(img_bytes)
                            with open(latest_path, "wb") as lf:
                                lf.write(img_bytes)
                            cleanup_old_screenshots(d_dir)
                        except Exception as se:
                            print(f"[Camoufox Screenshot Warning] Failed to save PNG to {d_dir}: {se}", flush=True)
                        b64 = base64.b64encode(img_bytes).decode('utf-8')
                        page_title = safe_get_title(curr_page)
                        result_holder["payload"] = {
                            "status": "ok",
                            "filename": shot_filename,
                            "screenshot_path": f"/screenshots/{shot_filename}",
                            "latest_path": "/screenshot.png",
                            "size_bytes": len(img_bytes),
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
                        if url_t and not url_t.startswith("http://") and not url_t.startswith("https://"):
                            url_t = "https://" + url_t
                        req_container = str(data.get('container') or '').strip()

                        if req_container:
                            ident, all_containers = resolve_container(req_container, profile_dir)
                            if not ident:
                                avail = [c.get("name") for c in all_containers]
                                result_holder["http_status"] = 400
                                result_holder["payload"] = {
                                    "error": f"Container '{req_container}' not found. Available containers: {', '.join(avail) if avail else '(none)'}. Use browse_create_container to create one.",
                                    "available_containers": all_containers
                                }
                                continue

                            pages_before = set(browser.pages)
                            new_p = None
                            bridge_open_res = None
                            proxies_snapshot = load_container_proxies(profile_dir)
                            try:
                                with browser.expect_page(timeout=15000) as p_info:
                                    bridge_open_res = call_container_bridge(
                                        "open_tab",
                                        {
                                            "cookieStoreId": ident["cookieStoreId"],
                                            "url": url_t,
                                            "proxies": proxies_snapshot,
                                        },
                                        timeout=10.0
                                    )
                                if bridge_open_res and bridge_open_res.get("ok"):
                                    cand = p_info.value
                                    new_pages = [p for p in browser.pages if p not in pages_before and not p.is_closed()]
                                    target_host = (urlparse(url_t).hostname or "").lower()
                                    matched = next((p for p in reversed(new_pages) if target_host and target_host in (p.url or "").lower()), None)
                                    new_p = matched or (new_pages[-1] if new_pages else cand)
                            except Exception as e_exp:
                                print(f"[Camoufox Container NewTab] expect_page notice: {e_exp}", flush=True)

                            if bridge_open_res and not bridge_open_res.get("ok"):
                                result_holder["http_status"] = 500
                                result_holder["payload"] = {
                                    "error": f"Failed to open tab in container '{ident['name']}': {bridge_open_res.get('error', 'unknown error')}"
                                }
                                continue

                            if not new_p:
                                for _ in range(15):
                                    candidates = [p for p in browser.pages if p not in pages_before and not p.is_closed()]
                                    if candidates:
                                        new_p = candidates[-1]
                                        break
                                    time.sleep(0.2)

                            if not new_p:
                                result_holder["http_status"] = 500
                                result_holder["payload"] = {
                                    "error": f"Opened tab in container '{ident['name']}', but Playwright could not attach to the new tab."
                                }
                                continue

                            page_containers[new_p] = ident["name"]
                            geo_js = build_geo_init_script(ident.get("geo"))
                            if geo_js:
                                try:
                                    new_p.add_init_script(geo_js)
                                except Exception:
                                    pass
                            active_pages = [p for p in browser.pages if not p.is_closed()]
                            active_tab_index = active_pages.index(new_p) if new_p in active_pages else len(active_pages) - 1
                            curr_page = active_pages[active_tab_index]
                            try:
                                curr_page.bring_to_front()
                            except Exception:
                                pass
                            try:
                                curr_page.wait_for_load_state("domcontentloaded", timeout=15000)
                            except Exception:
                                pass
                            if geo_js:
                                try:
                                    curr_page.evaluate(geo_js)
                                except Exception:
                                    pass
                            page_title = safe_get_title(curr_page)
                            status_cache["url"] = curr_page.url
                            status_cache["title"] = page_title
                            status_cache["tabs_count"] = len(active_pages)
                            if req_session_id:
                                session_tabs[req_session_id] = curr_page
                            page_last_touch[curr_page] = (req_session_id or req.client_id, time.time())
                            result_holder["payload"] = {
                                "status": "ok",
                                "tab_index": active_tab_index,
                                "session_id": req_session_id,
                                "container": ident["name"],
                                "cookieStoreId": ident["cookieStoreId"],
                                "proxy": ident.get("proxy"),
                                "url": curr_page.url,
                                "title": page_title
                            }
                            continue

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
                        raw_idx = data.get('index') if data.get('index') is not None else req_tab_index
                        if raw_idx is not None:
                            try:
                                target_idx = int(raw_idx)
                            except (ValueError, TypeError):
                                target_idx = active_tab_index
                        elif req_session_id and req_session_id in session_tabs and session_tabs[req_session_id] in active_pages:
                            target_idx = active_pages.index(session_tabs[req_session_id])
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
                        for cp in list(page_containers.keys()):
                            if cp not in active_pages:
                                del page_containers[cp]
                        ext_tabs = []
                        ext_res = call_container_bridge("list_tabs", timeout=3.0)
                        if ext_res.get("ok") and isinstance(ext_res.get("tabs"), list):
                            ext_tabs = ext_res["tabs"]
                        tabs_list = []
                        for idx, p in enumerate(active_pages):
                            owner_sid = next((sid for sid, sp in session_tabs.items() if sp == p), None)
                            c_name = page_containers.get(p)
                            c_store = None
                            if idx < len(ext_tabs) and ext_tabs[idx].get("url") == p.url:
                                c_store = ext_tabs[idx].get("cookieStoreId")
                                if ext_tabs[idx].get("container"):
                                    c_name = ext_tabs[idx]["container"]
                            else:
                                match_t = next((t for t in ext_tabs if t.get("url") == p.url), None)
                                if match_t:
                                    c_store = match_t.get("cookieStoreId")
                                    if match_t.get("container"):
                                        c_name = match_t["container"]
                            tabs_list.append({
                                "index": idx,
                                "url": p.url,
                                "title": safe_get_title(p),
                                "is_active": idx == active_tab_index,
                                "session_id": owner_sid,
                                "container": c_name,
                                "cookieStoreId": c_store
                            })
                        result_holder["payload"] = {"status": "ok", "tabs": tabs_list, "count": len(tabs_list)}

                    elif endpoint == '/containers':
                        containers = get_containers_list(profile_dir)
                        result_holder["payload"] = {"status": "ok", "containers": containers, "count": len(containers)}

                    elif endpoint == '/containers/create':
                        c_name = str(data.get('name') or '').strip()
                        c_color = str(data.get('color') or 'blue').strip().lower()
                        c_icon = str(data.get('icon') or 'fingerprint').strip().lower()
                        c_proxy_raw = data.get('proxy')
                        c_timezone = data.get('timezone')
                        c_locale = data.get('locale')
                        c_auto_geo = data.get('auto_geo', True)
                        c_lat = data.get('latitude') if data.get('latitude') is not None else data.get('lat')
                        c_lon = data.get('longitude') if data.get('longitude') is not None else data.get('lon')
                        c_data_saver = str(data.get('data_saver') or 'off').strip().lower()
                        if c_data_saver not in VALID_DATA_SAVER_MODES:
                            result_holder["http_status"] = 400
                            result_holder["payload"] = {"error": f"Invalid data_saver mode '{c_data_saver}'. Valid modes: {', '.join(sorted(VALID_DATA_SAVER_MODES))}."}
                            continue

                        if not c_name:
                            result_holder["http_status"] = 400
                            result_holder["payload"] = {"error": "Parameter 'name' is required."}
                        else:
                            parsed_proxy = None
                            if c_proxy_raw is not None and str(c_proxy_raw).strip():
                                try:
                                    parsed_proxy = parse_proxy_url(c_proxy_raw)
                                except ValueError as ve:
                                    result_holder["http_status"] = 400
                                    result_holder["payload"] = {"error": str(ve)}
                                    continue

                            if c_color not in VALID_CONTAINER_COLORS:
                                c_color = "blue"
                            if c_icon not in VALID_CONTAINER_ICONS:
                                c_icon = "fingerprint"

                            res_create = call_container_bridge(
                                "create_container",
                                {"name": c_name, "color": c_color, "icon": c_icon},
                                timeout=10.0
                            )
                            if not res_create.get("ok"):
                                result_holder["http_status"] = 409 if res_create.get("already_exists") else 500
                                result_holder["payload"] = {
                                    "error": res_create.get("error", "Failed to create container"),
                                    "container": res_create.get("container")
                                }
                            else:
                                created = dict(res_create["container"])
                                store_id = created.get("cookieStoreId")
                                try:
                                    geo_profile = detect_proxy_geo(
                                        parsed_proxy,
                                        explicit_timezone=c_timezone,
                                        explicit_locale=c_locale,
                                        auto_geo=bool(c_auto_geo),
                                        explicit_lat=c_lat,
                                        explicit_lon=c_lon,
                                    )
                                except ValueError as ve:
                                    result_holder["http_status"] = 400
                                    result_holder["payload"] = {"error": str(ve)}
                                    continue
                                if (parsed_proxy or geo_profile or c_data_saver != "off") and store_id:
                                    entry = dict(parsed_proxy) if parsed_proxy else {}
                                    if geo_profile:
                                        entry["geo"] = geo_profile
                                    if c_data_saver != "off":
                                        entry["data_saver"] = c_data_saver
                                    proxies = load_container_proxies(profile_dir)
                                    proxies[store_id] = entry
                                    save_container_proxies(proxies, profile_dir)
                                    call_container_bridge("sync_proxies", {"proxies": proxies}, timeout=5.0)
                                    created["proxy"] = mask_proxy_config(parsed_proxy)
                                    created["geo"] = geo_profile
                                    created["data_saver"] = c_data_saver
                                else:
                                    created["proxy"] = None
                                    created["geo"] = None
                                    created["data_saver"] = "off"
                                result_holder["payload"] = {"status": "ok", "container": created}

                    elif endpoint == '/containers/proxy':
                        c_query = str(data.get('container') or data.get('name') or '').strip()
                        c_proxy_provided = 'proxy' in data
                        c_proxy_raw = data.get('proxy')
                        c_timezone = data.get('timezone')
                        c_locale = data.get('locale')
                        c_auto_geo = data.get('auto_geo', True)
                        c_lat = data.get('latitude') if data.get('latitude') is not None else data.get('lat')
                        c_lon = data.get('longitude') if data.get('longitude') is not None else data.get('lon')
                        c_data_saver_raw = data.get('data_saver')
                        if c_data_saver_raw is not None:
                            c_data_saver = str(c_data_saver_raw).strip().lower()
                            if c_data_saver not in VALID_DATA_SAVER_MODES:
                                result_holder["http_status"] = 400
                                result_holder["payload"] = {"error": f"Invalid data_saver mode '{c_data_saver}'. Valid modes: {', '.join(sorted(VALID_DATA_SAVER_MODES))}."}
                                continue
                        else:
                            c_data_saver = None

                        if not c_query:
                            result_holder["http_status"] = 400
                            result_holder["payload"] = {"error": "Parameter 'container' is required."}
                        else:
                            ident, all_containers = resolve_container(c_query, profile_dir)
                            if not ident:
                                avail = [c.get("name") for c in all_containers]
                                result_holder["http_status"] = 400
                                result_holder["payload"] = {
                                    "error": f"Container '{c_query}' not found. Available containers: {', '.join(avail) if avail else '(none)'}.",
                                    "available_containers": all_containers
                                }
                            else:
                                store_id = ident["cookieStoreId"]
                                proxies = load_container_proxies(profile_dir)
                                existing_entry = dict(proxies.get(store_id) or {})

                                if c_proxy_provided:
                                    if c_proxy_raw is None or not str(c_proxy_raw).strip():
                                        for k in ("type", "host", "port", "username", "password", "proxyDNS", "geo"):
                                            existing_entry.pop(k, None)
                                        parsed_proxy = None
                                    else:
                                        try:
                                            parsed_proxy = parse_proxy_url(c_proxy_raw)
                                        except ValueError as ve:
                                            result_holder["http_status"] = 400
                                            result_holder["payload"] = {"error": str(ve)}
                                            continue
                                        for k in ("type", "host", "port", "username", "password", "proxyDNS"):
                                            existing_entry.pop(k, None)
                                        existing_entry.update(parsed_proxy)
                                else:
                                    parsed_proxy = existing_entry if existing_entry.get("host") else None

                                if c_proxy_provided or c_timezone or c_locale or (c_lat is not None and c_lon is not None):
                                    try:
                                        geo_profile = detect_proxy_geo(
                                            parsed_proxy,
                                            explicit_timezone=c_timezone,
                                            explicit_locale=c_locale,
                                            auto_geo=bool(c_auto_geo),
                                            explicit_lat=c_lat,
                                            explicit_lon=c_lon,
                                        )
                                    except ValueError as ve:
                                        result_holder["http_status"] = 400
                                        result_holder["payload"] = {"error": str(ve)}
                                        continue
                                    if geo_profile:
                                        if not c_proxy_provided and isinstance(existing_entry.get("geo"), dict):
                                            merged_geo = dict(existing_entry["geo"])
                                            merged_geo.update(geo_profile)
                                            existing_entry["geo"] = merged_geo
                                        else:
                                            existing_entry["geo"] = geo_profile
                                    elif c_proxy_provided and not parsed_proxy:
                                        existing_entry.pop("geo", None)

                                if c_data_saver is not None:
                                    if c_data_saver == "off":
                                        existing_entry.pop("data_saver", None)
                                    else:
                                        existing_entry["data_saver"] = c_data_saver

                                if not existing_entry:
                                    proxies.pop(store_id, None)
                                else:
                                    proxies[store_id] = existing_entry
                                save_container_proxies(proxies, profile_dir)
                                call_container_bridge("sync_proxies", {"proxies": proxies}, timeout=5.0)

                                masked = mask_proxy_config(existing_entry if existing_entry.get("host") else None)
                                eff_geo = existing_entry.get("geo")
                                eff_ds = existing_entry.get("data_saver") or "off"
                                geo_desc = ""
                                if eff_geo:
                                    parts = [x for x in [eff_geo.get("country"), eff_geo.get("timezone"), eff_geo.get("locale")] if x]
                                    if parts:
                                        geo_desc = f" | Geo: {', '.join(parts)}"
                                ds_desc = f" | Data saver: {eff_ds}" if eff_ds != "off" else ""
                                result_holder["payload"] = {
                                    "status": "ok",
                                    "container": ident["name"],
                                    "cookieStoreId": store_id,
                                    "proxy": masked,
                                    "geo": eff_geo,
                                    "data_saver": eff_ds,
                                    "message": f"Container '{ident['name']}' updated — Proxy: {masked or 'default'}{geo_desc}{ds_desc}."
                                }

                    elif endpoint == '/containers/delete':
                        c_query = str(data.get('container') or data.get('name') or '').strip()
                        if not c_query:
                            result_holder["http_status"] = 400
                            result_holder["payload"] = {"error": "Parameter 'container' is required."}
                        else:
                            ident, all_containers = resolve_container(c_query, profile_dir)
                            if not ident:
                                avail = [c.get("name") for c in all_containers]
                                result_holder["http_status"] = 400
                                result_holder["payload"] = {
                                    "error": f"Container '{c_query}' not found. Available containers: {', '.join(avail) if avail else '(none)'}.",
                                    "available_containers": all_containers
                                }
                            else:
                                store_id = ident["cookieStoreId"]
                                res_del = call_container_bridge(
                                    "delete_container",
                                    {"cookieStoreId": store_id},
                                    timeout=10.0
                                )
                                if not res_del.get("ok"):
                                    result_holder["http_status"] = 500
                                    result_holder["payload"] = {
                                        "error": res_del.get("error", f"Failed to delete container '{ident['name']}'")
                                    }
                                else:
                                    proxies = load_container_proxies(profile_dir)
                                    if store_id in proxies:
                                        proxies.pop(store_id, None)
                                        save_container_proxies(proxies, profile_dir)
                                        call_container_bridge("sync_proxies", {"proxies": proxies}, timeout=5.0)
                                    for cp, cname in list(page_containers.items()):
                                        if cname == ident["name"]:
                                            del page_containers[cp]
                                    result_holder["payload"] = {
                                        "status": "ok",
                                        "deleted_container": ident["name"],
                                        "cookieStoreId": store_id,
                                        "message": f"Container '{ident['name']}' ({store_id}) deleted."
                                    }

                    elif endpoint == '/wait':
                        selector = data.get('selector')
                        text_wait = data.get('text')
                        state = str(data.get('state') or 'visible').strip().lower()
                        timeout_ms = int(data.get('timeout_ms') or data.get('timeout') or 15000)
                        if selector:
                            if state not in ('visible', 'attached', 'hidden', 'detached'):
                                state = 'visible'
                            curr_page.locator(selector).first.wait_for(state=state, timeout=timeout_ms)
                            result_holder["payload"] = {"status": "ok", "waited_for": f"selector:{selector}", "state": state, "url": curr_page.url}
                        elif text_wait:
                            curr_page.get_by_text(str(text_wait), exact=False).first.wait_for(state='visible', timeout=timeout_ms)
                            result_holder["payload"] = {"status": "ok", "waited_for": f"text:{text_wait}", "url": curr_page.url}
                        else:
                            load_state = str(data.get('load_state') or 'networkidle').strip().lower()
                            if load_state not in ('load', 'domcontentloaded', 'networkidle'):
                                load_state = 'networkidle'
                            curr_page.wait_for_load_state(load_state, timeout=timeout_ms)
                            result_holder["payload"] = {"status": "ok", "waited_for": f"load_state:{load_state}", "url": curr_page.url}

                    elif endpoint == '/select':
                        selector = data.get('selector')
                        if not selector:
                            result_holder["http_status"] = 400
                            result_holder["payload"] = {"error": "Parameter 'selector' is required."}
                        else:
                            loc = curr_page.locator(selector).first
                            if data.get('value') is not None:
                                selected = loc.select_option(value=str(data['value']))
                            elif data.get('label') is not None:
                                selected = loc.select_option(label=str(data['label']))
                            elif data.get('index') is not None:
                                selected = loc.select_option(index=int(data['index']))
                            else:
                                result_holder["http_status"] = 400
                                result_holder["payload"] = {"error": "One of 'value', 'label', or 'index' is required."}
                                continue
                            result_holder["payload"] = {"status": "ok", "selector": selector, "selected": selected}

                    elif endpoint == '/cookies':
                        c_action = str(data.get('action') or 'get').strip().lower()
                        c_container = str(data.get('container') or '').strip()
                        store_id = "firefox-default"
                        c_name_out = "default"
                        if c_container:
                            ident, all_containers = resolve_container(c_container, profile_dir)
                            if not ident:
                                avail = [c.get("name") for c in all_containers]
                                result_holder["http_status"] = 400
                                result_holder["payload"] = {
                                    "error": f"Container '{c_container}' not found. Available containers: {', '.join(avail) if avail else '(none)'}.",
                                    "available_containers": all_containers
                                }
                                continue
                            store_id = ident["cookieStoreId"]
                            c_name_out = ident["name"]

                        if c_action == 'get':
                            res_ck = call_container_bridge("get_cookies", {
                                "cookieStoreId": store_id,
                                "domain": data.get("domain"),
                                "url": data.get("url"),
                            }, timeout=10.0)
                        elif c_action == 'set':
                            res_ck = call_container_bridge("set_cookie", {
                                "cookieStoreId": store_id,
                                "url": data.get("url"),
                                "name": data.get("name"),
                                "value": data.get("value"),
                                "domain": data.get("domain"),
                                "path": data.get("path"),
                                "secure": data.get("secure"),
                                "httpOnly": data.get("httpOnly"),
                                "expirationDate": data.get("expirationDate"),
                            }, timeout=10.0)
                        elif c_action == 'clear':
                            res_ck = call_container_bridge("clear_cookies", {
                                "cookieStoreId": store_id,
                                "domain": data.get("domain"),
                                "url": data.get("url"),
                            }, timeout=10.0)
                        else:
                            result_holder["http_status"] = 400
                            result_holder["payload"] = {"error": f"Invalid cookies action '{c_action}'. Use 'get', 'set', or 'clear'."}
                            continue

                        if not res_ck.get("ok"):
                            result_holder["http_status"] = 500
                            result_holder["payload"] = {"error": res_ck.get("error", "Cookie operation failed")}
                        else:
                            res_ck["status"] = "ok"
                            res_ck["container"] = c_name_out
                            result_holder["payload"] = res_ck

                    elif endpoint == '/switch_tab':
                        raw_sw = data.get('index') if data.get('index') is not None else req_tab_index
                        idx = int(raw_sw or 0)
                        active_pages = [p for p in browser.pages if not p.is_closed()]
                        if 0 <= idx < len(active_pages):
                            active_tab_index = idx
                            p = active_pages[idx]
                            if req_session_id:
                                session_tabs[req_session_id] = p
                            p.bring_to_front()
                            page_title = safe_get_title(p)
                            status_cache["url"] = p.url
                            status_cache["title"] = page_title
                            result_holder["payload"] = {
                                "status": "ok",
                                "active_index": idx,
                                "tab_index": idx,
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

                    # Update session_tabs and page_last_touch after command execution
                    active_pages_after = [p for p in browser.pages if not p.is_closed()]
                    if curr_page and not curr_page.is_closed() and curr_page in active_pages_after:
                        active_tab_index = active_pages_after.index(curr_page)
                        if req_session_id and endpoint != '/close_tab':
                            session_tabs[req_session_id] = curr_page
                        if endpoint not in ('/tabs', '/downloads', '/list_downloads', '/get_download'):
                            page_last_touch[curr_page] = (req_session_id or req.client_id, time.time())
                    elif req_session_id and endpoint == '/close_tab':
                        session_tabs.pop(req_session_id, None)

                    payload_obj = result_holder.get("payload")
                    if isinstance(payload_obj, dict) and "error" not in payload_obj:
                        payload_obj.setdefault("tab_index", active_tab_index)
                        if req_session_id:
                            payload_obj.setdefault("session_id", req_session_id)

                except Exception as ex:
                    result_holder["http_status"] = 500
                    result_holder["payload"] = {"error": str(ex)}

                finally:
                    req.finished_at = time.time()
                    exec_dur = req.finished_at - req.started_at if req.started_at else 0.0
                    print(f"[Camoufox Lock] 🔓 Lock released by '{req.client_id}' for '{req.endpoint}' (duration: {exec_dur:.2f}s)", flush=True)
                    status_cache["is_busy"] = False
                    status_cache["active_client"] = None
                    status_cache["active_command"] = None
                    status_cache["queue_length"] = command_queue.qsize()
                    req.done_event.set()

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
