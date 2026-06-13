"""Tests for uncovered code paths in ASS and SRT parsers."""

import pytest
from subtitle_editor.parsers import SRTParser, ASSParser
from subtitle_editor.models import SubtitleFormat, TimeCode


class TestASSParserEdgeCases:
    """Tests for edge cases in ASS parser (uncovered paths)."""

    @pytest.mark.unit
    @pytest.mark.parser
    def test_style_with_insufficient_fields(self):
        """Style lines with fewer fields than Format expects are skipped."""
        content = """[Script Info]
Title: Test

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.50,0:00:02.00,Default,,,0,0,0,,Test
"""
        doc = ASSParser.parse(content)
        assert len(doc.styles) == 1
        assert doc.styles[0].name == "Default"

    @pytest.mark.unit
    @pytest.mark.parser
    def test_dialogue_with_insufficient_fields(self):
        """Dialogue lines with fewer fields than Format expects are skipped."""
        content = """[Script Info]
Title: Test

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H00000000,&H00000000,&H00000000,0,0,0,0,100.0,100.0,0.0,0.0,1,2.0,0.0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.50,0:00:02.00
Dialogue: 0,0:00:03.00,0:00:05.00,Default,,0,0,0,effect,Valid
"""
        doc = ASSParser.parse(content)
        assert len(doc.entries) == 1
        assert doc.entries[0].text == "Valid"

    @pytest.mark.unit
    @pytest.mark.parser
    def test_dialogue_with_invalid_margin_values(self):
        """Non-integer margin values fall back to 0."""
        content = """[Script Info]
Title: Test

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H00000000,&H00000000,&H00000000,0,0,0,0,100.0,100.0,0.0,0.0,1,2.0,0.0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.50,0:00:02.00,Default,,abc,def,ghi,,Test margins
"""
        doc = ASSParser.parse(content)
        entry = doc.entries[0]
        assert entry.margin_l == 0
        assert entry.margin_r == 0
        assert entry.margin_v == 0
        assert entry.text == "Test margins"

    @pytest.mark.unit
    @pytest.mark.parser
    def test_dialogue_with_invalid_layer_value(self):
        """Non-integer layer value falls back to 0."""
        content = """[Script Info]
Title: Test

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H00000000,&H00000000,&H00000000,0,0,0,0,100.0,100.0,0.0,0.0,1,2.0,0.0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: abc,0:00:00.50,0:00:02.00,Default,,0,0,0,,Invalid layer
"""
        doc = ASSParser.parse(content)
        entry = doc.entries[0]
        assert entry.layer == 0
        assert entry.text == "Invalid layer"

    @pytest.mark.unit
    @pytest.mark.parser
    def test_dialogue_missing_start_or_end_time(self):
        """Dialogue with missing Start or End field in format is skipped."""
        content = """[Script Info]
Title: Test

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H00000000,&H00000000,&H00000000,0,0,0,0,100.0,100.0,0.0,0.0,1,2.0,0.0,2,10,10,10,1

[Events]
Format: Layer, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,Default,,0,0,0,,No start or end
"""
        doc = ASSParser.parse(content)
        assert len(doc.entries) == 0

    @pytest.mark.unit
    @pytest.mark.parser
    def test_malformed_timecode_returns_default(self):
        """Invalid timecode format returns TimeCode(), entry is still created."""
        content = """[Script Info]
Title: Test

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H00000000,&H00000000,&H00000000,0,0,0,0,100.0,100.0,0.0,0.0,1,2.0,0.0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,NOT_A_TIMECODE,ALSO_INVALID,Default,,0,0,0,,Bad times
"""
        doc = ASSParser.parse(content)
        assert len(doc.entries) == 1
        entry = doc.entries[0]
        assert entry.start_time.total_milliseconds == 0
        assert entry.end_time.total_milliseconds == 0

    @pytest.mark.unit
    @pytest.mark.parser
    def test_aegisub_garbage_line_without_colon(self):
        """Aegisub Project Garbage line without colon is skipped (no crash)."""
        content = """[Script Info]
Title: Test

[Aegisub Project Garbage]
Audio File: audio.wav
GarbageLineNoColon

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H00000000,&H00000000,&H00000000,0,0,0,0,100.0,100.0,0.0,0.0,1,2.0,0.0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.50,0:00:02.00,Default,,0,0,0,,Test
"""
        doc = ASSParser.parse(content)
        assert "Audio File" in doc.aegisub_project_garbage
        assert "GarbageLineNoColon" not in doc.aegisub_project_garbage

    @pytest.mark.unit
    @pytest.mark.parser
    def test_script_info_without_colon(self):
        """Script Info line without colon is skipped (no crash)."""
        content = """[Script Info]
Title: Test
NoColonLine

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H00000000,&H00000000,&H00000000,0,0,0,0,100.0,100.0,0.0,0.0,1,2.0,0.0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.50,0:00:02.00,Default,,0,0,0,,Test
"""
        doc = ASSParser.parse(content)
        assert doc.metadata["Title"] == "Test"
        assert "NoColonLine" not in doc.metadata


class TestSRTParserEdgeCases:
    """Tests for edge cases in SRT parser (uncovered paths)."""

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_srt_invalid_index_value(self):
        """SRT block with non-integer index is skipped."""
        content = """abc
00:00:01,000 --> 00:00:02,000
This should be skipped

1
00:00:03,000 --> 00:00:04,000
Valid subtitle
"""
        doc = SRTParser.parse(content)
        assert len(doc.entries) == 1
        assert doc.entries[0].text == "Valid subtitle"

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_srt_block_with_fewer_than_2_lines(self):
        """SRT block with only 1 line is skipped."""
        content = """1

2
00:00:03,000 --> 00:00:04,000
Valid subtitle
"""
        doc = SRTParser.parse(content)
        assert len(doc.entries) == 1
        assert doc.entries[0].text == "Valid subtitle"

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_srt_timecode_regex_no_match_path(self, caplog):
        """SRT block with timecode not matching regex issues a warning."""
        import logging
        caplog.set_level(logging.WARNING)
        content = """1
INVALID --> 00:00:02,000
Skipped due to bad timecode

2
00:00:03,000 --> 00:00:04,000
Valid subtitle
"""
        doc = SRTParser.parse(content)
        assert len(doc.entries) == 1
        assert doc.entries[0].text == "Valid subtitle"
        assert any("invalid timecode" in msg.lower() for msg in caplog.messages)


class TestAdditionalASSFeatures:
    """Additional ASS parser feature tests."""

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_ass_with_only_events_section(self):
        """ASS content with only [Events] section creates default style."""
        content = """[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.50,0:00:02.00,Default,,0,0,0,,Only events
"""
        doc = ASSParser.parse(content)
        assert len(doc.styles) >= 1
        assert doc.styles[0].name == "Default"
        assert len(doc.entries) == 1

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_ass_case_insensitive_sections(self):
        """Mixed-case section headers are parsed correctly."""
        content = """[Script Info]
Title: Test

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H00000000,&H00000000,&H00000000,0,0,0,0,100.0,100.0,0.0,0.0,1,2.0,0.0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.50,0:00:02.00,Default,,0,0,0,,Mixed case test
"""
        doc = ASSParser.parse(content)
        assert doc.metadata["Title"] == "Test"
        assert len(doc.entries) == 1

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_ass_dialogue_with_extra_commas_in_text(self):
        """Commas in dialogue text are preserved via split limit."""
        content = """[Script Info]
Title: Test

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H00000000,&H00000000,&H00000000,0,0,0,0,100.0,100.0,0.0,0.0,1,2.0,0.0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.50,0:00:02.00,Default,,0,0,0,,Text with, commas, and more
"""
        doc = ASSParser.parse(content)
        entry = doc.entries[0]
        assert entry.text == "Text with, commas, and more"
