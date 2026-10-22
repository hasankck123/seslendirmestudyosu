# -*- coding: utf-8 -*-
"""Seslendirme Stüdyosu — soru görselinin üzerine "kalemle yazma" videosu.

Çözüm adımlarını soru görselinin üzerindeki boş alana, el yazısı fontuyla,
sanki biri kalemle yazıyormuş gibi harf harf çizer ve sessiz bir mp4 üretir.
Seslendirme sonra eklenir (`serve.py`).

Tasarım:
- Sabit Reels arka planı (assets/arkaplan.png, 1080x1920) kullanılır; soru
  görseli arka plandaki beyaz kartın içine oranı korunarak sığdırılır.
- Yazı alanı: görseldeki en büyük "boş" (açık renkli) dikdörtgen bölgeler
  (grid tabanlı en büyük dikdörtgen araması; gerekirse 2-3 bölgeye taşar).
- Yazı boyutu tüm adımlar sığacak şekilde otomatik küçültülür.
- Her adımın yazımı, o adımın sesi başladığı an başlar; ses bitmeden tamamlanır.
- Son adımın altına el çizimi alt çizgi çekilir.
"""
from __future__ import annotations

import math
import re
import shutil
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0

INK = (26, 42, 120)          # dolma kalem mavisi
EXP_RAISE = 0.24             # üs simgesinin tabana göre yüksekliği (× yazı boyu)
FPS = 15
FONT_PATHS = [
    r"C:\Windows\Fonts\segoescb.ttf",   # Segoe Script Bold (el yazısı, Türkçe ✓)
    r"C:\Windows\Fonts\Inkfree.ttf",
    r"C:\Windows\Fonts\comic.ttf",
]


_FONT_CACHE: dict[int, object] = {}


def _load_font(size: int):
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    for p in FONT_PATHS:
        try:
            f = ImageFont.truetype(p, size)
            _FONT_CACHE[size] = f
            return f
        except OSError:
            continue
    try:
        f = ImageFont.truetype("segoescb.ttf", size)
    except Exception:
        f = ImageFont.load_default()
    _FONT_CACHE[size] = f
    return f


_EXP_CACHE: dict[int, object] = {}


def _exp_font(size: int):
    """Üst simge (üs) yazısı için küçük font (önbellekli)."""
    s = max(10, int(round(size * 0.58)))
    if s not in _EXP_CACHE:
        _EXP_CACHE[s] = _load_font(s)
    return _EXP_CACHE[s]


FRAC_RE = re.compile(r"(\d{1,4}(?:[.,]\d{1,4})?)\s*/\s*(\d{1,4}(?:[.,]\d{1,4})?)")


def _tokenize(line: str) -> list[tuple[str, str]]:
    """Satırı parçalara ayırır: 't' normal metin, 'e' üs, 'f' kesir (pay/payda).
    '^4', '^-3' üs olur; '1/8', '0,5/2' gibi ifadeler alt alta kesir olarak çizilir."""
    toks: list[tuple[str, str]] = []
    i, n = 0, len(line)

    def add(kind: str, text: str) -> None:
        if not text:
            return
        if toks and toks[-1][0] == kind and kind != "f":
            toks[-1] = (kind, toks[-1][1] + text)
        else:
            toks.append((kind, text))

    while i < n:
        ch = line[i]
        if ch == "^" and i + 1 < n:
            j = i + 1
            if line[j] == "(":
                k = line.find(")", j)
                if k > j:
                    add("e", line[j + 1:k])
                    i = k + 1
                    continue
            else:
                if line[j] in "+-−":
                    j += 1
                k = j
                while k < n and (line[k].isdigit() or line[k] in ",."):
                    k += 1
                if k > j:
                    add("e", line[i + 1:k])
                    i = k
                    continue
        m = FRAC_RE.match(line, i)
        if m:
            add("f", f"{m.group(1)}/{m.group(2)}")
            i = m.end()
            continue
        add("t", ch)
        i += 1
    return toks


def _has_frac(line: str) -> bool:
    return any(kind == "f" for kind, _ in _tokenize(line))


def _line_h(line: str, size: int) -> int:
    """Satır yüksekliği: kesirli satırlar iki katına yakın yer kaplar."""
    if _has_frac(line):
        return int(size * 2) + 16
    return int(round(size * 1.45))


def _line_w(probe: ImageDraw.ImageDraw, line: str, font, size: int) -> float:
    """Satırın piksel genişliği (üst simgeler küçük, kesirler pay/payda genişliğinde)."""
    ef = _exp_font(size)
    w = 0.0
    for kind, txt in _tokenize(line):
        if kind == "e":
            w += probe.textlength(txt, font=ef)
        elif kind == "f":
            num, den = txt.split("/", 1)
            w += max(probe.textlength(num, font=font), probe.textlength(den, font=font)) + 8
        else:
            w += probe.textlength(txt, font=font)
    return w


def _draw_line(d: ImageDraw.ImageDraw, x: float, y: float, line: str, font, size: int,
               budget: int) -> None:
    """Satırı üst simgeler ve alt alta kesirlerle çizer;
    'budget' kadar karakter yazar (kalemle yazma animasyonu)."""
    ef = _exp_font(size)
    if _has_frac(line):
        box_h = int(size * 2) + 16
        frac_top = y + (box_h - (2 * size + 12)) // 2
        bar_y = frac_top + size + 6
        text_y = bar_y - int(size * 0.62)
    else:
        bar_y = text_y = y
    ey = text_y - int(size * EXP_RAISE)
    big_font = _load_font(int(round(size * 1.75)))
    toks = _tokenize(line)
    for idx, (kind, txt) in enumerate(toks):
        if budget <= 0:
            break
        if kind == "f":
            num, den = txt.split("/", 1)
            wn = d.textlength(num, font=font)
            wd = d.textlength(den, font=font)
            w = max(wn, wd)
            take = min(budget, len(num) + 1 + len(den))
            # pay ve paydayı görsel kenarlarından çizgiye hizala
            bbn = d.textbbox((0, 0), num, font=font)
            bbd = d.textbbox((0, 0), den, font=font)
            # pay → çizgi → payda sırayla "yazılır"
            d.text((x + (w - wn) / 2, bar_y - 7 - bbn[3]), num[:min(take, len(num))],
                   font=font, fill=INK)
            if take > len(num):
                d.line([(x - 3, bar_y), (x + w + 5, bar_y)], fill=INK, width=max(2, size // 12))
            if take > len(num) + 1:
                d.text((x + (w - wd) / 2, bar_y + 6 - bbd[1]), den[:take - len(num) - 1],
                       font=font, fill=INK)
            x += w + 8
            budget -= take
            continue
        if kind == "e":
            part = txt[:budget]
            d.text((x, ey), part, font=ef, fill=INK)
            x += d.textlength(part, font=ef)
            budget -= len(part)
            continue
        # normal metin; kesrin yanındaki parantezler büyük çizilir
        nxt = toks[idx + 1][0] if idx + 1 < len(toks) else None
        prv = toks[idx - 1][0] if idx > 0 else None
        pieces: list[tuple[str, object, float]] = []
        if nxt == "f" and txt.endswith("("):
            pieces.append((txt[:-1], font, text_y))
            pieces.append(("(", big_font, bar_y - int(size * 0.85)))
        elif prv == "f" and txt.startswith(")"):
            pieces.append((")", big_font, bar_y - int(size * 0.85)))
            pieces.append((txt[1:], font, text_y))
        else:
            pieces.append((txt, font, text_y))
        for ptxt, pfont, py in pieces:
            if budget <= 0:
                break
            part = ptxt[:budget]
            d.text((x, py), part, font=pfont, fill=INK)
            x += d.textlength(part, font=pfont)
            budget -= len(part)


def _paren_frac_pow(t: str) -> str:
    """Bir kesrin üssü alınıyorsa parantez ekler: 1/2^3 → (1/2)^3.
    Zaten parantezli ya da öncesinde üs/sayı olan (4^4 / 4^1 gibi) durumlara dokunmaz."""
    return re.sub(
        r"(?<![\^\d.,(])(\d{1,4}(?:[.,]\d{1,4})?)\s*/\s*(\d{1,4}(?:[.,]\d{1,4})?)\s*\^\s*(-?\d{1,3})",
        r"(\1/\2)^\3", t)


_MATH_WORDS = [
    (r"üzeri\s+eksi", "^-"),
    (r"eksi", "-"),
    (r"üzeri", "^"),
    (r"kare", "^2"),
    (r"küp", "^3"),
    (r"çarpı", "·"),
    (r"eşittir", "="),
    (r"bölü", "/"),
    (r"artı", "+"),
]


def _mathify(t: str) -> str:
    """Konuşma metnini kabaca matematiksel yazıma çevirir (display yoksa yedek)."""
    out = t
    for pat, rep in _MATH_WORDS:
        out = re.sub(rf"\b{pat}\b", rep, out, flags=re.IGNORECASE)
    out = re.sub(r"\s+\^", "^", out)
    out = re.sub(r"\^\s*([-+])?\s*", lambda m: "^" + (m.group(1) or ""), out)
    out = re.sub(r"\s*([=+·/])\s*", r" \1 ", out)
    return re.sub(r"\s+", " ", out).strip()


# --- sabit Reels arka planı -------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent
ASSETS_DIR = ROOT_DIR / "assets"
BG_FILE = ASSETS_DIR / "arkaplan.png"     # sabit marka arka planı (1080x1920)
CANVAS_SIZE = (1080, 1920)                # tüm videolar bu ölçüde üretilir
CARD_FALLBACK = (156, 443, 923, 1705)     # arka plandaki beyaz kart sınırları
CARD_PAD = 26                             # soru görselinin kart içi kenar boşluğu


def _find_card(canvas: Image.Image) -> tuple[int, int, int, int] | None:
    """Sabit arka plandaki beyaz kartın sınırlarını kaba (1/8 ölçekte) bulur."""
    try:
        g = canvas.convert("L").resize((canvas.width // 8, canvas.height // 8), Image.BOX)
        bb = g.point(lambda v: 255 if v >= 246 else 0).convert("1").getbbox()
        if bb:
            return (bb[0] * 8, bb[1] * 8,
                    min(canvas.width, bb[2] * 8), min(canvas.height, bb[3] * 8))
    except Exception:
        pass
    return None


def _base_canvas(image_path: Path) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """Sabit Reels arka planı + otomatik yerleşen soru görseli.

    assets/arkaplan.png her videoda aynıdır (1080x1920, ortada beyaz kart).
    Soru görseli kartın içine oranı korunarak, üstten hizalı ve yatayda
    ortalanmış biçimde yerleştirilir; yazı alanı kartın içidir.
    """
    if BG_FILE.is_file():
        bg = ImageOps.exif_transpose(Image.open(BG_FILE).convert("RGB"))
        if bg.size != CANVAS_SIZE:
            bg = ImageOps.fit(bg, CANVAS_SIZE, Image.LANCZOS)
        canvas = bg
        card = _find_card(canvas) or CARD_FALLBACK
        ix0, iy0, ix1, iy1 = (card[0] + CARD_PAD, card[1] + CARD_PAD,
                              card[2] - CARD_PAD, card[3] - CARD_PAD)
        q = ImageOps.exif_transpose(Image.open(image_path).convert("RGB"))
        s = min((ix1 - ix0) / q.width, (iy1 - iy0) / q.height)
        qw, qh = max(1, round(q.width * s)), max(1, round(q.height * s))
        if (qw, qh) != q.size:
            q = q.resize((qw, qh), Image.LANCZOS)
        canvas.paste(q, (ix0 + ((ix1 - ix0) - qw) // 2, iy0))
        return canvas, (card[0] + 8, card[1] + 8, card[2] - 8, card[3] - 8)

    # arka plan yoksa eski davranış: soru görseli tuvali doldurur
    im = ImageOps.exif_transpose(Image.open(image_path).convert("RGB"))
    w, h = im.size
    vw, vh = (1920, 1080) if w > h else (1080, 1920)
    s = min(vw / w, vh / h)
    if abs(s - 1.0) > 0.001:
        im = im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
    canvas = Image.new("RGB", (vw, vh), "white")
    ox, oy = (vw - im.width) // 2, (vh - im.height) // 2
    canvas.paste(im, (ox, oy))
    return canvas, (ox, oy, ox + im.width, oy + im.height)


def _empty_rects(canvas: Image.Image, area: tuple[int, int, int, int],
                 gw: int = 56, gh: int = 110, min_light: int = 150, avg_light: int = 205,
                 max_rects: int = 4, min_cells: int = 60) -> list[tuple[int, int, int, int]]:
    """Yazı/doodle içermeyen (hücredeki en koyu piksel bile açık olan) en büyük boş bölgeler."""
    x0, y0, x1, y1 = area
    crop = canvas.crop(area).convert("L")
    # her hücre 3x3 alt piksele iner: min + ortalamaya bakarız
    mid = crop.resize((gw * 3, gh * 3), Image.BOX)
    mp = mid.load()
    grid: list[list[bool]] = []
    for gy in range(gh):
        row = []
        for gx in range(gw):
            vals = [mp[gx * 3 + i, gy * 3 + j] for i in range(3) for j in range(3)]
            row.append(min(vals) >= min_light and sum(vals) / 9 >= avg_light)
        grid.append(row)
    found: list[tuple[int, int, int, int]] = []
    for _ in range(max_rects):
        heights = [0] * gw
        best, best_area = None, 0
        for gy in range(gh):
            for gx in range(gw):
                heights[gx] = heights[gx] + 1 if grid[gy][gx] else 0
            stack: list[tuple[int, int]] = []
            for gx in range(gw + 1):
                cur = heights[gx] if gx < gw else 0
                start = gx
                while stack and stack[-1][1] > cur:
                    sx, sh = stack.pop()
                    a = sh * (gx - sx)
                    if a > best_area:
                        best_area = a
                        best = (sx, gy - sh + 1, gx, gy + 1)
                    start = sx
                stack.append((start, cur))
        if not best or best_area < min_cells:
            break
        bx0, by0, bx1, by1 = best
        for gy in range(by0, by1):
            for gx in range(bx0, bx1):
                grid[gy][gx] = False
        cw, ch = x1 - x0, y1 - y0
        found.append((x0 + round(bx0 / gw * cw), y0 + round(by0 / gh * ch),
                      x0 + round(bx1 / gw * cw), y0 + round(by1 / gh * ch)))
    return found


def _wrap_words(measure, words: list[str], width: float) -> tuple[list[str], list[int]]:
    """Kelimeleri satırlara sarar; (satırlar, her satırın kelime sayısı) döner."""
    lines: list[str] = []
    counts: list[int] = []
    cur = ""
    cnt = 0
    for w in words:
        t = (cur + " " + w).strip()
        if not cur or measure(t) <= width:
            cur = t
            cnt += 1
        else:
            lines.append(cur)
            counts.append(cnt)
            cur = w
            cnt = 1
    if cur:
        lines.append(cur)
        counts.append(cnt)
    return lines, counts


def _layout(canvas: Image.Image, rects: list[tuple[int, int, int, int]],
            texts: list[str], log=print):
    """Tüm adımlar bu bölgelere sığana dek yazı boyutunu küçültür.
    Sığdıran en büyük boyutta (font, size, lh, plans) döner; hiç sığmazsa None."""
    probe = ImageDraw.Draw(canvas)
    pad = 16
    for size in range(52, 15, -2):
        font = _load_font(size)
        lh = int(round(size * 1.45))

        def measure(s: str, _font=font, _size=size) -> float:
            return _line_w(probe, s, _font, _size)

        ri = 0
        x = rects[0][0] + pad
        y = rects[0][1] + pad
        plans: list[list[tuple[int, int, str]]] = []
        fits = True
        for ti, text in enumerate(texts):
            if not text:
                plans.append([])  # bu adımda tahtaya yazı yok
                continue
            words = text.split()
            step_lines: list[tuple[int, int, str]] = []
            while words:
                x0, y0, x1, y1 = rects[ri]
                x = max(x, x0 + pad)
                avail = (x1 - pad) - x
                lines_all, counts = _wrap_words(measure, words, avail)
                taken = 0
                yy = y
                for ln in lines_all:
                    h = _line_h(ln, size)
                    if yy + h > y1 - pad:
                        break
                    yy += h
                    taken += 1
                if taken <= 0:
                    if ri + 1 < len(rects):
                        ri += 1
                        x, y = rects[ri][0] + pad, rects[ri][1] + pad
                        continue
                    fits = False
                    break
                for i in range(taken):
                    ln = lines_all[i]
                    jx = x + ((ti * 5 + i) % 3 - 1) * 2  # hafif el titremesi
                    step_lines.append((jx, y, ln))
                    y += _line_h(ln, size)
                words = words[sum(counts[:taken]):]
                if words:
                    if ri + 1 < len(rects):
                        ri += 1
                        x, y = rects[ri][0] + pad, rects[ri][1] + pad
                    else:
                        fits = False
                        break
            if not fits:
                break
            plans.append(step_lines)
            y += int(size * 0.35)  # adımlar arası küçük boşluk
        if fits and len(plans) == len(texts):
            return font, size, lh, plans
    return None


def _layout_forced(canvas: Image.Image, rects: list[tuple[int, int, int, int]],
                   texts: list[str], log=print):
    """Son çare: çok küçük boyutla yaz, alan bitince kalanı kes."""
    probe = ImageDraw.Draw(canvas)
    pad = 16
    font = _load_font(16)
    lh = 23
    log("kalem uyarı: yazı tam sığmadı, küçük boyutta kesiliyor")
    ri = 0
    x = rects[0][0] + pad
    y = rects[0][1] + pad
    plans = []
    for ti, text in enumerate(texts):
        if not text:
            plans.append([])
            continue
        words = text.split()
        step_lines = []
        while words:
            x0, y0, x1, y1 = rects[ri]
            x = max(x, x0 + pad)
            avail = (x1 - pad) - x
            lines_all, counts = _wrap_words(lambda s: _line_w(probe, s, font, 16), words, avail)
            if not lines_all:
                break
            ln = lines_all[0]
            h = _line_h(ln, 16)
            if y + h > y1 - pad:
                if ri + 1 < len(rects):
                    ri += 1
                    x, y = rects[ri][0] + pad, rects[ri][1] + pad
                    continue
                return font, 16, lh, plans
            step_lines.append((x, y, ln))
            y += h
            words = words[counts[0]:]
        plans.append(step_lines)
    return font, 16, lh, plans


def build_handwrite_video(image: Path, out_path: Path, placements: list[dict],
                          segments: list[dict], frames_dir: Path,
                          ffmpeg: str | None = None, log=print) -> Path:
    """Soru görseli + adım zamanlarından 'kalemle yazılmış' sessiz video üretir."""
    ffmpeg = ffmpeg or shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg bulunamadı")
    image = Path(image)
    out_path = Path(out_path)
    frames_dir = Path(frames_dir)
    if frames_dir.is_dir():
        shutil.rmtree(frames_dir, ignore_errors=True)
    frames_dir.mkdir(parents=True, exist_ok=True)

    canvas, area = _base_canvas(image)
    by_id = {s["id"]: s for s in segments}
    texts: list[str | None] = []
    for p in placements:
        s = by_id.get(p["id"], {})
        disp = s.get("display")
        if isinstance(disp, str):
            # AI'nın ürettiği kısa matematik yazısı ("" veya "-" = bu adımda yazı yok)
            t = disp.strip()
            if t in ("-", "–", "—"):
                t = ""
            else:
                t = t.replace("*", "·")            # AI bazen yıldız yazar; tahtada orta nokta olsun
                t = re.sub(r"(?<=\S)\s+[xX]\s+(?=\S)", " · ", t)  # "2 x 3" yazımını noktaya çevir
                t = re.sub(r"\s*·\s*", " · ", t)  # çarpma noktası aralarına boşluk
                t = _paren_frac_pow(t)            # 1/2^3 → (1/2)^3
        else:
            # display yoksa konuşma metnini kabaca sembollere çevirip yaz
            t = _paren_frac_pow(_mathify((s.get("text") or s.get("spoken") or "").strip().replace("*", "·")))
        texts.append(t or None)

    rects = _empty_rects(canvas, area)
    if not rects:
        x0, y0, x1, y1 = area
        rects = [(x0 + 20, y0 + int((y1 - y0) * 0.55), x1 - 20, y1 - 20)]
        log("kalem: boş alan bulunamadı, alt bölge kullanılıyor")
    log(f"kalem: {len(rects)} yazı bölgesi · ör. {rects[0]}")

    # yazım akışı: en büyük bölgeden başla, sonra ALTINDAKİLERE (yakından uzağa) geç;
    # üstte kalan bölgeler yalnızca hiçbir şey sığmazsa kullanılır
    def _cy(r):
        return (r[1] + r[3]) / 2
    head = rects[0]
    down = sorted([r for r in rects[1:] if _cy(r) > _cy(head)],
                  key=lambda r: _cy(r) - _cy(head))
    up = sorted([r for r in rects[1:] if _cy(r) <= _cy(head)],
                key=lambda r: _cy(head) - _cy(r))
    layout = None
    for region_set in ([head] + down, [head] + down + up):
        layout = _layout(canvas, region_set, texts, log)
        if layout:
            break
    if layout:
        font, size, lh, plans = layout
    else:
        font, size, lh, plans = _layout_forced(canvas, rects, texts, log)
    log(f"kalem: yazı boyutu {size}px · {sum(len(p) for p in plans)} satır")

    # zaman çizgisi
    starts = [float(p["start"]) for p in placements]
    durs = [float(p["dur"]) for p in placements]
    total = starts[-1] + durs[-1] + 0.3

    spans = []
    for i, pl in enumerate(plans):
        chars = sum(len(ln) for _, _, ln in pl) or 1
        spans.append(max(0.5, min(3.5, chars * 0.035, durs[i] * 0.85)))

    # alt çizgi: yazı yazılan SON adımın son satırının altı çizilir
    ul_start = None
    last_x = last_y = 0.0
    last_w = 0.0
    last_base_y = 0
    for i in range(len(plans) - 1, -1, -1):
        if plans[i]:
            last_x, last_y, last_line = plans[i][-1]
            last_w = _line_w(ImageDraw.Draw(canvas), last_line, font, size)
            last_base_y = last_y + (int(size * 2) + 12 if _has_frac(last_line) else size + 8)
            ul_start = starts[i] + spans[i] + 0.15
            break

    n_frames = int(math.ceil(total * FPS)) + 1
    log(f"kalem: {n_frames} kare çiziliyor ({total:.1f} sn, {FPS} fps)")
    t_draw0 = time.time()
    for k in range(n_frames):
        t = k / FPS
        frame = canvas.copy()
        d = ImageDraw.Draw(frame)
        for i, pl in enumerate(plans):
            if t < starts[i]:
                break
            prog = min(1.0, (t - starts[i]) / spans[i])
            all_lines = [ln for _, _, ln in pl]
            total_chars = sum(len(ln) for ln in all_lines) or 1
            n_chars = int(prog * total_chars + 0.5)
            if n_chars <= 0:
                continue
            rem = n_chars
            for (lx, ly, ln) in pl:
                if rem <= 0:
                    break
                _draw_line(d, lx, ly, ln, font, size, rem)
                rem -= len(ln)
        # alt çizgi: son yazı tamamlandıktan sonra soldan sağa uzar
        if ul_start is not None and t >= ul_start:
            uprog = min(1.0, (t - ul_start) / 0.5)
            end_x = last_x + last_w * uprog
            xx = last_x
            while xx < end_x - 1:
                y1_ = last_base_y + int(math.sin(xx / 17.0) * 2)
                y2_ = last_base_y + int(math.sin((xx + 7) / 17.0) * 2)
                d.line([(xx, y1_), (min(xx + 7, end_x), y2_)], fill=INK, width=4)
                xx += 7
        frame.save(frames_dir / f"f_{k:05d}.jpg", quality=92)

    log(f"kalem: kareler bitti ({time.time() - t_draw0:.0f} sn) · ffmpeg ile videoya çevriliyor")
    args = [ffmpeg, "-y", "-v", "error", "-framerate", str(FPS),
            "-i", str(frames_dir / "f_%05d.jpg"),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)]
    proc = subprocess.run(args, capture_output=True, text=True, timeout=1800,
                          creationflags=NO_WINDOW)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-6:]
        raise RuntimeError("kalem videosu hatası:\n" + "\n".join(tail))
    shutil.rmtree(frames_dir, ignore_errors=True)  # kareler diskte kalmasın
    log(f"kalem videosu hazır: {out_path.name} ({total:.1f} sn)")
    return out_path
