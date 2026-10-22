---
title: Antalia-2 Mini
colorFrom: blue
colorTo: indigo
sdk: static
app_file: index.html
license: apache-2.0
pinned: false
models:
- cloud0day3/antalia-mini
short_description: Turkish text-to-speech running entirely in your browser
custom_headers:
  cross-origin-embedder-policy: require-corp
  cross-origin-opener-policy: same-origin
  cross-origin-resource-policy: cross-origin
---

# Antalia-2 Mini in the browser

A static page that runs Antalia-2 Mini 1.0.0 (7.62M parameters, Turkish text to speech, 48 kHz) entirely on the
visitor's device with ONNX Runtime Web: no server, and the text never leaves the browser. It synthesises the way
the released Python package does: the same text and seed give the same audio as
`from antalia_mini import Antalia; Antalia().say(text, seed=0)` (`tests/release_parity/REPORT.md`). This folder is
deployable as a Hugging Face static Space as it is (index.html at the root, every path relative).

## Layout

| Path | What |
|---|---|
| `index.html`, `css/`, `js/app.js`, `js/strings.js` | the page (Turkish UI, English toggle, light and dark) |
| `js/worker.js` | runs the frontend and the model in a Web Worker |
| `js/tts.js` | the inference glue, as `antalia_mini.api`: durations (with the release's double-sound stretch), torch-identical noise, guided flow steps, iSTFT, the spoken prefix / suffix cut away, chunking, pauses, tone EQ and limiter |
| `js/frontend.js`, `assets/frontend-data.json.gz` | the Turkish normaliser ported to JS (`normalize_for_cased_model` + `respell_foreign`), with a compact lexicon, CMU respellings and Turkish vocabulary subset |
| `models/` | `text`, `cond`, `flow`, `vocoder` graphs in fp32, fp16 storage (from the release's fp16 weights) and int8; `manifest.json` names the release, its defaults and synthesis options. The page loads "mixed" by default: fp32 acoustic graphs + fp16 vocoder, 22.8 MB |
| `vendor/ort/` | ONNX Runtime Web (MIT), WASM build |
| `sw.js` | offline cache, and COOP/COEP headers so the page is cross-origin isolated and ORT can use threads |
| `tools/`, `tests/` | export, verification, precision comparison, parity tests (not needed by the page) |

## Commands (run from the repo root)

```bash
web/update_weights.sh ../antalia-mini-release/dist/hf   # a release directory (or two runs / .pt files) -> export -> verify -> swap
web/tools/fetch_ort.sh                       # vendor ONNX Runtime Web (WEBGPU=1 adds the WebGPU build)
python3 web/tools/serve.py --port 8840       # local static server (add --coi to send COOP/COEP itself)
.venv/bin/python web/tools/verify_onnx.py --release DIR --precision mixed --strict   # vs the package's Antalia().say
node web/tests/release_parity/run_js.mjs OUT --precision mixed   # the page's own JS in Node (then verify_onnx.py --js OUT)
node web/tests/glue/run_glue.mjs                                 # glue units vs torch and the package
node web/tests/parity/run_parity.mjs         # normaliser parity, Python vs JS (see the file header)
```

URL options for measuring: `?threads=N`, `?precision=mixed|fp32|fp16|int8`, `?backend=webgpu` (needs the WebGPU
build), `?noreload` (skip the one-time reload that turns on cross-origin isolation). In the console,
`await amBench({runs: 3})` times every example sentence without playing it.

Model and voice: Antalia-2 Mini, Apache-2.0, PatientDesk AI. The voice is synthetic; no real person's voice was
used in training.
