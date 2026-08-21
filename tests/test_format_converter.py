"""Tests for format converter."""

import pytest
from gsub.models import SubtitleDocument, SubtitleFormat, SubtitleEntry, TimeCode, ASSStyle
from gsub.converters import FormatConverter


class TestFormatConverter:
    """Test format conversion between SRT, ASS, and SSA."""
    
    def test_convert_same_format(self):
        """Test that converting to same format returns document unchanged."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        doc.entries.append(SubtitleEntry(
            index=1,
            start_time=TimeCode(0, 0, 1, 0),
            end_time=TimeCode(0, 0, 3, 0),
            text="Test subtitle"
        ))
        
        result = FormatConverter.convert(doc, SubtitleFormat.SRT)
        assert result.format == SubtitleFormat.SRT
        assert len(result.entries) == 1
    
    def test_convert_srt_to_ass(self):
        """Test converting SRT to ASS."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        doc.entries.append(SubtitleEntry(
            index=1,
            start_time=TimeCode(0, 0, 1, 0),
            end_time=TimeCode(0, 0, 3, 0),
            text="Hello World"
        ))
        doc.entries.append(SubtitleEntry(
            index=2,
            start_time=TimeCode(0, 0, 5, 0),
            end_time=TimeCode(0, 0, 7, 0),
            text="Second subtitle"
        ))
        
        result = FormatConverter.convert(doc, SubtitleFormat.ASS)
        
        assert result.format == SubtitleFormat.ASS
        assert len(result.entries) == 2
        assert result.entries[0].text == "Hello World"
        assert result.entries[1].text == "Second subtitle"
        
        # Should have default style
        assert len(result.styles) > 0
        assert result.styles[0].name == "Default"
        
        # Should have metadata
        assert result.metadata is not None
        assert "PlayResX" in result.metadata
        assert "PlayResY" in result.metadata
    
    def test_convert_ass_to_srt(self):
        """Test converting ASS to SRT strips styling."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        
        # Add style
        style = ASSStyle(
            name="Default",
            fontname="Arial",
            fontsize=20,
            primary_color="&H00FFFFFF",
            bold=True
        )
        doc.styles.append(style)
        
        # Add entries with style tags
        doc.entries.append(SubtitleEntry(
            index=1,
            start_time=TimeCode(0, 0, 1, 0),
            end_time=TimeCode(0, 0, 3, 0),
            text="{\\i1}Italic text{\\i0}",
            style="Default"
        ))
        
        result = FormatConverter.convert(doc, SubtitleFormat.SRT)
        
        assert result.format == SubtitleFormat.SRT
        assert len(result.entries) == 1
        # Style tags should be stripped
        assert result.entries[0].text == "Italic text"
        # No styles in SRT
        assert len(result.styles) == 0
    
    def test_convert_ass_to_ssa(self):
        """Test converting ASS to SSA preserves styles."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        
        style = ASSStyle(
            name="CustomStyle",
            fontname="Comic Sans",
            fontsize=24,
            primary_color="&H00FF0000"
        )
        doc.styles.append(style)
        
        doc.entries.append(SubtitleEntry(
            index=1,
            start_time=TimeCode(0, 0, 1, 0),
            end_time=TimeCode(0, 0, 3, 0),
            text="Styled text",
            style="CustomStyle"
        ))
        
        result = FormatConverter.convert(doc, SubtitleFormat.SSA)
        
        assert result.format == SubtitleFormat.SSA
        assert len(result.entries) == 1
        assert len(result.styles) == 1
        assert result.styles[0].name == "CustomStyle"
        assert result.entries[0].style == "CustomStyle"
    
    def test_convert_preserves_timing(self):
        """Test that conversion preserves timing information."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        
        start = TimeCode(0, 1, 23, 456)
        end = TimeCode(0, 1, 25, 789)
        
        doc.entries.append(SubtitleEntry(
            index=1,
            start_time=start,
            end_time=end,
            text="Test"
        ))
        
        result = FormatConverter.convert(doc, SubtitleFormat.ASS)
        
        assert result.entries[0].start_time.total_milliseconds == start.total_milliseconds
        assert result.entries[0].end_time.total_milliseconds == end.total_milliseconds
    
    def test_convert_strips_ass_tags(self):
        """Test that ASS override tags are stripped when converting to SRT."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        
        doc.entries.append(SubtitleEntry(
            index=1,
            start_time=TimeCode(0, 0, 1, 0),
            end_time=TimeCode(0, 0, 3, 0),
            text="{\\b1}Bold{\\b0} {\\i1}Italic{\\i0} {\\u1}Underline{\\u0}"
        ))
        
        result = FormatConverter.convert(doc, SubtitleFormat.SRT)
        
        # All tags should be stripped
        assert result.entries[0].text == "Bold Italic Underline"
    
    def test_convert_preserves_metadata_ass_to_ass(self):
        """Test that metadata is preserved when converting between ASS formats."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        doc.metadata = {
            "Title": "My Subtitle",
            "PlayResX": "1280",
            "PlayResY": "720"
        }
        
        doc.entries.append(SubtitleEntry(
            index=1,
            start_time=TimeCode(0, 0, 1, 0),
            end_time=TimeCode(0, 0, 3, 0),
            text="Test"
        ))
        
        result = FormatConverter.convert(doc, SubtitleFormat.SSA)
        
        assert result.metadata is not None
        assert result.metadata.get("Title") == "My Subtitle"
        assert result.metadata.get("PlayResX") == "1280"
    
    def test_convert_creates_default_style_for_srt(self):
        """Test that converting SRT to ASS creates a default style."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        doc.entries.append(SubtitleEntry(
            index=1,
            start_time=TimeCode(0, 0, 1, 0),
            end_time=TimeCode(0, 0, 3, 0),
            text="Test"
        ))
        
        result = FormatConverter.convert(doc, SubtitleFormat.ASS)
        
        assert len(result.styles) == 1
        default_style = result.styles[0]
        assert default_style.name == "Default"
        assert default_style.fontname == "Arial"
        assert default_style.fontsize == 52
        assert default_style.bold is True
        assert default_style.alignment == 2  # Bottom center
    
    def test_convert_marks_as_modified(self):
        """Test that conversion marks document as modified."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        doc.modified = False
        doc.entries.append(SubtitleEntry(
            index=1,
            start_time=TimeCode(0, 0, 1, 0),
            end_time=TimeCode(0, 0, 3, 0),
            text="Test"
        ))
        
        result = FormatConverter.convert(doc, SubtitleFormat.ASS)
        
        assert result.modified is True
    
    def test_convert_empty_document(self):
        """Test converting an empty document."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        
        result = FormatConverter.convert(doc, SubtitleFormat.ASS)
        
        assert result.format == SubtitleFormat.ASS
        assert len(result.entries) == 0
        assert len(result.styles) > 0  # Should still have default style
    
    def test_convert_preserves_multiple_styles(self):
        """Test that multiple styles are preserved in ASS to SSA conversion."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        
        doc.styles.append(ASSStyle(name="Style1", fontname="Arial", fontsize=20))
        doc.styles.append(ASSStyle(name="Style2", fontname="Comic Sans", fontsize=24))
        doc.styles.append(ASSStyle(name="Style3", fontname="Times New Roman", fontsize=18))
        
        doc.entries.append(SubtitleEntry(
            index=1,
            start_time=TimeCode(0, 0, 1, 0),
            end_time=TimeCode(0, 0, 3, 0),
            text="Test",
            style="Style2"
        ))
        
        result = FormatConverter.convert(doc, SubtitleFormat.SSA)
        
        assert len(result.styles) == 3
        assert result.styles[0].name == "Style1"
        assert result.styles[1].name == "Style2"
        assert result.styles[2].name == "Style3"
    
    def test_convert_preserves_margins(self):
        """Test that margin information is preserved during conversion."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        
        doc.styles.append(ASSStyle(name="Default", fontname="Arial", fontsize=20))
        
        doc.entries.append(SubtitleEntry(
            index=1,
            start_time=TimeCode(0, 0, 1, 0),
            end_time=TimeCode(0, 0, 3, 0),
            text="Test",
            style="Default",
            margin_l=10,
            margin_r=20,
            margin_v=30
        ))
        
        result = FormatConverter.convert(doc, SubtitleFormat.SSA)
        
        assert result.entries[0].margin_l == 10
        assert result.entries[0].margin_r == 20
        assert result.entries[0].margin_v == 30
