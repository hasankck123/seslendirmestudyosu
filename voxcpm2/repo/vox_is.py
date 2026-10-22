# -*- coding: utf-8 -*-
"""Tek seferlik VoxCPM2 işi: stüdyodan gelen JSON'u okur, sesleri üretir, sonucu JSON'a yazar.

Çağrı:  <python> vox_is.py <is.json> <sonuc.json>
İş dosyası isteğe bağlı "motor" ve "backend" alanlarıyla ayarlar.json'u geçersiz kılabilir
(taşınabilir pakette CUDA/Vulkan motoru otomatik seçilir).
"""
import base64
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from ses_tasarim import ayarlar, motor, okunus, oku  # noqa: E402


def sayi_cevir(text: str, modul_yolu: str | None) -> str:
    """Rakamları Türkçe okunuşa çevirir (2,5 → iki virgül beş). Modül stüdyodan gelir."""
    if not modul_yolu:
        return text
    try:
        import re
        if modul_yolu not in sys.path:
            sys.path.insert(0, modul_yolu)
        from mathspeak import number_to_words
    except Exception:
        return text

    def cevir(m):
        tok = m.group(0)
        try:
            if "," in tok:
                tam, kesir = tok.split(",", 1)
                return f"{number_to_words(int(tam))} virgül {' '.join(number_to_words(int(d)) for d in kesir)}"
            return number_to_words(int(tok))
        except Exception:
            return tok

    return re.sub(r"\d+(?:,\d+)?", cevir, text)


def main() -> int:
    is_yolu, sonuc_yolu = Path(sys.argv[1]), Path(sys.argv[2])
    istek = json.loads(is_yolu.read_text(encoding="utf-8"))
    try:
        settings = ayarlar.load(str(REPO / "ayarlar.json"))
        if istek.get("motor"):
            settings["motor"] = Path(str(istek["motor"]))
        if istek.get("backend"):
            settings["backend"] = str(istek["backend"])
        settings["cuda_bin"] = None  # CUDA DLL'leri motorun yanında; PATH'e eklemek gerekmez
        voice_dir = oku.find_voice(settings, istek["ses"])
        card = json.loads((voice_dir / "ses.json").read_text(encoding="utf-8"))
        is_klasor = Path(istek["cikti"])
        is_klasor.mkdir(parents=True, exist_ok=True)
        reference = motor.reference_wav(voice_dir / card.get("referans", "referans.wav"), is_klasor)

        istekler, metinler = [], {}
        for it in istek["items"]:
            ham = sayi_cevir(it.get("text") or "", istek.get("sayi_modulu"))
            metin = " ".join(line for line, _ in okunus.lines(okunus.spoken(ham))).strip()
            if not metin:
                continue
            istekler.append(motor.read_request(str(it["id"]), metin, int(card["okuma_tohumu"]), reference,
                                               card["ses_yaratilirken_okutulan_metin"]))
            metinler[str(it["id"])] = metin

        def ilerle(bitti, toplam, sn):
            print(f"{bitti}/{toplam} adim, {sn:.0f} sn", file=sys.stderr, flush=True)

        sonuc = motor.run_sequence(settings, istekler, is_klasor, ilerle) if istekler else {"audios": {}, "bad": [],
                                                                                           "seconds": 0, "vram_peak_mb": 0}
        cikti = []
        for req in istekler:
            audio = sonuc["audios"].get(req["id"])
            if audio is None:
                raise RuntimeError(f"{req['id']} üretilemedi (yarım kalan cümle olabilir)")
            wav = is_klasor / "out" / f"{req['id']}.wav"
            cikti.append({"id": req["id"], "seconds": round(len(audio) / motor.SAMPLE_RATE, 3),
                          "modelText": metinler[req["id"]],
                          "wav": base64.b64encode(wav.read_bytes()).decode("ascii")})
        veri = {"ok": True, "items": cikti, "seconds": sonuc["seconds"], "bellek_mb": sonuc["vram_peak_mb"]}
    except Exception as exc:  # sonucu her durumda yaz ki stüdyo mesajı gösterebilsin
        veri = {"ok": False, "hata": f"{type(exc).__name__}: {exc}"}
    sonuc_yolu.write_text(json.dumps(veri, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
