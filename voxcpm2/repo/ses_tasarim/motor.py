"""audio.cpp (hazır Vulkan/CPU derlemesi) motorunu tek oturumda istek dizisiyle çalıştırır.

Bu sürüm, repodaki yamalı CUDA derlemesi yerine audio.cpp v0.9.2'nin hazır Windows derlemesini kullanır
(AMD/Vulkan ya da CPU). Kalite sabit: 16 adım, cfg 2.0. Tohum kalite ayarı değildir.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
import soundfile as sf

FIXED = {"adim": 16, "cfg": 2.0}
SAMPLE_RATE = 48000
TEXT_CHUNK = 2048
# referans kodlayıcı örnek kapasitesi: motor varsayılanı 240000 (16 kHz, 15 sn); tasarım kayıtları 20-35 sn → 36 sn
REFERENCE_OPTION = ("--session-option", "voxcpm2.audiovae_encoder_sample_capacity=576000")
MIN_REFERENCE_SECONDS = 8.0
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


class MotorHatasi(RuntimeError):
    pass


def _rss_mb(pid: int) -> int:
    """Windows'ta çalışma kümesi (KB) → MB. / Working set via tasklist."""
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=5, creationflags=NO_WINDOW).stdout
        line = out.strip().splitlines()[0]
        digits = re.sub(r"\D", "", line.rsplit(",", 1)[-1])
        return int(digits) // 1024 if digits else 0
    except Exception:
        return 0


class VramWatcher:
    """nvidia-smi varsa VRAM, yoksa süreç belleği tepe değeri (MB). / Peak VRAM or process memory."""

    def __init__(self):
        self.peak_mb = 0
        self.pid = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self):
        while not self._stop.is_set():
            try:
                out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                     capture_output=True, text=True, timeout=5, creationflags=NO_WINDOW).stdout
                self.peak_mb = max(self.peak_mb, int(out.strip().splitlines()[0]))
            except Exception:
                if self.pid:
                    self.peak_mb = max(self.peak_mb, _rss_mb(self.pid))
            self._stop.wait(1.5)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()


def engine_env(settings: dict, work_dir: Path) -> dict:
    """Yalnız motor sürecine verilen ortam. / Environment for the engine process only."""
    env = dict(os.environ)
    if settings.get("cuda_bin"):
        env["PATH"] = str(settings["cuda_bin"]) + os.pathsep + env.get("PATH", "")
    # Vulkan'da tek seferde tek büyük tampon; parçalanmayı azalt
    env.setdefault("GGML_VK_DISABLE_COOPMAT", "1")
    return env


def reference_wav(reference: Path, work_dir: Path) -> Path:
    """FLAC ya da başka biçimdeki referansı motor için WAV'a çevirir (kayıpsız). / Decode reference to WAV."""
    reference = Path(reference)
    if reference.suffix.lower() == ".wav":
        return reference
    audio, rate = sf.read(reference, dtype="float32")
    work_dir.mkdir(parents=True, exist_ok=True)
    target = work_dir / (reference.stem + ".wav")
    sf.write(target, audio, rate, subtype="PCM_16")
    return target


def design_request(request_id: str, description: str, text: str, seed: int) -> dict:
    # tarif parantez içinde metnin önüne; parantez prompt sınırıdır
    return {"id": request_id, "text": f"({description.strip()}){text.strip()}", "seed": int(seed)}


def read_request(request_id: str, text: str, seed: int, reference: Path, reference_text: str) -> dict:
    # tasarım kaydı iki girişe birden (audio + voice_ref), yanında okunan metni (reference_text) ve sesin tohumu
    return {"id": request_id, "text": text, "seed": int(seed), "audio": str(reference), "voice_ref": str(reference),
            "reference_text": reference_text.strip()}


def _completed(log_path: Path) -> int:
    """Motorda biten istek sayısı (her istek sonunda 'request_id=' satırı düşer). / Finished request count."""
    if not log_path.exists():
        return 0
    try:
        return log_path.read_text(encoding="utf-8", errors="replace").count("request_id=")
    except OSError:
        return 0


def _plausible(audio: np.ndarray, text: str) -> bool:
    """Yarım kalmış ses koruması: çok kısa çıktı 'kötü' sayılır. / Guards against half-finished audio."""
    seconds = len(audio) / SAMPLE_RATE
    expected = max(0.8, len(text.strip()) * 0.045)
    return seconds >= 0.25 and seconds >= 0.35 * expected


def run_sequence(settings: dict, requests: list, work_dir: Path, progress=None) -> dict:
    """İstekleri tek motor oturumunda üretir. Dönen: audios {id: float32}, bad [id], seconds, vram_peak_mb."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    for request in requests:
        request.update({"num_inference_steps": FIXED["adim"], "guidance_scale": FIXED["cfg"],
                        "text_chunk_size": TEXT_CHUNK, "max_tokens": 80 + int(len(request["text"]) * 1.2)})
    (work_dir / "dizi.json").write_text(json.dumps({"requests": requests}, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    log_path = work_dir / "motor.log"
    command = [str(settings["motor"]), "--model", str(settings["model"]), "--task", "tts",
               "--backend", settings.get("backend", "vulkan"), "--threads", str(settings.get("motor_threads", 6)),
               "--request-sequence", str(work_dir / "dizi.json"), *REFERENCE_OPTION,
               "--out-dir", str(work_dir / "out"), "--batch-manifest-out", str(work_dir / "manifest.json"),
               "--log", "--log-file", str(log_path), "--metrics"]
    started = time.time()
    with (work_dir / "stdout.txt").open("w", encoding="utf-8") as out, VramWatcher() as watcher:
        process = subprocess.Popen(command, env=engine_env(settings, work_dir), stdout=out, stderr=subprocess.STDOUT,
                                   creationflags=NO_WINDOW)
        watcher.pid = process.pid
        while process.poll() is None:
            if progress:
                progress(_completed(log_path), len(requests), time.time() - started)
            time.sleep(2)
    if process.returncode != 0:
        tail = (work_dir / "stdout.txt").read_text(encoding="utf-8", errors="replace")[-1500:]
        raise MotorHatasi(f"motor rc={process.returncode}; {work_dir / 'stdout.txt'}\n{tail}")
    audios, bad = {}, []
    for request in requests:
        wav = work_dir / "out" / f"{request['id']}.wav"
        if not wav.exists():
            bad.append(request["id"])
            continue
        audio, rate = sf.read(wav, dtype="float32")
        if rate != SAMPLE_RATE:
            raise MotorHatasi(f"beklenmeyen örnekleme {rate}")
        if not _plausible(audio, request["text"]):
            bad.append(request["id"])
            continue
        audios[request["id"]] = audio
    return {"audios": audios, "bad": bad, "seconds": round(time.time() - started, 1), "vram_peak_mb": watcher.peak_mb}


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SAMPLE_RATE), dtype=np.float32)


def join_lines(audios: list, pauses: list) -> np.ndarray:
    """Satırları aralarına durak koyarak birleştirir (ses işlenmez). / Concatenate with pauses, no processing."""
    pieces = []
    for index, audio in enumerate(audios):
        if index:
            pieces.append(silence(pauses[index - 1]))
        pieces.append(audio)
    return np.concatenate(pieces)


def write_wav(path: Path, audio: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.wav")
    sf.write(tmp, audio, SAMPLE_RATE, subtype="PCM_16")
    os.replace(tmp, path)


def list_devices(settings: dict) -> str:
    env = engine_env(settings, Path("."))
    result = subprocess.run([str(settings["motor"]), "--list-devices"], env=env, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", creationflags=NO_WINDOW, timeout=120)
    return (result.stdout + result.stderr).strip()
