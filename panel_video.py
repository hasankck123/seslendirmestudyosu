# -*- coding: utf-8 -*-
"""Seslendirme Stüdyosu — soru görselinden adım adım çözüm videosu üretici.

Bir soru görseli alır; her anlatım adımı için "görsel + o ana kadarki çözüm
yazıları" panelini tarayıcıda (Playwright/Edge) oluşturur ve panelleri
süreleriyle birleştirip sessiz bir mp4 yazar. Seslendirme daha sonra eklenir.

Yazılar tarayıcıda çizildiği için Türkçe karakterler sorunsuz görünür;
uzun çözümler panel alanına otomatik sığdırılır (yazı boyutu küçültülür).
"""
from __future__ import annotations

import base64
import mimetypes
import subprocess
from pathlib import Path

NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0

PAGE_TEMPLATE = """<!doctype html>
<html lang="tr"><head><meta charset="utf-8"><style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html, body { width: 100%; height: 100%; background: #ffffff;
               font-family: "Segoe UI", Arial, sans-serif; }
  body { display: flex; flex-direction: column; }
  #imgbox { flex: 0 0 auto; height: @@IMGH@@px; background: #f1f5f9;
            display: flex; align-items: center; justify-content: center; padding: 24px; }
  #imgbox img { max-width: 100%; max-height: 100%; object-fit: contain;
                border-radius: 10px; box-shadow: 0 4px 18px rgba(15,23,42,.14); }
  #head { flex: 0 0 auto; display: flex; justify-content: space-between; align-items: center;
          padding: 22px 40px 10px; }
  #head .t { font-size: 40px; font-weight: 700; color: #0f172a; letter-spacing: .5px; }
  #head .n { font-size: 32px; color: #64748b; }
  #steps { flex: 1 1 auto; overflow: hidden; padding: 6px 40px 26px; }
  #steps-inner { font-size: 44px; line-height: 1.34; color: #334155; }
  .st { margin-top: 12px; padding: 6px 0 6px 18px; border-left: 8px solid transparent; }
  .st .no { color: #f97316; font-weight: 700; margin-right: 10px; }
  .st.cur { color: #0f172a; font-weight: 700; border-left-color: #f97316;
            background: #fff7ed; border-radius: 6px; }
  .st.past { color: #64748b; }
</style></head><body>
  <div id="imgbox"><img src="@@IMG@@" alt="soru"></div>
  <div id="head"><span class="t">Çözüm</span><span class="n">@@COUNT@@</span></div>
  <div id="steps"><div id="steps-inner">@@STEPS@@</div></div>
</body></html>"""

FIT_JS = """() => {
  const box = document.getElementById('steps');
  const inner = document.getElementById('steps-inner');
  let fs = parseFloat(getComputedStyle(inner).fontSize) || 44;
  while ((inner.scrollHeight > box.clientHeight || inner.scrollWidth > box.clientWidth) && fs > 17) {
    fs -= 2;
    inner.style.fontSize = fs + 'px';
  }
  return fs;
}"""


def _data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _probe_size(ffprobe: Path | None, image: Path) -> tuple[int, int] | None:
    if not ffprobe:
        return None
    try:
        out = subprocess.run(
            [str(ffprobe), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(image)],
            capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW,
        )
        w, h = (int(x) for x in out.stdout.strip().split("x")[:2])
        return (w, h) if w > 0 and h > 0 else None
    except Exception:
        return None


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def render_panels(image: Path, placements: list[dict], segments: list[dict],
                  out_dir: Path, ffprobe: Path | None, log=print) -> list[Path]:
    """Her adım için bir panel PNG'si üretir; panel sayısı = adım sayısı."""
    from playwright.sync_api import sync_playwright

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("p_*.png"):
        try:
            old.unlink()
        except OSError:
            pass

    by_id = {s["id"]: s for s in segments}
    texts = []
    for p in placements:
        s = by_id.get(p["id"], {})
        t = (s.get("spoken") or s.get("text") or "").strip()
        texts.append(t or "…")
    n = len(texts)

    size = _probe_size(ffprobe, image)
    landscape = bool(size and size[0] > size[1] * 1.05)
    vw, vh = (1920, 1080) if landscape else (1080, 1920)
    img_h = 600 if landscape else 940
    url = _data_uri(image)
    log(f"panel: {n} adım · {vw}x{vh} · görsel {'yatay' if landscape else 'dikey'}")

    panels: list[Path] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        try:
            page = browser.new_page(viewport={"width": vw, "height": vh})
            page.set_default_timeout(20000)
            for i in range(1, n + 1):
                rows = []
                for j, t in enumerate(texts[:i], start=1):
                    cls = "st cur" if j == i else "st past"
                    rows.append(f'<div class="{cls}"><span class="no">{j})</span>{_esc(t)}</div>')
                html = (PAGE_TEMPLATE
                        .replace("@@IMGH@@", str(img_h))
                        .replace("@@IMG@@", url)
                        .replace("@@COUNT@@", f"{i} / {n}")
                        .replace("@@STEPS@@", "".join(rows)))
                page.set_content(html, wait_until="load")
                page.wait_for_timeout(60)
                fs = page.evaluate(FIT_JS)
                shot = out_dir / f"p_{i:03d}.png"
                page.screenshot(path=str(shot))
                panels.append(shot)
                if fs and fs <= 18:
                    log(f"panel: {i}. adımda yazı çok uzun, küçültüldü")
        finally:
            browser.close()
    return panels


def build_panel_video(image: Path, out_path: Path, placements: list[dict], segments: list[dict],
                      ffmpeg: Path, ffprobe: Path | None, log=print) -> Path:
    """Soru görselinden (paneller + süreler) sessiz bir mp4 üretir."""
    image = Path(image)
    out_path = Path(out_path)
    panels = render_panels(image, placements, segments, out_path.parent / "panels", ffprobe, log=log)

    durs: list[float] = []
    for i, p in enumerate(placements):
        if i + 1 < len(placements):
            d = float(placements[i + 1]["start"]) - float(p["start"])
        else:
            d = float(p["dur"]) + 0.3
        durs.append(max(0.5, d))
    if len(durs) != len(panels):
        raise RuntimeError("panel/adım sayısı uyuşmadı")

    args = ["-y", "-v", "error"]
    for p, d in zip(panels, durs):
        args += ["-loop", "1", "-framerate", "30", "-t", f"{d:.3f}", "-i", str(p)]
    n = len(panels)
    filt = "".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]"
    args += ["-filter_complex", filt, "-map", "[v]", "-r", "30",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)]
    proc = subprocess.run([str(ffmpeg)] + args, capture_output=True, text=True, timeout=1800,
                          creationflags=NO_WINDOW)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-6:]
        raise RuntimeError("panel videosu hatası:\n" + "\n".join(tail))
    log(f"panel videosu hazır: {out_path.name} ({sum(durs):.1f} sn, {n} panel)")
    return out_path
