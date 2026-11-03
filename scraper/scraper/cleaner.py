import re

PUBLISHER_REPLACEMENTS = {
    r"\bUniv\.?\b": "Universitas",
    r"\bInst\.?\b": "Institut",
    r"\bPolines\b": "Politeknik Negeri Semarang",
    r"\bUnnes\b": "Universitas Negeri Semarang",
    r"\bUndip\b": "Universitas Diponegoro",
}

ACRONYM_MAX_LENGTH = 5

def normalize_publisher_name(raw_name: str) -> str:
    if not raw_name:
        return raw_name
    name = raw_name.strip()
    name = re.sub(r"\s+", " ", name)

    for pattern, replacement in PUBLISHER_REPLACEMENTS.items():
        name = re.sub(pattern, replacement, name, flags=re.IGNORECASE)

    words = []
    for w in name.split():
        letters_only = re.sub(r"[^A-Za-z]", "", w)
        if w.isupper() and len(letters_only) <= ACRONYM_MAX_LENGTH and len(letters_only) >= 2:
            words.append(w)
        elif w.isupper() and len(letters_only) > ACRONYM_MAX_LENGTH:
            words.append(w.capitalize())
        else:
            words.append(w)
    name = " ".join(words)

    return name.strip()


def validate_issn(issn: str) -> bool:
    if not issn:
        return False
    issn = issn.strip().upper()
    return bool(re.match(r"^\d{4}-?\d{3}[\dxX]$", issn))

def issn_check_char(d7: str) -> str:
    total = sum(
        int(c) * w
        for c, w in zip(d7, range(8, 1, -1))
    )
    r = (11 - total % 11) % 11
    return "X" if r == 10 else str(r)


def clean_issn(issn: str) -> str | None:
    if not issn:
        return None

    s = re.sub(r"[\s-]", "", issn.strip().upper())

    # Memulihkan ISSN 7 digit yang check digit-nya X
    if re.fullmatch(r"\d{7}", s) and issn_check_char(s) == "X":
        s += "X"

    if not re.fullmatch(r"\d{7}[\dX]", s):
        return None

    return f"{s[:4]}-{s[4:]}"