import re
import unicodedata


_ABBREVIATIONS = {
    "synth": "synthetic",
    "synth.": "synthetic",
}


def normalize_product_name(value: str | None) -> str:
    """Return a lowercase, punctuation-free comparison key for a product name."""
    if not value:
        return ""

    text = unicodedata.normalize("NFKD", value)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)

    words = [_ABBREVIATIONS.get(word, word) for word in text.strip().split()]
    return " ".join(words)
