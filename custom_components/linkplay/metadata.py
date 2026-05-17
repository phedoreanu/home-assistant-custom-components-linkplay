"""Pure parsing helpers for LinkPlay metadata sources.

The functions here are deliberately side-effect free so they can be
unit-tested without spinning up an entity or HTTP server. The entity
methods in :mod:`media_player` delegate to these.
"""

from __future__ import annotations

import re
import string
from collections.abc import Iterable

import chardet


# ---- LinkPlay getPlayerStatus hex fields ----

_PLACEHOLDER = {"unknown"}


def decode_hex_utf8(value: str) -> str:
    """Decode a hex-encoded UTF-8 string from a LinkPlay status response.

    The device serialises track metadata as hex-encoded UTF-8 (each byte
    as two hex characters). Falls back to the raw value when the input
    is not valid hex.
    """
    try:
        return str(bytearray.fromhex(value).decode("utf-8"))
    except ValueError:
        return value


def parse_player_status_field(value: str) -> str | None:
    """Decode a metadata field from a getPlayerStatus response.

    Returns the title-cased decoded value, or ``None`` if the field is
    empty or the device reports a placeholder like ``"unknown"``.
    """
    if not value:
        return None
    decoded = decode_hex_utf8(value)
    if decoded.lower() in _PLACEHOLDER:
        return None
    return string.capwords(decoded)


# ---- Icecast ICY metadata ----

_ICY_NAME_PLACEHOLDERS = {"no name", "Unspecified name", "-"}

# SomaFM (and similar) advertise their channel as
# "SomaFM Drone Zone (#3 - 128k mp3): description here". Trim the
# parenthetical bitrate annotation and the trailing description so the
# UI shows just the station / channel name.
_SOMAFM_NAME_RE = re.compile(r"\s*\(#\d+\s*-\s*[^)]*\)\s*:?.*$")


def parse_icy_name(raw: str | None) -> str | None:
    """Normalise the icy-name response header.

    Strips known placeholder strings the integration treats as "no
    station name", best-effort re-decodes latin1 bytes that Icecast
    servers commonly send as UTF-8, and trims the verbose SomaFM
    ``(#N - bitrate): description`` suffix down to just the channel
    name.
    """
    if raw is None or raw in _ICY_NAME_PLACEHOLDERS:
        return None
    try:
        # 'latin1' default for mp3, 'utf-8' for ogg; many servers
        # send UTF-8 bytes through an HTTP layer that decoded them as
        # latin-1, so re-encode and decode to recover the original.
        decoded = raw.encode("latin1").decode("utf-8")
    except UnicodeDecodeError:
        decoded = raw
    cleaned = _SOMAFM_NAME_RE.sub("", decoded).strip()
    return cleaned or None


_STREAM_TITLE_RE = re.compile(br"StreamTitle='(.*)';")


def _clean_part(part: str) -> str | None:
    cleaned = string.capwords(part.strip().strip("-")).replace("/", " / ").replace("  ", " ")
    return cleaned or None


def parse_icy_stream_title(
    metadata_bytes: bytes,
    icecast_name: str | None = None,
) -> tuple[str | None, str | None]:
    """Extract ``(artist, title)`` from one ICY metadata chunk.

    Handles three formats commonly seen in the wild:

    * ``StreamTitle='Artist~~~~~Title';``  - United Music / Subasio
    * ``StreamTitle='Artist - Title';``    - generic Icecast
    * ``StreamTitle='Title';``             - single-field; artist falls
      back to ``[icecast_name]`` (or ``None`` when not provided)

    Returns ``(None, None)`` when the chunk has no recognisable
    StreamTitle entry. A single ``"-"`` value in either field is
    reported as ``None``.
    """
    match = _STREAM_TITLE_RE.search(metadata_bytes)
    if not match:
        return (None, None)

    raw_title = match.group(0)
    if not raw_title:
        return (None, None)

    # chardet handles whatever encoding the broadcaster decided to use.
    encoding = chardet.detect(raw_title)["encoding"]
    decoded = raw_title.decode(encoding or "utf-8", errors="ignore")
    # `decoded` still looks like "StreamTitle='...';" — strip wrapper.
    after_eq = decoded.split("='", 1)
    if len(after_eq) < 2:
        return (None, None)
    inner = after_eq[1].split("';", 1)[0]

    # Strip "[...]" prefixes (commercial breaks, jingle tags).
    inner = re.sub(r"\[.*?\]\ *", "", inner)

    # Some stations (SomaFM, BBC) prepend the channel name to every
    # StreamTitle, producing 3-part "Station - Artist - Title" entries.
    # When the leading part matches the icecast_name, drop it so the
    # caller gets the real artist/title pair.
    if icecast_name and " - " in inner:
        head, rest = inner.split(" - ", 1)
        if head.strip().lower() == icecast_name.strip().lower():
            inner = rest

    if "~~~~~" in inner:
        artist, title = inner.split("~~~~~", 1)
    elif " - " in inner:
        artist, title = inner.split(" - ", 1)
    else:
        artist = f"[{icecast_name}]" if icecast_name else None
        title = inner

    artist_out = _clean_part(artist) if artist is not None else None
    title_out = _clean_part(title)
    return artist_out, title_out


# ---- Playlist parsers ----

def parse_m3u_first_url(text: str) -> str | None:
    """Return the first ``http://`` URL from an M3U playlist body."""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("http"):
            return line
    return None


_PLS_FILE_RE = re.compile(r"^\s*File\d*\s*=\s*(.+?)\s*$", re.MULTILINE)


def parse_pls_first_url(text: str) -> str | None:
    """Return the first URL behind a ``FileN=...`` entry in a PLS body."""
    match = _PLS_FILE_RE.search(text)
    return match.group(1) if match else None


# ---- Exposed helpers iterator (for type-checkers) ----

__all__: Iterable[str] = (
    "decode_hex_utf8",
    "parse_icy_name",
    "parse_icy_stream_title",
    "parse_m3u_first_url",
    "parse_player_status_field",
    "parse_pls_first_url",
)
