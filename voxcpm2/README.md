# VoxCPM2 — Türkçe ses tasarımı (stüdyo entegrasyonu)

Bu klasör, [alexturkey/voxcpm2-turkce-ses-tasarimi](https://github.com/alexturkey/voxcpm2-turkce-ses-tasarimi)
projesinin **audio.cpp v0.9.2 hazır motoruna** uyarlanmış halidir. Derleme, CUDA araç zinciri veya
projenin 4 GB yaması gerekmez; hazır Windows ikilisini indirip koymak yeterlidir.

- Motor: [audio.cpp v0.9.2](https://github.com/0xShug0/audio.cpp/releases/tag/v0.9.2-drama3-base-small)
- Model: VoxCPM2 Q8_0 GGUF (2,95 GB)
- 7 hazır Türkçe ses + ses tasarımı
- Çıktı: 48 kHz mono WAV

## Klasör düzeni

```
voxcpm2/
  engine-cuda/audiocpp_cli.exe     NVIDIA (CUDA 12.4) — repoda yok, indirilir
  engine-vulkan/audiocpp_cli.exe   AMD/Intel yedeği — repoda yok, indirilir
  model/voxcpm2-q8_0.gguf          repoda yok, indirilir
  repo/                            kod + 7 hazır ses + ayarlar
```

## Kurulum

### 1) Motoru indir

**NVIDIA (RTX 4060 Ti / Ada ve üzeri):** CUDA 12.4 paketi. Sürücü 550+ olmalı.

```powershell
New-Item -ItemType Directory -Force voxcpm2\engine-cuda | Out-Null
curl.exe -L -o "$env:TEMP\cuda124.zip" "https://github.com/0xShug0/audio.cpp/releases/download/v0.9.2-drama3-base-small/audio-v0.9.2-drama3-base-small-bin-windows-x64-cuda12.4.zip"
curl.exe -L -o "$env:TEMP\cudart124.zip" "https://github.com/0xShug0/audio.cpp/releases/download/v0.9.2-drama3-base-small/audio-v0.9.2-drama3-base-small-cudart-windows-x64-cuda12.4.zip"
Expand-Archive "$env:TEMP\cuda124.zip" voxcpm2\engine-cuda -Force
Expand-Archive "$env:TEMP\cudart124.zip" voxcpm2\engine-cuda -Force
```

**NVIDIA yoksa (AMD/Intel):** Vulkan paketi.

```powershell
New-Item -ItemType Directory -Force voxcpm2\engine-vulkan | Out-Null
curl.exe -L -o "$env:TEMP\vulkan.zip" "https://github.com/0xShug0/audio.cpp/releases/download/v0.9.2-drama3-base-small/audio-v0.9.2-drama3-base-small-bin-windows-x64-vulkan.zip"
Expand-Archive "$env:TEMP\vulkan.zip" voxcpm2\engine-vulkan -Force
```

### 2) Modeli indir

```powershell
New-Item -ItemType Directory -Force voxcpm2\model | Out-Null
curl.exe -L -o voxcpm2\model\voxcpm2-q8_0.gguf "https://huggingface.co/audio-cpp/audio.cpp-gguf/resolve/main/VoxCPM2-GGUF/voxcpm2-q8_0.gguf"
```

### 3) Ayarları oluştur

```powershell
Copy-Item voxcpm2\repo\ayarlar.example.json voxcpm2\repo\ayarlar.json
```

Varsayılan örnek CUDA 12.4 içindir. Vulkan kullanacaksan `ayarlar.json` içinde:

```json
"motor": "../engine-vulkan/audiocpp_cli.exe",
"cuda_bin": "",
"backend": "vulkan"
```

### 4) Python paketleri

```powershell
python -m pip install -r voxcpm2\repo\requirements.txt
```

Stüdyo ile aynı Python'u kullanacaksan üst klasördeki `requirements.txt` yeterlidir
(içinde `soundfile` de var).

### 5) Dene

```powershell
cd voxcpm2\repo
python -m ses_tasarim.oku --liste
python -m ses_tasarim.oku --ses hazir/gizemli_bilge --metin "Merhaba, bu bir denemedir." --cikti cikti\deneme
```

## Stüdyo ile kullanım

`voxcpm_engine.py` bu klasörü otomatik bulur (uygulamanın yanındaki `voxcpm2/`).
Stüdyoda **Motor → VoxCPM2**, ardından **VoxCPM2 sesi** seç.

- Motor seçimi otomatiktir: `nvidia-smi` çalışıyorsa `engine-cuda`, yoksa `engine-vulkan`.
- CUDA açılamazsa Vulkan yedeği otomatik denenir.
- Aynı anda tek VoxCPM2 işi çalıştır (model ~3 GB, tepe bellek ~7-8 GB).

## Hız

| Makine | 40 sn ses |
|---|---|
| RTX 4060 Ti (CUDA 12.4, Q8, 16 adım) | ~25-35 sn |
| Vega 10 laptop (Vulkan, Q8) | ~20 dakika |

İlk çalıştırmada model yükleme + referans kodlama ~15 sn ekler.

## Lisans ve kaynak

- Bu uyarlama: Apache-2.0 (bkz. `repo/LICENSE`).
- Özgün proje: Ali Haydar Öztürk — [voxcpm2-turkce-ses-tasarimi](https://github.com/alexturkey/voxcpm2-turkce-ses-tasarimi).
- audio.cpp: ShugoAI LLC, Apache-2.0.
- VoxCPM2 modeli: OpenBMB.
- Ayrıntılı liste: `repo/THIRD_PARTY.md`.
