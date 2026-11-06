"use strict";
// Light by day, dark by night: follows sunrise/sunset at the feeder (lat/lon on <html data-lat data-lon>).
// The ☀/🌙 button cycles Auto → Light → Dark; the choice is kept per device (default: the Settings page).
(function () {
  const root = document.documentElement;
  const lat = parseFloat(root.dataset.lat || "45.42"), lon = parseFloat(root.dataset.lon || "-75.70");
  const KEY = "wbs.theme";
  const fallback = root.dataset.themeDefault || "auto";   // from the Settings page
  const get = () => { try { return localStorage.getItem(KEY) || fallback; } catch (e) { return fallback; } };
  const set = (v) => { try { localStorage.setItem(KEY, v); } catch (e) { /* private mode */ } };

  // Sunrise equation (NOAA/Wikipedia simplified; within a couple of minutes). Returns ms times or null.
  function sunTimes(day, latDeg, lonDeg) {
    const rad = Math.PI / 180, lw = -lonDeg;
    const noon = new Date(day.getFullYear(), day.getMonth(), day.getDate(), 12).getTime();
    const jd = noon / 86400000 + 2440587.5;
    const n = Math.round(jd - 2451545.0009 - lw / 360);
    const jStar = 2451545.0009 + lw / 360 + n;
    const M = (357.5291 + 0.98560028 * (jStar - 2451545)) % 360;
    const C = 1.9148 * Math.sin(M * rad) + 0.02 * Math.sin(2 * M * rad) + 0.0003 * Math.sin(3 * M * rad);
    const L = (M + C + 180 + 102.9372) % 360;
    const jTransit = jStar + 0.0053 * Math.sin(M * rad) - 0.0069 * Math.sin(2 * L * rad);
    const dec = Math.asin(Math.sin(L * rad) * Math.sin(23.4397 * rad));
    const cosW = (Math.sin(-0.833 * rad) - Math.sin(latDeg * rad) * Math.sin(dec)) / (Math.cos(latDeg * rad) * Math.cos(dec));
    if (cosW > 1) return { rise: null, set: null, polar: "night" };
    if (cosW < -1) return { rise: null, set: null, polar: "day" };
    const w = Math.acos(cosW) / rad;
    const toMs = (j) => (j - 2440587.5) * 86400000;
    return { rise: toMs(jTransit - w / 360), set: toMs(jTransit + w / 360) };
  }

  function sunIsUp(now) {
    const t = sunTimes(now, lat, lon);
    if (t.polar) return t.polar === "day";
    return now.getTime() >= t.rise && now.getTime() < t.set;
  }

  function apply() {
    const mode = get();
    const dark = mode === "dark" || (mode === "auto" && !sunIsUp(new Date()));
    root.dataset.theme = dark ? "dark" : "light";
    const b = document.getElementById("theme-toggle");
    if (b) {
      const t = sunTimes(new Date(), lat, lon);
      const hm = (ms) => ms ? new Date(ms).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "-";
      b.textContent = mode === "auto" ? (dark ? "🌙" : "☀️") : mode === "dark" ? "🌙•" : "☀️•";
      b.title = (mode === "auto" ? `Auto: light ${hm(t.rise)} – ${hm(t.set)} (sunrise to sunset)` :
                 `Always ${mode}`) + ". Click to change.";
    }
  }

  apply();   // runs in <head>, before the page paints: no flash
  document.addEventListener("DOMContentLoaded", () => {
    const b = document.getElementById("theme-toggle");
    if (b) b.addEventListener("click", () => {
      const order = ["auto", "light", "dark"];
      set(order[(order.indexOf(get()) + 1) % order.length]);
      apply();
    });
    apply();
  });
  setInterval(apply, 60000);
  window.wbsSunTimes = sunTimes;   // for tests
})();
