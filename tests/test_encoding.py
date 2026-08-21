"""Tests for robust subtitle text decoding."""

import os

import pytest

from gsub.parsers.encoding import decode_subtitle_text
from gsub.parsers import ASSParser


def test_decode_utf8_bom():
    raw = "\ufeff[Script Info]\nTitle: Test\n".encode("utf-8")
    assert decode_subtitle_text(raw) == "[Script Info]\nTitle: Test\n"


def test_decode_plain_utf8():
    raw = "Hello, world\n".encode("utf-8")
    assert decode_subtitle_text(raw) == "Hello, world\n"


def test_decode_utf16():
    raw = "[Script Info]\nTitle: Test\n".encode("utf-16")
    # Must not raise and must contain the expected content.
    text = decode_subtitle_text(raw)
    assert "Script Info" in text
    assert "Title: Test" in text


def test_decode_cp1252_fallback():
    # Accented Western-European text that is not valid UTF-8 (cp1252 only).
    raw = "Café déjà vu - naïve".encode("cp1252")
    text = decode_subtitle_text(raw)
    assert "Café" in text
    assert "naïve" in text


def test_decode_empty():
    assert decode_subtitle_text(b"") == ""


def test_decode_bom_utf8_with_invalid_body_never_raises():
    # A UTF-8 BOM followed by bytes that are not valid UTF-8: the decoder
    # must still return usable text (via the legacy fallbacks) instead of
    # raising. The exact replacement bytes depend on charset-normalizer's
    # best guess, so only the stable prefix is asserted.
    raw = b"\xef\xbb\xbf" + b"Hello " + b"\x81"
    text = decode_subtitle_text(raw)
    assert isinstance(text, str)
    assert text.startswith("Hello")


def test_decode_utf16_be_bom():
    raw = b"\xfe\xff" + "héllo wörld".encode("utf-16-be")
    text = decode_subtitle_text(raw)
    assert text == "héllo wörld"


def test_decode_undefined_cp1252_byte_never_raises():
    # 0x81 is undefined in strict cp1252; with charset-normalizer or the
    # replacement fallback the decoder still returns a string.
    raw = "Café".encode("cp1252") + b"\x81"
    assert isinstance(decode_subtitle_text(raw), str)


def test_ass_parse_bom_populates_metadata():
    content = "\ufeff[Script Info]\nTitle: My Show\nScriptType: v4.00+\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,Hello\n"
    doc = ASSParser.parse(content)
    assert doc.metadata.get("Title") == "My Show"
    assert doc.metadata.get("ScriptType") == "v4.00+"
    assert len(doc.entries) == 1


@pytest.mark.skipif(not os.path.exists(
    "/home/obaida/Anime/Undead Unluck Winter-hen/mkvextract_subtitle.ass"),
    reason="reference ASS not present")
def test_real_ass_metadata_loaded():
    path = "/home/obaida/Anime/Undead Unluck Winter-hen/mkvextract_subtitle.ass"
    with open(path, "rb") as fh:
        doc = ASSParser.parse(decode_subtitle_text(fh.read()))
    assert doc.metadata.get("Title") == "Freehold Quick TS"
    assert "PlayResX" in doc.metadata
