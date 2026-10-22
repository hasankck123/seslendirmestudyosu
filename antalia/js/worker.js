// Runs the text frontend and the model off the main thread.
//   -> {type: "init", backend: "wasm" | "webgpu", threads, precision: "mixed" | "fp32" | "fp16" | "int8"}
//   <- {type: "progress", loaded, total} ... {type: "ready", info}
//   -> {type: "synth", id, text, steps?, speed?, seed}   (steps / speed default to the release's)
//   <- {type: "text", id, modelText} {type: "chunk", id, index, count, audio, timings} ... {type: "done", id, stats}
//   <- {type: "error", id?, message}
import { Engine, PRECISIONS, SAMPLE_RATE, speak } from "./tts.js";
import { loadFrontend } from "./frontend.js";

const BASE = new URL("../", import.meta.url);
let engine = null, frontend = null, manifest = null;

async function fetchWithProgress(urls, onProgress) {
  // Content-Length per file when the server sends it, else the sizes recorded in the manifest
  const sizes = urls.map((u) => manifest?.files?.[u.split("/").pop().split("?")[0]]?.bytes || 0);
  const loaded = urls.map(() => 0);
  const report = () => onProgress(loaded.reduce((a, b) => a + b, 0), sizes.reduce((a, b) => a + b, 0));
  return Promise.all(urls.map(async (u, i) => {
    const res = await fetch(new URL(u, BASE));
    if (!res.ok) throw new Error(`${u}: HTTP ${res.status}`);
    const len = Number(res.headers.get("Content-Length")) || 0;
    if (len && !res.headers.get("Content-Encoding")) sizes[i] = len;
    if (!res.body) { const b = await res.arrayBuffer(); loaded[i] = b.byteLength; report(); return b; }
    const reader = res.body.getReader();
    const parts = [];
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      parts.push(value);
      loaded[i] += value.byteLength;
      report();
    }
    const out = new Uint8Array(loaded[i]);
    let o = 0;
    for (const p of parts) { out.set(p, o); o += p.byteLength; }
    return out.buffer;
  }));
}

async function init({ backend = "wasm", threads = 0, precision = "mixed" }) {
  const t0 = performance.now();
  manifest = await (await fetch(new URL("models/manifest.json", BASE), { cache: "no-cache" })).json();
  const useGpu = backend === "webgpu";
  const ort = await import(useGpu ? "../vendor/ort/ort.webgpu.min.mjs" : "../vendor/ort/ort.wasm.min.mjs");
  ort.env.wasm.wasmPaths = new URL("vendor/ort/", BASE).href;
  // threads need SharedArrayBuffer, i.e. a cross-origin isolated page. Half the cores, at most 4: on a
  // 10-core M5, 1/2/4/6/8 threads gave 27/41/46/50/41x real time, and phones mix fast and slow cores.
  const cores = self.crossOriginIsolated ? navigator.hardwareConcurrency || 1 : 1;
  ort.env.wasm.numThreads = threads ? Math.min(threads, cores) : Math.max(1, Math.min(4, Math.floor(cores / 2)));
  if (!PRECISIONS[precision]) precision = "mixed";
  // ?v=<sha256 prefix>: new weights get new URLs, so the service worker's cache-first copy is never stale
  const files = ["text", "cond", "flow", "vocoder"].map((k) => {
    const name = `${k}${PRECISIONS[precision][k]}.onnx`;
    return `models/${name}?v=${manifest.files[name]?.sha256 || "0"}`;
  });
  const [buffers, fe] = await Promise.all([
    fetchWithProgress(files, (loaded, total) => postMessage({ type: "progress", loaded, total })),
    loadFrontend(new URL("assets/frontend-data.json.gz", BASE)),
  ]);
  frontend = fe;
  const tLoaded = performance.now();
  engine = await Engine.create(ort, { text: buffers[0], cond: buffers[1], flow: buffers[2], vocoder: buffers[3] },
    manifest, useGpu ? ["webgpu", "wasm"] : ["wasm"]);
  // warm-up: the first run of each graph allocates and picks kernels; the frontend compiles its patterns
  for await (const _ of speak(engine, fe.modelText("Merhaba, 15 Ekim'de 1.250 TL."), { steps: 1 }));
  const tReady = performance.now();
  postMessage({
    type: "ready",
    info: {
      backend: useGpu ? "webgpu" : "wasm", threads: ort.env.wasm.numThreads, crossOriginIsolated: self.crossOriginIsolated,
      precision, bytes: buffers.reduce((a, b) => a + b.byteLength, 0), downloadMs: tLoaded - t0,
      initMs: tReady - tLoaded, weights: manifest.weights, params: manifest.params_inference, ortVersion: ort.env.versions?.web,
      model: manifest.model, version: manifest.version, defaults: engine.defaults,
    },
  });
}

async function synth({ id, text, steps, speed, seed = 0 }) {
  const t0 = performance.now();
  const modelText = frontend.modelText(text);
  const tNorm = performance.now() - t0;
  postMessage({ type: "text", id, modelText });
  let samples = 0, compute = tNorm, count = 0;
  const timings = { normalize: tNorm, text: 0, cond: 0, flow: 0, vocoder: 0, istft: 0, post: 0 };
  let c0 = performance.now();
  for await (const { audio, index, count: n, timings: tm } of speak(engine, modelText, { seed, steps, speed })) {
    compute += performance.now() - c0;
    for (const k in tm) timings[k] += tm[k];
    samples += audio.length;
    count = n;
    postMessage({ type: "chunk", id, index, count: n, audio, sinceStart: performance.now() - t0 }, [audio.buffer]);
    c0 = performance.now();
  }
  postMessage({ type: "done", id, stats: { computeMs: compute, wallMs: performance.now() - t0, seconds: samples / SAMPLE_RATE, chunks: count, timings } });
}

let queue = Promise.resolve();
onmessage = (ev) => {
  const msg = ev.data;
  queue = queue.then(async () => {
    try {
      if (msg.type === "init") await init(msg);
      else if (msg.type === "synth") await synth(msg);
    } catch (err) {
      postMessage({ type: "error", id: msg.id, message: String(err?.message || err) });
    }
  });
};
