# -*- coding: utf-8 -*-
"""Seslendirme Stüdyosu — AI taslak üretici.

Soru görselini, kullanıcının kurulu opencode CLI'si üzerinden ÜCRETSİZ bir
görsel-dil modeline gönderir; model soruyu bir matematik profesörü titizliğiyle
çözer ve adım adım Türkçe çözüm taslağını (anlatım + tahtaya yazılacak matematik)
döndürür; anlatım ortaokul seviyesine uygun ve reels tarzı hook'larla yazılır.
API anahtarı gerekmez; opencode kurulumu yeterlidir.

Deneme (komut satırı):
    python ai_draft.py <soru_gorseli.png|jpg>
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_MODEL = "opencode/deepseek-v4.1-flash-free"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
MAX_FRAMES = 20
MIN_FRAMES = 8
FRAME_WIDTH = 810
NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
STRICT_RE = re.compile(r"^\[(?:(\d{1,2}):)?(\d+(?:[.,]\d+)?)\]\s*(.+)$")
DISPLAY_RE = re.compile(
    r"^\[\s*(\d{1,2})\s*\]\s*d(?=[\s.:)\-–—]|$)\s*[.:)]?\s*(.*)$"
    r"|^\[\s*(\d{1,2})\s*d\s*\]\s*(.*)$",
    re.IGNORECASE,
)


def _display_match(line: str) -> str | None:
    """'[n]d ifade' biçimindeki tahta-yazısı satırını yakalar (yoksa None)."""
    m = DISPLAY_RE.match(line)
    if not m:
        return None
    return m.group(2) if m.group(1) is not None else m.group(4)
BUILD_RE = re.compile(r"^>?\s*build\s*[·•]")
RULE_RE = re.compile(r"^[-=*_~]{3,}$")
HEADER_WORD_RE = re.compile(r"^(sahne|bölüm|adım|kısım|scene|chapter)\b", re.IGNORECASE)
META_RE = re.compile(r"^(konu|soru|doğru cevap|cevap|başlık|seviye|ders|zorluk|not)\s*:", re.IGNORECASE)
SCENE_MS_RE = re.compile(r"[([]\s*(\d{1,2}):(\d{2})(?::\d{2})?\s*(?:[-–—)\]]|$)")

_OC_CACHE: str | None = None


# --------------------------------------------------------------------------- opencode bulma
def find_opencode() -> str | None:
    """opencode çalıştırılabilirini bulur (varsa gerçek .exe'yi tercih eder)."""
    global _OC_CACHE
    if _OC_CACHE and Path(_OC_CACHE).is_file():
        return _OC_CACHE
    cands: list[Path] = []
    for name in ("opencode.exe", "opencode.cmd", "opencode"):
        p = shutil.which(name)
        if p:
            real = Path(p).parent / "node_modules" / "@opencode" / "cli" / "bin" / "opencode.exe"
            cands.append(real if real.is_file() else Path(p))
    import os

    appdata = os.environ.get("APPDATA") or ""
    localapp = os.environ.get("LOCALAPPDATA") or ""
    if appdata:
        cands.append(Path(appdata) / "npm" / "node_modules" / "@opencode" / "cli" / "bin" / "opencode.exe")
        cands.append(Path(appdata) / "npm" / "opencode.cmd")
    if localapp:
        cands.append(Path(localapp) / "Programs" / "opencode" / "opencode.exe")
    for c in cands:
        if c.is_file():
            _OC_CACHE = str(c)
            return _OC_CACHE
    return None


def _oc_cmd(exe: str) -> list[str]:
    if exe.lower().endswith((".cmd", ".bat")):
        import os

        return [os.environ.get("COMSPEC", "cmd.exe"), "/c", exe]
    return [exe]


# --------------------------------------------------------------------------- kare çıkarma
def extract_frames(ffmpeg: str, video: str, out_dir: Path,
                   dur: float | None) -> tuple[list[str], float]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("f_*.jpg"):
        try:
            old.unlink()
        except OSError:
            pass
    if dur and dur > 2:
        n = max(MIN_FRAMES, min(MAX_FRAMES, int(round(dur / 3.5))))
        step = dur / n
    else:
        n, step = MIN_FRAMES, 3.0
    vf = f"fps=1/{step:.4f},scale={FRAME_WIDTH}:-2:flags=bicubic"
    cmd = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
           "-vf", vf, "-q:v", "3", "-frames:v", str(n), str(out_dir / "f_%03d.jpg")]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                          creationflags=NO_WINDOW)
    if proc.returncode != 0:
        raise RuntimeError("kare çıkarma hatası: " + (proc.stderr or "").strip()[-300:])
    frames = sorted(str(p) for p in out_dir.glob("f_*.jpg"))
    if not frames:
        raise RuntimeError("videodan kare çıkarılamadı")
    return frames, step


def frame_from_image(ffmpeg: str, image: str, out_dir: Path) -> tuple[list[str], float]:
    """Soru görselini AI'ya gönderilecek tek kareye dönüştürür (küçültür)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("f_*.jpg"):
        try:
            old.unlink()
        except OSError:
            pass
    dest = out_dir / "f_001.jpg"
    cmd = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-i", str(image),
           "-vf", f"scale={FRAME_WIDTH}:-2:flags=bicubic", "-q:v", "3", "-frames:v", "1", str(dest)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                          creationflags=NO_WINDOW)
    if proc.returncode != 0 or not dest.is_file():
        raise RuntimeError("görsel işlenemedi: " + (proc.stderr or "").strip()[-300:])
    return [str(dest)], 0.0


# --------------------------------------------------------------------------- model çağrısı
def build_prompt(n_frames: int, step: float, dur: float) -> str:
    return f"""Sen bir eğitim videosu için Türkçe seslendirme metni yazan bir asistansın.
Sana bir matematik soru çözüm videosundan kronolojik sırayla {n_frames} kare gönderildi. Kareler arası süre yaklaşık {step:.1f} saniyedir; video toplam {dur:.0f} saniyedir.

Görevin: İzleyiciye soruyu ve çözümü anlatan, videoya eklenecek seslendirme metnini adım adım yaz.

Kurallar:
1. Üslü ifadeleri oku ve hesaplanmış SONUCUNU SÖYLEME. Örnek: 4⁴ için "4 üzeri 4" de; "iki yüz elli altı" deme. Sonuç videoda açıkça yazılıysa söylenebilir.
2. Her satırın başına, o adımın videoda başlayacağı saniyeyi köşeli parantez içinde yaz. Örnek: [7] Şimdi 4 üzeri 4'ü 4 üzeri 1'e bölelim.
3. Matematik ifadelerini şu kısayollarla yaz (uygulama okunuşa çevirir): çarpma *, bölme /, üs ^, eşittir =. Örnek: 4^4 / 4^1 = 4^3
4. Her adım 1-2 kısa cümle olsun; doğal, akıcı konuşma dili kullan.
5. ÇIKTI BİÇİMİ KESİN: Yalnızca "[saniye] metin" satırları yaz. Başlık, madde imi, alıntı işareti (>), yıldız (**), açıklama, giriş veya kapanış cümlesi EKLEME. Örnek çıktı:
[0] Merhaba! Bugün üslü sayılarla ilgili bir soru çözeceğiz.
[5] Soruyu birlikte okuyalım: 4^4 litrelik bir deponun yüzde yirmi beşi dolu.
[12] Depodaki suyu bulmak için 4 üzeri 4'ü dörde bölelim."""


def _style_rules(style: dict | None) -> str:
    """Kullanıcının seçtiği AI tarz ayarlarını (uzunluk/hitap/hook) isteme ekler."""
    style = style or {}
    lines: list[str] = []
    length = (style.get("ai_length") or "").strip()
    if length == "kisa":
        lines.append("- ANLATIM: Kısa ve öz tut. Her seslendirme adımı 1 kısa cümle olsun; adım sayısını olabildiğince azalt (video kısa kalsın).")
    elif length == "detayli":
        lines.append("- ANLATIM: Detaylı anlat. Adımlar 2 cümleye kadar çıkabilir; mantığı sezdirmeye özen göster.")
    else:
        lines.append("- ANLATIM: Dengeli; her adım 1-2 kısa cümle.")
    audience = (style.get("ai_audience") or "").strip()
    if audience == "veli":
        lines.append("- HİTAP: İzleyici bir VELİ. Daha açıklayıcı, saygılı ve güven veren bir dil kullan.")
    elif audience == "genel":
        lines.append("- HİTAP: Genel izleyici. Günlük, enerjik ve akıcı bir dil kullan.")
    else:
        lines.append("- HİTAP: Ortaokul öğrencisi (kural 2'deki gibi).")
    hook = (style.get("ai_hook") or "").strip()
    if hook == "soru":
        lines.append('- HOOK: İlk seslendirme cümlesi izleyiciye doğrudan bir SORU sorsun (ör. "Bu soruyu kaç saniyede çözersin?").')
    elif hook == "iddia":
        lines.append('- HOOK: İlk seslendirme cümlesi iddialı bir vaatle başlasın (ör. "Bu tipte soruyu bir daha kaçırmayacaksın!").')
    else:
        lines.append('- HOOK: İlk seslendirme cümlesi merak uyandırsın (ör. "Çoğu öğrencinin takıldığı bu soruya bak!").')
    return "\n\nTARZ AYARLARI (kural 3 ve 8'e ek olarak uygula):\n" + "\n".join(lines)


def build_prompt_image(style: dict | None = None) -> str:
    base = """Sen üç özelliği tek kişide birleştiren bir asistansın:
(1) konusuna hâkim, titiz bir MATEMATİK PROFESÖRÜ,
(2) milyonlarca izlenen Reels/TikTok çözüm videolarını yazan bir SOSYAL MEDYA PROFESYONELİ,
(3) ortaokul öğrencisine ders anlatan sabırlı bir ÖĞRETMEN.
Sana bir matematik sorusunun GÖRSELİ gönderildi (tek kare). Soruyu profesör titizliğiyle oku,
KENDİN çöz ve çözümü adım adım yaz. Her adım İKİ satırdan oluşur:
  [n] ...   → izleyiciye ANLATILACAK seslendirme cümlesi
  [n]d ...  → O SIRADA tahtaya kalemle YAZILACAK kısa matematik ifadesi

Kurallar:
1. ÇÖZ (profesör gibi düşün): Soruyu eksiksiz çöz; çözüm matematiksel olarak kusursuz ve tek sonuçlu olsun. İşlem sırasına, işaretlere ve birimlere dikkat et; sorudaki gizli varsayımları ve tuzakları fark et. Doğru cevabı net söyle. AYRI BİR DOĞRULAMA/KONTROL ADIMI EKLEME; videoyu uzatan gereksiz adım çıkarma (doğruluğu kendi içinde sağla; anlatıma "kontrol edelim", "doğrulayalım" gibi ek bir adım yazma).
2. ANLAT (ortaokul seviyesi): Sanki karşındaki ortaokul öğrencisiymiş gibi konuş. Kısa cümleler, günlük ve sıcak bir dil kullan; gereksiz terimlerden kaçın; her adımı sezgisel olarak açıkla. "Bak şimdi", "işte püf noktası burada", "yani" gibi doğal geçişler kullan. Soru ileri seviye olsa bile anlatımı olabildiğince sadeleştir.
3. HOOK AT (sosyal medya profesyoneli gibi): İlk seslendirme adımı izleyiciyi ekranda tutacak güçlü bir hook olsun: merak uyandıran, "kaydırsam mı" dedirtmeyen 1-2 kısa cümle (ör. "Bu soruyu 10 saniyede çözmenin yolunu göstereceğim." / "Bu tipte soru sınavda gelirse sakın kaçırma!"). Çözüm boyunca ara ara merak tazeleyen kısa vurgular serpiştir (ör. "Çoğu öğrenci tam burada hata yapıyor…"). Son seslendirme adımı hem cevabı net versin hem de kapanışta aynen "beni takip etmeyi unutmayın" desin (ör. "Cevap C çıkıyor. Beni takip etmeyi unutmayın!"). Abartma; samimi ve enerjik ol.
4. İlk adımda soruya hook'la gir ve soruyu kısaca tanıt (bu adımda tahtaya yazı yoktur → "[0]d -"); sonraki adımlarda çözümü anlat ve hesaplamaları yaz; son adımda cevabı söyle ve "beni takip etmeyi unutmayın" diyerek kapat. Ayrı bir doğrulama adımı ekleme.
5. Her satırı köşeli parantezle başlat ve sayıyı birer artır: [0], [0]d, [1], [1]d …
6. Seslendirme satırında matematik ifadelerini şu kısayollarla yaz (uygulama okunuşa çevirir): çarpma *, bölme /, üs ^, eşittir =. Örnek: 4^4 / 4^1 = 4^3
7. Üslü ifadeleri "4 üzeri 3" gibi oku; üslü ifadenin sayısal sonucunu yalnızca çözümün gerektirdiği yerde söyle.
8. Her seslendirme adımı 1-2 kısa cümle olsun; görseldeki sayı ve ifadeleri doğru oku.
9. TÜRKÇE İMLA (çok önemli): ç, ğ, ı, ö, ş, ü harflerini eksiksiz kullan; harfleri sadeleştirip ASCII yazma. "şimdi", "doğru", "çoğu", "yanlış", "püf noktası", "şıklara" gibi yaz; "simdi", "dogru", "cogu", "yanlis" YAZMA.
10. [n]d satırı tahtaya yazılan GERÇEK ÇÖZÜMDÜR ve şu kurallara uyar:
   - YALNIZCA matematiksel semboller, rakamlar ve çok kısa etiketler (ör. "Cevap: D) -9"). Cümle/kelime anlatımı YAZMA.
   - Adım numarası KULLANMA: "1)", "2)", "3)" gibi sıra numaraları yazma; satır doğrudan ifadeyle başlasın (anlatımda da adımları numaralandırma).
   - Kısayollar: eşittir =, çarpma · (orta nokta), bölme /, üs ^, eksi -, artı +, ok →. Çarpma için küçük "x" harfini KULLANMA ("2,4 x 10^9" değil "2,4 · 10^9").
   - Kesirleri eğik çizgiyle yaz: 1/2, 16/8, 15/4 gibi (uygulama onları alt alta, kesir çizgili olarak çizer).
   - Bir KESRİN üssü varsa parantez kullan: (1/2)^3 yaz; "1/2^3" YAZMA (yanlış anlaşılır).
   - Hesap zincirlerini = ile bağla. Örnek: 16 · 2^-3 = 16 · 1/8 = 2   |   2^4 = 2 · 2 · 2 · 2 = 16
   - Üsleri ^ ile yaz (2^4, 2^-3, 10^5); uygulama onları otomatik üst simge olarak çizer.
   - O adımda tahtaya yazılacak hesap/ifade yoksa (soruyu okuma, sözel açıklama) sadece "[n]d -" yaz.
   - [n]d satırı kısa olsun (45 karakteri geçmesin).
11. ÇIKTI BİÇİMİ KESİN: Yalnızca "[sayı] metin" ve "[sayı]d ifade" satırları yaz. Başlık, madde imi, alıntı (>), yıldız (**), emoji, açıklama, giriş veya kapanış EKLEME. Örnek çıktı:
[0] Bu depo sorusunda çoğu kişi takılıyor; birlikte 30 saniyede çözelim!
[0]d -
[1] Depodaki suyu bulmak için 4 üzeri 4 litreyi 4'e bölmemiz yeterli; işte püf noktası burada.
[1]d 4^4 / 4 = 4^3
[2] Yani depoda 4 üzeri 3 litre, yani 64 litre su var.
[2]d 4^3 = 64
[3] Cevabımız 64! Beni takip etmeyi unutmayın.
[3]d Cevap: 64"""
    return base + _style_rules(style)


def run_ai(exe: str, model: str, frames: list[str], prompt: str,
           timeout: int = 900) -> tuple[str, float]:
    cmd = _oc_cmd(exe) + ["run", "-m", model, "--title", "Seslendirme Stüdyosu: AI taslak"]
    for f in frames:
        cmd += ["-f", f]
    cmd.append(prompt)
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout,
                              creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise RuntimeError("AI yanıtı zaman aşımına uğradı (15 dk). İnternet bağlantısını kontrol et.")
    out = (proc.stdout or b"").decode("utf-8", errors="replace")
    err = (proc.stderr or b"").decode("utf-8", errors="replace")
    if proc.returncode != 0:
        tail = " / ".join((err or out).strip().splitlines()[-3:])[-300:]
        raise RuntimeError("opencode hatası: " + (tail or f"çıkış kodu {proc.returncode}"))
    return out, time.time() - t0


# --------------------------------------------------------------------------- yanıt ayrıştırma
def _scene_start(line: str) -> float | None:
    m = SCENE_MS_RE.search(line)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    return None


def _clean_piece(s: str) -> str:
    s = s.replace("**", "").replace("``", "")
    s = re.sub(r"`+", "", s)
    s = re.sub(r"^[-–—•·]\s+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_draft(raw: str, dur: float | None = None) -> list[dict]:
    """AI yanıtını {start, text} adımlarına çevirir (toleranslı ayrıştırma)."""
    text = ANSI_RE.sub("", raw or "")
    segs: list[dict] = []
    cur: dict | None = None

    def flush():
        nonlocal cur
        if cur is not None:
            t = _clean_piece(" ".join(cur.pop("_parts")))
            if t:
                segs.append({"start": cur["start"], "text": t})
        cur = None

    for raw_line in text.splitlines():
        line = ANSI_RE.sub("", raw_line).strip()
        if not line:
            # düz (zamansız) modda boş satır paragraf sınırıdır → mevcut adımı bitir
            if cur is not None and not cur.get("timed"):
                flush()
            continue
        if BUILD_RE.match(line) or RULE_RE.match(line):
            continue
        # 0) tahtaya yazılacak matematik satırı: [n]d ifade  (seslendirme metninden önce kontrol)
        dm = _display_match(line)
        if dm is not None:
            flush()
            if segs:
                d = _clean_piece(dm)
                # "-" = bu adımda tahtaya yazı yok; kutu boş bırakılırsa "otomatik" sayılır
                segs[-1]["display"] = "-" if d in ("", "-", "–", "—") else d
            continue
        # 1) tercih edilen biçim: [12] metin
        m = STRICT_RE.match(line)
        if m:
            flush()
            mins = int(m.group(1) or 0)
            secs = float(m.group(2).replace(",", "."))
            cur = {"start": mins * 60 + secs, "timed": True, "_parts": [m.group(3)]}
            continue
        # 2) zamanlı sahne başlığı: "## Sahne 3 – ... (0:22 – 0:40)"
        st = _scene_start(line) if len(line) < 120 else None
        is_header = line.startswith("#") or bool(HEADER_WORD_RE.match(line))
        if st is not None and (is_header or len(line) < 60):
            flush()
            cur = {"start": st, "timed": True, "_parts": []}
            continue
        if is_header:
            continue  # zamansız başlık satırı: yok say
        # 3) adım başlamadan gelen "Konu: ... / Soru: ..." gibi meta satırları atla
        probe = re.sub(r"^[\s#>•·]+", "", line).replace("**", "")
        if cur is None and META_RE.match(probe):
            continue
        # 4) normal metin satırı (alıntı ve madde işaretlerini temizle)
        if cur is None:
            cur = {"start": None, "timed": False, "_parts": []}
        piece = re.sub(r"^[-–—•·]\s+", "", line.lstrip(">»").strip())
        cur["_parts"].append(piece)
    flush()

    # zamanı eksik adımları doldur / aralığa sıkıştır
    n = len(segs)
    for i, sg in enumerate(segs):
        if sg["start"] is None:
            sg["start"] = (i + 0.5) * dur / n if (dur and dur > 2) else i * 10.0
        if dur and dur > 2:
            sg["start"] = min(max(0.0, float(sg["start"])), dur - 0.3)
        sg["start"] = round(float(sg["start"]), 2)
    return segs


# --------------------------------------------------------------------------- ana akış
def generate_draft(video: str, dur: float | None, ffmpeg: str | Path | None,
                   work_dir: str | Path, model: str | None = None,
                   style: dict | None = None) -> dict:
    if not ffmpeg:
        raise RuntimeError("ffmpeg bulunamadı (kare çıkarma için gerekli)")
    exe = find_opencode()
    if not exe:
        raise RuntimeError("opencode bulunamadı — opencode kurulu ve PATH'te olmalı")
    src = Path(video)
    if not src.is_file():
        raise RuntimeError("video/görsel dosyası bulunamadı")
    model = model or DEFAULT_MODEL
    is_image = src.suffix.lower() in IMAGE_EXTS
    t0 = time.time()
    if is_image:
        frames, step = frame_from_image(str(ffmpeg), str(src), Path(work_dir) / "ai_frames")
        prompt = build_prompt_image(style)
    else:
        frames, step = extract_frames(str(ffmpeg), str(video), Path(work_dir) / "ai_frames", dur)
        prompt = build_prompt(len(frames), step, float(dur or 0.0))
    out, ai_secs = run_ai(exe, model, frames, prompt)
    segs = parse_draft(out, None if is_image else dur)
    if not segs:
        raise RuntimeError("AI yanıtından anlatım adımları çıkarılamadı")
    return {
        "segments": segs,
        "frames": len(frames),
        "step": round(step, 2),
        "ai_seconds": round(ai_secs, 1),
        "seconds": round(time.time() - t0, 1),
        "model": model,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("kullanım: python ai_draft.py <video.mp4> [sure_saniye] [ffmpeg_yolu]")
        raise SystemExit(2)
    vid = sys.argv[1]
    dur = float(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else None
    ff = sys.argv[3] if len(sys.argv) > 3 else shutil.which("ffmpeg")
    res = generate_draft(vid, dur, ff, Path(__file__).resolve().parent / "work")
    for s in res["segments"]:
        print(f"[{s['start']:7.2f}] {s['text']}")
    print(f"--- {res['frames']} kare · {res['seconds']} sn · {res['model']}")
