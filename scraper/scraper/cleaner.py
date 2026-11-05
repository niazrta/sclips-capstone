import re

INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200e\u200f\u202a\u202b\u202c\u202d\u202e\ufeff"))


def collapse_spaces(s):
    """Rapikan spasi ganda/baris baru jadi satu spasi. Huruf tidak diubah."""
    return " ".join((s or "").split()) or None


def classify_issn(raw):
    """Return (nilai, status). Tidak menambah, menghitung, atau membuang angka dan huruf."""
    raw = (raw or "").translate(INVISIBLE).strip()
    if raw in ("", "0", "-"):
        return None, "none"
    m = re.fullmatch(r"(\d{4})[\s\-\u2010-\u2015:_]?(\d{3}[\dXx])", raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}", "valid"
    if re.fullmatch(r"[\dXx-]{1,7}", raw) and re.search(r"\d", raw):
        return raw, "short"
    return raw, "invalid"