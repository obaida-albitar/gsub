"""Integration tests for subtitle editor components."""

import pytest
from gsub.models import SubtitleDocument, SubtitleFormat, SubtitleEntry, TimeCode, ASSStyle
from gsub.parsers import SRTParser, ASSParser
from gsub.commands import (
    CommandManager, AddEntryCommand, EditTextCommand, TimeShiftCommand,
    EditStyleCommand
)


class TestSRTWorkflow:
    """Integration tests for SRT workflow."""

    @pytest.mark.integration
    def test_complete_srt_workflow(self):
        """Test complete SRT editing workflow."""
        # Parse SRT file
        content = """1
00:00:01,000 --> 00:00:02,000
First subtitle

2
00:00:03,000 --> 00:00:04,000
Second subtitle
"""
        doc = SRTParser.parse(content)
        cm = CommandManager()
        
        # Add a new entry
        new_entry = SubtitleEntry(3, TimeCode(0, 0, 5, 0), TimeCode(0, 0, 6, 0), "New subtitle")
        cm.execute(AddEntryCommand(doc, new_entry))
        assert len(doc.entries) == 3
        
        # Edit text
        cm.execute(EditTextCommand(doc, 0, "Modified first subtitle"))
        assert doc.entries[0].text == "Modified first subtitle"
        
        # Shift timing
        cm.execute(TimeShiftCommand(doc, 1000))
        assert doc.entries[0].start_time.total_milliseconds == 2000
        
        # Undo all changes
        cm.undo()
        cm.undo()
        cm.undo()
        
        assert len(doc.entries) == 2
        assert doc.entries[0].text == "First subtitle"
        assert doc.entries[0].start_time.total_milliseconds == 1000
        
        # Redo changes
        cm.redo()
        cm.redo()
        cm.redo()
        
        assert len(doc.entries) == 3
        assert doc.entries[0].text == "Modified first subtitle"

    @pytest.mark.integration
    def test_srt_parse_edit_serialize(self, sample_srt_content):
        """Test parsing, editing, and serializing SRT."""
        # Parse
        doc = SRTParser.parse(sample_srt_content)
        
        # Edit
        doc.entries[0].text = "Modified text"
        doc.entries[1].shift_time(1000)
        
        # Serialize
        output = SRTParser.serialize(doc)
        
        # Parse again
        doc2 = SRTParser.parse(output)
        
        assert doc2.entries[0].text == "Modified text"
        assert doc2.entries[1].start_time.total_milliseconds == 3500


class TestASSWorkflow:
    """Integration tests for ASS workflow."""

    @pytest.mark.integration
    def test_complete_ass_workflow(self):
        """Test complete ASS editing workflow."""
        # Create ASS document
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        doc.styles = [ASSStyle(name="Default"), ASSStyle(name="Title")]
        cm = CommandManager()
        
        # Add entries with styles
        entry1 = SubtitleEntry(1, TimeCode(0, 0, 1, 0), TimeCode(0, 0, 2, 0), "First", style="Default")
        entry2 = SubtitleEntry(2, TimeCode(0, 0, 3, 0), TimeCode(0, 0, 4, 0), "Second", style="Title")
        cm.execute(AddEntryCommand(doc, entry1))
        cm.execute(AddEntryCommand(doc, entry2))
        
        # Change style
        cm.execute(EditStyleCommand(doc, 0, "Title"))
        assert doc.entries[0].style == "Title"
        
        # Undo all changes
        for _ in range(3):
            cm.undo()
        
        assert len(doc.entries) == 0

    @pytest.mark.integration
    def test_ass_parse_edit_serialize(self, sample_ass_content):
        """Test parsing, editing, and serializing ASS."""
        # Parse
        doc = ASSParser.parse(sample_ass_content)
        
        # Edit metadata
        doc.metadata["Author"] = "New Author"
        
        # Edit style
        style = doc.get_style_by_name("Default")
        style.fontsize = 25
        
        # Edit entry
        doc.entries[0].text = "Modified subtitle"
        doc.entries[0].style = "Default"
        
        # Serialize
        output = ASSParser.serialize(doc)
        
        # Parse again
        doc2 = ASSParser.parse(output)
        
        assert doc2.metadata["Author"] == "New Author"
        assert doc2.get_style_by_name("Default").fontsize == 25
        assert doc2.entries[0].text == "Modified subtitle"

    @pytest.mark.integration
    def test_ass_style_operations(self):
        """Test complex style operations."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        doc.styles = [
            ASSStyle(name="Style1"),
            ASSStyle(name="Style2"),
            ASSStyle(name="Style3"),
        ]
        doc.entries = [
            SubtitleEntry(1, TimeCode(), TimeCode(), "Text 1", style="Style1"),
            SubtitleEntry(2, TimeCode(), TimeCode(), "Text 2", style="Style2"),
            SubtitleEntry(3, TimeCode(), TimeCode(), "Text 3", style="Style3"),
        ]
        
        # Rename style
        doc.rename_style("Style1", "MainStyle")
        assert doc.entries[0].style == "MainStyle"
        
        # Remove style
        doc.remove_style("Style2", fallback="MainStyle")
        assert doc.entries[1].style == "MainStyle"
        
        # Upsert style
        new_style = ASSStyle(name="Style3", fontsize=30)
        doc.upsert_style(new_style)
        assert doc.get_style_by_name("Style3").fontsize == 30


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.integration
    def test_empty_document_operations(self):
        """Test operations on empty document."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        cm = CommandManager()
        
        # Try to remove from empty document
        cm.execute(RemoveEntryCommand(doc, 0))
        assert len(doc.entries) == 0
        
        # Add to empty document
        entry = SubtitleEntry(1, TimeCode(), TimeCode(), "First")
        cm.execute(AddEntryCommand(doc, entry))
        assert len(doc.entries) == 1

    @pytest.mark.integration
    def test_large_document_performance(self):
        """Test performance with large number of entries."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        
        # Add many entries
        for i in range(1000):
            entry = SubtitleEntry(
                i + 1,
                TimeCode(0, 0, i, 0),
                TimeCode(0, 0, i + 1, 0),
                f"Subtitle {i + 1}"
            )
            doc.entries.append(entry)
        
        # Sort by time
        doc.sort_by_time()
        assert len(doc.entries) == 1000
        
        # Shift all timings
        cm = CommandManager()
        cm.execute(TimeShiftCommand(doc, 5000))
        assert doc.entries[0].start_time.total_milliseconds == 5000

    @pytest.mark.integration
    def test_malformed_content_parsing(self):
        """Test parsing malformed content."""
        # Malformed SRT
        bad_srt = """1
INVALID TIMECODE
Text

2
00:00:01,000 --> 00:00:02,000
Valid text
"""
        doc = SRTParser.parse(bad_srt)
        assert len(doc.entries) >= 1  # At least valid entry parsed
        
        # Malformed ASS
        bad_ass = """[Script Info]
Title: Test

[V4+ Styles]
Format: Name
Style: Incomplete

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.00,Default,,,0,0,0,,Valid
"""
        doc = ASSParser.parse(bad_ass)
        assert len(doc.entries) == 1  # Only the valid dialogue entry is parsed

    @pytest.mark.integration
    def test_unicode_content(self):
        """Test handling of Unicode content."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        entries = [
            SubtitleEntry(1, TimeCode(), TimeCode(), "Hello 世界"),
            SubtitleEntry(2, TimeCode(), TimeCode(), "Привет мир"),
            SubtitleEntry(3, TimeCode(), TimeCode(), "مرحبا العالم"),
            SubtitleEntry(4, TimeCode(), TimeCode(), "🌍🌎🌏"),
        ]
        
        for entry in entries:
            doc.add_entry(entry)
        
        # Serialize and parse
        output = SRTParser.serialize(doc)
        doc2 = SRTParser.parse(output)
        
        for i, entry in enumerate(doc2.entries):
            assert entry.text == entries[i].text

    @pytest.mark.integration
    def test_timecode_edge_cases(self):
        """Test edge cases in timecode handling."""
        # Zero duration
        entry = SubtitleEntry(1, TimeCode(0, 0, 1, 0), TimeCode(0, 0, 1, 0), "Zero duration")
        assert entry.duration_ms == 0
        
        # Large timecode
        entry = SubtitleEntry(1, TimeCode(99, 59, 59, 999), TimeCode(100, 0, 0, 0), "Large time")
        assert entry.duration_ms == 1
        
        # Negative shift clamping
        entry = SubtitleEntry(1, TimeCode(0, 0, 0, 100), TimeCode(0, 0, 1, 0), "Small start")
        entry.shift_time(-1000)
        assert entry.start_time.total_milliseconds == 0
        assert entry.end_time.total_milliseconds == 0

    @pytest.mark.integration
    def test_style_name_conflicts(self):
        """Test handling style name conflicts."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        doc.styles = [ASSStyle(name="Style1")]
        
        # Try to rename to existing name
        doc.styles.append(ASSStyle(name="Style2"))
        with pytest.raises(ValueError):
            doc.rename_style("Style1", "Style2")

    @pytest.mark.integration
    def test_command_history_overflow(self):
        """Test command history with many operations."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        cm = CommandManager(max_history=10)
        
        # Execute more commands than history size
        for i in range(20):
            entry = SubtitleEntry(i, TimeCode(), TimeCode(), f"Entry {i}")
            cm.execute(AddEntryCommand(doc, entry))
        
        # Should only be able to undo up to history limit
        undo_count = 0
        while cm.can_undo():
            cm.undo()
            undo_count += 1
        
        assert undo_count == 10

    @pytest.mark.integration
    def test_multiline_text_handling(self):
        """Test handling of multiline subtitle text."""
        # SRT format
        doc_srt = SubtitleDocument(format=SubtitleFormat.SRT)
        entry = SubtitleEntry(1, TimeCode(), TimeCode(), "Line 1\nLine 2\nLine 3")
        doc_srt.add_entry(entry)
        
        output = SRTParser.serialize(doc_srt)
        doc_srt2 = SRTParser.parse(output)
        assert "\n" in doc_srt2.entries[0].text
        
        # ASS format (should convert to \N)
        doc_ass = SubtitleDocument(format=SubtitleFormat.ASS)
        doc_ass.styles = [ASSStyle(name="Default")]
        entry = SubtitleEntry(1, TimeCode(), TimeCode(), "Line 1\nLine 2")
        doc_ass.add_entry(entry)
        
        output = ASSParser.serialize(doc_ass)
        assert "\\N" in output
        doc_ass2 = ASSParser.parse(output)
        assert "\n" in doc_ass2.entries[0].text


class TestConcurrentOperations:
    """Tests for concurrent or complex operation sequences."""

    @pytest.mark.integration
    def test_multiple_undo_redo_cycles(self, sample_srt_document):
        """Test multiple undo/redo cycles."""
        cm = CommandManager()
        
        # Perform multiple operations
        cm.execute(EditTextCommand(sample_srt_document, 0, "Edit 1"))
        cm.execute(EditTextCommand(sample_srt_document, 1, "Edit 2"))
        cm.execute(EditTextCommand(sample_srt_document, 2, "Edit 3"))
        
        # Undo all
        cm.undo()
        cm.undo()
        cm.undo()
        
        # Redo some
        cm.redo()
        cm.redo()
        
        assert sample_srt_document.entries[0].text == "Edit 1"
        assert sample_srt_document.entries[1].text == "Edit 2"
        
        # Undo again
        cm.undo()
        assert sample_srt_document.entries[1].text == "Second subtitle"

    @pytest.mark.integration
    def test_interleaved_operations(self, sample_ass_document):
        """Test interleaved metadata and content operations."""
        cm = CommandManager()
        
        # Interleave different types of operations
        cm.execute(EditTextCommand(sample_ass_document, 0, "New text"))
        cm.execute(EditStyleCommand(sample_ass_document, 1, "Default"))
        
        # Undo in reverse order
        cm.undo()
        assert sample_ass_document.entries[1].style == "Title"
        
        cm.undo()
        assert "Key2" not in sample_ass_document.metadata
        
        cm.undo()
        assert sample_ass_document.entries[0].text != "New text"

    @pytest.mark.integration
    def test_document_state_consistency(self, sample_srt_document):
        """Test that document state remains consistent through operations."""
        cm = CommandManager()
        
        initial_entry_count = len(sample_srt_document.entries)
        
        # Perform various operations
        new_entry = SubtitleEntry(99, TimeCode(), TimeCode(), "New")
        cm.execute(AddEntryCommand(sample_srt_document, new_entry))
        cm.execute(RemoveEntryCommand(sample_srt_document, 1))
        cm.execute(DuplicateEntryCommand(sample_srt_document, 0))
        
        # Check indices are consistent
        for i, entry in enumerate(sample_srt_document.entries, start=1):
            assert entry.index == i
        
        # Undo all
        cm.undo()
        cm.undo()
        cm.undo()
        
        # Should be back to original state
        assert len(sample_srt_document.entries) == initial_entry_count
        for i, entry in enumerate(sample_srt_document.entries, start=1):
            assert entry.index == i


# Import statements for integration tests
from gsub.commands import RemoveEntryCommand, DuplicateEntryCommand


class TestFormatConversionIntegration:
    """Integration tests for format conversion workflows."""
    
    def test_srt_to_ass_conversion_workflow(self):
        """Test complete workflow of converting SRT to ASS."""
        from gsub.converters import FormatConverter
        
        # Create SRT document
        srt_content = """1
00:00:01,000 --> 00:00:03,000
First subtitle

2
00:00:05,000 --> 00:00:07,000
Second subtitle
"""
        
        srt_doc = SRTParser.parse(srt_content)
        assert srt_doc.format == SubtitleFormat.SRT
        assert len(srt_doc.entries) == 2
        
        # Convert to ASS
        ass_doc = FormatConverter.convert(srt_doc, SubtitleFormat.ASS)
        assert ass_doc.format == SubtitleFormat.ASS
        assert len(ass_doc.entries) == 2
        assert len(ass_doc.styles) > 0
        
        # Serialize and verify it's valid ASS
        ass_content = ASSParser.serialize(ass_doc)
        assert "[Script Info]" in ass_content
        assert "[V4+ Styles]" in ass_content
        assert "[Events]" in ass_content
        
        # Re-parse to verify integrity
        reparsed = ASSParser.parse(ass_content)
        assert len(reparsed.entries) == 2
        assert reparsed.entries[0].text == "First subtitle"
    
    def test_ass_to_srt_conversion_workflow(self):
        """Test complete workflow of converting ASS to SRT."""
        from gsub.converters import FormatConverter
        
        # Create ASS document with styling
        ass_content = """[Script Info]
Title: Test

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\i1}Styled text{\\i0}
"""
        
        ass_doc = ASSParser.parse(ass_content)
        assert ass_doc.format == SubtitleFormat.ASS
        
        # Convert to SRT
        srt_doc = FormatConverter.convert(ass_doc, SubtitleFormat.SRT)
        assert srt_doc.format == SubtitleFormat.SRT
        assert len(srt_doc.entries) == 1
        
        # Verify style tags are stripped
        assert srt_doc.entries[0].text == "Styled text"
        
        # Serialize and verify it's valid SRT
        srt_content = SRTParser.serialize(srt_doc)
        assert "00:00:01,000 --> 00:00:03,000" in srt_content
        assert "Styled text" in srt_content
    
    def test_roundtrip_conversion_preserves_content(self):
        """Test that content is preserved through format conversions."""
        from gsub.converters import FormatConverter
        
        # Start with SRT
        original_srt = """1
00:00:01,000 --> 00:00:03,000
Test subtitle one

2
00:00:05,500 --> 00:00:08,750
Test subtitle two
"""
        
        doc1 = SRTParser.parse(original_srt)
        
        # Convert to ASS
        doc2 = FormatConverter.convert(doc1, SubtitleFormat.ASS)
        
        # Convert back to SRT
        doc3 = FormatConverter.convert(doc2, SubtitleFormat.SRT)
        
        # Verify content is preserved
        assert len(doc3.entries) == 2
        assert doc3.entries[0].text == "Test subtitle one"
        assert doc3.entries[1].text == "Test subtitle two"
        assert doc3.entries[0].start_time.total_milliseconds == 1000
        assert doc3.entries[1].end_time.total_milliseconds == 8750
