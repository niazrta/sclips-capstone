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


def clean_issn(issn: str) -> str | None:
    if not issn:
        return None
    issn = issn.strip().upper().replace("-", "")
    if not re.match(r"^\d{7}[\dX]$", issn):
        return None
    return f"{issn[:4]}-{issn[4:]}"