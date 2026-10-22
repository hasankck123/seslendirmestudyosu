# Seslendirme Stüdyosu

Soru görselinden otomatik **çözüm videosu** üreten yerel stüdyo. Görseli okur, soruyu çözer,
görseli sabit Reels arka planına oranı korunarak yerleştirir, çözümü üzerine **kalemle adım adım
yazar** ve seslendirir. Seslendirme tamamen bu bilgisayarda çalışır; internet gerekmez.

- **Antalia-2 Mini** — varsayılan, hızlı yerel TTS (saniyeler)
- **VoxCPM2** — isteğe bağlı, 48 kHz yüksek kalite ve ses tasarımı (`voxcpm2/README.md`)
- **AI taslak** — isteğe bağlı; soruyu `opencode` CLI üzerinden ücretsiz bir görsel-dil modeline çözdürür

## Hızlı başlangıç

1. **Python 3.10+** (3.11 önerilir) kur ve PATH'e ekle.
2. Paketleri kur:

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. **ffmpeg** kur (`winget install Gyan.FFmpeg`) ya da `ffmpeg\ffmpeg.exe` olarak koy.
4. `Baslat.bat` dosyasına çift tıkla. Tarayıcıda arayüz açılır (ilk açılışta motor 10-20 sn hazırlanır).
5. Durdurmak için `Durdur.bat`.

Telefondan kullanmak için `Baslat-telefon.bat` (aynı Wi-Fi); şifre `work\password.txt` içinde
ilk açılışta oluşur. Ayrıntılar: [KULLANIM.md](KULLANIM.md).

## VoxCPM2 (yüksek kalite, isteğe bağlı)

VoxCPM2 motoru ve 2,95 GB modeli boyut nedeniyle repoda yoktur. İndirme, kurulum ve ayarlar:

**[voxcpm2/README.md](voxcpm2/README.md)**

Kurulduktan sonra stüdyoda **Motor → VoxCPM2**, ardından **VoxCPM2 sesi** seçilir. 7 hazır Türkçe
ses ve ses tasarımı desteği gelir. Motor seçimi otomatiktir (NVIDIA → CUDA, yoksa Vulkan).

## Klasörler

| Yol | İçerik |
|---|---|
| `serve.py` | yerel web sunucusu ve API |
| `tts_engine.py` | Antalia motoru (başsız Edge + ONNX) |
| `voxcpm_engine.py` | VoxCPM2 köprüsü (alt süreç) |
| `ai_draft.py` | AI taslak (opencode CLI) |
| `handwrite_video.py`, `panel_video.py` | kalemle yazma videosu |
| `mathspeak.py` | matematik okunuşu |
| `web/` | arayüz |
| `antalia/` | Antalia-2 Mini modeli ve çalışma zamanı |
| `assets/` | yazı tipi ve görseller |
| `voxcpm2/` | VoxCPM2 kodu, 7 ses, kurulum notları |
| `work/` | ayarlar, üretilen ses/video (git'e girmez) |

## Notlar

- `work/` klasörü kullanıcı verisidir (ayarlar, geçmiş, üretimler); repoya dahil edilmez.
- VoxCPM2 aynı anda tek iş çalıştırmalıdır (model ~3 GB, tepe bellek ~7-8 GB).
- Antalia motoru Microsoft Edge'i başsız kullanır; Windows'ta Edge hazırdır.

## Kaynaklar ve lisans

- VoxCPM2 Türkçe uyarlaması: [alexturkey/voxcpm2-turkce-ses-tasarimi](https://github.com/alexturkey/voxcpm2-turkce-ses-tasarimi) (Apache-2.0)
- audio.cpp: ShugoAI LLC (Apache-2.0)
- VoxCPM2 modeli: OpenBMB
- Antalia-2 Mini: kendi lisans dosyası `antalia/LICENSE` içinde
