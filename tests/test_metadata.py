"""Unit tests for the pure metadata parsers in metadata.py."""

from __future__ import annotations

import pytest

from custom_components.linkplay.metadata import (
    decode_hex_utf8,
    parse_icy_name,
    parse_icy_stream_title,
    parse_m3u_first_url,
    parse_player_status_field,
    parse_pls_first_url,
)


class TestDecodeHexUtf8:
    def test_decodes_valid_hex(self) -> None:
        # "Hello" in hex
        assert decode_hex_utf8("48656c6c6f") == "Hello"

    def test_decodes_utf8_multibyte(self) -> None:
        # "Café" - ascii then UTF-8 acute-é (0xc3 0xa9)
        assert decode_hex_utf8("436166c3a9") == "Café"

    def test_invalid_hex_falls_through(self) -> None:
        assert decode_hex_utf8("not-hex-data") == "not-hex-data"

    def test_empty_returns_empty(self) -> None:
        assert decode_hex_utf8("") == ""


class TestPlayerStatusField:
    def test_empty_returns_none(self) -> None:
        assert parse_player_status_field("") is None

    def test_unknown_placeholder_returns_none(self) -> None:
        # "unknown" hex-encoded
        assert parse_player_status_field("756e6b6e6f776e") is None

    def test_uppercase_unknown_placeholder_returns_none(self) -> None:
        assert parse_player_status_field("Unknown") is None

    def test_titlecases_decoded_value(self) -> None:
        # "the dark side"
        assert parse_player_status_field("746865206461726b2073696465") == "The Dark Side"

    def test_non_hex_value_titlecased(self) -> None:
        assert parse_player_status_field("hello world") == "Hello World"


class TestIcyName:
    def test_none_returns_none(self) -> None:
        assert parse_icy_name(None) is None

    @pytest.mark.parametrize("placeholder", ["no name", "Unspecified name", "-"])
    def test_placeholders_return_none(self, placeholder: str) -> None:
        assert parse_icy_name(placeholder) is None

    def test_returns_plain_name(self) -> None:
        assert parse_icy_name("My Radio") == "My Radio"

    def test_redecodes_latin1_to_utf8(self) -> None:
        # Server sent UTF-8 bytes for "Café"; HTTP layer decoded as latin-1
        # producing "CafÃ©". We recover the original by re-encoding latin-1
        # then decoding as UTF-8.
        latin1_misdecoded = "Café".encode("utf-8").decode("latin1")
        assert parse_icy_name(latin1_misdecoded) == "Café"

    def test_strips_somafm_verbose_suffix(self) -> None:
        assert (
            parse_icy_name("SomaFM Drone Zone (#3 - 128k mp3): ambient drone")
            == "SomaFM Drone Zone"
        )

    def test_strips_somafm_suffix_without_description(self) -> None:
        assert parse_icy_name("Groove Salad (#2 - 256k aac)") == "Groove Salad"

    def test_keeps_plain_name_without_somafm_suffix(self) -> None:
        assert parse_icy_name("BBC Radio 1") == "BBC Radio 1"


class TestStreamTitle:
    def test_no_match_returns_none_tuple(self) -> None:
        assert parse_icy_stream_title(b"") == (None, None)

    def test_no_match_with_junk_returns_none_tuple(self) -> None:
        assert parse_icy_stream_title(b"no metadata here") == (None, None)

    def test_simple_artist_title(self) -> None:
        artist, title = parse_icy_stream_title(b"StreamTitle='The Beatles - Hey Jude';")
        assert artist == "The Beatles"
        assert title == "Hey Jude"

    def test_subasio_tilde_separator(self) -> None:
        artist, title = parse_icy_stream_title(
            b"StreamTitle='Subasio~~~~~Some Song';"
        )
        assert artist == "Subasio"
        assert title == "Some Song"

    def test_title_only_uses_station_as_artist(self) -> None:
        artist, title = parse_icy_stream_title(
            b"StreamTitle='Solo Title';", icecast_name="My Radio"
        )
        assert artist == "[my Radio]"  # capwords lowercases the prefix bracket
        assert title == "Solo Title"

    def test_title_only_without_station_has_no_artist(self) -> None:
        artist, title = parse_icy_stream_title(b"StreamTitle='Solo Title';")
        assert artist is None
        assert title == "Solo Title"

    def test_bracket_prefix_stripped(self) -> None:
        artist, title = parse_icy_stream_title(
            b"StreamTitle='[Ad break] Artist - Track';"
        )
        assert artist == "Artist"
        assert title == "Track"

    def test_dash_placeholders_return_none(self) -> None:
        artist, title = parse_icy_stream_title(b"StreamTitle='- - -';")
        # Both sides are "-" after split + strip; both reported as None.
        assert artist is None
        assert title is None

    def test_strips_leading_station_prefix(self) -> None:
        """SomaFM-style 'Station - Artist - Title' should yield (artist, title)
        rather than (station, 'Artist - Title')."""
        artist, title = parse_icy_stream_title(
            b"StreamTitle='SomaFM Drone Zone - Carbon Based Lifeforms - World Of Sleepers';",
            icecast_name="SomaFM Drone Zone",
        )
        assert artist == "Carbon Based Lifeforms"
        assert title == "World Of Sleepers"

    def test_keeps_artist_title_when_no_station_prefix(self) -> None:
        artist, title = parse_icy_stream_title(
            b"StreamTitle='Carbon Based Lifeforms - World Of Sleepers';",
            icecast_name="SomaFM Drone Zone",
        )
        assert artist == "Carbon Based Lifeforms"
        assert title == "World Of Sleepers"

    def test_station_prefix_case_insensitive(self) -> None:
        artist, title = parse_icy_stream_title(
            b"StreamTitle='somafm drone zone - Loscil - Charlie';",
            icecast_name="SomaFM Drone Zone",
        )
        assert artist == "Loscil"
        assert title == "Charlie"


class TestPlaylistParsers:
    def test_m3u_returns_first_http_url(self) -> None:
        text = "#EXTM3U\n#EXTINF:-1\nhttp://example.com/stream\nhttp://other/x\n"
        assert parse_m3u_first_url(text) == "http://example.com/stream"

    def test_m3u_returns_none_when_no_url(self) -> None:
        text = "#EXTM3U\n#EXTINF:-1\nrelative-path.mp3\n"
        assert parse_m3u_first_url(text) is None

    def test_m3u_handles_crlf(self) -> None:
        text = "#EXTM3U\r\nhttp://example.com/stream\r\n"
        assert parse_m3u_first_url(text) == "http://example.com/stream"

    def test_pls_returns_first_file_url(self) -> None:
        text = "[playlist]\nNumberOfEntries=2\nFile1=http://example.com/stream\nFile2=http://other/x\n"
        assert parse_pls_first_url(text) == "http://example.com/stream"

    def test_pls_returns_none_when_no_file_entry(self) -> None:
        text = "[playlist]\nNumberOfEntries=0\n"
        assert parse_pls_first_url(text) is None

    def test_pls_tolerates_whitespace(self) -> None:
        text = "[playlist]\n  File1  =  http://example.com/stream  \n"
        assert parse_pls_first_url(text) == "http://example.com/stream"
