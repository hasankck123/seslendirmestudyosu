# -*- coding: utf-8 -*-
"""Antalia-2 Mini motoru: başsız Edge içinde uygulamanın worker.js'ini çalıştırır.

Motor kendi iş parçacığında yaşar (Playwright sync API iş parçacığına bağlıdır).
Sunucudaki istekler `synth()` üzerinden kuyruğa iş verir ve sonucu bekler.
"""
from __future__ import annotations

import base64
import queue
import threading
import time

INIT_JS = r"""
async () => {
  const w = new Worker(new URL('js/worker.js', location.href), {type: 'module'});
  window.__antWorker = w;
  window.__antId = 0;
  const info = await new Promise((res, rej) => {
    const h = (ev) => { const m = ev.data;
      if (m.type === 'progress') return;
      if (m.type === 'ready') { w.removeEventListener('message', h); res(m.info); }
      else if (m.type === 'error') { w.removeEventListener('message', h); rej(new Error(m.message)); }
    };
    w.addEventListener('message', h);
    w.postMessage({type: 'init', backend: 'wasm', threads: 2, precision: 'mixed'});
  });
  return info;
}
"""

SYNTH_JS = r"""
async ({text, steps, speed, seed}) => {
  const w = window.__antWorker;
  const id = ++window.__antId;
  const chunks = []; let modelText = '';
  const stats = await new Promise((res, rej) => {
    const h = (ev) => { const m = ev.data; if (m.id !== id) return;
      if (m.type === 'text') modelText = m.modelText;
      else if (m.type === 'chunk') chunks[m.index] = m.audio;
      else if (m.type === 'done') { w.removeEventListener('message', h); res(m.stats); }
      else if (m.type === 'error') { w.removeEventListener('message', h); rej(new Error(m.message)); }
    };
    w.addEventListener('message', h);
    w.postMessage({type: 'synth', id, text, steps, speed, seed});
  });
  let n = 0; for (const c of chunks) n += c.length;
  const pcm = new Int16Array(n); let o = 0;
  for (const c of chunks) {
    for (let j = 0; j < c.length; j++) {
      const v = Math.round(c[j] * 32767);
      pcm[o + j] = v < -32768 ? -32768 : (v > 32767 ? 32767 : v);
    }
    o += c.length;
  }
  const header = new DataView(new ArrayBuffer(44));
  const wr = (off, s) => { for (let i = 0; i < s.length; i++) header.setUint8(off + i, s.charCodeAt(i)); };
  wr(0, "RIFF"); header.setUint32(4, 36 + pcm.byteLength, true); wr(8, "WAVE"); wr(12, "fmt ");
  header.setUint32(16, 16, true); header.setUint16(20, 1, true); header.setUint16(22, 1, true);
  header.setUint32(24, 48000, true); header.setUint32(28, 96000, true);
  header.setUint16(32, 2, true); header.setUint16(34, 16, true);
  wr(36, "data"); header.setUint32(40, pcm.byteLength, true);
  const bytes = new Uint8Array(44 + pcm.byteLength);
  bytes.set(new Uint8Array(header.buffer), 0);
  bytes.set(new Uint8Array(pcm.buffer), 44);
  let binary = ''; const CH = 0x8000;
  for (let i = 0; i < bytes.length; i += CH) binary += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
  return {modelText, stats, wav: btoa(binary)};
}
"""


class AntaliaEngine:
    """Tek örnekli motor; state: starting | ready | error | stopped."""

    def __init__(self, page_url: str, log=print):
        self.url = page_url
        self.log = log
        self._q: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._state = "starting"
        self._message = "Antalia motoru başlatılıyor..."
        self._info: dict | None = None

    # ------------------------------------------------------------------ API
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._main, name="antalia-engine", daemon=True)
        self._thread.start()

    def status(self) -> dict:
        with self._lock:
            return {"state": self._state, "message": self._message, "info": self._info}

    def synth(self, items: list[dict], steps: int = 8, speed: float = 0.95, seed: int = 0) -> list[dict]:
        """items: [{id, text}] -> [{id, modelText, seconds, chunks, computeMs, wav(b64)}]"""
        with self._lock:
            if self._state == "error":
                raise RuntimeError(self._message)
        box: dict = {}
        ev = threading.Event()
        self._q.put(("synth", (items, steps, speed, seed), box, ev))
        ev.wait()
        if "e" in box:
            raise box["e"]
        return box["r"]

    def stop(self, timeout: float = 15.0) -> None:
        if not (self._thread and self._thread.is_alive()):
            return
        box: dict = {}
        ev = threading.Event()
        self._q.put(("stop", (), box, ev))
        ev.wait(timeout)

    def restart(self) -> None:
        """Hatadan sonra motoru yeniden başlatır."""
        self.stop()
        with self._lock:
            self._state = "starting"
            self._message = "Antalia motoru yeniden başlatılıyor..."
        self.start()

    # -------------------------------------------------------------- internals
    def _set(self, state: str, message: str, info: dict | None = None) -> None:
        with self._lock:
            self._state = state
            self._message = message
            if info is not None:
                self._info = info
        self.log(f"[engine] {state}: {message}")

    def _main(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # playwright yok
            self._set("error", f"Playwright bulunamadı ({exc}). 'python -m pip install playwright' gerekli.")
            self._fail_pending(RuntimeError(self._message))
            return
        try:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(channel="msedge", headless=True)
            self._open_page()
            self._set("ready", "Antalia motoru hazır", self._page_info)
        except Exception as exc:
            self._set("error", f"Motor başlatılamadı: {exc}")
            self._fail_pending(RuntimeError(self._message))
            return

        while True:
            job, args, box, ev = self._q.get()
            if job == "stop":
                try:
                    self._close()
                except Exception:
                    pass
                self._set("stopped", "Antalia motoru durduruldu")
                ev.set()
                return
            try:
                box["r"] = getattr(self, "_job_" + job)(*args)
            except Exception as exc:
                # tarayıcı çökmüş olabilir: bir kez kurtarmayı dene
                try:
                    self.log(f"[engine] hata, kurtarma denemesi: {exc}")
                    self._recover()
                    box["r"] = getattr(self, "_job_" + job)(*args)
                except Exception as exc2:
                    box["e"] = exc2
            finally:
                ev.set()

    def _open_page(self) -> None:
        page = self._browser.new_page()
        page.goto(self.url, wait_until="load", timeout=90_000)
        self._page_info = page.evaluate(INIT_JS)
        self._page = page

    def _recover(self) -> None:
        try:
            self._page.close()
        except Exception:
            pass
        self._open_page()

    def _close(self) -> None:
        try:
            self._page.close()
        except Exception:
            pass
        try:
            self._browser.close()
        except Exception:
            pass
        try:
            self._pw.stop()
        except Exception:
            pass

    def _job_synth(self, items: list[dict], steps: int, speed: float, seed: int) -> list[dict]:
        out = []
        for it in items:
            t0 = time.time()
            r = self._page.evaluate(SYNTH_JS, {"text": it["text"], "steps": steps, "speed": speed, "seed": seed})
            out.append({
                "id": it["id"],
                "modelText": r["modelText"],
                "seconds": r["stats"]["seconds"],
                "chunks": r["stats"]["chunks"],
                "computeMs": r["stats"]["computeMs"],
                "wav": r["wav"],
            })
            self.log(f"[engine] {it['id']}: {r['stats']['seconds']:.2f} sn ses, {r['stats']['computeMs']:.0f} ms üretim (toplam {(time.time()-t0):.1f} sn)")
        return out

    def _fail_pending(self, exc: Exception) -> None:
        while True:
            try:
                job, args, box, ev = self._q.get_nowait()
            except queue.Empty:
                return
            box["e"] = exc
            ev.set()
