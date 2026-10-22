# -*- coding: utf-8 -*-
"""VoxCPM2 motoru: hazır ve tasarlanmış seslerle yüksek kaliteli Türkçe okuma.

Antalia hızlıdır (saniyeler); VoxCPM2 yavaştır (bu laptopta 1 sn ses ≈ 20 sn üretim) ama ses
tasarımı ve 48 kHz doğal konuşma sunar. Stüdyoda "Ses motoru" seçeneğiyle devreye girer.

Klasör düzeni (taşınabilir paket veya GitHub reposu):
    <kök>\\engine-cuda\\audiocpp_cli.exe     (NVIDIA varsa)
    <kök>\\engine-vulkan\\audiocpp_cli.exe   (yedek / AMD-Intel)
    <kök>\\model\\voxcpm2-q8_0.gguf
    <kök>\\repo\\...                        (sesler, ayarlar.json, vox_is.py)

Kök sırası: VOXCPM2_KOK > uygulamanın yanındaki vox > repodaki voxcpm2 > C:\\vox.
VoxCPM2 ayrı bir Python sürecinde çalışır; stüdyonun bağımlılıklarına dokunmaz.
Tüm adımlar tek motor oturumunda üretilir.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _kok() -> Path:
    """VoxCPM2 klasörü: VOXCPM2_KOK > yandaki vox > repodaki voxcpm2 > C:\\vox."""
    ortam = os.environ.get("VOXCPM2_KOK", "").strip()
    if ortam:
        return Path(ortam).expanduser().resolve()
    yan = Path(__file__).resolve().parent.parent / "vox"
    if (yan / "repo").is_dir():
        return yan
    yerel = Path(__file__).resolve().parent / "voxcpm2"
    if (yerel / "repo").is_dir():
        return yerel
    return Path(r"C:\vox")


VOX_KOK = _kok()
REPO = VOX_KOK / "repo"
AYAR = REPO / "ayarlar.json"
ISCI = REPO / "vox_is.py"
IS_KLASORU = VOX_KOK / "studio"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _yol(deger) -> Path | None:
    """ayarlar.json'daki göreli yolu repo klasörüne göre çözer."""
    metin = str(deger or "").strip()
    if not metin:
        return None
    yol = Path(metin)
    return yol if yol.is_absolute() else (REPO / yol)


def _python() -> Path:
    """İşçiyi çalıştıracak Python: repo venv'i varsa o, yoksa stüdyonun Python'u (taşınabilir)."""
    venv = REPO / ".venv" / "Scripts" / "python.exe"
    if venv.is_file():
        return venv
    return Path(sys.executable)


_NVIDIA: bool | None = None


def _nvidia_var() -> bool:
    global _NVIDIA
    if _NVIDIA is None:
        _NVIDIA = False
        exe = shutil.which("nvidia-smi")
        if exe:
            try:
                _NVIDIA = subprocess.run([exe, "-L"], capture_output=True, timeout=8,
                                         creationflags=NO_WINDOW).returncode == 0
            except Exception:
                _NVIDIA = False
    return _NVIDIA


def _motorlar() -> list[tuple[str, Path]]:
    """(backend, exe) listesi: NVIDIA varsa önce CUDA, sonra Vulkan."""
    adaylar: list[tuple[str, Path]] = []
    cuda = VOX_KOK / "engine-cuda" / "audiocpp_cli.exe"
    vulkan = VOX_KOK / "engine-vulkan" / "audiocpp_cli.exe"
    if cuda.is_file() and _nvidia_var():
        adaylar.append(("cuda", cuda))
    if vulkan.is_file():
        adaylar.append(("vulkan", vulkan))
    if not adaylar:  # eski/tek klasör düzeni: ayarlar.json'daki motor
        try:
            ayar = json.loads(AYAR.read_text(encoding="utf-8"))
            motor = _yol(ayar.get("motor"))
            if motor and motor.is_file():
                adaylar.append((str(ayar.get("backend") or "vulkan"), motor))
        except Exception:
            pass
    return adaylar


class VoxcpmEngine:
    """Alt süreçli sarmalayıcı; her çağrıda model bir kez yüklenir (~15 sn)."""

    def __init__(self, log=print):
        self.log = log
        self._sesler: list | None = None

    # ------------------------------------------------------------------ API
    def status(self) -> dict:
        try:
            if not AYAR.is_file():
                return {"state": "error", "message": f"ayar dosyası yok: {AYAR}"}
            ayar = json.loads(AYAR.read_text(encoding="utf-8"))
            model = _yol(ayar.get("model"))
            adaylar = _motorlar()
            eksik = []
            if not model or not model.is_file():
                eksik.append("model")
            if not adaylar:
                eksik.append("motor (engine-cuda / engine-vulkan)")
            if not _python().is_file() or not ISCI.is_file():
                eksik.append("python/vox_is.py")
            if eksik:
                return {"state": "error", "message": "VoxCPM2 eksik: " + ", ".join(eksik)}
            backend, _motor = adaylar[0]
            return {"state": "ready", "message": f"VoxCPM2 hazır ({backend})", "backend": backend,
                    "model": model.name}
        except Exception as exc:
            return {"state": "error", "message": f"VoxCPM2 okunamadı: {exc}"}

    def sesler(self) -> list:
        if self._sesler is not None:
            return self._sesler
        out = []
        try:
            hazir = REPO / "hazir_sesler"
            for klasor in sorted(p for p in hazir.iterdir() if (p / "ses.json").is_file()):
                kart = json.loads((klasor / "ses.json").read_text(encoding="utf-8"))
                out.append({"kimlik": f"hazir/{klasor.name}", "ad": kart.get("gorunen_ad") or klasor.name,
                            "grup": "hazir", "tanitim": (kart.get("tanitim_tr") or "")[:160]})
            tasarlanan = REPO / "sesler"
            if tasarlanan.is_dir():
                for ses in sorted(p for p in tasarlanan.iterdir() if p.is_dir()):
                    for cesit in sorted(ses.glob("cesit_*")):
                        kart_yolu = cesit / "ses.json"
                        if not kart_yolu.is_file():
                            continue
                        kart = json.loads(kart_yolu.read_text(encoding="utf-8"))
                        numara = int(cesit.name.split("_")[1])
                        out.append({"kimlik": f"{ses.name}/{numara}",
                                    "ad": f"{kart.get('gorunen_ad') or ses.name} ({numara})",
                                    "grup": "tasarlanan", "tanitim": (kart.get("tanitim_tr") or "")[:160]})
        except Exception as exc:
            self.log(f"[voxcpm] ses listesi okunamadı: {exc}")
        self._sesler = out
        return out

    def synth(self, items: list[dict], ses: str = "hazir/belgesel_hanim") -> list[dict]:
        """items: [{id, text}] → [{id, seconds, modelText, wav(b64)}]"""
        durum = self.status()
        if durum["state"] != "ready":
            raise RuntimeError(durum["message"])
        son_hata: Exception | None = None
        adaylar = _motorlar()
        for deneme, (backend, motor) in enumerate(adaylar):
            klasor = IS_KLASORU / (time.strftime("is_%Y%m%d_%H%M%S") + f"_{backend}")
            try:
                return self._calistir(items, ses, klasor, backend, motor)
            except RuntimeError as exc:
                son_hata = exc
                if deneme + 1 < len(adaylar):
                    self.log(f"[voxcpm] {backend} başarısız, yedek motor denenecek: {exc}")
        raise son_hata or RuntimeError("VoxCPM2 motoru bulunamadı")

    def _calistir(self, items: list[dict], ses: str, is_klasor: Path,
                  backend: str, motor: Path) -> list[dict]:
        is_klasor.mkdir(parents=True, exist_ok=True)
        is_yolu, sonuc_yolu = is_klasor / "is.json", is_klasor / "sonuc.json"
        is_yolu.write_text(json.dumps({"ses": ses, "motor": str(motor), "backend": backend,
                                       "items": [{"id": str(i["id"]), "text": i.get("text") or ""}
                                                 for i in items], "cikti": str(is_klasor),
                                       "sayi_modulu": str(Path(__file__).resolve().parent)},
                                      ensure_ascii=False), encoding="utf-8")
        self.log(f"[voxcpm] {len(items)} adım, ses {ses}, motor {backend}")
        t0 = time.time()
        with (is_klasor / "isci.log").open("w", encoding="utf-8") as log_dosya:
            surec = subprocess.run([str(_python()), str(ISCI), str(is_yolu), str(sonuc_yolu)],
                                   stdout=log_dosya, stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
                                   timeout=6 * 3600)
        if not sonuc_yolu.is_file():
            kuyruk = (is_klasor / "isci.log").read_text(encoding="utf-8", errors="replace")[-1200:]
            raise RuntimeError(f"VoxCPM2 işçisi çıktı vermedi (rc={surec.returncode}): {kuyruk}")
        veri = json.loads(sonuc_yolu.read_text(encoding="utf-8"))
        if not veri.get("ok"):
            kuyruk = (is_klasor / "isci.log").read_text(encoding="utf-8", errors="replace")[-1200:]
            raise RuntimeError("VoxCPM2: " + str(veri.get("hata") or "bilinmeyen hata")
                               + (f" | {kuyruk}" if kuyruk else ""))
        self.log(f"[voxcpm] bitti: {len(veri['items'])} adım, {veri['seconds']} sn, "
                 f"bellek tepe {veri.get('bellek_mb', 0)} MB (toplam {(time.time() - t0):.0f} sn)")
        return veri["items"]
