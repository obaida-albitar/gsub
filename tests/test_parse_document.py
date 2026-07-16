"""Tests for subtitle format dispatch (open-file parsing flow).

These cover the extension-based dispatch used when opening a file, including
the regression where opening an SRT file crashed because ``parse_warnings``
was referenced before being assigned on the non-ASS path.
"""

import pytest
from subtitle_editor.parsers import parse_subtitle_document
from subtitle_editor.models import SubtitleFormat


@pytest.mark.unit
@pytest.mark.parser
class TestParseSubtitleDocument:
    @pytest.mark.unit
    @pytest.mark.parser
    def test_srt_returns_document_and_empty_warnings(self):
        content = "1\n00:00:01,000 --> 00:00:02,000\nHello\n"
        doc, warnings = parse_subtitle_document(content, ".srt")
        assert doc is not None
        assert doc.format == SubtitleFormat.SRT
        assert len(doc.entries) == 1
        # The returned warnings object is always a defined (empty) list.
        assert warnings == []

    @pytest.mark.unit
    @pytest.mark.parser
    def test_srt_without_dot_extension(self):
        content = "1\n00:00:01,000 --> 00:00:02,000\nHello\n"
        doc, warnings = parse_subtitle_document(content, "srt")
        assert doc is not None
        assert doc.format == SubtitleFormat.SRT
        assert warnings == []

    @pytest.mark.unit
    @pytest.mark.parser
    def test_ass_with_bad_style_values_populates_warnings(self):
        content = """[Script Info]
Title: Bad
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Broken,Arial,notanumber,&H00FFFFFF,&H00000000,&H00000000,&H00000000,-1,0,0,0,-50,0,0,0,2,2,2,99,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.00,Broken,,,0,0,0,,Hi
"""
        doc, warnings = parse_subtitle_document(content, ".ass")
        assert doc is not None
        assert doc.format == SubtitleFormat.ASS
        style = doc.styles[0]
        # Sanitized values.
        assert style.fontsize == 20
        assert style.scale_x == 100.0
        assert style.alignment == 9
        assert style.border_style == 1
        # Warnings were collected (this used to require the caller to pass a list).
        assert len(warnings) >= 3

    @pytest.mark.unit
    @pytest.mark.parser
    def test_ssa_extension_is_supported(self):
        content = """[Script Info]
ScriptType: v4.00

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H00000000,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1
"""
        doc, warnings = parse_subtitle_document(content, ".ssa")
        assert doc is not None
        assert doc.format == SubtitleFormat.SSA
        # File looks like ASS/SSA (has a styles section) but defines no
        # [Events] section, so the parser reports it has no subtitles.
        assert any("No [Events]" in w for w in warnings)

    @pytest.mark.unit
    @pytest.mark.parser
    def test_unsupported_extension_returns_none(self):
        doc, warnings = parse_subtitle_document("whatever", ".txt")
        assert doc is None
        assert warnings == []

    @pytest.mark.unit
    @pytest.mark.parser
    def test_regression_warnings_always_defined_for_srt(self):
        """Opening an SRT must never raise UnboundLocalError on the warnings list."""
        content = "1\n00:00:01,000 --> 00:00:02,000\nHi\n"
        # This mirrors the open_file flow that previously crashed on SRT.
        doc, parse_warnings = parse_subtitle_document(content, ".srt")
        assert doc is not None
        # The "show warnings toast" branch must have a defined list to test.
        assert isinstance(parse_warnings, list)
        if parse_warnings:
            pass
