import re
import unicodedata

VERIFIED_PLAYER_ALIASES = {
    "messi": "lionel messi",
    "lionel andres messi cuccittini": "lionel messi",
}


def normalize_player_name(name):
    value = (name or "Unknown player").strip()
    if "," in value:
        parts = [part.strip() for part in value.split(",", 1)]
        if all(parts):
            value = f"{parts[1]} {parts[0]}"
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.casefold()
    value = re.sub(r"[\u2018\u2019\u201b\u2032'`´]", "", value)
    value = re.sub(r"[\u2010-\u2015\-]", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return VERIFIED_PLAYER_ALIASES.get(value, value)


def is_partial_name_match(left, right):
    left_parts = normalize_player_name(left).split()
    right_parts = normalize_player_name(right).split()
    return len(left_parts) == 1 or len(right_parts) == 1
