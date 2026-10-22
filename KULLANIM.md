# Seslendirme Stüdyosu

**Soru görselinden** (fotoğraf ya da ekran görüntüsü) otomatik **çözüm videosu** hazırlar:
görseli okur, soruyu çözer; görseli **sabit Reels arka planına** oranı korunarak yerleştirir,
çözümü üzerine kalemle adım adım yazar ve Antalia ile seslendirir. Seslendirme tamamen bu
bilgisayarda çalışır; internet gerekmez.
Ses motoru: **Antalia-2 Mini** (yerel TTS).
İsteğe bağlı **AI taslak** özelliği internet kullanır (ücretsiz; bkz. 2. adım).

---

## Çalıştırma

- **Başlatmak için:** `Baslat.bat` dosyasına çift tıkla. Tarayıcıda arayüz açılır.
  - İlk açılışta motor 10–20 sn hazırlanır (üstteki rozet "Motor: hazır" olana kadar bekle).
- **Durdurmak için:** `Durdur.bat` dosyasına çift tıkla.

> Not: Antalia Mini uygulamasını ayrıca açmana gerek yok; stüdyo kendi kopyasını kullanır.

### Telefondan / tabletten kullanma (aynı Wi-Fi)

- **Başlatmak için:** `Baslat-telefon.bat` dosyasına çift tıkla (sunucu yerel ağa açılır).
- Arayüzün üstünde çıkan **"📱 Telefondan aç: http://192.168.x.x:8770/"** adresini telefonun
  tarayıcısına yaz (bir kez yeter; sonra yer imine ekle).
- Telefon **şifre** sorar. Şifre `work\password.txt` dosyasında yazılıdır (ilk LAN açılışında
  otomatik oluşturulur; dilediğin zaman bu dosyayı düzenleyip değiştirebilirsin).
- **Videoyu telefona alma:** üretim bitince **⬇** indirme bağlantısına dokun → dosya doğrudan
  telefona iner. (iPhone: **Dosyalar → İndirilenler**; Android: **İndirilenler**.) Telefondaki
  kopya bilgisayardaki kayıt klasöründen bağımsızdır; ikisi de kalır.
- **Soru fotoğrafı:** telefonda **🖼️ Soru görseli yükle** ile kamerayı ya da galeriyi seçebilirsin.
  Sayfa içindeki **📷 Kamera** düğmesi https olmadan telefonda çalışmaz; sorun değil, yükleme
  düğmesi zaten telefonun kamerasını kullanır.
- **Durdurmak için:** yine bilgisayarda `Durdur.bat` (telefondan kapatılamaz).

> Telefon ve bilgisayar **aynı Wi-Fi** ağında olmalı. Bağlanamıyorsan Windows Güvenlik Duvarı
> iznini kontrol et.

### Her yerden erişim (Tailscale — ev dışında da olur)

Ev/ofis Wi-Fi'sinin dışından (mobil veriyle) da kullanmak için **Tailscale** kullan:

1. **Bilgisayara** ve **telefona** ücretsiz Tailscale uygulamasını kur
   (`tailscale.com`). İkisinde de **aynı hesapla** giriş yap.
2. **Bir kez:** `GuvenlikDuvari-Izni.bat` dosyasına **sağ tık → Yönetici olarak çalıştır**
   (telefondan erişim için güvenlik duvarı izni; sonra kapatabilirsin).
3. Bilgisayarda stüdyoyu **`Baslat-telefon.bat`** ile başlat.
4. Telefon tarayıcısına arayüzün üstünde görünen **"📱 Her yerden (Tailscale)"** adresini yaz
   (100.x.x.x biçiminde; Tailscale kuruluyken otomatik görünür).
5. Şifre: `work\password.txt`.

> Bilgisayar açık ve stüdyo çalışıyor olmalı. Bu yöntem sunucuyu **internete açmaz**;
> yalnızca senin Tailscale hesabındaki cihazlar erişebilir.

---

## Güvenlik

Bu stüdyo **yalnızca senin bilgisayarında** çalışır ve internete bir şey yüklemez.

- **`Baslat.bat` (varsayılan):** sunucu yalnızca bu bilgisayardan (`127.0.0.1`) erişilebilir.
  Dışarıya kapalıdır.
- **`Baslat-telefon.bat`:** sunucu yerel ağa açılır; bu yüzden **telefondan gelen isteklerde şifre zorunludur**.
  Aynı Wi-Fi'deki başka biri parolayı bilmeden bağlanamaz. **Bu bilgisayarda (127.0.0.1) şifre sorulmaz** —
  ne yerel tarayıcıya ne de ses motoruna. (Ses motoru da yerelden çalıştığı için şifreden etkilenmez.)
- **CSRF koruması:** Tarayıcıda açık kötü niyetli bir site bile stüdyoya istem dışı işlem
  yaptıramaz (her istek gizli bir `X-Studio-Token` ve Origin kontrolünden geçer).
- **Durdurma:** `/__stop` yalnızca bu bilgisayardan çalışır; ağdan kapatılamaz.
- **API anahtarı saklanmaz.** AI taslak özelliği bilgisayarındaki `opencode` CLI'yi kullanır;
  bu yüzden sunucuyu internete (LAN dışına) açma — açılırsa başkaları senin hesabını kullanabilir.

---

## Kullanım: 3 adım

### 1) Soru görselini seç
- **Gözat** ile klasörlerden görselini seç (jpg/png/webp/bmp), ya da yolunu yapıştırıp **Aç**'a bas.
- Ya da **🖼️ Soru görseli yükle** ile bilgisayarından seç.
- **Sürükle-bırak:** görseli sayfaya sürükleyip bırak. **Ctrl+V** ile panodaki görseli yapıştır.
- **📷 Kamera** ile web kamerasından soru fotoğrafı çekip doğrudan yükle.
- **🧹 Yeni soru** ile mevcut görseli ve tüm adımları temizleyip sıfırdan başla.
- Görsel açılınca altta önizlenir.
- **Farklı bir görsel açarsan** önceki anlatım adımları otomatik sıfırlanır
  (adımlar ve zamanlamalar seçtiğin görsele özeldir).

> Arayüz ipuçları: sağ üstteki **🌙/☀️** düğmesi açık/koyu tema; üst şeritteki **Kopyala** düğmesi
> telefon adresini tek dokunuşla kopyalar. Adımlar sol sütunda, ayarlar ve üretim sağ sütundadır.

### 2) Anlatım adımlarını yaz

**İstersen yapay zekâya hazırlat:** **🤖 AI ile taslak yaz** düğmesine bas. Uygulama görseli
ücretsiz bir yapay zekâ modeline gönderir (internet gerekir; genelde 20–60 sn). Model soruyu
**bir matematik profesörü titizliğiyle çözer**; anlatımı **ortaokul
seviyesindeki izleyicinin anlayacağı sade bir dille** yazar; sosyal medya videolarındaki gibi
**dikkat çeken bir giriş (hook)** ile başlar; sonunda **“beni takip etmeyi unutmayın”**
diyen bir kapanış yapar. Sonra
kontrol edip düzeltirsin. (Bu özellik bilgisayarındaki *opencode* kurulumunu kullanır; ek
ücret veya API anahtarı gerekmez. Mevcut adımların üzerine yazar — önce onay ister.)

**AI tarz ayarları:** Adımların üstündeki üç seçici ile taslağın üslubunu belirle:
**AI anlatım** (Kısa/Dengeli/Detaylı), **Hitap** (Öğrenci/Veli/Genel), **Hook**
(Merak/Soru/İddia). Seçimler bir sonraki *AI ile taslak yaz* çağrısında uygulanır.

Her adım bir paragraf. Matematik kısayollarını kullan:

| Yazdığın | Okunuşu |
|---|---|
| `4^3` veya `4³` veya `4**3` | dört üzeri üç |
| `(2²)³` veya `(2^2)^3` | parantez iki üzeri iki parantez üzeri üç |
| `12²` · `2¹⁰` · `x²` · `2^n` | on iki üzeri iki · iki üzeri on · iks üzeri iki · iki üzeri ne |
| `4^4 / 4^1 = 4^3` | dört üzeri dört bölü dört üzeri bir eşittir dört üzeri üç |
| `2*3` · `5 + 3` · `5 - 3 = 2` | iki çarpı üç · beş artı üç · beş eksi üç eşittir 2 |
| `2x` · `2x²` | iki iks · iki çarpı iks üzeri iki |
| `%25'i` · `64 litre` · `1.250 TL` | yüzde yirmi beşi · altmış dört litre · bin iki yüz elli lira |

**Önemli kural:** Üslü ifadenin **sonucu kendiliğinden söylenmez.**
`4^3` yazarsan ses "dört üzeri üç" der, "altmış dört" demez. Sonucu anlatmak istiyorsan
metne sen ekle (ör. `4^3 = 64` gibi sonucu açıkça yaz), o zaman okunur.

Her adımın altında **"Okunuş"** kutusu ne söyleneceğini canlı gösterir; üretimden sonra
Antalia'nın son normalizasyonu da görünür.

**✍️ Tahtaya yazılacak kutusu:** Her adımın altındaki ikinci kutudur. Buraya yazdığın metin,
o adımda soru görselinin üzerine kalemle **aynen** yazılır. (AI taslağı bu kutuyu `[n]d`
satırlarından otomatik doldurur; istediğin gibi düzeltirsin.)
- **Boş bırakırsan** → yazı, o adımın seslendirme metninden otomatik üretilir.
- **Yalnızca `-` yazarsan** → o adımda tahtaya hiçbir şey yazılmaz.
- **Matematik yazarsan** → tahtaya aynen bu yazılır (ör. `4^4 / 4 = 4^3`).

Bu kutuyu değiştirmek **sesi** etkilemez (ses seslendirme metninden gelir); yalnızca videoyu
yeniden oluşturman gerekir. Kutunun altındaki **canlı önizleme**, yazının ekrana nasıl
çizileceğini gösterir: üsler üst simge (`2^4` → 2⁴), kesirler alt alta (`1/2`) gösterilir.

### 3) Üret, önizle ve kaydet
1. **Sesleri oluştur** — her adım için ses üretilir (ilk sefer biraz sürer; her adımda
   küçük oynatıcıyla dinleyip beğenmediğini düzeltip yeniden üretebilirsin). Tek bir adımı
   beğenmediysen, o adımın sağ üstündeki **🔁** düğmesiyle yalnız o adımı **yeni bir tonla**
   hızlıca yeniden okutabilirsin (başlangıçları sonra **⏱ Önerilen zamanlama** ile tazele).
   Üretim bitince başlangıçlar **otomatik sırayla dizilir**.
2. Zamanlama (isteğe bağlı): **⏱ Önerilen zamanlama** ile adımları yeniden dizdirebilirsin;
   boş bırakılan adımlar bir öncekinin ardına otomatik yerleşir. Ok işaretleriyle
   adımların sırasını değiştirebilirsin.
3. **Videoya ekle (önizleme)** — çözüm videosu üretilir: çözüm, soru görselinin üzerine
   kalemle yazılır; seslendirme eklenir ve sonuç sayfanın altında hemen dinlenir.
   Bu adım klasörüne **hiçbir şey yazmaz** — istediğin kadar deneyebilirsin.
4. **Kaydet** — önizlemeyi beğendiysen bas: dosyalar "Kayıt klasörü" alanına yazılır.

Kaydet'e bastığında "Kayıt klasörü" alanına **yalnızca birleştirilmiş video** yazılır
(varsayılan: Masaüstü):

- `..._seslendirmeli.mp4` — sesi eklenmiş çözüm videosu

Ses (wav/mp3) ve metin (txt) dosyaları **kaydedilmez**; bunlara yalnızca önizleme sonrası
sayfadaki indirme bağlantılarından ulaşabilirsin.

### Çözüm yazısı hakkında (kalem modu)

- Her video **aynı sabit Reels arka planı** ile üretilir: 1080×1920, ortada beyaz kart
  (`assets\arkaplan.png`). Soru görseli boyutu ne olursa olsun kartın içine **oranı
  korunarak otomatik yerleştirilir**.
- Çözüm, soru görselinin **üzerine kalemle yazıyormuş gibi** harf harf yazılır;
  yazı görselin **boş (açık renkli) bölgelerine** yerleşir, sorunun üzerine taşmaz.
- Tahtaya **yalnızca matematik** yazılır: `=`, `·`, `+`, `-`, `/`, üs (`2^4` → 2⁴), ok (`→`).
  Düz cümleler ve soruyu okuma kısımları yazılmaz.
- **Kesirler alt alta** yazılır, kesir çizgisi ortada olur (`1/8`); bir kesrin üssü varsa
  parantez kullanılır: `(1/2)^3`.
- Adımlar çoğalınca yazı boyutu boş alana sığacak şekilde otomatik küçülür.
- ✍️ **Sorunun üzerine kalemle yaz** onay kutusunu kapatırsan çözüm, görselin altındaki
  panelde okunan metinle birebir yazılır (kalem modu yerine panel modu).
- Video her zaman dikey **1080×1920** (Reels ölçüsü) üretilir.

---

## Ayarlar

| Ayar | Açıklama |
|---|---|
| Motor | **Antalia — hızlı** (varsayılan, saniyeler) ya da **VoxCPM2 — kalite** (yavaş, 1 sn ses ≈ 20 sn). |
| VoxCPM2 sesi | VoxCPM2 seçiliyken kullanılacak ses: 7 hazır ses + `voxcpm2\repo\sesler` içinde tasarladıkların. |
| Hız | Konuşma hızı (0.95 varsayılan). Düşük = daha sakin. Yalnız Antalia için. |
| Adım | Ses kalite/hız dengesi. 8 tavsiye edilir; 4 daha hızlı üretir. Yalnız Antalia için. |
| Ton | Konuşma varyasyonu (seed). Değiştirip **1) Sesleri oluştur** dersen okuma üslubu değişir. Yalnız Antalia için. |
| Aralık | Otomatik zamanlamada iki adım arasındaki boşluk (sn). |
| Kayıt klasörü | Çıktıların yazılacağı klasör. |

### VoxCPM2 motoru (yüksek kalite, isteğe bağlı)

Kurulum ayrı bir adımdır: **[voxcpm2/README.md](voxcpm2/README.md)**. Motor ve model boyut nedeniyle
repoda yoktur; indirme adımları orada anlatılır.

- Stüdyo, uygulamanın yanındaki `voxcpm2\` klasörünü otomatik bulur (motor seçimi: NVIDIA → CUDA, yoksa Vulkan).
- Hız makineye göre değişir: RTX 4060 Ti'da 40 sn ses ≈ 25-35 sn; zayıf laptopta çok daha yavaş.
- İlk adımda model yüklenir ve referans ses kodlanır; bunlar her üretimde bir kez ödenir.
- Metinde tırnak kullanma; sayılar otomatik yazıya çevrilir.
- Aynı anda tek motor işi çalıştır (model ~3 GB, tepe bellek ~7-8 GB).

Ses listesini yenilemek için sayfayı yenile (Ctrl+F5). Yeni tasarlanan sesler `voxcpm2\repo\sesler` altına düşer.

---

## Sorun giderme

- **"Motor: başlatılıyor…"da kaldı:** ilk sefer modeller yüklenirken 10–20 sn sürer.
  Uzun sürerse `Durdur.bat` → `Baslat.bat` yap. Ayrıntılar: `work\studio.log`.
- **ffmpeg bulunamadı:** Terminalde `winget install Gyan.FFmpeg` çalıştır (bir kez).
- **Motor hatası:** Başsız Edge kullanamıyorsa Microsoft Edge'in kurulu olduğundan emin ol.
- **"AI taslağı oluşturulamadı" hatası:** internet bağlantısını kontrol et; `opencode`
  kurulumunun çalıştığından emin ol (PowerShell'de `opencode --version`). Ayrıntı: `work\studio.log`.
- **Çözüm yazısı çok küçük görünüyor:** görseldeki boş alan azsa yazı otomatik küçülür;
  görseli daha ferah kırpıp yeniden yüklemek ya da adım sayısını azaltmak yardımcı olur.

---

## Dosya yapısı

```
SeslendirmeStudyosu\
  Baslat.bat / Durdur.bat   — başlat / durdur (yalnız bu bilgisayar)
  Baslat-telefon.bat        — aynı Wi-Fi'deki telefondan kullanmak için başlat (şifreli)
  GuvenlikDuvari-Izni.bat   — telefondan (Tailscale) erişim için güvenlik duvarı izni (bir kez)
  serve.py                  — yerel sunucu (arayüz + API)
  ai_draft.py               — AI taslak: soru görseli → ücretsiz model → adım adım çözüm
  mathspeak.py              — matematik kısayol çevirisi (üssün sonucu hesaplanmaz)
  tts_engine.py             — Antalia motorunu yönetir
  voxcpm_engine.py          — VoxCPM2 köprüsü (isteğe bağlı, alt süreç)
  handwrite_video.py        — sabit arka plan + soru üzerine kalemle yazma
  panel_video.py            — panel modu (kalem modu kapalıysa)
  web\                      — arayüz dosyaları
  assets\                   — sabit Reels arka planı (arkaplan.png) + logo (logo.png)
  antalia\                  — Antalia-2 Mini motorunun kopyası (LICENSE/NOTICE dahil)
  voxcpm2\                  — VoxCPM2 kodu, 7 hazır ses ve kurulum notları (motor/model hariç)
  work\                     — geçici dosyalar + studio.log (+ password.txt: LAN şifresi)
```

---

## Lisans / atıf

- Ses modeli: **Antalia-2 Mini** — © cloud0day3, Apache-2.0 lisansı ile kullanılmaktadır
  (ayrıntı: `antalia\LICENSE`, `antalia\NOTICE`).
- Video birleştirme: **ffmpeg** (LGPL/GPL).
- Üretilen ses **yapay zekâ ile oluşturulmuştur**; paylaşırken bunu belirtmen önerilir.
