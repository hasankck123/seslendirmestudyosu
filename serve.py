# -*- coding: utf-8 -*-
"""Seslendirme Stüdyosu — yerel web sunucusu.

Soru görseli seç / AI çözsün ya da adımları sen yaz / Antalia-2 Mini ile seslendir /
çözümü görselin üzerine kalemle yazan videoyu üret.

Uçlar (hepsi yerel):
  GET  /                     -> web arayüzü
  GET  /antalia/*            -> Antalia Mini motoru (COOP/COEP başlıklarıyla)
  GET  /api/state            -> durum
  GET  /api/browse?dir=      -> klasör gezme
  GET  /api/media?k=token    -> medya (Range destekli)
  POST /api/video            -> {mode:'path', path} soru görseli seç
  POST /api/video/upload?name=  -> gövdedeki baytlar görseli kaydeder
  POST /api/segments         -> adımları kaydet, okunuş önizlemelerini döndür
  POST /api/settings         -> ayarları kaydet
  POST /api/synth            -> sesleri üret
  POST /api/resynth          -> yalnız bir adımı yeni tonda yeniden oku
  POST /api/render           -> çözüm videosunu üret + sesi ekle (önizleme)
  POST /api/reset            -> görsel + adımlar + sonucu sıfırla
  GET  /api/net              -> telefon erişimi için adres bilgisi
  POST /api/openfolder       -> klasörü gezginde aç
  POST /__stop               -> sunucuyu ve motoru durdur (yalnız yerelden)

Güvenlik: Tüm POST uçları `X-Studio-Token` başlığı ister (CSRF). Telefon/LAN modunda
(0.0.0.0) Basic Auth şifresi de istenir; şifre work/password.txt'te tutulur.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import uuid
import wave
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

import ai_draft
from mathspeak import speak_math
from panel_video import build_panel_video
try:
    from handwrite_video import build_handwrite_video
except Exception:  # Pillow yoksa veya modül hatalıysa panel moduna düşülür
    build_handwrite_video = None
from tts_engine import AntaliaEngine
try:
    from voxcpm_engine import VoxcpmEngine
except Exception:  # VoxCPM2 kurulumu yoksa stüdyo Antalia ile çalışmaya devam eder
    VoxcpmEngine = None

APP_ID = "seslendirme-studyosu"
VERSION = "1.0"
HOST = "127.0.0.1"
DEFAULT_PORT = 8770

# Güvenlik: CSRF token, isteğe bağlı LAN şifresi, LAN'a bağlı mıyız?
STUDIO_TOKEN = uuid.uuid4().hex
PASSWORD = ""
LOCAL_IPS: list[str] = []
BOUND_ALL = False

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
ASSETS_DIR = ROOT / "assets"
ANT_DIR = ROOT / "antalia"
WORK_DIR = ROOT / "work"
UPLOAD_DIR = WORK_DIR / "uploads"
SEG_DIR = WORK_DIR / "segments"
LOG_FILE = WORK_DIR / "studio.log"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
SR = 48000

_log_lock = threading.Lock()


NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    with _log_lock:
        try:
            with LOG_FILE.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass
    try:
        print(line, flush=True)
    except Exception:
        pass


# --------------------------------------------------------------------------- yardımcılar
_FF_CACHE: dict[tuple[str, str], Path | None] = {}


def find_ffmpeg(name: str = "ffmpeg.exe", override: str = "") -> Path | None:
    key = (name, override or "")
    if key in _FF_CACHE:
        return _FF_CACHE[key]
    result = _find_ffmpeg_uncached(name, override)
    _FF_CACHE[key] = result
    return result


def _find_ffmpeg_uncached(name: str = "ffmpeg.exe", override: str = "") -> Path | None:
    cands: list[Path] = []
    if override:
        p = Path(override)
        cands.append(p if p.name.lower().endswith(".exe") else p / name)
    w = shutil.which(name[:-4])
    if w:
        cands.append(Path(w))
    la = os.environ.get("LOCALAPPDATA", "")
    if la:
        cands.append(Path(la) / "Microsoft" / "WinGet" / "Links" / name)
        pk = Path(la) / "Microsoft" / "WinGet" / "Packages"
        if pk.is_dir():
            try:
                cands += sorted(pk.glob(f"*FFmpeg*/**/bin/{name}"))
            except OSError:
                pass
    cands += [
        Path(r"C:\ffmpeg\bin") / name,
        Path(r"C:\Program Files\ffmpeg\bin") / name,
        Path(r"C:\ProgramData\chocolatey\bin") / name,
        ROOT / "ffmpeg" / name,
    ]
    for c in cands:
        try:
            if c.is_file():
                return c
        except OSError:
            continue
    return None


def ffprobe_duration(path: Path, ffprobe: Path | None) -> float | None:
    if not ffprobe:
        return None
    try:
        out = subprocess.run(
            [str(ffprobe), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW,
        )
        v = float(out.stdout.strip())
        return v if v > 0 else None
    except Exception:
        return None


def ffprobe_size(path: Path, ffprobe: Path | None) -> tuple[int, int] | None:
    if not ffprobe:
        return None
    try:
        out = subprocess.run(
            [str(ffprobe), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(path)],
            capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW,
        )
        w, h = (int(x) for x in out.stdout.strip().split("x")[:2])
        return (w, h) if w > 0 and h > 0 else None
    except Exception:
        return None


def unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    stem, suf, parent = p.stem, p.suffix, p.parent
    for i in range(2, 500):
        q = parent / f"{stem} ({i}){suf}"
        if not q.exists():
            return q
    return parent / f"{stem} ({uuid.uuid4().hex[:6]}){suf}"


def safe_name(name: str) -> str:
    name = Path(name).name
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip() or "gorsel.png"


def local_ipv4s() -> list[str]:
    """Bu bilgisayarın yerel ağ IPv4 adresleri (telefon erişimi için)."""
    ips: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
        except Exception:
            pass
        finally:
            s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    return ips


def tailscale_ipv4s() -> list[str]:
    """Tailscale (özel VPN) IPv4 adresleri — telefondan her yerden erişim için."""
    ips: list[str] = []
    exe = shutil.which("tailscale")
    if not exe:
        for c in (r"C:\Program Files\Tailscale\tailscale.exe",
                  r"C:\Program Files (x86)\Tailscale\tailscale.exe"):
            if os.path.isfile(c):
                exe = c
                break
    if not exe:
        return ips
    try:
        out = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True,
                             timeout=6, creationflags=NO_WINDOW)
        for line in (out.stdout or "").splitlines():
            line = line.strip()
            if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", line) and line not in ips:
                ips.append(line)
    except Exception:
        pass
    return ips


def load_password() -> str:
    """LAN erişim şifresini work/password.txt ya da STUDIO_PASSWORD ortam değişkeninden okur."""
    p = WORK_DIR / "password.txt"
    try:
        if p.is_file():
            return p.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return (os.environ.get("STUDIO_PASSWORD") or "").strip()


# --------------------------------------------------------------------------- durum
class State:
    def __init__(self) -> None:
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        SEG_DIR.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.render_lock = threading.Lock()
        self.settings: dict = {
            "speed": 0.95, "steps": 8, "gap": 0.2, "pen_style": True,
            "out_dir": str(Path.home() / "Desktop"), "ffmpeg": "",
        }
        self.video: dict | None = None
        self.segments: list[dict] = []
        self.last_result: dict | None = None
        self.fit_speed = 1.0  # anlatımın videoya sığdırılma oranı (1.0 = hızlandırma yok)
        self.media: dict[str, str] = {}
        self.media_rev: dict[str, str] = {}
        self._wf = WORK_DIR / "settings.json"
        self._sf = WORK_DIR / "state.json"
        self._load()

    # -------------------------------------------------- kalıcılık
    def _load(self) -> None:
        try:
            if self._wf.is_file():
                self.settings.update(json.loads(self._wf.read_text(encoding="utf-8")))
        except Exception as exc:
            log(f"ayarlar okunamadı: {exc}")
        try:
            if self._sf.is_file():
                d = json.loads(self._sf.read_text(encoding="utf-8"))
                vp = d.get("video_path")
                if vp and Path(vp).is_file():
                    self.set_video(Path(vp), persist=False)
                segs = d.get("segments") or []
                self.segments = []
                for s in segs:
                    seg = {"id": s.get("id") or uuid.uuid4().hex[:8], "text": s.get("text", ""),
                           "start": s.get("start"), "spoken": speak_math(s.get("text", ""))}
                    if isinstance(s.get("display"), str):
                        seg["display"] = s["display"]
                    wav = Path(str(s.get("wav") or ""))
                    if s.get("wav") and wav.is_file():
                        seg["wav"] = str(wav)
                        seg["dur"] = s.get("dur")
                        seg["key"] = s.get("key")
                        if not seg.get("dur"):
                            try:
                                with wave.open(str(wav), "rb") as wf:
                                    seg["dur"] = round(wf.getnframes() / wf.getframerate(), 3)
                            except Exception:
                                pass
                    self.segments.append(seg)
                self.fit_speed = float(d.get("fit_speed") or 1.0)
        except Exception as exc:
            log(f"durum okunamadı: {exc}")

    def _save(self) -> None:
        try:
            self._wf.write_text(json.dumps(self.settings, ensure_ascii=False, indent=1), encoding="utf-8")
            self._sf.write_text(json.dumps({
                "video_path": (self.video or {}).get("path"),
                "segments": [{"id": s["id"], "text": s.get("text", ""), "start": s.get("start"),
                              "dur": s.get("dur"), "wav": s.get("wav"), "key": s.get("key"),
                              "display": s.get("display")} for s in self.segments],
                "fit_speed": round(self.fit_speed, 3),
            }, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as exc:
            log(f"durum yazılamadı: {exc}")

    # -------------------------------------------------- medya jetonları
    def add_media(self, path: Path | str) -> str:
        key = str(Path(path).resolve())
        with self.lock:
            tok = self.media_rev.get(key)
            if not tok:
                tok = uuid.uuid4().hex[:12]
                self.media_rev[key] = tok
                self.media[tok] = key
            return tok

    def media_path(self, token: str) -> Path | None:
        with self.lock:
            p = self.media.get(token)
        return Path(p) if p and Path(p).is_file() else None

    # -------------------------------------------------- video
    def set_video(self, path: Path, persist: bool = True) -> dict:
        is_img = path.suffix.lower() in IMAGE_EXTS
        dur = None
        if not is_img:
            ffprobe = find_ffmpeg("ffprobe.exe", str(self.settings.get("ffmpeg") or ""))
            dur = ffprobe_duration(path, ffprobe)
        info = {"path": str(path), "name": path.name, "dur": dur, "token": self.add_media(path),
                "image": is_img}
        cleared = False
        with self.lock:
            old = (self.video or {}).get("path")
            # farklı bir videoya geçildiyse eski videonun anlatım adımları geçersizdir → sıfırla
            if old and old != info["path"] and self.segments:
                self.segments = []
                self.fit_speed = 1.0
                cleared = True
            self.video = info
            self.last_result = None
        info["cleared_segments"] = cleared
        if persist:
            self._save()
        return info

    # -------------------------------------------------- segment yardımcıları
    def spoken_of(self, seg: dict) -> str:
        return speak_math(seg.get("text", ""))

    def seg_public(self, seg: dict) -> dict:
        out = {k: seg.get(k) for k in ("id", "text", "start", "dur", "model_text", "spoken", "display")}
        wav = seg.get("wav")
        out["token"] = self.add_media(wav) if wav and Path(wav).is_file() else None
        return out


STATE = State()
ENGINE: AntaliaEngine | None = None
VOX = VoxcpmEngine(log=log) if VoxcpmEngine else None


# --------------------------------------------------------------------------- ses birleştirme
def read_wav_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wf:
        if wf.getsampwidth() != 2 or wf.getnchannels() != 1:
            raise RuntimeError(f"beklenmeyen WAV biçimi: {path.name}")
        return wf.readframes(wf.getnframes())


def autofit_starts(segments: list[dict], video_dur: float | None, gap: float) -> float:
    """Adım başlangıçlarını videoya sığacak şekilde otomatik dizer.

    Sesler toplamda videodan uzunsa zaman çizelgesi sıkıştırılır; kayıt sırasında
    aynı oranda `atempo` (perde korunur) uygulanır ve anlatım videoya tam sığar.
    Dönüş: sıkıştırma oranı (1.0 = gerek yok)."""
    gap = max(0.05, min(2.0, float(gap or 0.2)))
    segs = [s for s in segments if (s.get("text") or "").strip()]
    if not segs:
        return 1.0
    durs = []
    for s in segs:
        d = s.get("dur")
        if d in (None, ""):
            d = len(s.get("spoken") or s.get("text") or "") * 0.075 + 0.4
        durs.append(max(0.2, float(d)))
    end = sum(durs) + gap * max(0, len(segs) - 1)
    k = 1.0
    if video_dur and video_dur > 1.0:
        k = min(1.45, max(1.0, (end + 0.3) / video_dur))
    t = 0.0
    for s, d in zip(segs, durs):
        s["start"] = round(t / k, 2)
        t += d + gap
    return round(k, 3)


def assemble(segments: list[dict], gap: float, video_dur: float | None) -> tuple[Path, list[dict], list[str]]:
    """Segmentleri zaman çizgisine yerleştirir ve tek WAV yazar."""
    placements: list[dict] = []
    warnings: list[str] = []
    out = bytearray()
    cursor = 0.0
    for i, seg in enumerate(segments):
        pcm = read_wav_pcm(Path(seg["wav"]))
        dur = len(pcm) / 2 / SR
        want = seg.get("start")
        want = float(want) if want not in (None, "") else (cursor + (gap if i else 0.0))
        eff = max(want, cursor + gap) if i else max(want, 0.0)
        off = int(round(eff * SR)) * 2
        if off + len(pcm) > len(out):
            out.extend(b"\x00" * (off + len(pcm) - len(out)))
        out[off:off + len(pcm)] = pcm
        cursor = eff + dur
        placements.append({"id": seg["id"], "want": round(want, 3), "start": round(eff, 3), "dur": round(dur, 3)})
    total_s = max(cursor + 0.3, (video_dur or 0.0))
    need = int(round(total_s * SR)) * 2
    if need > len(out):
        out.extend(b"\x00" * (need - len(out)))
    final = WORK_DIR / "final.wav"
    with wave.open(str(final), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(bytes(out))
    if video_dur and cursor > video_dur + 0.05:
        warnings.append(
            f"Ses videodan {cursor - video_dur:.1f} sn uzun. Videoya eklenen sürümde ses video sonunda kesilir; "
            "adım başlangıçlarını öne çekebilirsiniz."
        )
    return final, placements, warnings


def run_ffmpeg(args: list[str]) -> None:
    ffmpeg = find_ffmpeg("ffmpeg.exe", str(STATE.settings.get("ffmpeg") or ""))
    if not ffmpeg:
        raise RuntimeError("ffmpeg bulunamadı. Kurulum: winget install Gyan.FFmpeg")
    proc = subprocess.run([str(ffmpeg)] + args, capture_output=True, text=True, timeout=1800,
                          creationflags=NO_WINDOW)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-6:]
        raise RuntimeError("ffmpeg hatası:\n" + "\n".join(tail))


def narration_txt(video_name: str, placements: list[dict], segments: list[dict], total: float, video_dur: float | None, fit_speed: float = 1.0) -> str:
    by_id = {s["id"]: s for s in segments}
    lines = [
        f"Videoya Seslendirme Metni — {video_name}",
        f"Toplam ses: {total:.2f} sn · Video: {video_dur:.2f} sn" if video_dur else f"Toplam ses: {total:.2f} sn",
        "",
    ]
    if fit_speed and fit_speed > 1.01:
        lines.append(
            f"Not: anlatım videoya sığsın diye %{round((fit_speed - 1) * 100)} hızlandırıldı; "
            "aşağıdaki süreler videodaki nihai zamanlardır.")
        lines.append("")
    for p in placements:
        seg = by_id.get(p["id"], {})
        m, s = divmod(p["start"], 60)
        lines.append(f"[{int(m):02d}:{s:05.2f}] {seg.get('text','').strip()}")
        spoken = seg.get("spoken") or ""
        if spoken and spoken != seg.get("text", "").strip():
            lines.append(f"        (okunuş: {spoken})")
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"{APP_ID}/{VERSION}"

    # -------------------------------------------------- temel
    def log_message(self, fmt, *args):  # gürültüyü dosyaya yaz
        log("http " + (fmt % args))

    def _json(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, code: int = 500) -> None:
        self._json({"error": message}, code)

    # -------------------------------------------------- güvenlik
    def _auth_ok(self) -> bool:
        """LAN modunda Basic Auth şifresi doğru mu? (Yerel modda hiç sorulmaz.)"""
        if not (BOUND_ALL and PASSWORD):
            return True
        # Bu bilgisayarın kendisi (motor + yerel tarayıcı) şifre istemez;
        # şifre yalnızca ağdan (telefondan) gelen istekler için geçerlidir.
        if (self.client_address[0] if self.client_address else "") in ("127.0.0.1", "::1"):
            return True
        hdr = self.headers.get("Authorization") or ""
        if not hdr.startswith("Basic "):
            return False
        try:
            raw = base64.b64decode(hdr[6:]).decode("utf-8", "replace")
        except Exception:
            return False
        _, _, pw = raw.partition(":")
        return hmac.compare_digest(pw, PASSWORD)

    def _unauthorized(self) -> None:
        body = "Yetkisiz erisim".encode("utf-8")
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Seslendirme Studyosu"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _csrf_ok(self) -> bool:
        """Sahte sitelerin yerel sunucuya istek atmasını engeller (token + Origin)."""
        if (self.headers.get("X-Studio-Token") or "") != STUDIO_TOKEN:
            return False
        origin = self.headers.get("Origin")
        if origin:
            try:
                oh = urlparse(origin).hostname or ""
            except Exception:
                return False
            req_host = (self.headers.get("Host") or "").split(":")[0]
            if oh not in ("127.0.0.1", "localhost", "::1") and oh != req_host and oh not in LOCAL_IPS:
                return False
        return True

    def _send_html(self, path: Path) -> None:
        """index.html'i servis ederken CSRF token'ını sayfaya gömer."""
        try:
            html = path.read_text(encoding="utf-8")
        except OSError:
            return self._error("bulunamadı", 404)
        body = html.replace("__STUDIO_TOKEN__", STUDIO_TOKEN).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body_json(self) -> dict:
        raw = self._read_body()
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            return {}

    def _read_body(self) -> bytes:
        """İstek gövdesini bir kez oku ve önbelleğe al.

        Önemli: keep-alive bağlantısında gövde tüketilmezse kalan baytlar bir
        sonraki isteğin satırına yapışır ('{}GET ...') ve 501'e yol açar.
        """
        if getattr(self, "_cached_body", None) is None:
            n = int(self.headers.get("Content-Length") or 0)
            self._cached_body = self.rfile.read(n) if n > 0 else b""
        return self._cached_body

    def _ctype(self, p: Path) -> str:
        return {
            ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8", ".wav": "audio/wav", ".mp3": "audio/mpeg",
            ".mp4": "video/mp4", ".webm": "video/webm", ".svg": "image/svg+xml",
            ".wasm": "application/wasm", ".gz": "application/gzip", ".onnx": "application/octet-stream",
            ".png": "image/png", ".ico": "image/x-icon", ".txt": "text/plain; charset=utf-8",
            ".webmanifest": "application/manifest+json",
        }.get(p.suffix.lower(), "application/octet-stream")

    # -------------------------------------------------- dosya sunumu (Range destekli)
    def _send_file(self, path: Path, extra_headers: dict | None = None, allow_range: bool = True) -> None:
        try:
            size = path.stat().st_size
        except OSError:
            return self._error("dosya bulunamadı", 404)
        ctype = self._ctype(path)
        start, end = 0, size - 1
        code = 200
        rng = self.headers.get("Range") if allow_range else None
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)$", rng.strip())
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else size - 1
                else:  # son X bayt
                    start = max(0, size - int(m.group(2)))
                end = min(end, size - 1)
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                code = 206
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            with path.open("rb") as fh:
                fh.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = fh.read(min(65536, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    # -------------------------------------------------- GET
    def do_GET(self):
        self._cached_body = None  # her istekte gövde önbelleğini sıfırla (keep-alive)
        try:
            self._do_get()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception:
            log("GET hata:\n" + traceback.format_exc())
            try:
                self._error("sunucu hatası")
            except Exception:
                pass

    def _do_get(self):
        u = urlparse(self.path)
        p, qs = u.path, parse_qs(u.query)

        if p != "/__health" and not self._auth_ok():
            return self._unauthorized()
        if p == "/__health":
            return self._json({"app": APP_ID, "version": 1, "pid": os.getpid(), "port": self.server.server_port})
        if p == "/" or p == "/index.html":
            return self._send_html(WEB_DIR / "index.html")
        if p == "/api/net":
            return self._json(self.api_net())
        if p.startswith("/web/"):
            f = (WEB_DIR / p[5:]).resolve()
            if WEB_DIR.resolve() in f.parents and f.is_file():
                return self._send_file(f, {"Cache-Control": "no-store"})
            return self._error("bulunamadı", 404)
        if p.startswith("/assets/"):
            f = (ASSETS_DIR / p[len("/assets/"):]).resolve()
            if ASSETS_DIR.resolve() in f.parents and f.is_file():
                return self._send_file(f, {"Cache-Control": "no-store"})
            return self._error("bulunamadı", 404)
        if p.startswith("/antalia/"):
            f = (ANT_DIR / p[len("/antalia/"):]).resolve()
            if ANT_DIR.resolve() in f.parents and f.is_file():
                return self._send_file(f, {
                    "Cross-Origin-Opener-Policy": "same-origin",
                    "Cross-Origin-Embedder-Policy": "require-corp",
                    "Cross-Origin-Resource-Policy": "same-origin",
                })
            return self._error("bulunamadı", 404)
        if p == "/api/state":
            return self._json(self.api_state())
        if p == "/api/browse":
            return self._json(self.api_browse(qs.get("dir", [""])[0]))
        if p == "/api/media":
            tok = (qs.get("k") or [""])[0]
            path = STATE.media_path(tok)
            if not path:
                return self._error("medya bulunamadı", 404)
            if (qs.get("dl") or [""])[0]:
                raw = (qs.get("name") or [""])[0]
                name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(raw).name).strip() or path.name
                ascii_name = re.sub(r'[^\x20-\x7e]', "_", name).replace('"', "'")
                disp = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
                return self._send_file(path, {"Content-Disposition": disp})
            return self._send_file(path)
        if p == "/api/narration":
            res = STATE.last_result or {}
            if res.get("txt") and Path(res["txt"]).is_file():
                txt = Path(res["txt"])
                if (qs.get("dl") or [""])[0]:
                    name = txt.name
                    ascii_name = re.sub(r'[^\x20-\x7e]', "_", name).replace('"', "'")
                    disp = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
                    return self._send_file(txt, {"Content-Disposition": disp})
                return self._send_file(txt)
            return self._error("metin yok", 404)
        return self._error("bulunamadı", 404)

    def api_state(self) -> dict:
        with STATE.lock:
            segs = [STATE.seg_public(s) for s in STATE.segments]
            video = dict(STATE.video) if STATE.video else None
            engine = ENGINE.status() if ENGINE else {"state": "off", "message": "", "info": None}
            result = None
            if STATE.last_result:
                r = STATE.last_result
                result = {
                    "dir": r.get("dir"),
                    "mp4": {"path": r["mp4"], "token": STATE.add_media(r["mp4"])} if r.get("mp4") else None,
                    "wav": {"path": r["wav"], "token": STATE.add_media(r["wav"])} if r.get("wav") else None,
                    "mp3": {"path": r["mp3"], "token": STATE.add_media(r["mp3"])} if r.get("mp3") else None,
                    "txt": r.get("txt"),
                    "total": r.get("total"),
                    "video_dur": (video or {}).get("dur"),
                    "warnings": r.get("warnings") or [],
                    "placements": r.get("placements") or [],
                    "fit_speed": r.get("fit_speed"),
                    "saved": r.get("saved"),
                    "saved_dir": r.get("saved_dir"),
                }
            return {
                "app": APP_ID, "version": VERSION,
                "engine": engine,
                "vox": VOX.status() if VOX else {"state": "off", "message": "VoxCPM2 kurulu değil"},
                "vox_sesler": VOX.sesler() if VOX else [],
                "ffmpeg": bool(find_ffmpeg("ffmpeg.exe", str(STATE.settings.get("ffmpeg") or ""))),
                "video": video, "segments": segs,
                "settings": dict(STATE.settings), "result": result,
                "fit_speed": round(getattr(STATE, "fit_speed", 1.0), 3),
            }

    def api_net(self) -> dict:
        """Telefon erişimi için adres bilgisi (LAN + Tailscale)."""
        port = self.server.server_port
        lan = list(LOCAL_IPS)
        ts = [ip for ip in tailscale_ipv4s() if ip not in lan]
        return {
            "port": port,
            "bound_all": BOUND_ALL,
            "ips": lan,
            "ts_ips": ts,
            "urls": [f"http://{ip}:{port}/" for ip in lan],
            "ts_urls": [f"http://{ip}:{port}/" for ip in ts],
            "password_required": bool(BOUND_ALL and PASSWORD),
        }

    def api_browse(self, d: str) -> dict:
        try:
            base = Path(d).expanduser() if d else Path.home() / "Desktop"
            base = base.resolve()
        except Exception:
            base = Path.home()
        if not base.is_dir():
            drives = [f"{c}:/" for c in "CDEFGH" if Path(f"{c}:/").exists()]
            return {"dir": "", "parent": None, "dirs": drives, "files": [], "drives_mode": True}
        dirs, files = [], []
        try:
            for e in sorted(base.iterdir(), key=lambda x: x.name.lower()):
                try:
                    if e.is_dir() and not e.name.startswith(("$", ".")):
                        dirs.append({"name": e.name, "path": str(e)})
                    elif e.is_file() and e.suffix.lower() in IMAGE_EXTS:
                        files.append({"name": e.name, "path": str(e), "size": e.stat().st_size})
                except OSError:
                    continue
        except PermissionError:
            pass
        parent = str(base.parent) if base.parent != base else None
        return {"dir": str(base), "parent": parent, "dirs": dirs, "files": files}

    # -------------------------------------------------- POST
    def do_POST(self):
        self._cached_body = None  # her istekte gövde önbelleğini sıfırla (keep-alive)
        try:
            self._do_post()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as exc:
            log("POST hata:\n" + traceback.format_exc())
            try:
                self._error(str(exc))
            except Exception:
                pass

    def _do_post(self):
        u = urlparse(self.path)
        p, qs = u.path, parse_qs(u.query)
        if p != "/api/video/upload":
            self._read_body()  # gövdeyi her koşulda tüket (yükleme kendi akışını okur)

        if p == "/__stop":
            # yalnızca bu bilgisayardan durdurulabilir (LAN'dan kapatılamaz)
            if (self.client_address[0] if self.client_address else "") not in ("127.0.0.1", "::1"):
                return self._error("yasak", 403)
            self._json({"app": APP_ID, "stopping": True})
            def _later():
                time.sleep(0.3)
                if ENGINE:
                    ENGINE.stop()
                self.server.shutdown()
            threading.Thread(target=_later, daemon=True).start()
            return

        if not self._auth_ok():
            return self._unauthorized()
        if not self._csrf_ok():
            return self._error("geçersiz istek (CSRF koruması)", 403)

        if p == "/api/video":
            d = self._body_json()
            mode = d.get("mode")
            if mode == "path":
                path = Path(str(d.get("path") or "").strip().strip('"'))
                if not path.is_file() or path.suffix.lower() not in IMAGE_EXTS:
                    return self._error("Soru görseli bulunamadı ya da desteklenmeyen biçim (jpg/png bekleniyor).", 400)
                with STATE.lock:
                    info = STATE.set_video(path)
                    if STATE.settings.get("out_dir") in ("", str(Path.home() / "Desktop")) and path.parent.is_dir():
                        STATE.settings["out_dir"] = str(path.parent)
                    STATE._save()
                return self._json({"ok": True, "video": info})
            return self._error("bilinmeyen mod", 400)

        if p == "/api/video/upload":
            name = safe_name((qs.get("name") or ["gorsel.png"])[0])
            # akışı dosyaya yaz (büyük videolar için parça parça)
            dest = UPLOAD_DIR / f"{uuid.uuid4().hex[:6]}_{name}"
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0:
                return self._error("boş yükleme", 400)
            left = n
            with dest.open("wb") as fh:
                while left > 0:
                    chunk = self.rfile.read(min(1 << 20, left))
                    if not chunk:
                        break
                    fh.write(chunk)
                    left -= len(chunk)
            if dest.suffix.lower() not in IMAGE_EXTS:
                dest.unlink(missing_ok=True)
                return self._error("Yalnızca soru görseli yükleyebilirsin (jpg/png/webp/bmp).", 400)
            with STATE.lock:
                info = STATE.set_video(dest)
                if STATE.settings.get("out_dir") in ("", str(Path.home() / "Desktop")):
                    STATE.settings["out_dir"] = str(Path.home() / "Desktop")
                STATE._save()
            return self._json({"ok": True, "video": info})

        if p == "/api/settings":
            d = self._body_json()
            with STATE.lock:
                for k in ("speed", "steps", "gap", "out_dir", "ffmpeg", "pen_style",
                          "seed", "ai_length", "ai_audience", "ai_hook", "ai_model",
                          "tts_motor", "vox_ses"):
                    if k in d:
                        STATE.settings[k] = d[k]
                STATE._save()
            return self._json({"ok": True, "settings": dict(STATE.settings)})

        if p == "/api/segments":
            d = self._body_json()
            incoming = d.get("segments") or []
            with STATE.lock:
                old = {s["id"]: s for s in STATE.segments}
                segs = []
                for s in incoming:
                    sid = str(s.get("id") or uuid.uuid4().hex[:8])
                    text = str(s.get("text") or "")
                    start = s.get("start")
                    prev = old.get(sid, {})
                    keep = prev if prev.get("text") == text and prev.get("spoken") == speak_math(text) else None
                    seg = {"id": sid, "text": text, "start": start, "spoken": speak_math(text)}
                    if keep:
                        for k in ("wav", "dur", "model_text", "key"):
                            if k in keep:
                                seg[k] = keep[k]
                    # tahtaya yazılacak yazı: boş/verilmemiş = otomatik, "-" = yazı yok
                    if "display" in s:
                        dv = s.get("display")
                        if isinstance(dv, str) and dv.strip():
                            seg["display"] = dv.strip()
                    elif keep and "display" in keep:
                        seg["display"] = keep["display"]
                    segs.append(seg)
                STATE.segments = segs
                STATE._save()
                pub = [STATE.seg_public(s) for s in segs]
            return self._json({"ok": True, "segments": pub})

        if p == "/api/ai_draft":
            return self._json(self.api_ai_draft())

        if p == "/api/synth":
            return self._json(self.api_synth())

        if p == "/api/resynth":
            return self._json(self.api_resynth(self._body_json()))

        if p == "/api/reset":
            return self._json(self.api_reset())

        if p == "/api/render":
            return self._json(self.api_render())

        if p == "/api/save":
            return self._json(self.api_save())

        if p == "/api/openfolder":
            d = self._body_json()
            target = Path(str(d.get("path") or STATE.settings.get("out_dir") or ""))
            if target.is_file():
                target = target.parent
            if target.is_dir():
                try:
                    os.startfile(str(target))  # type: ignore[attr-defined]
                except Exception as exc:
                    return self._error(f"klasör açılamadı: {exc}")
                return self._json({"ok": True})
            return self._error("klasör yok", 404)

        return self._error("bulunamadı", 404)

    # -------------------------------------------------- işlemler
    def api_ai_draft(self) -> dict:
        with STATE.render_lock:
            with STATE.lock:
                video = dict(STATE.video or {})
                model = str(STATE.settings.get("ai_model") or "") or None
                style = {k: STATE.settings.get(k) for k in ("ai_length", "ai_audience", "ai_hook")}
            if not video.get("path"):
                return {"error": "önce bir soru görseli seçin"}
            if not video.get("image"):
                return {"error": "bu sürüm yalnızca soru görselleriyle çalışır"}
            if not Path(video["path"]).is_file():
                return {"error": "görsel dosyası bulunamadı"}
            log("ai: soru görseli inceleniyor ve ücretsiz model çağrılıyor…")
            try:
                res = ai_draft.generate_draft(
                    video["path"], video.get("dur"),
                    find_ffmpeg("ffmpeg.exe", str(STATE.settings.get("ffmpeg") or "")),
                    WORK_DIR, model=model, style=style,
                )
            except Exception as exc:
                log(f"ai hata: {exc}")
                return {"error": str(exc)}
            segs = []
            for s in res["segments"]:
                text = str(s.get("text") or "").strip()
                if not text:
                    continue
                seg = {
                    "id": uuid.uuid4().hex[:8],
                    "text": text,
                    "start": s.get("start"),
                    "spoken": speak_math(text),
                }
                if isinstance(s.get("display"), str):
                    seg["display"] = s["display"]
                segs.append(seg)
            with STATE.lock:
                STATE.segments = segs
                STATE._save()
                pub = [STATE.seg_public(s) for s in STATE.segments]
            log(f"ai taslak: {len(pub)} adım · {res['seconds']} sn · {res['model']}")
            return {"ok": True, "segments": pub, "frames": res["frames"],
                    "seconds": res["seconds"], "model": res["model"]}

    def api_synth(self) -> dict:
        motor_secim = str(STATE.settings.get("tts_motor") or "antalia")
        vox_ses = str(STATE.settings.get("vox_ses") or "hazir/belgesel_hanim")
        if motor_secim == "voxcpm":
            if not VOX:
                return {"error": "VoxCPM2 modülü yok (voxcpm_engine.py)"}
            st = VOX.status()
        else:
            if not ENGINE:
                return {"error": "motor yok"}
            st = ENGINE.status()
        if st["state"] != "ready":
            return {"error": st["message"] or "motor hazır değil"}
        with STATE.render_lock:
            with STATE.lock:
                segs = STATE.segments
                if not segs:
                    return {"error": "önce adım ekleyin"}
                speed = float(STATE.settings.get("speed", 0.95))
                steps = int(STATE.settings.get("steps", 8))
                seed = int(STATE.settings.get("seed", 0) or 0)

            todo = []
            for s in segs:
                spoken = s.get("spoken") or speak_math(s.get("text") or "")
                if not spoken.strip():
                    continue
                key = hashlib.sha1(f"{spoken}|{speed}|{steps}|{seed}|{motor_secim}|{vox_ses}".encode("utf-8")).hexdigest()[:16]
                if s.get("key") == key and s.get("wav") and Path(s["wav"]).is_file():
                    continue
                todo.append({"id": s["id"], "text": spoken, "_key": key})

            if todo:
                log(f"synth: {len(todo)} adım üretiliyor (motor {motor_secim}, hız {speed}, adım {steps}, ton {seed})")
                if motor_secim == "voxcpm":
                    results = VOX.synth(todo, vox_ses)
                else:
                    results = ENGINE.synth(todo, steps=steps, speed=speed, seed=seed)
                by_id = {r["id"]: r for r in results}
                with STATE.lock:
                    for s in STATE.segments:
                        r = by_id.get(s["id"])
                        if not r:
                            continue
                        wav_path = SEG_DIR / f"seg_{s['id']}.wav"
                        wav_path.write_bytes(base64.b64decode(r["wav"]))
                        s["wav"] = str(wav_path)
                        s["dur"] = round(r["seconds"], 3)
                        s["model_text"] = r["modelText"]
                        todo_key = next((t["_key"] for t in todo if t["id"] == s["id"]), None)
                        if todo_key:
                            s["key"] = todo_key
                    STATE._save()
            with STATE.lock:
                video_dur = (STATE.video or {}).get("dur")
                fit = autofit_starts(STATE.segments, video_dur, STATE.settings.get("gap", 0.2))
                STATE.fit_speed = fit
                STATE._save()
                pub = [STATE.seg_public(s) for s in STATE.segments]
                total = sum((s.get("dur") or 0) for s in STATE.segments)
            log(f"synth: {len(pub)} adım · toplam {total:.1f} sn · sığdırma x{fit}")
            return {"ok": True, "segments": pub, "total": round(total, 3),
                    "video_dur": video_dur, "fit_speed": fit}

    def api_render(self) -> dict:
        with STATE.render_lock:
            with STATE.lock:
                if not STATE.video:
                    return {"error": "önce bir soru görseli seçin"}
                if not STATE.video.get("image"):
                    return {"error": "bu sürüm yalnızca soru görselleriyle çalışır"}
                segs = [s for s in STATE.segments if (s.get("text") or "").strip()]
                if not segs:
                    return {"error": "önce anlatım adımlarını yazın"}
                missing = [s["id"] for s in segs if not (s.get("wav") and Path(s["wav"]).is_file())]
                if missing:
                    return {"error": "önce sesleri oluşturun (eksik adımlar var)"}
                gap = float(STATE.settings.get("gap", 0.2))
                video = dict(STATE.video)

            log("render: ses birleştiriliyor")
            final_wav, placements, warnings = assemble(segs, gap, video.get("dur"))

            # Anlatım videodan uzunsa otomatik sığdır: sesi atempo ile hafifçe hızlandır (perde korunur)
            fit_speed = 1.0
            vdur = float(video.get("dur") or 0.0)
            last_end = (placements[-1]["start"] + placements[-1]["dur"]) if placements else 0.0
            if vdur > 1.0 and last_end > 0:
                fit_speed = min(1.45, max(1.0, (last_end + 0.3) / vdur))
            if fit_speed >= 1.005:
                fitted = WORK_DIR / "final_fit.wav"
                run_ffmpeg(["-y", "-v", "error", "-i", str(final_wav),
                            "-filter:a", f"atempo={fit_speed:.4f}", str(fitted)])
                final_wav = fitted
                placements = [{**p, "start": round(p["start"] / fit_speed, 3),
                               "dur": round(p["dur"] / fit_speed, 3)} for p in placements]
                end_final = (placements[-1]["start"] + placements[-1]["dur"]) if placements else 0.0
                warnings = []
                if end_final > vdur - 0.05:
                    warnings.append(
                        f"Ses, %{round((fit_speed - 1) * 100)} hızlandırmaya rağmen videodan "
                        f"{end_final - vdur:.1f} sn uzun. Metni kısaltmayı dene.")
                log(f"render: anlatım videoya sığdırıldı (x{fit_speed:.3f})")
            else:
                fit_speed = 1.0

            # önizleme çıktıları çalışma klasörüne yazılır; kaydetme ayrı adımdır
            # (eski dosyalar render bitene kadar yerinde kalır; yeni render aynı adların üzerine yazar,
            #  sonra farklı adlı eskiler temizlenir — oynatıcılar geçici 404 görmez)
            prev_dir = WORK_DIR / "preview"
            prev_dir.mkdir(parents=True, exist_ok=True)
            stem = re.sub(r"^[0-9a-f]{6}_", "", Path(video["name"]).stem) or Path(video["name"]).stem
            disp = re.sub(r"^[0-9a-f]{6}_", "", video["name"]) or video["name"]
            names = {
                "mp4": f"{stem}_seslendirmeli.mp4",
                "wav": f"{stem}_ses.wav",
                "mp3": f"{stem}_ses.mp3",
                "txt": f"{stem}_seslendirme_metni.txt",
            }
            mp4 = prev_dir / names["mp4"]
            wav_out = prev_dir / names["wav"]
            mp3_out = prev_dir / names["mp3"]
            txt_out = prev_dir / names["txt"]

            use_pen = build_handwrite_video is not None and bool(STATE.settings.get("pen_style", True))
            log("render: soru görselinden çözüm videosu oluşturuluyor ("
                + ("kalemle soru üzerine yazılıyor)" if use_pen else "adım panelleri hazırlanıyor)"))
            try:
                if use_pen:
                    base = build_handwrite_video(
                        Path(video["path"]), WORK_DIR / "base_video.mp4", placements, segs,
                        WORK_DIR / "write_frames",
                        ffmpeg=find_ffmpeg("ffmpeg.exe", str(STATE.settings.get("ffmpeg") or "")),
                        log=log)
                else:
                    base = build_panel_video(
                        Path(video["path"]), WORK_DIR / "base_video.mp4", placements, segs,
                        find_ffmpeg("ffmpeg.exe", str(STATE.settings.get("ffmpeg") or "")),
                        find_ffmpeg("ffprobe.exe", str(STATE.settings.get("ffmpeg") or "")),
                        log=log)
            except Exception as exc:
                log(f"görsel video hata: {exc}")
                return {"error": f"görselden video oluşturulamadı: {exc}"}
            mux_src = str(base)
            log("render: video+ses birleştiriliyor (ffmpeg)")
            run_ffmpeg(["-y", "-v", "error", "-i", mux_src, "-i", str(final_wav),
                        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(mp4)])
            log("render: mp3 yazılıyor")
            run_ffmpeg(["-y", "-v", "error", "-i", str(final_wav), "-codec:a", "libmp3lame", "-b:a", "192k", str(mp3_out)])
            shutil.copy2(final_wav, wav_out)

            total = None
            with wave.open(str(final_wav), "rb") as wf:
                total = wf.getnframes() / wf.getframerate()
            txt_out.write_text(
                narration_txt(disp, placements, segs, total, video.get("dur"), fit_speed),
                encoding="utf-8",
            )

            # aynı adla yazılmayan eski önizleme dosyalarını temizle
            keep = set(names.values())
            for f in prev_dir.iterdir():
                if f.is_file() and f.name not in keep:
                    try:
                        f.unlink()
                    except OSError:
                        pass

            with STATE.lock:
                STATE.fit_speed = round(fit_speed, 3)
                STATE.last_result = {
                    "dir": str(prev_dir), "mp4": str(mp4), "wav": str(wav_out), "mp3": str(mp3_out),
                    "txt": str(txt_out), "placements": placements, "warnings": warnings, "total": round(total, 3),
                    "fit_speed": round(fit_speed, 3), "names": names, "saved": None, "saved_dir": None,
                }
                res = {
                    "dir": str(prev_dir),
                    "mp4": {"path": str(mp4), "token": STATE.add_media(mp4)},
                    "wav": {"path": str(wav_out), "token": STATE.add_media(wav_out)},
                    "mp3": {"path": str(mp3_out), "token": STATE.add_media(mp3_out)},
                    "txt": str(txt_out),
                    "total": round(total, 3),
                    "video_dur": video.get("dur"),
                    "warnings": warnings,
                    "placements": placements,
                    "fit_speed": round(fit_speed, 3),
                    "saved": None,
                }
            log(f"render tamam (önizleme): {mp4.name}")
            return {"ok": True, "result": res, "placements": placements, "warnings": warnings,
                    "total": round(total, 3), "video_dur": video.get("dur"),
                    "fit_speed": round(fit_speed, 3)}

    def api_save(self) -> dict:
        """Önizlemede oluşan dosyaları kullanıcının kayıt klasörüne kopyalar."""
        with STATE.render_lock:
            with STATE.lock:
                r = STATE.last_result
                if not r or not r.get("mp4"):
                    return {"error": "önce “Videoya ekle” ile önizlemeyi oluştur"}
                if r.get("saved"):
                    return {"ok": True, "saved": r["saved"], "already": True}
                names = r.get("names") or {}
                video = dict(STATE.video or {})
                out_dir = Path(str(STATE.settings.get("out_dir") or "")).expanduser()
                if not out_dir.is_dir():
                    vp = Path(video.get("path") or "").resolve()
                    base = vp.parent if vp.name else Path.home() / "Desktop"
                    out_dir = Path.home() / "Desktop" if base == UPLOAD_DIR.resolve() else base
                if not out_dir.is_dir():
                    out_dir = Path.home() / "Desktop"
                # yalnızca birleştirilmiş videoyu kaydet (ses/metin dosyaları kaydedilmez)
                mp4_target = unique_path(out_dir / (names.get("mp4") or "seslendirmeli.mp4"))
                src = r.get("mp4")
                if src and Path(src).is_file():
                    shutil.copy2(src, mp4_target)
                saved = {"dir": str(out_dir), "mp4": str(mp4_target)}
                r["saved"] = saved
                r["saved_dir"] = str(out_dir)
            log(f"kaydedildi: {saved['dir']} → {mp4_target.name}")
            return {"ok": True, "saved": saved}

    def api_resynth(self, d: dict) -> dict:
        """Tek bir adımı yeni bir ton/varyasyonla (seed) yeniden okur."""
        motor_secim = str(STATE.settings.get("tts_motor") or "antalia")
        vox_ses = str(STATE.settings.get("vox_ses") or "hazir/belgesel_hanim")
        if motor_secim == "voxcpm":
            if not VOX:
                return {"error": "VoxCPM2 modülü yok (voxcpm_engine.py)"}
            st = VOX.status()
        else:
            if not ENGINE:
                return {"error": "motor yok"}
            st = ENGINE.status()
        if st["state"] != "ready":
            return {"error": st["message"] or "motor hazır değil"}
        sid = str(d.get("id") or "")
        raw_seed = d.get("seed")
        with STATE.render_lock:
            with STATE.lock:
                seg = next((s for s in STATE.segments if s["id"] == sid), None)
                if not seg:
                    return {"error": "adım bulunamadı"}
                speed = float(STATE.settings.get("speed", 0.95))
                steps = int(STATE.settings.get("steps", 8))
                spoken = seg.get("spoken") or speak_math(seg.get("text") or "")
                if not spoken.strip():
                    return {"error": "bu adımda okunacak metin yok"}
            try:
                seed = int(raw_seed)
            except (TypeError, ValueError):
                seed = int(time.time()) % 100000
            log(f"resynth: {sid} (ton {seed})")
            if motor_secim == "voxcpm":
                results = VOX.synth([{"id": sid, "text": spoken}], vox_ses)
            else:
                results = ENGINE.synth([{"id": sid, "text": spoken}], steps=steps, speed=speed, seed=seed)
            r = results[0]
            # her okuma ayrı dosyaya yazılır → tarayıcı eski sesi önbellekten çalmaz
            wav_path = SEG_DIR / f"seg_{sid}_r{int(time.time() * 1000) % 1000000}.wav"
            wav_path.write_bytes(base64.b64decode(r["wav"]))
            with STATE.lock:
                seg["wav"] = str(wav_path)
                seg["dur"] = round(r["seconds"], 3)
                seg["model_text"] = r["modelText"]
                seg.pop("key", None)  # sonraki tam üretimde yeniden hesaplansın
                STATE._save()
                pub = STATE.seg_public(seg)
            return {"ok": True, "segment": pub}

    def api_reset(self) -> dict:
        """Yeni bir soruya başlamak için görsel + adımlar + sonuç sıfırlanır."""
        with STATE.render_lock:
            with STATE.lock:
                STATE.video = None
                STATE.segments = []
                STATE.last_result = None
                STATE.fit_speed = 1.0
                STATE._save()
        log("durum sıfırlandı (yeni soru)")
        return {"ok": True}


# --------------------------------------------------------------------------- main
class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return  # istemci bağlantıyı kapattı (video araması vb.) — gürültü yapma
        super().handle_error(request, client_address)


def stop_existing(port: int, timeout: float = 3.0) -> bool:
    try:
        req = urllib.request.Request(f"http://{HOST}:{port}/__stop", data=b"", method="POST")
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout) as r:
            d = json.load(r)
            return d.get("app") == APP_ID
    except Exception:
        return False


def main() -> None:
    global ENGINE, PASSWORD, BOUND_ALL, LOCAL_IPS
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default=HOST, help="Dinlenecek adres; telefondan erişim için 0.0.0.0")
    ap.add_argument("--open-browser", action="store_true")
    ap.add_argument("--stop", action="store_true")
    args = ap.parse_args()

    if args.stop:
        ok = stop_existing(args.port)
        print("Sunucu durduruldu." if ok else "Çalışan sunucu bulunamadı.")
        return

    LOCAL_IPS = local_ipv4s()
    BOUND_ALL = args.host not in ("127.0.0.1", "localhost")
    PASSWORD = load_password()
    if BOUND_ALL and not PASSWORD:
        PASSWORD = uuid.uuid4().hex[:8]
        try:
            (WORK_DIR / "password.txt").write_text(PASSWORD + "\n", encoding="utf-8")
        except OSError:
            pass

    log(f"--- {APP_ID} {VERSION} başlatılıyor (port {args.port}) ---")
    server = None
    for attempt in range(2):
        try:
            server = Server((args.host, args.port), Handler)
            break
        except OSError as exc:
            if attempt == 0 and stop_existing(args.port):
                log("önceki kopya durduruldu; yeniden başlatılıyor…")
                time.sleep(1.0)
                continue
            log(f"port açılamadı: {exc}")
            sys.exit(1)

    base = f"http://{HOST}:{args.port}/"
    log(f"arayüz: {base}")
    if BOUND_ALL:
        log(f"LAN modu AÇIK · erişim şifresi: {PASSWORD}  (work/password.txt)")
        for ip in LOCAL_IPS:
            log(f"telefon için: http://{ip}:{args.port}/")
    ENGINE = AntaliaEngine(base + "antalia/engine.html", log=log)
    ENGINE.start()

    if args.open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(base)).start()

    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        if ENGINE:
            ENGINE.stop()
        server.server_close()
        log("sunucu kapandı")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log("ölümcül hata:\n" + traceback.format_exc())
        sys.exit(1)
