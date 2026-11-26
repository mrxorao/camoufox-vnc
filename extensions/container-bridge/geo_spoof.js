/**
 * Camoufox Container Geo Spoof (Content Script, run_at: document_start)
 *
 * Uses Firefox's native window.wrappedJSObject / exportFunction (immune to page CSP)
 * to apply per-container timezone, locale and geolocation overrides.
 */
(function () {
  function applyGeoToPage(geo) {
    if (!geo || (!geo.timezone && !geo.locale && geo.lat === undefined)) {
      return;
    }
    const pageWin = window.wrappedJSObject || window;
    try {
      if (pageWin.__camoufoxGeoApplied) return;
      pageWin.__camoufoxGeoApplied = true;

      if (geo.locale) {
        const loc = String(geo.locale);
        const navProto = pageWin.Navigator && pageWin.Navigator.prototype;
        if (navProto) {
          pageWin.Object.defineProperty(navProto, "language", cloneInto({
            get: exportFunction(() => loc, pageWin),
            configurable: true,
          }, pageWin, { cloneFunctions: true }));
        }
      }

      const langsArr = Array.isArray(geo.languages) && geo.languages.length > 0
        ? geo.languages
        : (geo.locale ? [geo.locale, geo.locale.split("-")[0]] : null);
      if (langsArr) {
        const clonedLangs = cloneInto(langsArr, pageWin);
        const navProto = pageWin.Navigator && pageWin.Navigator.prototype;
        if (navProto) {
          pageWin.Object.defineProperty(navProto, "languages", cloneInto({
            get: exportFunction(() => clonedLangs, pageWin),
            configurable: true,
          }, pageWin, { cloneFunctions: true }));
        }
      }

      if (geo.timezone) {
        const tz = String(geo.timezone);
        const loc = geo.locale ? String(geo.locale) : undefined;
        const OrigDTF = pageWin.Intl.DateTimeFormat;

        const PatchedDTF = exportFunction(function DateTimeFormat(locales, options) {
          const opts = options ? Object.assign({}, options) : {};
          if (!opts.timeZone) opts.timeZone = tz;
          const effLoc = locales !== undefined ? locales : loc;
          return new OrigDTF(effLoc, cloneInto(opts, pageWin));
        }, pageWin);

        PatchedDTF.prototype = OrigDTF.prototype;
        pageWin.Intl.DateTimeFormat = PatchedDTF;

        const origResolved = OrigDTF.prototype.resolvedOptions;
        OrigDTF.prototype.resolvedOptions = exportFunction(function () {
          const res = origResolved.call(this);
          if (res && !res.timeZone) {
            res.timeZone = tz;
          }
          return res;
        }, pageWin);

        const getOffsetFn = exportFunction(function () {
          try {
            const parts = new Intl.DateTimeFormat("en-US", {
              timeZone: tz,
              year: "numeric", month: "2-digit", day: "2-digit",
              hour: "2-digit", minute: "2-digit", second: "2-digit",
              hour12: false,
            }).formatToParts(new Date(this.getTime()));
            const map = {};
            for (const p of parts) map[p.type] = p.value;
            const h = map.hour === "24" ? "00" : map.hour;
            const asUtc = Date.UTC(
              Number(map.year), Number(map.month) - 1, Number(map.day),
              Number(h), Number(map.minute), Number(map.second)
            );
            return Math.round((this.getTime() - asUtc) / 60000);
          } catch (_) {
            return 0;
          }
        }, pageWin);

        pageWin.Date.prototype.getTimezoneOffset = getOffsetFn;
      }

      if (typeof geo.lat === "number" && typeof geo.lon === "number" && pageWin.navigator && pageWin.navigator.geolocation) {
        const lat = geo.lat;
        const lon = geo.lon;
        const makePos = () => cloneInto({
          coords: {
            latitude: lat,
            longitude: lon,
            accuracy: 35,
            altitude: null,
            altitudeAccuracy: null,
            heading: null,
            speed: null,
          },
          timestamp: Date.now(),
        }, pageWin);

        pageWin.navigator.geolocation.getCurrentPosition = exportFunction((success) => {
          if (typeof success === "function") {
            setTimeout(() => success(makePos()), 10);
          }
        }, pageWin);
        pageWin.navigator.geolocation.watchPosition = exportFunction((success) => {
          if (typeof success === "function") {
            setTimeout(() => success(makePos()), 10);
          }
          return 1;
        }, pageWin);
      }
    } catch (_) {}
  }

  try {
    browser.runtime.sendMessage({ type: "get_tab_geo" }).then((resp) => {
      if (resp && resp.geo) {
        applyGeoToPage(resp.geo);
      }
    }).catch(() => {});
  } catch (_) {}
})();
