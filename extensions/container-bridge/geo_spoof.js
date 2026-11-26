/**
 * Camoufox Container Geo Spoof (Content Script, run_at: document_start)
 *
 * Applies per-container timezone, locale and geolocation overrides when the
 * active container has a custom proxy/geo profile configured.
 */
(function () {
  function injectGeoOverride(geo) {
    if (!geo || (!geo.timezone && !geo.locale && geo.lat === undefined)) {
      return;
    }
    const payload = JSON.stringify({
      timezone: geo.timezone || null,
      locale: geo.locale || null,
      languages: geo.languages || (geo.locale ? [geo.locale, geo.locale.split("-")[0]] : null),
      lat: typeof geo.lat === "number" ? geo.lat : null,
      lon: typeof geo.lon === "number" ? geo.lon : null,
    });

    const script = document.createElement("script");
    script.textContent = `(() => {
      try {
        if (window.__camoufoxGeoApplied) return;
        window.__camoufoxGeoApplied = true;
        const cfg = ${payload};

        if (cfg.locale) {
          Object.defineProperty(Navigator.prototype, "language", {
            get: () => cfg.locale,
            configurable: true
          });
        }
        if (Array.isArray(cfg.languages) && cfg.languages.length > 0) {
          const langs = Object.freeze([...cfg.languages]);
          Object.defineProperty(Navigator.prototype, "languages", {
            get: () => langs,
            configurable: true
          });
        }

        if (cfg.timezone) {
          const tz = cfg.timezone;
          const OrigDTF = Intl.DateTimeFormat;
          const PatchedDTF = function DateTimeFormat(locales, options) {
            const opts = Object.assign({}, options || {});
            if (!opts.timeZone) opts.timeZone = tz;
            const loc = locales !== undefined ? locales : (cfg.locale || undefined);
            return new OrigDTF(loc, opts);
          };
          PatchedDTF.prototype = OrigDTF.prototype;
          PatchedDTF.supportedLocalesOf = OrigDTF.supportedLocalesOf.bind(OrigDTF);
          Intl.DateTimeFormat = PatchedDTF;

          const origResolved = OrigDTF.prototype.resolvedOptions;
          OrigDTF.prototype.resolvedOptions = function () {
            const res = origResolved.call(this);
            if (!res.timeZone) res.timeZone = tz;
            return res;
          };

          const computeOffsetMinutes = (date) => {
            try {
              const parts = new OrigDTF("en-US", {
                timeZone: tz,
                year: "numeric", month: "2-digit", day: "2-digit",
                hour: "2-digit", minute: "2-digit", second: "2-digit",
                hour12: false
              }).formatToParts(date);
              const map = {};
              for (const p of parts) map[p.type] = p.value;
              const h = map.hour === "24" ? "00" : map.hour;
              const asUtc = Date.UTC(
                Number(map.year), Number(map.month) - 1, Number(map.day),
                Number(h), Number(map.minute), Number(map.second)
              );
              return Math.round((date.getTime() - asUtc) / 60000);
            } catch (_) {
              return 0;
            }
          };

          Date.prototype.getTimezoneOffset = function () {
            return computeOffsetMinutes(this);
          };
        }

        if (typeof cfg.lat === "number" && typeof cfg.lon === "number" && navigator.geolocation) {
          const mockPos = () => ({
            coords: {
              latitude: cfg.lat,
              longitude: cfg.lon,
              accuracy: 35,
              altitude: null,
              altitudeAccuracy: null,
              heading: null,
              speed: null
            },
            timestamp: Date.now()
          });
          navigator.geolocation.getCurrentPosition = (success) => {
            if (typeof success === "function") setTimeout(() => success(mockPos()), 10);
          };
          navigator.geolocation.watchPosition = (success) => {
            if (typeof success === "function") setTimeout(() => success(mockPos()), 10);
            return 1;
          };
        }
      } catch (_) {}
    })();`;
    (document.documentElement || document.head || document).appendChild(script);
    script.remove();
  }

  try {
    browser.runtime.sendMessage({ type: "get_tab_geo" }).then((resp) => {
      if (resp && resp.geo) {
        injectGeoOverride(resp.geo);
      }
    }).catch(() => {});
  } catch (_) {}
})();
