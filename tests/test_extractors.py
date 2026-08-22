"""Tests for the subtitle extraction backend."""

import os

import pytest

av = pytest.importorskip("av")

from gsub.extractors import (
    EXTENSION_FOR_FORMAT,
    detect_format,
    extract_track_by_gst,
    list_subtitle_tracks,
)
from gsub.extractors.pyav_extractor import (
    _fmt_ass_time,
    _fmt_srt_time,
    _reconstruct_ass_line,
    _resolve_family,
)

# Optional, user-provided fixtures used for fidelity comparison.
_ANIME_DIR = "/home/obaida/Anime/Undead Unluck Winter-hen"
TEST_MKV = os.path.join(
    _ANIME_DIR,
    "Undead.Unluck.S00E01v2.Winter.Arc.1080p.AMZN.WEB-DL.JPN.DDP2.0.H.264.ESub-ToonsHub.mkv",
)
REF_ASS = os.path.join(_ANIME_DIR, "mkvextract_subtitle.ass")


def test_fmt_ass_time():
    assert _fmt_ass_time(1.67) == "0:00:01.67"
    assert _fmt_ass_time(5.18) == "0:00:05.18"
    assert _fmt_ass_time(3661.5) == "1:01:01.50"
    assert _fmt_ass_time(None) == "0:00:00.00"


def test_fmt_srt_time():
    assert _fmt_srt_time(1.0) == "00:00:01,000"
    assert _fmt_srt_time(3.5) == "00:00:03,500"
    assert _fmt_srt_time(None) == "00:00:00,000"


def test_reconstruct_ass_line():
    raw = "0,0,Default,,0,0,0,,{\\an8}Hello\\NWorld"
    line = _reconstruct_ass_line(raw, 1.67, 3.51)
    assert line.startswith("Dialogue: 0,0:00:01.67,0:00:05.18,Default,,")
    assert line.endswith("{\\an8}Hello\\NWorld")


def test_reconstruct_ass_line_short_payload():
    raw = "garbage"
    assert _reconstruct_ass_line(raw, 0.0, 1.0) == "Dialogue: garbage"


def test_family():
    class _S:
        def __init__(self, name, extra=b""):
            self.codec_context = type("C", (), {"name": name, "extradata": extra})()

    assert _resolve_family(_S("ass", b"[V4+ Styles]")) == "ass"
    assert _resolve_family(_S("ssa", b"[V4+ Styles]")) == "ass"
    assert _resolve_family(_S("ssa", b"[V4 Styles]")) == "ssa"
    assert _resolve_family(_S("subrip")) == "srt"
    assert _resolve_family(_S("mov_text")) == "srt"
    with pytest.raises(Exception):
        _resolve_family(_S("hdmv_pgs_subtitle"))


def test_extension_mapping():
    assert EXTENSION_FOR_FORMAT["ass"] == ".ass"
    assert EXTENSION_FOR_FORMAT["ssa"] == ".ssa"
    assert EXTENSION_FOR_FORMAT["srt"] == ".srt"


@pytest.mark.skipif(not os.path.exists(TEST_MKV), reason="test MKV not present")
def test_list_and_detect(tmp_path):
    tracks = list_subtitle_tracks(TEST_MKV)
    assert tracks
    assert all(t.codec_family in ("ass", "ssa", "srt") for t in tracks)

    # This track is true ASS (v4+); it must not be reported as SSA even though
    # PyAV labels the codec "ssa".
    assert tracks[0].codec_family == "ass"

    gst = {"index": 0, "language": "eng", "codec": "application/x-ass", "title": None}
    assert detect_format(TEST_MKV, gst) == "ass"


@pytest.mark.skipif(not os.path.exists(TEST_MKV), reason="test MKV not present")
def test_gst_codec_substation_alpha_is_recognised(tmp_path):
    # GStreamer commonly reports ASS/SSA tracks as "SubStation Alpha".
    gst = {"index": 0, "language": "eng", "codec": "SubStation Alpha", "title": None}
    assert detect_format(TEST_MKV, gst) == "ass"

    out = tmp_path / "out.ass"
    fmt = extract_track_by_gst(TEST_MKV, gst, str(out))
    assert fmt == "ass"
    assert out.exists()


@pytest.mark.skipif(not os.path.exists(TEST_MKV), reason="test MKV not present")
def test_extract_matches_mkvextract(tmp_path):
    gst = {"index": 0, "language": "eng", "codec": "application/x-ass", "title": None}
    out = tmp_path / "out.ass"
    fmt = extract_track_by_gst(TEST_MKV, gst, str(out))

    assert fmt == "ass"
    assert out.exists()

    content = out.read_text(encoding="utf-8-sig")
    # Styles and override codes must be preserved (the original SRT bug lost these).
    assert "[V4+ Styles]" in content
    assert "Dialogue:" in content
    assert "{\\an8}" in content

    # Output should be identical to mkvextract (ignoring BOM and blank lines).
    ref = open(REF_ASS, encoding="utf-8-sig").read().splitlines()
    got = content.splitlines()
    ref_n = [line for line in ref if line.strip()]
    got_n = [line for line in got if line.strip()]
    assert got_n == ref_n
