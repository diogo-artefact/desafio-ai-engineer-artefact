from __future__ import annotations

import re
import unicodedata


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", without_accents.lower()).strip()


def normalize_phone_digits(phone: str) -> str:
    return re.sub(r"\D", "", phone)
