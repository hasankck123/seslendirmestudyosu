# -*- coding: utf-8 -*-
"""Matematik kısayollarını Türkçe okunuşa çevirir (seslendirme için).

Kurallar:
  - Üslü ifadeler OKUNUR, SONUCU ASLA HESAPLANMAZ:
        4^3, 4**3, 4³   ->  "dört üzeri üç"      (64 DENMEZ)
        (2²)³           ->  "parantez iki üzeri iki parantez üzeri üç"
        12², 2¹⁰, x², 2^n
  - Örtük çarpım: 2x -> "iki iks", 2x² -> "iki çarpı iks üzeri iki"
  - İşleçler: / -> bölü, * veya × -> çarpı, + -> artı, = -> eşittir
  - Eksi: yalnızca iki yanı boşluklu " - " ya da "=" içeren satırdaki "5-3"
    kalıbı "eksi" olur; "3-5 gün" gibi aralıklar korunur.
  - Kalan her şey (yüzdeler, normal sayılar, TL, C şıkkı...) Antalia'nın kendi
    normalizasyonuna bırakılır.
"""
from __future__ import annotations

import re

__all__ = ["speak_math"]

SUPS = {"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9"}
SUP_CHARS = "⁰¹²³⁴⁵⁶⁷⁸⁹⁻"
SUP_RE = f"[{SUP_CHARS}]+"

ONES = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
TENS = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]

LETTER_NAMES = {
    "a": "a", "b": "be", "c": "ce", "ç": "çe", "d": "de", "e": "e", "f": "fe", "g": "ge",
    "h": "he", "ı": "ı", "i": "i", "j": "je", "k": "ke", "l": "le", "m": "me", "n": "ne",
    "o": "o", "ö": "ö", "p": "pe", "q": "kü", "r": "re", "s": "se", "ş": "şe", "t": "te",
    "u": "u", "ü": "ü", "v": "ve", "w": "dabılyu", "x": "iks", "y": "ye", "z": "ze",
}

# örtük çarpımda değişken sayılan harfler
VAR_LETTERS = "xyz nktmab".replace(" ", "")


def _three(n: int) -> str:
    h, r = divmod(n, 100)
    t, o = divmod(r, 10)
    out = []
    if h:
        out.append("yüz" if h == 1 else ONES[h] + " yüz")
    if t:
        out.append(TENS[t])
    if o:
        out.append(ONES[o])
    return " ".join(out)


def number_to_words(n: int) -> str:
    if n < 0:
        return "eksi " + number_to_words(-n)
    if n == 0:
        return "sıfır"
    out = []
    mg, rest = divmod(n, 1_000_000)
    kb, rest2 = divmod(rest, 1000)
    if mg:
        out.append("bir milyon" if mg == 1 else number_to_words(mg) + " milyon")
    if kb:
        out.append("bin" if kb == 1 else _three(kb) + " bin")
    if rest2:
        out.append(_three(rest2))
    return " ".join(out)


def _num_token_to_words(tok: str) -> str:
    tok = tok.strip()
    if "," in tok or "." in tok:
        whole, frac = re.split(r"[.,]", tok, maxsplit=1)
        whole_w = number_to_words(int(whole)) if whole else "sıfır"
        frac_w = number_to_words(int(frac)) if frac else ""
        return f"{whole_w} virgül {frac_w}".strip()
    return number_to_words(int(tok))


def _letter_to_words(ch: str) -> str:
    return LETTER_NAMES.get(ch.lower(), ch)


def _sup_to_words(sup: str) -> str:
    neg = sup.startswith("⁻")
    digits = sup.replace("⁻", "")
    val = int("".join(SUPS[d] for d in digits)) if digits else 0
    words = number_to_words(val)
    return f"eksi {words}" if neg else words


# gövde: parantezli grup | ondalık sayı | tek harf
_BASE = r"(?:\([^()]{1,60}\)|[0-9]{1,15}(?:[.,][0-9]{1,6})?|[A-Za-zÇĞİÖŞÜçğıöşü])"
_EXP = r"(?:\([^()]{1,60}\)|[0-9]{1,15}|[A-Za-zÇĞİÖŞÜçğıöşü])"
_POWER_RE = re.compile(
    f"(?:(?P<sb>{_BASE})(?P<sup>{SUP_RE}))|(?:(?P<cb>{_BASE})\\s*(?:\\^|\\*\\*)\\s*(?P<exp>{_EXP}))"
)


def _token_words(tok: str) -> str:
    """Üs veya gövde belirteci -> okunuş. Parantezliyse içi özyinelemeli çevrilir."""
    tok = tok.strip()
    if tok.startswith("(") and tok.endswith(")"):
        return "parantez " + speak_math(tok[1:-1].strip()) + " parantez"
    if tok and tok[0].isdigit():
        return _num_token_to_words(tok)
    if len(tok) == 1:
        return _letter_to_words(tok)
    return speak_math(tok)


def speak_math(text: str) -> str:
    """Metni seslendirilebilir hâle çevirir (üssün sonucu hesaplanmaz)."""
    if not text:
        return text
    t = text
    # benzer işaretleri normalize et
    t = t.replace("−", "-").replace("–", "-").replace("×", "*").replace("·", "*").replace("÷", "/")

    store: list[str] = []

    def _expand(m: re.Match) -> str:
        if m.group("sb") is not None:
            base, exp_w = m.group("sb"), _sup_to_words(m.group("sup"))
        else:
            base, exp = m.group("cb"), m.group("exp")
            exp_w = _token_words(exp)
        spoken = f"{_token_words(base)} üzeri {exp_w}"
        store.append(spoken)
        return f"\x01{len(store) - 1}\x02"

    for _ in range(200):  # iç içe ifadeler için sabit nokta
        t, n = _POWER_RE.subn(_expand, t)
        if not n:
            break

    # örtük çarpım: 2x -> "iki iks" (2x1 gibi kalıplara dokunmaz)
    t = re.sub(
        rf"(?<![0-9A-Za-zÇĞİÖŞÜçğıöşü\x02])([0-9]{{1,3}})([{VAR_LETTERS}])\b",
        lambda m: f"{number_to_words(int(m.group(1)))} {_letter_to_words(m.group(2))}",
        t,
    )
    # basamak + üslü belirteç: 2x² -> "iki çarpı iks üzeri iki"
    t = re.sub(
        r"(?<![0-9A-Za-zÇĞİÖŞÜçğıöşü\x02])([0-9]{1,3})(?=\x01)",
        lambda m: f"{number_to_words(int(m.group(1)))} çarpı ",
        t,
    )

    # eksi: iki yanı boşluklu " - "
    t = re.sub(r"(?<=[^\s])\s+-\s+(?=[^\s])", " eksi ", t)

    # eksi: "=" içeren satırda bitişik çıkarma (5-3=2); aralık (3-5 gün) korunur
    def _dash(m: re.Match) -> str:
        if "=" in t[m.end():]:
            return f"{m.group(1)} eksi {m.group(2)}"
        return m.group(0)

    t = re.sub(r"([0-9\x02])-([0-9\x01(])", _dash, t)

    # bölü / çarpı / artı / eşittir
    t = re.sub(r"(?<=[^\s])\s*/\s*(?=[^\s])", " bölü ", t)
    t = re.sub(r"(?<=[^\s])\s*\*+\s*(?=[^\s])", " çarpı ", t)
    t = re.sub(r"(?<=[^\s])\s*\+\s*(?=[^\s])", " artı ", t)
    t = re.sub(r"\s*=\s*", " eşittir ", t)

    # yer tutucuları okunuşlarıyla değiştir
    t = re.sub(r"\x01(\d+)\x02", lambda m: store[int(m.group(1))], t)
    # boşlukları toparla
    t = re.sub(r"\s{2,}", " ", t).strip()
    t = re.sub(r"\s+([,.;!?])", r"\1", t)
    return t


def _self_test() -> None:
    cases = [
        ("4^4 / 4^1 = 4^3", "dört üzeri dört bölü dört üzeri bir eşittir dört üzeri üç"),
        ("4⁴ / 4¹ = 4³", "dört üzeri dört bölü dört üzeri bir eşittir dört üzeri üç"),
        ("(2^2)^3 = 2^6", "parantez iki üzeri iki parantez üzeri üç eşittir iki üzeri altı"),
        ("(2²)³ = 2⁶", "parantez iki üzeri iki parantez üzeri üç eşittir iki üzeri altı"),
        ("2⁶ / 2¹ = 2⁵", "iki üzeri altı bölü iki üzeri bir eşittir iki üzeri beş"),
        ("12² işleminin sonucu", "on iki üzeri iki işleminin sonucu"),
        ("2¹⁰ kaçtır", "iki üzeri on kaçtır"),
        ("x² + 2x - 3 = 0", "iks üzeri iki artı iki iks eksi 3 eşittir 0"),
        ("2x² ifadesi", "iki çarpı iks üzeri iki ifadesi"),
        ("2^n ifadesi", "iki üzeri ne ifadesi"),
        ("5 - 3 = 2", "5 eksi 3 eşittir 2"),
        ("5-3=2", "5 eksi 3 eşittir 2"),
        ("3-5 gün sürer", "3-5 gün sürer"),
        ("2*3", "2 çarpı 3"),
        ("%25'i dolu", "%25'i dolu"),
        ("64 litre", "64 litre"),
        ("C seçeneği", "C seçeneği"),
        ("4 üzeri 3 zaten yazılmış", "4 üzeri 3 zaten yazılmış"),
        ("(2+3) toplamı", "(2 artı 3) toplamı"),
        ("256 litre", "256 litre"),
        ("2x1 tablet", "2x1 tablet"),
    ]
    bad = 0
    for src, want in cases:
        got = speak_math(src)
        if got != want:
            bad += 1
            print(f"FAIL: {src!r}\n  got : {got!r}\n  want: {want!r}")
    print("OK" if not bad else f"{bad} FAIL")
    for src, _ in cases:
        print(f"  {src!r:42} -> {speak_math(src)!r}")


if __name__ == "__main__":
    _self_test()
