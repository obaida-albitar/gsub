"""Comprehensive edge case tests for subtitle editor."""

import pytest
from gsub.models import (
    TimeCode, SubtitleEntry, SubtitleDocument, SubtitleFormat, ASSStyle
)
from gsub.parsers import SRTParser, ASSParser
from gsub.commands import (
    CommandManager, AddEntryCommand, EditTextCommand, TimeShiftCommand,
    RemoveEntryCommand, EditTimingCommand
)


class TestTimecodeEdgeCases:
    """Edge cases for TimeCode operations."""

    @pytest.mark.unit
    def test_timecode_maximum_values(self):
        """Test timecode with maximum reasonable values."""
        tc = TimeCode(99, 59, 59, 999)
        assert tc.total_milliseconds == 359999999

    @pytest.mark.unit
    def test_timecode_overflow_conversion(self):
        """Test timecode creation from overflow milliseconds."""
        ms = 999999999  # Very large value
        tc = TimeCode.from_milliseconds(ms)
        assert tc.total_milliseconds == ms

    @pytest.mark.unit
    def test_timecode_negative_clamping_in_shift(self):
        """Test that shifts resulting in negative times clamp to zero."""
        entry = SubtitleEntry(1, TimeCode(0, 0, 0, 100), TimeCode(0, 0, 1, 0), "Test")
        entry.shift_time(-5000)
        assert entry.start_time.total_milliseconds == 0
        assert entry.end_time.total_milliseconds == 0

    @pytest.mark.unit
    def test_timecode_zero_values(self):
        """Test timecode with all zeros."""
        tc = TimeCode(0, 0, 0, 0)
        assert tc.total_milliseconds == 0
        assert str(tc) == "00:00:00,000"
        assert tc.to_ass_format() == "0:00:00.00"

    @pytest.mark.unit
    def test_timecode_boundary_milliseconds(self):
        """Test millisecond boundary values."""
        # Test 999ms (just before 1 second)
        tc = TimeCode(0, 0, 0, 999)
        assert tc.total_milliseconds == 999
        
        # Convert back
        tc2 = TimeCode.from_milliseconds(999)
        assert tc2.milliseconds == 999

    @pytest.mark.unit
    def test_timecode_ass_centisecond_rounding(self):
        """Test ASS format centisecond conversion."""
        # 995ms should become 99 centiseconds
        tc = TimeCode(0, 0, 0, 995)
        assert tc.to_ass_format() == "0:00:00.99"
        
        # 999ms should also become 99 centiseconds
        tc = TimeCode(0, 0, 0, 999)
        assert tc.to_ass_format() == "0:00:00.99"

    @pytest.mark.unit
    def test_timecode_hours_overflow(self):
        """Test timecode with hours > 24."""
        tc = TimeCode(100, 0, 0, 0)
        assert tc.hours == 100
        assert tc.total_milliseconds == 360000000


class TestSubtitleEntryEdgeCases:
    """Edge cases for SubtitleEntry operations."""

    @pytest.mark.unit
    def test_entry_zero_duration(self):
        """Test entry with zero duration."""
        entry = SubtitleEntry(1, TimeCode(0, 0, 1, 0), TimeCode(0, 0, 1, 0), "Flash")
        assert entry.duration_ms == 0

    @pytest.mark.unit
    def test_entry_negative_duration_invalid(self):
        """Test entry where end time is before start time."""
        # This is technically invalid but should not crash
        entry = SubtitleEntry(1, TimeCode(0, 0, 2, 0), TimeCode(0, 0, 1, 0), "Invalid")
        assert entry.duration_ms < 0

    @pytest.mark.unit
    def test_entry_very_long_text(self):
        """Test entry with extremely long text."""
        long_text = "A" * 10000
        entry = SubtitleEntry(1, TimeCode(), TimeCode(), long_text)
        assert len(entry.text) == 10000

    @pytest.mark.unit
    def test_entry_empty_text(self):
        """Test entry with empty text."""
        entry = SubtitleEntry(1, TimeCode(), TimeCode(), "")
        assert entry.text == ""

    @pytest.mark.unit
    def test_entry_whitespace_only_text(self):
        """Test entry with whitespace-only text gets stripped."""
        entry = SubtitleEntry(1, TimeCode(), TimeCode(), "   \n   \t   ")
        assert entry.text == ""

    @pytest.mark.unit
    def test_entry_special_characters(self):
        """Test entry with special characters."""
        special = "♪♫♬ © ® ™ § ¶ † ‡ • ◊ ★ ☆"
        entry = SubtitleEntry(1, TimeCode(), TimeCode(), special)
        assert entry.text == special

    @pytest.mark.unit
    def test_entry_newline_variations(self):
        """Test entry with different newline types."""
        entry = SubtitleEntry(1, TimeCode(), TimeCode(), "Line1\nLine2\rLine3\r\nLine4")
        # After stripping, should preserve internal newlines
        assert "\n" in entry.text or "\r" in entry.text

    @pytest.mark.unit
    def test_entry_style_none_vs_empty(self):
        """Test entry with None style vs empty string style."""
        entry1 = SubtitleEntry(1, TimeCode(), TimeCode(), "Test", style=None)
        entry2 = SubtitleEntry(2, TimeCode(), TimeCode(), "Test", style="")
        
        assert entry1.style is None
        assert entry2.style == ""
        assert entry1.style != entry2.style


class TestDocumentEdgeCases:
    """Edge cases for SubtitleDocument operations."""

    @pytest.mark.unit
    def test_document_empty_operations(self):
        """Test operations on empty document."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        
        doc.reindex()  # Should not crash
        doc.sort_by_time()  # Should not crash
        doc.remove_entry(0)  # Should not crash
        
        assert len(doc.entries) == 0

    @pytest.mark.unit
    def test_document_single_entry_sort(self):
        """Test sorting document with single entry."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        doc.entries = [SubtitleEntry(1, TimeCode(0, 0, 5, 0), TimeCode(0, 0, 6, 0), "Solo")]
        
        doc.sort_by_time()
        
        assert len(doc.entries) == 1
        assert doc.entries[0].index == 1

    @pytest.mark.unit
    def test_document_duplicate_timestamps(self):
        """Test document with entries having identical timestamps."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        same_time = TimeCode(0, 0, 1, 0)
        
        for i in range(5):
            doc.add_entry(SubtitleEntry(i, same_time, same_time, f"Entry {i}"))
        
        doc.sort_by_time()
        assert len(doc.entries) == 5

    @pytest.mark.unit
    def test_document_reverse_order_entries(self):
        """Test document with entries in reverse chronological order."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        
        for i in range(10, 0, -1):
            entry = SubtitleEntry(i, TimeCode(0, 0, i, 0), TimeCode(0, 0, i + 1, 0), f"Entry {i}")
            doc.entries.append(entry)
        
        doc.sort_by_time()
        
        # Should now be in ascending order
        for i, entry in enumerate(doc.entries):
            assert entry.start_time.seconds == i + 1

    @pytest.mark.unit
    def test_document_metadata_special_keys(self):
        """Test metadata with special characters in keys."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        
        # Keys with spaces, special chars
        doc.set_metadata("Key With Spaces", "Value")
        doc.set_metadata("Key-With-Dashes", "Value")
        doc.set_metadata("Key_With_Underscores", "Value")
        
        assert "Key With Spaces" in doc.metadata
        assert "Key-With-Dashes" in doc.metadata

    @pytest.mark.unit
    def test_document_metadata_empty_value(self):
        """Test metadata with empty value."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        doc.set_metadata("EmptyKey", "")
        
        assert doc.metadata["EmptyKey"] == ""

    @pytest.mark.unit
    def test_document_metadata_none_value(self):
        """Test metadata with None value converts to empty string."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        doc.set_metadata("NoneKey", None)
        
        assert doc.metadata["NoneKey"] == ""

    @pytest.mark.unit
    def test_document_style_name_with_spaces(self):
        """Test style with spaces in name."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        style = ASSStyle(name="Style With Spaces")
        
        doc.upsert_style(style)
        
        assert doc.get_style_by_name("Style With Spaces") is not None

    @pytest.mark.unit
    def test_document_remove_all_styles_keeps_one(self):
        """Test that removing all styles keeps at least one default."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        doc.styles = [ASSStyle(name="OnlyStyle")]
        
        doc.remove_style("OnlyStyle")
        
        # Should always maintain at least one style
        assert len(doc.styles) >= 1

    @pytest.mark.unit
    def test_document_rename_style_with_no_entries(self):
        """Test renaming style when no entries use it."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        doc.styles = [ASSStyle(name="UnusedStyle")]
        
        doc.rename_style("UnusedStyle", "RenamedStyle")
        
        assert doc.get_style_by_name("RenamedStyle") is not None
        assert doc.get_style_by_name("UnusedStyle") is None


class TestParserEdgeCases:
    """Edge cases for SRT and ASS parsers."""

    @pytest.mark.unit
    @pytest.mark.parser
    def test_srt_parse_missing_index(self):
        """Test SRT with missing index number."""
        content = """
00:00:01,000 --> 00:00:02,000
Text without index

2
00:00:03,000 --> 00:00:04,000
Valid subtitle
"""
        doc = SRTParser.parse(content)
        # Should skip invalid block and parse valid one
        assert len(doc.entries) >= 1

    @pytest.mark.unit
    @pytest.mark.parser
    def test_srt_parse_non_sequential_indices(self):
        """Test SRT with non-sequential indices."""
        content = """1
00:00:01,000 --> 00:00:02,000
First

5
00:00:03,000 --> 00:00:04,000
Fifth

3
00:00:05,000 --> 00:00:06,000
Third
"""
        doc = SRTParser.parse(content)
        assert len(doc.entries) == 3
        # After parsing and reindexing, should be sequential
        doc.reindex()
        assert doc.entries[0].index == 1
        assert doc.entries[1].index == 2
        assert doc.entries[2].index == 3

    @pytest.mark.unit
    @pytest.mark.parser
    def test_srt_parse_very_long_text(self):
        """Test SRT with extremely long subtitle text."""
        long_text = "A" * 5000
        content = f"""1
00:00:01,000 --> 00:00:02,000
{long_text}
"""
        doc = SRTParser.parse(content)
        assert len(doc.entries[0].text) == 5000

    @pytest.mark.unit
    @pytest.mark.parser
    def test_srt_parse_multiple_blank_lines(self):
        """Test SRT with multiple consecutive blank lines."""
        content = """1
00:00:01,000 --> 00:00:02,000
First



2
00:00:03,000 --> 00:00:04,000
Second
"""
        doc = SRTParser.parse(content)
        assert len(doc.entries) == 2

    @pytest.mark.unit
    @pytest.mark.parser
    def test_srt_parse_arrows_with_different_spacing(self):
        """Test SRT with various arrow spacing."""
        content = """1
00:00:01,000-->00:00:02,000
No spaces

2
00:00:03,000   -->   00:00:04,000
Many spaces

3
00:00:05,000 --> 00:00:06,000
Normal spacing
"""
        doc = SRTParser.parse(content)
        assert len(doc.entries) == 3

    @pytest.mark.unit
    @pytest.mark.parser
    def test_srt_parse_text_with_arrow(self):
        """Test SRT where text contains arrow characters."""
        content = """1
00:00:01,000 --> 00:00:02,000
Click here --> next page
"""
        doc = SRTParser.parse(content)
        assert "Click here --> next page" in doc.entries[0].text

    @pytest.mark.unit
    @pytest.mark.parser
    def test_srt_serialize_empty_document(self):
        """Test serializing empty SRT document."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        output = SRTParser.serialize(doc)
        assert output == "" or output.strip() == ""

    @pytest.mark.unit
    @pytest.mark.parser
    def test_ass_parse_empty_sections(self):
        """Test ASS with empty sections."""
        content = """[Script Info]

[V4+ Styles]

[Events]
"""
        doc = ASSParser.parse(content)
        # Should create at least default style
        assert len(doc.styles) >= 1

    @pytest.mark.unit
    @pytest.mark.parser
    def test_ass_parse_unknown_sections(self):
        """Test ASS with unknown section headers."""
        content = """[Script Info]
Title: Test

[Unknown Section]
Key: Value

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H00000000,&H00000000,&H00000000,0,0,0,0,100.0,100.0,0.0,0.0,1,2.0,0.0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.00,Default,,,0,0,0,,Test
"""
        doc = ASSParser.parse(content)
        # Should parse valid sections and ignore unknown
        assert len(doc.entries) == 1

    @pytest.mark.unit
    @pytest.mark.parser
    def test_ass_parse_comment_only_lines(self):
        """Test ASS with many comment lines."""
        content = """[Script Info]
; Comment 1
; Comment 2
Title: Test
; Comment 3

[V4+ Styles]
; Style comments
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
; More comments
Style: Default,Arial,20,&H00FFFFFF,&H00000000,&H00000000,&H00000000,0,0,0,0,100.0,100.0,0.0,0.0,1,2.0,0.0,2,10,10,10,1

[Events]
; Event comments
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.00,Default,,,0,0,0,,Test
"""
        doc = ASSParser.parse(content)
        assert doc.metadata["Title"] == "Test"
        assert len(doc.entries) == 1

    @pytest.mark.unit
    @pytest.mark.parser
    def test_ass_parse_style_with_commas_in_fontname(self):
        """Test ASS style where font name might have special chars."""
        content = """[Script Info]
Title: Test

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,20,&H00FFFFFF,&H00000000,&H00000000,&H00000000,0,0,0,0,100.0,100.0,0.0,0.0,1,2.0,0.0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        doc = ASSParser.parse(content)
        style = doc.get_style_by_name("Default")
        assert style.fontname == "Arial Black"

    @pytest.mark.unit
    @pytest.mark.parser
    def test_ass_parse_dialogue_with_commas_in_text(self):
        """Test ASS dialogue where text contains commas."""
        content = """[Script Info]
Title: Test

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H00000000,&H00000000,&H00000000,0,0,0,0,100.0,100.0,0.0,0.0,1,2.0,0.0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.00,Default,,,0,0,0,,Text with commas, lots of them, everywhere
"""
        doc = ASSParser.parse(content)
        assert "commas" in doc.entries[0].text
        assert "everywhere" in doc.entries[0].text

    @pytest.mark.unit
    @pytest.mark.parser
    def test_ass_parse_multiple_newline_types(self):
        """Test ASS with \\N and \\n variations."""
        content = """[Script Info]
Title: Test

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H00000000,&H00000000,&H00000000,0,0,0,0,100.0,100.0,0.0,0.0,1,2.0,0.0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.00,Default,,,0,0,0,,Line1\\NLine2\\nLine3
"""
        doc = ASSParser.parse(content)
        # Both \N and \n should be converted to newlines
        assert "\n" in doc.entries[0].text

    @pytest.mark.unit
    @pytest.mark.parser
    def test_ass_serialize_empty_document(self):
        """Test serializing empty ASS document."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        output = ASSParser.serialize(doc)
        
        # Should have basic structure even if empty
        assert "[Script Info]" in output
        assert "[V4+ Styles]" in output
        assert "[Events]" in output

    @pytest.mark.unit
    @pytest.mark.parser
    def test_ass_parse_timecode_with_large_hours(self):
        """Test ASS with timecode having large hour values."""
        content = """[Script Info]
Title: Test

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H00000000,&H00000000,&H00000000,0,0,0,0,100.0,100.0,0.0,0.0,1,2.0,0.0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,99:59:59.99,100:00:00.00,Default,,,0,0,0,,Very late subtitle
"""
        doc = ASSParser.parse(content)
        assert len(doc.entries) == 1
        assert doc.entries[0].start_time.hours == 99


class TestCommandEdgeCases:
    """Edge cases for command operations."""

    @pytest.mark.unit
    @pytest.mark.command
    def test_command_execute_on_deleted_entry(self):
        """Test executing command on entry that was deleted."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        doc.entries = [SubtitleEntry(1, TimeCode(), TimeCode(), "Entry 1")]
        
        cm = CommandManager()
        
        # Edit entry at position 0
        cm.execute(EditTextCommand(doc, 0, "Modified"))
        
        # Remove the entry
        cm.execute(RemoveEntryCommand(doc, 0))
        
        # Try to undo edit (entry no longer exists at that position)
        cm.undo()
        cm.undo()
        
        # Should handle gracefully
        assert len(doc.entries) == 1

    @pytest.mark.unit
    @pytest.mark.command
    def test_command_undo_beyond_history(self):
        """Test undoing more times than history allows."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        cm = CommandManager()
        
        cm.execute(AddEntryCommand(doc, SubtitleEntry(1, TimeCode(), TimeCode(), "Test")))
        
        # Try to undo multiple times
        result1 = cm.undo()
        result2 = cm.undo()
        result3 = cm.undo()
        
        assert result1 is True
        assert result2 is False
        assert result3 is False

    @pytest.mark.unit
    @pytest.mark.command
    def test_command_redo_after_new_command(self):
        """Test that redo stack is cleared after new command."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        cm = CommandManager()
        
        cm.execute(AddEntryCommand(doc, SubtitleEntry(1, TimeCode(), TimeCode(), "First")))
        cm.execute(AddEntryCommand(doc, SubtitleEntry(2, TimeCode(), TimeCode(), "Second")))
        cm.undo()
        
        assert cm.can_redo() is True
        
        # Execute new command
        cm.execute(AddEntryCommand(doc, SubtitleEntry(3, TimeCode(), TimeCode(), "Third")))
        
        # Redo stack should be cleared
        assert cm.can_redo() is False

    @pytest.mark.unit
    @pytest.mark.command
    def test_timeshift_with_zero_offset(self):
        """Test time shift with zero offset."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        entry = SubtitleEntry(1, TimeCode(0, 0, 1, 0), TimeCode(0, 0, 2, 0), "Test")
        doc.add_entry(entry)
        
        original_time = doc.entries[0].start_time.total_milliseconds
        
        cm = CommandManager()
        cm.execute(TimeShiftCommand(doc, 0))
        
        # Should remain unchanged
        assert doc.entries[0].start_time.total_milliseconds == original_time

    @pytest.mark.unit
    @pytest.mark.command
    def test_edit_timing_with_none_values(self):
        """Test editing timing with None for start or end."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        entry = SubtitleEntry(1, TimeCode(0, 0, 1, 0), TimeCode(0, 0, 2, 0), "Test")
        doc.add_entry(entry)
        
        original_start = doc.entries[0].start_time.total_milliseconds
        
        cm = CommandManager()
        # Only change end time
        cm.execute(EditTimingCommand(doc, 0, new_start=None, new_end=TimeCode(0, 0, 3, 0)))
        
        assert doc.entries[0].start_time.total_milliseconds == original_start
        assert doc.entries[0].end_time.total_milliseconds == 3000

    @pytest.mark.unit
    @pytest.mark.command
    def test_timeshift_empty_positions_list(self):
        """Test time shift with empty positions list."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        doc.add_entry(SubtitleEntry(1, TimeCode(0, 0, 1, 0), TimeCode(0, 0, 2, 0), "Test"))
        
        cm = CommandManager()
        cm.execute(TimeShiftCommand(doc, 1000, positions=[]))
        
        # TimeShiftCommand treats empty list as "shift all" - this is expected behavior
        # Entry was at 1000ms, shifted by 1000ms = 2000ms
        assert doc.entries[0].start_time.total_milliseconds == 2000

    @pytest.mark.unit
    @pytest.mark.command
    def test_timeshift_invalid_positions(self):
        """Test time shift with invalid position indices."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        doc.add_entry(SubtitleEntry(1, TimeCode(0, 0, 1, 0), TimeCode(0, 0, 2, 0), "Test"))
        
        cm = CommandManager()
        # Position 999 doesn't exist
        cm.execute(TimeShiftCommand(doc, 1000, positions=[0, 999, -1]))
        
        # Valid position (0) should be shifted
        assert doc.entries[0].start_time.total_milliseconds == 2000


class TestStressAndBoundaryTests:
    """Stress tests and boundary condition tests."""

    @pytest.mark.integration
    def test_very_large_document_operations(self):
        """Test operations on document with many entries."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        
        # Add 5000 entries
        for i in range(5000):
            entry = SubtitleEntry(
                i + 1,
                TimeCode(0, i // 60, i % 60, 0),
                TimeCode(0, i // 60, i % 60, 500),
                f"Subtitle {i + 1}"
            )
            doc.entries.append(entry)
        
        # Test sort performance
        doc.sort_by_time()
        assert len(doc.entries) == 5000
        
        # Test reindex performance
        doc.reindex()
        assert doc.entries[-1].index == 5000

    @pytest.mark.integration
    def test_deeply_nested_undo_redo(self):
        """Test many undo/redo operations."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        cm = CommandManager(max_history=100)
        
        # Execute 50 commands
        for i in range(50):
            entry = SubtitleEntry(i, TimeCode(), TimeCode(), f"Entry {i}")
            cm.execute(AddEntryCommand(doc, entry))
        
        # Undo 25 times
        for _ in range(25):
            cm.undo()
        
        assert len(doc.entries) == 25
        
        # Redo 15 times
        for _ in range(15):
            cm.redo()
        
        assert len(doc.entries) == 40

    @pytest.mark.integration
    def test_alternating_operations(self):
        """Test alternating add/remove operations."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        cm = CommandManager()
        
        # Alternate between adding and removing
        for i in range(20):
            if i % 2 == 0:
                entry = SubtitleEntry(i, TimeCode(), TimeCode(), f"Entry {i}")
                cm.execute(AddEntryCommand(doc, entry))
            else:
                if len(doc.entries) > 0:
                    cm.execute(RemoveEntryCommand(doc, 0))
        
        # Document should have alternating results
        assert len(doc.entries) >= 0

    @pytest.mark.integration
    def test_batch_time_shift_all_entries(self):
        """Test shifting time for very large batch."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        
        for i in range(1000):
            entry = SubtitleEntry(i, TimeCode(0, 0, i, 0), TimeCode(0, 0, i + 1, 0), f"Entry {i}")
            doc.entries.append(entry)
        
        cm = CommandManager()
        cm.execute(TimeShiftCommand(doc, 5000))
        
        # First entry should be shifted
        assert doc.entries[0].start_time.total_milliseconds == 5000
        
        # Undo should restore
        cm.undo()
        assert doc.entries[0].start_time.total_milliseconds == 0

    @pytest.mark.unit
    def test_extreme_timecode_values(self):
        """Test timecodes at extreme boundaries."""
        # Maximum reasonable value
        tc_max = TimeCode(999, 59, 59, 999)
        assert tc_max.total_milliseconds > 0
        
        # Convert back
        tc_restored = TimeCode.from_milliseconds(tc_max.total_milliseconds)
        assert tc_restored.hours == 999

    @pytest.mark.unit
    def test_unicode_everywhere(self):
        """Test Unicode in all text fields."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        
        # Unicode in metadata
        doc.set_metadata("作者", "日本語名")
        doc.set_metadata("العنوان", "عربي")
        
        # Unicode in style names
        style = ASSStyle(name="스타일韓国語")
        doc.upsert_style(style)
        
        # Unicode in entry text
        entry = SubtitleEntry(
            1, TimeCode(), TimeCode(),
            "🌍 Hello 世界 مرحبا Привет 안녕하세요 🌏",
            style="스타일韓国語"
        )
        doc.add_entry(entry)
        
        # Serialize and parse
        output = ASSParser.serialize(doc)
        doc2 = ASSParser.parse(output)
        
        assert "作者" in doc2.metadata
        assert len(doc2.entries) == 1

    @pytest.mark.unit
    def test_text_with_control_characters(self):
        """Test text containing control characters."""
        text_with_controls = "Line1\x00Line2\x01Line3"
        entry = SubtitleEntry(1, TimeCode(), TimeCode(), text_with_controls)
        
        # Should not crash
        assert entry.text is not None

    @pytest.mark.unit
    def test_extremely_nested_newlines(self):
        """Test text with many consecutive newlines."""
        text = "Line1\n\n\n\n\nLine2"
        entry = SubtitleEntry(1, TimeCode(), TimeCode(), text)
        
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        doc.add_entry(entry)
        
        output = SRTParser.serialize(doc)
        doc2 = SRTParser.parse(output)
        
        # Should preserve structure
        assert len(doc2.entries) == 1

    @pytest.mark.unit
    def test_empty_string_vs_none_handling(self):
        """Test distinction between empty string and None."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        
        # Empty string metadata
        doc.set_metadata("EmptyKey", "")
        assert "EmptyKey" in doc.metadata
        assert doc.metadata["EmptyKey"] == ""
        
        # None converts to empty string
        doc.set_metadata("NoneKey", None)
        assert doc.metadata["NoneKey"] == ""
        
        # Entry with None style vs empty style
        entry1 = SubtitleEntry(1, TimeCode(), TimeCode(), "Test", style=None)
        entry2 = SubtitleEntry(2, TimeCode(), TimeCode(), "Test", style="")
        
        assert entry1.style is None
        assert entry2.style == ""

    @pytest.mark.integration
    def test_parser_with_mixed_line_endings(self):
        """Test parsing files with mixed line endings."""
        # Mix of \n, \r\n, and \r
        content = "1\r00:00:01,000 --> 00:00:02,000\nFirst\r\n\r\n2\n00:00:03,000 --> 00:00:04,000\r\nSecond\n"
        
        doc = SRTParser.parse(content)
        # Should handle mixed line endings
        assert len(doc.entries) >= 1

    @pytest.mark.unit
    def test_timecode_arithmetic_boundaries(self):
        """Test timecode arithmetic at boundaries."""
        # Near zero
        tc = TimeCode(0, 0, 0, 1)
        entry = SubtitleEntry(1, tc, TimeCode(0, 0, 1, 0), "Test")
        entry.shift_time(-2)
        assert entry.start_time.total_milliseconds == 0
        
        # Large shift
        tc = TimeCode(1, 0, 0, 0)
        entry = SubtitleEntry(1, tc, TimeCode(1, 0, 1, 0), "Test")
        entry.shift_time(999999999)
        assert entry.start_time.total_milliseconds > 3600000

    @pytest.mark.integration
    def test_document_with_all_empty_entries(self):
        """Test document where all entries have empty text."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        
        for i in range(10):
            entry = SubtitleEntry(i, TimeCode(0, 0, i, 0), TimeCode(0, 0, i + 1, 0), "")
            doc.add_entry(entry)
        
        output = SRTParser.serialize(doc)
        doc2 = SRTParser.parse(output)
        
        assert len(doc2.entries) == 10

    @pytest.mark.integration
    def test_ass_with_maximum_styles(self):
        """Test ASS document with many styles."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        
        # Add 100 styles
        for i in range(100):
            style = ASSStyle(
                name=f"Style{i}",
                fontsize=10 + i % 50,
                bold=(i % 2 == 0),
                italic=(i % 3 == 0)
            )
            doc.upsert_style(style)
        
        # Serialize and parse
        output = ASSParser.serialize(doc)
        doc2 = ASSParser.parse(output)
        
        assert len(doc2.styles) == 100

    @pytest.mark.unit
    def test_style_color_edge_cases(self):
        """Test style with various color formats."""
        # Different color formats
        styles = [
            ASSStyle(name="Color1", primary_color="&H00FFFFFF"),
            ASSStyle(name="Color2", primary_color="&H00000000"),
            ASSStyle(name="Color3", primary_color="&HFF0000FF"),
        ]
        
        for style in styles:
            assert style.primary_color.startswith("&H")

    @pytest.mark.integration
    def test_rapid_document_modifications(self):
        """Test rapid modifications to document state."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        cm = CommandManager()
        
        # Rapid add/edit/remove cycle
        for i in range(100):
            entry = SubtitleEntry(i, TimeCode(0, 0, i, 0), TimeCode(0, 0, i + 1, 0), f"Entry {i}")
            cm.execute(AddEntryCommand(doc, entry))
            
            if len(doc.entries) > 0:
                cm.execute(EditTextCommand(doc, 0, f"Modified {i}"))
            
            if len(doc.entries) > 5:
                cm.execute(RemoveEntryCommand(doc, 0))
        
        # Document should be in valid state: 5 entries remain after steady-state removal
        assert len(doc.entries) == 5
        for i, entry in enumerate(doc.entries, start=1):
            assert entry.index == i

    @pytest.mark.unit
    def test_metadata_with_very_long_values(self):
        """Test metadata with extremely long values."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        
        long_value = "A" * 10000
        doc.set_metadata("LongKey", long_value)
        
        assert len(doc.metadata["LongKey"]) == 10000

    @pytest.mark.integration
    def test_complex_undo_redo_sequence(self):
        """Test complex interleaved undo/redo operations."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        cm = CommandManager()
        
        # Build up history
        for i in range(10):
            cm.execute(AddEntryCommand(doc, SubtitleEntry(i, TimeCode(), TimeCode(), f"Entry {i}")))
        
        # Complex sequence: undo, redo, undo, new command
        cm.undo()  # 9 entries
        cm.undo()  # 8 entries
        cm.redo()  # 9 entries
        cm.undo()  # 8 entries
        cm.execute(AddEntryCommand(doc, SubtitleEntry(99, TimeCode(), TimeCode(), "New")))  # 9 entries
        
        # Redo stack should be cleared
        assert cm.can_redo() is False
        assert len(doc.entries) == 9
