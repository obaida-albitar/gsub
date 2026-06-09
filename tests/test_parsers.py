"""Unit tests for subtitle parsers."""

import pytest
from subtitle_editor.parsers import SRTParser, ASSParser
from subtitle_editor.models import SubtitleFormat, TimeCode


class TestSRTParser:
    """Tests for SRT parser."""

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_basic_srt(self, sample_srt_content):
        """Test parsing basic SRT content."""
        doc = SRTParser.parse(sample_srt_content)
        
        assert doc.format == SubtitleFormat.SRT
        assert len(doc.entries) == 3
        assert doc.modified is False

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_srt_first_entry(self, sample_srt_content):
        """Test first entry is parsed correctly."""
        doc = SRTParser.parse(sample_srt_content)
        entry = doc.entries[0]
        
        assert entry.index == 1
        assert entry.start_time.total_milliseconds == 500
        assert entry.end_time.total_milliseconds == 2000
        assert entry.text == "First subtitle"

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_srt_multiline_text(self, sample_srt_content):
        """Test parsing multiline subtitle text."""
        doc = SRTParser.parse(sample_srt_content)
        entry = doc.entries[1]
        
        assert "multiple lines" in entry.text
        assert "\n" in entry.text

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_empty_srt(self):
        """Test parsing empty SRT content."""
        doc = SRTParser.parse("")
        assert len(doc.entries) == 0

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_srt_with_blank_lines(self):
        """Test parsing SRT with extra blank lines."""
        content = """1
00:00:01,000 --> 00:00:02,000
Test


2
00:00:03,000 --> 00:00:04,000
Test 2
"""
        doc = SRTParser.parse(content)
        assert len(doc.entries) == 2

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_srt_multiparagraph_text(self):
        """Test parsing SRT with multi-paragraph text (blank lines within text)."""
        content = """1
00:00:01,000 --> 00:00:02,000
First paragraph

Second paragraph

2
00:00:03,000 --> 00:00:04,000
Next subtitle
"""
        doc = SRTParser.parse(content)
        assert len(doc.entries) == 2
        assert "First paragraph" in doc.entries[0].text
        assert "Second paragraph" in doc.entries[0].text
        assert doc.entries[1].text == "Next subtitle"

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_srt_multiparagraph_with_multiple_blank_lines(self):
        """Test parsing SRT with multiple blank lines within text."""
        content = """1
00:00:01,000 --> 00:00:02,000
Para 1


Para 2


2
00:00:03,000 --> 00:00:04,000
Next
"""
        doc = SRTParser.parse(content)
        assert len(doc.entries) == 2
        assert "Para 1" in doc.entries[0].text
        assert "Para 2" in doc.entries[0].text

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_srt_invalid_timecode(self):
        """Test parsing SRT with invalid timecode is skipped."""
        content = """1
INVALID --> 00:00:02,000
This should be skipped

2
00:00:03,000 --> 00:00:04,000
Valid subtitle
"""
        doc = SRTParser.parse(content)
        assert len(doc.entries) == 1
        assert doc.entries[0].text == "Valid subtitle"

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_srt_multiparagraph_does_not_drop_subsequent_entries(self):
        """Test that multi-paragraph text doesn't cause cascading entry loss."""
        lines = []
        for i in range(1, 51):
            lines.append(f"{i}")
            minutes = i // 60
            seconds = i % 60
            lines.append(f"00:{minutes:02d}:{seconds:02d},000 --> 00:{minutes:02d}:{seconds + 1:02d},000")
            if i == 25:
                lines.append("Line 1\n\nLine 3")
            else:
                lines.append(f"Subtitle {i}")
            lines.append("")
        content = '\n'.join(lines)
        doc = SRTParser.parse(content)
        assert len(doc.entries) == 50
        assert "Line 1" in doc.entries[24].text
        assert "Line 3" in doc.entries[24].text

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_srt_malformed_block(self):
        """Test parsing SRT with malformed blocks."""
        content = """1
00:00:01,000 --> 00:00:02,000

2
00:00:03,000 --> 00:00:04,000
Valid subtitle
"""
        doc = SRTParser.parse(content)
        # First block has no text, may be skipped or handled
        assert len(doc.entries) >= 1

    @pytest.mark.unit
    @pytest.mark.parser
    def test_serialize_srt(self, sample_srt_document):
        """Test serializing document to SRT format."""
        output = SRTParser.serialize(sample_srt_document)
        
        assert "1\n" in output
        assert "00:00:00,500 --> 00:00:02,000" in output
        assert "First subtitle" in output

    @pytest.mark.unit
    @pytest.mark.parser
    def test_serialize_srt_all_entries(self, sample_srt_document):
        """Test that all entries are serialized."""
        output = SRTParser.serialize(sample_srt_document)
        lines = output.strip().split('\n')
        
        # Count subtitle blocks
        assert "First subtitle" in output
        assert "Second subtitle" in output
        assert "Third subtitle" in output

    @pytest.mark.unit
    @pytest.mark.parser
    def test_srt_roundtrip(self, sample_srt_content):
        """Test parsing and serializing SRT maintains data."""
        doc = SRTParser.parse(sample_srt_content)
        output = SRTParser.serialize(doc)
        doc2 = SRTParser.parse(output)
        
        assert len(doc.entries) == len(doc2.entries)
        for e1, e2 in zip(doc.entries, doc2.entries):
            assert e1.start_time.total_milliseconds == e2.start_time.total_milliseconds
            assert e1.end_time.total_milliseconds == e2.end_time.total_milliseconds
            assert e1.text == e2.text

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_srt_timecode_formats(self):
        """Test various timecode formats."""
        content = """1
00:00:00,000 --> 00:00:01,000
Zero start

2
01:23:45,678 --> 01:23:46,789
Large time
"""
        doc = SRTParser.parse(content)
        assert len(doc.entries) == 2
        assert doc.entries[0].start_time.total_milliseconds == 0
        assert doc.entries[1].start_time.hours == 1
        assert doc.entries[1].start_time.minutes == 23


class TestASSParser:
    """Tests for ASS parser."""

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_basic_ass(self, sample_ass_content):
        """Test parsing basic ASS content."""
        doc = ASSParser.parse(sample_ass_content)
        
        assert doc.format == SubtitleFormat.ASS
        assert len(doc.entries) == 2
        assert len(doc.styles) >= 1
        assert doc.modified is False

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_ass_script_info(self, sample_ass_content):
        """Test parsing Script Info section."""
        doc = ASSParser.parse(sample_ass_content)
        
        assert "Title" in doc.metadata
        assert doc.metadata["Title"] == "Test Subtitle"
        assert "ScriptType" in doc.metadata

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_ass_styles(self, sample_ass_content):
        """Test parsing styles section."""
        doc = ASSParser.parse(sample_ass_content)
        
        default_style = doc.get_style_by_name("Default")
        assert default_style is not None
        assert default_style.fontname == "Arial"
        assert default_style.fontsize == 20

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_ass_dialogue(self, sample_ass_content):
        """Test parsing dialogue/events."""
        doc = ASSParser.parse(sample_ass_content)
        
        assert len(doc.entries) == 2
        entry = doc.entries[0]
        assert entry.start_time.total_milliseconds == 500
        assert entry.end_time.total_milliseconds == 2000
        assert "First subtitle" in entry.text
        assert entry.style == "Default"

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_ass_timecode_format(self):
        """Test parsing ASS timecode format (H:MM:SS.cc)."""
        content = """[Script Info]
Title: Test

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H00000000,&H00000000,&H00000000,0,0,0,0,100.0,100.0,0.0,0.0,1,2.0,0.0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,1:23:45.67,1:23:46.78,Default,,,0,0,0,,Test
"""
        doc = ASSParser.parse(content)
        entry = doc.entries[0]
        
        assert entry.start_time.hours == 1
        assert entry.start_time.minutes == 23
        assert entry.start_time.seconds == 45
        assert entry.start_time.milliseconds == 670

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_ass_newline_conversion(self):
        """Test that \\N is converted to actual newlines."""
        content = """[Script Info]
Title: Test

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H00000000,&H00000000,&H00000000,0,0,0,0,100.0,100.0,0.0,0.0,1,2.0,0.0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.50,0:00:02.00,Default,,,0,0,0,,Line 1\\NLine 2
"""
        doc = ASSParser.parse(content)
        assert "\n" in doc.entries[0].text
        assert "Line 1" in doc.entries[0].text
        assert "Line 2" in doc.entries[0].text

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_ass_empty_file(self):
        """Test parsing empty ASS file."""
        doc = ASSParser.parse("")
        
        assert doc.format == SubtitleFormat.ASS
        assert len(doc.entries) == 0
        assert len(doc.styles) >= 1  # At least default style

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_ass_comments_ignored(self):
        """Test that comments are ignored."""
        content = """[Script Info]
; This is a comment
Title: Test
; Another comment

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H00000000,&H00000000,&H00000000,0,0,0,0,100.0,100.0,0.0,0.0,1,2.0,0.0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.50,0:00:02.00,Default,,,0,0,0,,Test
"""
        doc = ASSParser.parse(content)
        assert doc.metadata["Title"] == "Test"
        assert len(doc.entries) == 1

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_ass_aegisub_garbage(self):
        """Test parsing Aegisub Project Garbage section."""
        content = """[Script Info]
Title: Test

[Aegisub Project Garbage]
Audio File: audio.wav
Video File: video.mp4

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H00000000,&H00000000,&H00000000,0,0,0,0,100.0,100.0,0.0,0.0,1,2.0,0.0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.50,0:00:02.00,Default,,,0,0,0,,Test
"""
        doc = ASSParser.parse(content)
        assert "Audio File" in doc.aegisub_project_garbage
        assert doc.aegisub_project_garbage["Audio File"] == "audio.wav"

    @pytest.mark.unit
    @pytest.mark.parser
    def test_serialize_ass(self, sample_ass_document):
        """Test serializing document to ASS format."""
        output = ASSParser.serialize(sample_ass_document)
        
        assert "[Script Info]" in output
        assert "[V4+ Styles]" in output
        assert "[Events]" in output
        assert "Dialogue:" in output

    @pytest.mark.unit
    @pytest.mark.parser
    def test_serialize_ass_metadata(self, sample_ass_document):
        """Test that metadata is serialized."""
        output = ASSParser.serialize(sample_ass_document)
        
        assert "Title: Test Subtitle" in output
        assert "ScriptType: v4.00+" in output

    @pytest.mark.unit
    @pytest.mark.parser
    def test_serialize_ass_styles(self, sample_ass_document):
        """Test that styles are serialized."""
        output = ASSParser.serialize(sample_ass_document)
        
        assert "Style: Default," in output
        assert "Style: Title," in output

    @pytest.mark.unit
    @pytest.mark.parser
    def test_serialize_ass_newline_conversion(self):
        """Test that newlines are converted to \\N."""
        from subtitle_editor.models import SubtitleDocument, SubtitleEntry, SubtitleFormat, TimeCode, ASSStyle
        
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        doc.styles = [ASSStyle(name="Default")]
        doc.entries = [
            SubtitleEntry(1, TimeCode(0, 0, 0, 500), TimeCode(0, 0, 2, 0), "Line 1\nLine 2")
        ]
        
        output = ASSParser.serialize(doc)
        assert "Line 1\\NLine 2" in output
        assert "Line 1\nLine 2" not in output.split("[Events]")[1]  # Not in events section

    @pytest.mark.unit
    @pytest.mark.parser
    def test_serialize_ass_aegisub_garbage(self):
        """Test serializing Aegisub Project Garbage."""
        from subtitle_editor.models import SubtitleDocument, SubtitleFormat, ASSStyle
        
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        doc.styles = [ASSStyle(name="Default")]
        doc.aegisub_project_garbage = {
            "Audio File": "audio.wav",
            "Video File": "video.mp4"
        }
        
        output = ASSParser.serialize(doc)
        assert "[Aegisub Project Garbage]" in output
        assert "Audio File: audio.wav" in output

    @pytest.mark.unit
    @pytest.mark.parser
    def test_ass_roundtrip(self, sample_ass_content):
        """Test parsing and serializing ASS maintains data."""
        doc = ASSParser.parse(sample_ass_content)
        output = ASSParser.serialize(doc)
        doc2 = ASSParser.parse(output)
        
        assert len(doc.entries) == len(doc2.entries)
        assert len(doc.styles) == len(doc2.styles)
        
        for e1, e2 in zip(doc.entries, doc2.entries):
            assert e1.start_time.total_milliseconds == e2.start_time.total_milliseconds
            assert e1.end_time.total_milliseconds == e2.end_time.total_milliseconds
            assert e1.text == e2.text
            assert e1.style == e2.style
            assert e1.layer == e2.layer
            assert e1.actor == e2.actor
            assert e1.effect == e2.effect

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_ass_style_boolean_fields(self):
        """Test parsing style boolean fields (bold, italic, etc.)."""
        content = """[Script Info]
Title: Test

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: BoldItalic,Arial,20,&H00FFFFFF,&H00000000,&H00000000,&H00000000,-1,-1,-1,-1,100.0,100.0,0.0,0.0,1,2.0,0.0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.50,0:00:02.00,BoldItalic,,,0,0,0,,Test
"""
        doc = ASSParser.parse(content)
        style = doc.get_style_by_name("BoldItalic")
        
        assert style.bold is True
        assert style.italic is True
        assert style.underline is True
        assert style.strikeout is True

    @pytest.mark.unit
    @pytest.mark.parser
    def test_parse_ass_detect_ssa_format(self):
        """Test detection of SSA format (v4.00)."""
        content = """[Script Info]
Title: Test
ScriptType: v4.00

[V4 Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, TertiaryColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, AlphaLevel, Encoding
Style: Default,Arial,20,16777215,255,65535,0,0,0,1,0,2,2,30,30,30,0,0

[Events]
Format: Marked, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: Marked=0,0:00:00.50,0:00:02.00,Default,,0,0,0,,Test
"""
        doc = ASSParser.parse(content)
        # Should detect as SSA
        assert doc.format in [SubtitleFormat.SSA, SubtitleFormat.ASS]

    @pytest.mark.unit
    @pytest.mark.parser
    def test_serialize_ass_default_metadata(self):
        """Test that default metadata is added if missing."""
        from subtitle_editor.models import SubtitleDocument, SubtitleFormat, ASSStyle
        
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        doc.styles = [ASSStyle(name="Default")]
        
        output = ASSParser.serialize(doc)
        
        # Should include default values
        assert "Title:" in output
        assert "ScriptType:" in output
