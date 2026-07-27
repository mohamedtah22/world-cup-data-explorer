import re
import unicodedata

VERIFIED_PLAYER_ALIASES = {
    "messi": "lionel messi",
    "lionel andres messi cuccittini": "lionel messi",
}


def normalize_player_name(name, resolve_verified_aliases=True):
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
    if resolve_verified_aliases:
        return VERIFIED_PLAYER_ALIASES.get(value, value)
    return value


def is_partial_name_match(left, right):
    left_parts = normalize_player_name(left, resolve_verified_aliases=False).split()
    right_parts = normalize_player_name(right, resolve_verified_aliases=False).split()
    return len(left_parts) == 1 or len(right_parts) == 1


def player_name_parts(name):
    return normalize_player_name(name, resolve_verified_aliases=False).split()


def is_surname_only_name(name):
    return len(player_name_parts(name)) == 1


def surname_key(name):
    parts = player_name_parts(name)
    return parts[-1] if parts else ""
