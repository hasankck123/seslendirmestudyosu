// UI strings (Turkish first) and the example sentences. The examples stay Turkish in both languages:
// the model speaks Turkish.
export const EXAMPLES = [
  "15 Ekim'de PatientDesk üzerinden WhatsApp ile 1.250.000 TL ödendi.",
  "Randevunuz 21 Ekim Salı günü saat 14:30'da, Dr. Ayşe Yılmaz ile. Lütfen 10 dakika önce gelin.",
  "Yarın İzmir'de hava parçalı bulutlu olacak; sıcaklık 18 ile 24 derece arasında.",
  "Iğdır'dan İstanbul'a giden uçak 2 saat 15 dakika rötar yaptı.",
];

export const STRINGS = {
  tr: {
    title: "Tarayıcınızda çalışan Türkçe ses",
    lead: "Antalia-2 Mini, 7,62 milyon parametrelik açık kaynak bir Türkçe metinden konuşma modeli. Bu sayfada tamamen sizin cihazınızda çalışıyor: sunucu yok, yazdığınız metin hiçbir yere gönderilmiyor.",
    textLabel: "Metin",
    examples: "Örnek cümleler",
    ex0: "Ödeme", ex1: "Randevu", ex2: "Hava durumu", ex3: "Iğdır'dan İstanbul'a",
    play: "Seslendir", stop: "Durdur", loading: "Model yükleniyor", loadModel: "Modeli yükle ve seslendir", failed: "Yüklenemedi",
    speed: "Hız", steps: "Örnekleme adımı", stepsShort: "Adım",
    aiLabel: "Yapay zekâ ile üretilmiş ses",
    readoutTitle: "Ölçümler",
    ttfa: "İlk ses", gen: "Üretim süresi", len: "Ses uzunluğu", rtf: "Gerçek zamandan hızlı",
    reading: "Modelin okuduğu metin",
    download: "WAV olarak indir",
    foot: "Apache-2.0 · Model, tarayıcınızda ONNX Runtime Web ile çalışır.",
    downloading: "İndiriliyor", thread: "iş parçacığı", threads: "iş parçacığı", chunks: "parça",
    error: "Hata", themeDark: "Koyu tema", themeLight: "Açık tema",
  },
  en: {
    title: "Turkish speech, running in your browser",
    lead: "Antalia-2 Mini is an open-source Turkish text-to-speech model with 7.62 million parameters. On this page it runs entirely on your device: no server, and the text you type is not sent anywhere.",
    textLabel: "Text",
    examples: "Example sentences",
    ex0: "Payment", ex1: "Appointment", ex2: "Weather", ex3: "Iğdır to İstanbul",
    play: "Speak", stop: "Stop", loading: "Loading model", loadModel: "Load model and speak", failed: "Could not load",
    speed: "Speed", steps: "Sampling steps", stepsShort: "Steps",
    aiLabel: "AI-generated voice",
    readoutTitle: "Measurements",
    ttfa: "First audio", gen: "Generation time", len: "Audio length", rtf: "Faster than real time",
    reading: "Text as the model reads it",
    download: "Download WAV",
    foot: "Apache-2.0 · The model runs in your browser with ONNX Runtime Web.",
    downloading: "Downloading", thread: "thread", threads: "threads", chunks: "chunks",
    error: "Error", themeDark: "Dark theme", themeLight: "Light theme",
  },
};
