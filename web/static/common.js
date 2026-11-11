// Utility condivise da tutte le pagine.

async function api(method, url, data) {
  const opts = { method, credentials: "same-origin", headers: {} };
  if (data !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(data);
  }
  let res;
  try {
    res = await fetch(url, opts);
  } catch (e) {
    throw Object.assign(new Error("Connessione assente. Riprova."), { status: 0 });
  }
  let json = {};
  try { json = await res.json(); } catch (e) { /* risposta vuota */ }
  if (!res.ok || json.ok === false) {
    throw Object.assign(new Error(json.error || "Errore imprevisto."), { status: res.status });
  }
  return json;
}

function $(sel, root = document) { return root.querySelector(sel); }

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "html") el.innerHTML = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return el;
}

// Come el.append(), ma ignora null/false (utile per elementi condizionali).
function add(el, ...children) {
  el.append(...children.flat().filter(c => c !== null && c !== undefined && c !== false));
  return el;
}

let toastTimer;
function toast(msg, kind = "") {
  let el = $(".toast");
  if (!el) { el = h("div", { class: "toast" }); document.body.append(el); }
  el.textContent = msg;
  el.className = "toast show " + kind;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 3200);
}

function fmtDate(epochSec) {
  if (!epochSec) return "";
  return new Date(epochSec * 1000).toLocaleString("it-IT", {
    weekday: "short", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit",
  });
}

function countdown(epochSec) {
  const ms = epochSec * 1000 - Date.now();
  if (ms <= 0) return "scaduto";
  const d = Math.floor(ms / 86400000);
  const hh = Math.floor((ms % 86400000) / 3600000);
  const mm = Math.floor((ms % 3600000) / 60000);
  if (d > 0) return `${d}g ${hh}h`;
  if (hh > 0) return `${hh}h ${mm}m`;
  return `${mm}m`;
}

// Conto alla rovescia "a orologio": 3g 04:12:09 (secondsLeft > 0).
function countdownClock(secondsLeft) {
  const t = Math.floor(secondsLeft);
  const d = Math.floor(t / 86400);
  const pad = (n) => String(n).padStart(2, "0");
  const hms = `${pad(Math.floor(t % 86400 / 3600))}:${pad(Math.floor(t % 3600 / 60))}:${pad(t % 60)}`;
  return d > 0 ? `${d}g ${hms}` : hms;
}

function letItSnow(count = 40) {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const box = h("div", { class: "snow", "aria-hidden": "true" });
  const glyphs = ["❄", "❅", "❆", "•"];
  for (let i = 0; i < count; i++) {
    const f = h("span", { class: "flake" }, glyphs[i % glyphs.length]);
    f.style.left = Math.random() * 100 + "vw";
    f.style.fontSize = 8 + Math.random() * 14 + "px";
    f.style.animationDuration = 8 + Math.random() * 14 + "s";
    f.style.animationDelay = -Math.random() * 20 + "s";
    f.style.opacity = 0.3 + Math.random() * 0.6;
    f.style.setProperty("--drift", (Math.random() * 80 - 40) + "px");
    box.append(f);
  }
  document.body.prepend(box);
}

document.addEventListener("DOMContentLoaded", () => letItSnow());
