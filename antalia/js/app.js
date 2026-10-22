// Page logic: UI, language and theme, playback, and the live readout. The model runs in js/worker.js.
// URL options for measuring: ?backend=webgpu|wasm  &threads=N  &precision=mixed|fp32|fp16|int8
import { STRINGS, EXAMPLES } from "./strings.js";

const $ = (s) => document.querySelector(s);
const params = new URLSearchParams(location.search);
const OPTS = {
  backend: params.get("backend") || "wasm",
  threads: Number(params.get("threads") || 0),
  precision: params.get("precision") || "mixed",
};
const SAMPLE_RATE = 48000;

// ------------------------------------------------------------------ language
let lang = "tr";
try { if (localStorage.getItem("am-lang") === "en") lang = "en"; } catch (e) {}
const t = (k) => STRINGS[lang][k] ?? STRINGS.tr[k] ?? k;
function applyLang() {
  document.documentElement.lang = lang;
  for (const el of document.querySelectorAll("[data-i18n]")) el.textContent = t(el.dataset.i18n);
  for (const el of document.querySelectorAll("[data-i18n-aria]")) el.setAttribute("aria-label", t(el.dataset.i18nAria));
  $("#lang").textContent = lang === "tr" ? "EN" : "TR";
  $("#lang").setAttribute("aria-label", lang === "tr" ? "Switch to English" : "Türkçeye geç");
  document.title = "Antalia-2 Mini";
  renderPlay();
  renderStatus();
  renderSpeed();
  renderTheme();
}
$("#lang").addEventListener("click", () => {
  lang = lang === "tr" ? "en" : "tr";
  try { localStorage.setItem("am-lang", lang); } catch (e) {}
  applyLang();
});

// ------------------------------------------------------------------ theme
function isDark() {
  const d = document.documentElement.dataset.theme;
  return d ? d === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
}
function renderTheme() { $("#theme").setAttribute("aria-label", t(isDark() ? "themeLight" : "themeDark")); }
matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => renderTheme());
$("#theme").addEventListener("click", () => {
  const next = isDark() ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("am-theme", next); } catch (e) {}
  renderTheme();
});

// ------------------------------------------------------------------ number formatting
const fmt = (x, d = 0) => new Intl.NumberFormat(lang === "tr" ? "tr-TR" : "en-US", { minimumFractionDigits: d, maximumFractionDigits: d }).format(x);
const mb = (b) => fmt(b / 1e6, 1);

// ------------------------------------------------------------------ worker
const worker = new Worker(new URL("./worker.js", import.meta.url), { type: "module" });
let ready = false, info = null, loadState = { loaded: 0, total: 0 }, errorMsg = "";
let current = null; // the utterance being generated / played
let pending = null; // a request made before the model was ready
let lastStats = null;

worker.onmessage = (ev) => {
  const m = ev.data;
  if (m.type === "progress") {
    loadState = m;
    $("#progress span").style.width = m.total ? `${Math.min(100, (100 * m.loaded) / m.total)}%` : "0";
    renderPlay();
  } else if (m.type === "ready") {
    ready = true; info = m.info;
    $("#progress").dataset.done = "";
    window.amInfo = info;
    applyDefaults(info.defaults);
    console.info("[antalia-mini] ready", info);
    renderPlay(); renderStatus();
    if (pending) { const p = pending; pending = null; speak({ ...p, t0: performance.now() }); }
  } else if (m.type === "error") {
    errorMsg = m.message;
    console.error("[antalia-mini]", m.message);
    if (current && m.id === current.id) finish();
    renderStatus(); renderPlay();
  } else if (current && m.id === current.id) {
    if (m.type === "text") $("#model-text").textContent = m.modelText;
    else if (m.type === "chunk") onChunk(m);
    else if (m.type === "done") onDone(m.stats);
  }
};

function startLoading() {
  if (startLoading.started) return;
  startLoading.started = true;
  worker.postMessage({ type: "init", ...OPTS });
  renderPlay();
}

// ------------------------------------------------------------------ playback
let ctx = null, sources = [], nextTime = 0;
function audioContext() {
  if (!ctx) {
    try { ctx = new AudioContext({ sampleRate: SAMPLE_RATE, latencyHint: "interactive" }); }
    catch (e) { ctx = new AudioContext(); }
  }
  if (ctx.state === "suspended") ctx.resume();
  return ctx;
}

let nextId = 1;
function speak(req) {
  if (!ready) { pending = req; renderPlay(); return; }
  stop();
  errorMsg = "";
  current = { id: nextId++, t0: req.t0, chunks: [], firstMs: null, playing: true };
  for (const k of ["#r-ttfa", "#r-gen", "#r-len", "#r-rtf"]) $(k).textContent = "–";
  renderPlay();
  worker.postMessage({ type: "synth", id: current.id, text: req.text, steps: req.steps, speed: req.speed, seed: 0 });
}

function onChunk(m) {
  const c = audioContext();
  const audio = m.audio;
  current.chunks.push(audio);
  if (current.firstMs === null) {
    current.firstMs = performance.now() - current.t0;
    nextTime = c.currentTime + 0.01;
    $("#r-ttfa").textContent = fmt(current.firstMs);
  }
  const buf = c.createBuffer(1, audio.length, SAMPLE_RATE);
  buf.copyToChannel(audio, 0);
  const src = c.createBufferSource();
  src.buffer = buf;
  src.connect(c.destination);
  const at = Math.max(nextTime, c.currentTime + 0.005);
  src.start(at);
  nextTime = at + buf.duration; // each chunk already ends with the pause before the next (as Antalia.stream)
  sources.push(src);
  const u = current;
  src.onended = () => {
    u.ended = (u.ended || 0) + 1;
    if (current === u && u.done && u.ended === u.chunks.length) finish();
  };
}

function onDone(stats) {
  current.done = true;
  current.stats = stats;
  lastStats = { ...stats, firstMs: current.firstMs };
  window.amLast = lastStats;
  $("#r-gen").textContent = fmt(stats.computeMs);
  $("#r-len").textContent = fmt(stats.seconds, 2);
  $("#r-rtf").textContent = fmt((stats.seconds * 1000) / stats.computeMs);
  makeDownload(current.chunks);
  renderStatus();
}

function finish() {
  if (current) current.playing = false;
  current = null;
  renderPlay();
}

function stop() {
  for (const s of sources) { try { s.stop(); } catch (e) {} }
  sources = [];
  if (current) { current.playing = false; current = null; }
  renderPlay();
}

function makeDownload(chunks) {
  // the chunks joined are Antalia().say's audio; 16-bit PCM as Speech.save writes .wav
  const n = chunks.reduce((a, c) => a + c.length, 0);
  if (!n) return;
  const pcm = new Int16Array(n);
  let o = 0;
  for (const c of chunks) {
    for (let j = 0; j < c.length; j++) pcm[o + j] = Math.max(-32768, Math.min(32767, Math.round(c[j] * 32767)));
    o += c.length;
  }
  const header = new DataView(new ArrayBuffer(44));
  const w = (off, s) => [...s].forEach((ch, i) => header.setUint8(off + i, ch.charCodeAt(0)));
  w(0, "RIFF"); header.setUint32(4, 36 + pcm.byteLength, true); w(8, "WAVE"); w(12, "fmt ");
  header.setUint32(16, 16, true); header.setUint16(20, 1, true); header.setUint16(22, 1, true);
  header.setUint32(24, SAMPLE_RATE, true); header.setUint32(28, SAMPLE_RATE * 2, true);
  header.setUint16(32, 2, true); header.setUint16(34, 16, true); w(36, "data"); header.setUint32(40, pcm.byteLength, true);
  const a = $("#download");
  if (a.href) URL.revokeObjectURL(a.href);
  a.href = URL.createObjectURL(new Blob([header, pcm], { type: "audio/wav" }));
  $("#download-row").hidden = false;
}

// ------------------------------------------------------------------ controls
function steps() { return Number(document.querySelector('input[name="steps"]:checked').value); }
function speed() { return Number($("#speed").value); }
function renderSpeed() { $("#speed-out").textContent = `${fmt(speed(), 2)}×`; }
let touched = false; // the visitor changed speed or steps: keep their choice
$("#speed").addEventListener("input", () => { touched = true; renderSpeed(); });
for (const r of document.querySelectorAll('input[name="steps"]')) r.addEventListener("change", () => { touched = true; });
/** The controls start at the release's defaults (models/manifest.json), as Antalia().say uses them. */
function applyDefaults(d) {
  if (!d || touched) return;
  $("#speed").value = String(d.speed);
  const r = document.querySelector(`input[name="steps"][value="${d.steps}"]`);
  if (r) r.checked = true;
  renderSpeed();
}

function renderPlay() {
  const b = $("#play"), label = $("#play-label");
  const playing = !!(current && current.playing);
  b.dataset.state = playing ? "playing" : "idle";
  if (ready) {
    b.disabled = false;
    label.textContent = playing ? t("stop") : t("play");
  } else if (!startLoading.started) {
    b.disabled = false;
    label.textContent = t("loadModel");
  } else {
    const pct = loadState.total ? Math.round((100 * loadState.loaded) / loadState.total) : 0;
    b.disabled = true;
    label.textContent = errorMsg ? t("failed") : `${t("loading")} ${fmt(pct)}%`;
  }
}

function renderStatus() {
  const el = $("#status");
  el.classList.toggle("err", !!errorMsg);
  if (errorMsg) { el.textContent = `${t("error")}: ${errorMsg}`; return; }
  if (!info) {
    el.textContent = loadState.total ? `${t("downloading")} ${mb(loadState.loaded)} / ${mb(loadState.total)} MB` : "";
    return;
  }
  const be = info.backend === "webgpu" ? "WebGPU" : `WASM SIMD · ${info.threads} ${t(info.threads === 1 ? "thread" : "threads")}`;
  const parts = [be, info.precision, `${mb(info.bytes)} MB`];
  if (lastStats) parts.push(`${t("chunks")} ${lastStats.chunks}`);
  el.textContent = parts.join(" · ");
}

$("#play").addEventListener("click", () => {
  if (current && current.playing) { stop(); return; }
  const text = $("#text").value.trim();
  if (!text) return;
  audioContext(); // unlock audio inside the click
  const req = { text, steps: steps(), speed: speed(), t0: performance.now() };
  if (!startLoading.started) { pending = req; startLoading(); renderPlay(); return; }
  speak(req);
});
$("#text").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); $("#play").click(); }
});
$("#text").addEventListener("input", () => {
  for (const c of document.querySelectorAll(".chip")) c.setAttribute("aria-pressed", "false");
});
for (const c of document.querySelectorAll(".chip")) {
  c.setAttribute("aria-pressed", c.dataset.example === "0" ? "true" : "false");
  c.addEventListener("click", () => {
    $("#text").value = EXAMPLES[Number(c.dataset.example)];
    for (const o of document.querySelectorAll(".chip")) o.setAttribute("aria-pressed", o === c ? "true" : "false");
    if (ready) $("#play").click();
  });
}

// ------------------------------------------------------------------ measurement hook (console / automation)
// await amBench({runs: 3}) synthesises every example `runs` times without playing and returns the timings
// (steps and speed default to the release's, as the page's controls do).
window.amBench = async ({ runs = 3, steps: st, speed: sp } = {}) => {
  while (!ready) await new Promise((r) => setTimeout(r, 100));
  const out = [];
  for (let r = 0; r < runs; r++) {
    for (const text of EXAMPLES) {
      const res = await new Promise((resolve) => {
        const id = nextId++;
        const t0 = performance.now();
        let first = null;
        const h = (ev) => {
          const m = ev.data;
          if (m.id !== id) return;
          if (m.type === "chunk" && first === null) first = performance.now() - t0;
          if (m.type === "done") { worker.removeEventListener("message", h); resolve({ text, firstMs: first, ...m.stats }); }
          if (m.type === "error") { worker.removeEventListener("message", h); resolve({ text, error: m.message }); }
        };
        worker.addEventListener("message", h);
        worker.postMessage({ type: "synth", id, text, steps: st, speed: sp, seed: 0 });
      });
      out.push({ ...res, xRealtime: (res.seconds * 1000) / res.computeMs });
    }
  }
  return { info, runs: out };
};

// ------------------------------------------------------------------ start
applyLang();
renderTheme();

// The service worker caches everything for offline use and adds the COOP/COEP headers that make the page
// cross-origin isolated, which ONNX Runtime needs for threads (about 2x faster here). Static hosts do not
// send those headers, so the first visit reloads once, as soon as the worker controls the page, before the
// model is downloaded. If isolation still fails (e.g. inside an iframe), the model runs on one thread.
async function prepare() {
  if (!("serviceWorker" in navigator) || !window.isSecureContext) return;
  try {
    await navigator.serviceWorker.register("sw.js");
  } catch (e) {
    console.warn("service worker", e);
    return;
  }
  let tried = false;
  try { tried = sessionStorage.getItem("am-coi") === "1"; } catch (e) { tried = true; }
  if (window.crossOriginIsolated || tried || params.has("noreload")) return;
  try { sessionStorage.setItem("am-coi", "1"); } catch (e) { return; }
  if (!navigator.serviceWorker.controller) {
    await new Promise((r) => {
      navigator.serviceWorker.addEventListener("controllerchange", r, { once: true });
      setTimeout(r, 3000);
    });
  }
  if (navigator.serviceWorker.controller) { location.reload(); await new Promise(() => {}); }
}

const saveData = navigator.connection && navigator.connection.saveData;
prepare().then(() => {
  // on a data-saver connection the model (about 23 MB, plus the runtime) waits for the first press
  if (!saveData) startLoading();
  renderPlay();
});
renderPlay();
