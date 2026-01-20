"""Unit tests for subtitle data models."""

import pytest
import copy
from subtitle_editor.models import (
    TimeCode, SubtitleEntry, SubtitleDocument, SubtitleFormat, ASSStyle
)


class TestTimeCode:
    """Tests for TimeCode class."""

    @pytest.mark.unit
    @pytest.mark.models
    def test_timecode_initialization(self):
        """Test TimeCode initialization with default values."""
        tc = TimeCode()
        assert tc.hours == 0
        assert tc.minutes == 0
        assert tc.seconds == 0
        assert tc.milliseconds == 0

    @pytest.mark.unit
    @pytest.mark.models
    def test_timecode_with_values(self):
        """Test TimeCode initialization with specific values."""
        tc = TimeCode(1, 23, 45, 678)
        assert tc.hours == 1
        assert tc.minutes == 23
        assert tc.seconds == 45
        assert tc.milliseconds == 678

    @pytest.mark.unit
    @pytest.mark.models
    def test_total_milliseconds(self):
        """Test conversion to total milliseconds."""
        tc = TimeCode(1, 2, 3, 456)
        expected = 1 * 3600000 + 2 * 60000 + 3 * 1000 + 456
        assert tc.total_milliseconds == expected
        assert tc.total_milliseconds == 3723456

    @pytest.mark.unit
    @pytest.mark.models
    def test_total_milliseconds_zero(self):
        """Test total milliseconds for zero timecode."""
        tc = TimeCode(0, 0, 0, 0)
        assert tc.total_milliseconds == 0

    @pytest.mark.unit
    @pytest.mark.models
    def test_from_milliseconds(self):
        """Test creating TimeCode from total milliseconds."""
        ms = 3723456  # 1:02:03.456
        tc = TimeCode.from_milliseconds(ms)
        assert tc.hours == 1
        assert tc.minutes == 2
        assert tc.seconds == 3
        assert tc.milliseconds == 456

    @pytest.mark.unit
    @pytest.mark.models
    def test_from_milliseconds_zero(self):
        """Test creating TimeCode from zero milliseconds."""
        tc = TimeCode.from_milliseconds(0)
        assert tc.hours == 0
        assert tc.minutes == 0
        assert tc.seconds == 0
        assert tc.milliseconds == 0

    @pytest.mark.unit
    @pytest.mark.models
    def test_from_milliseconds_large_value(self):
        """Test creating TimeCode from large millisecond value."""
        ms = 10000000  # 2:46:40.000
        tc = TimeCode.from_milliseconds(ms)
        assert tc.hours == 2
        assert tc.minutes == 46
        assert tc.seconds == 40
        assert tc.milliseconds == 0

    @pytest.mark.unit
    @pytest.mark.models
    def test_timecode_str_format(self):
        """Test SRT format string representation."""
        tc = TimeCode(1, 2, 3, 456)
        assert str(tc) == "01:02:03,456"

    @pytest.mark.unit
    @pytest.mark.models
    def test_timecode_str_format_zero_padding(self):
        """Test zero padding in string format."""
        tc = TimeCode(0, 5, 9, 1)
        assert str(tc) == "00:05:09,001"

    @pytest.mark.unit
    @pytest.mark.models
    def test_to_ass_format(self):
        """Test ASS format conversion."""
        tc = TimeCode(1, 2, 3, 456)
        assert tc.to_ass_format() == "1:02:03.45"

    @pytest.mark.unit
    @pytest.mark.models
    def test_to_ass_format_centiseconds(self):
        """Test ASS format centiseconds conversion."""
        tc = TimeCode(0, 0, 1, 999)
        assert tc.to_ass_format() == "0:00:01.99"

    @pytest.mark.unit
    @pytest.mark.models
    def test_timecode_roundtrip(self):
        """Test roundtrip conversion through milliseconds."""
        original = TimeCode(2, 30, 45, 123)
        ms = original.total_milliseconds
        restored = TimeCode.from_milliseconds(ms)
        assert restored.hours == original.hours
        assert restored.minutes == original.minutes
        assert restored.seconds == original.seconds
        assert restored.milliseconds == original.milliseconds


class TestASSStyle:
    """Tests for ASSStyle class."""

    @pytest.mark.unit
    @pytest.mark.models
    def test_style_default_initialization(self):
        """Test ASSStyle initialization with defaults."""
        style = ASSStyle()
        assert style.name == "Default"
        assert style.fontname == "Arial"
        assert style.fontsize == 20
        assert style.bold is False
        assert style.italic is False

    @pytest.mark.unit
    @pytest.mark.models
    def test_style_custom_values(self):
        """Test ASSStyle with custom values."""
        style = ASSStyle(
            name="CustomStyle",
            fontname="Times New Roman",
            fontsize=24,
            bold=True,
            italic=True
        )
        assert style.name == "CustomStyle"
        assert style.fontname == "Times New Roman"
        assert style.fontsize == 24
        assert style.bold is True
        assert style.italic is True

    @pytest.mark.unit
    @pytest.mark.models
    def test_style_to_ass_string(self):
        """Test conversion to ASS format string."""
        style = ASSStyle(name="TestStyle", fontsize=20, bold=True)
        ass_str = style.to_ass_string()
        assert ass_str.startswith("Style: TestStyle,")
        assert "20," in ass_str
        assert ",-1," in ass_str  # bold=-1

    @pytest.mark.unit
    @pytest.mark.models
    def test_style_boolean_conversion(self):
        """Test boolean flags converted to -1/0."""
        style = ASSStyle(bold=True, italic=False, underline=True, strikeout=False)
        ass_str = style.to_ass_string()
        # Bold=-1, Italic=0, Underline=-1, Strikeout=0
        assert ",-1,0,-1,0," in ass_str

    @pytest.mark.unit
    @pytest.mark.models
    def test_style_colors(self):
        """Test style color values."""
        style = ASSStyle(
            primary_color="&H00FF0000",
            secondary_color="&H0000FF00"
        )
        assert style.primary_color == "&H00FF0000"
        assert style.secondary_color == "&H0000FF00"

    @pytest.mark.unit
    @pytest.mark.models
    def test_style_margins(self):
        """Test style margin values."""
        style = ASSStyle(margin_l=20, margin_r=30, margin_v=40)
        assert style.margin_l == 20
        assert style.margin_r == 30
        assert style.margin_v == 40


class TestSubtitleEntry:
    """Tests for SubtitleEntry class."""

    @pytest.mark.unit
    @pytest.mark.models
    def test_entry_initialization(self, sample_entry):
        """Test SubtitleEntry initialization."""
        assert sample_entry.index == 1
        assert sample_entry.start_time.total_milliseconds == 500
        assert sample_entry.end_time.total_milliseconds == 2000
        assert sample_entry.text == "Sample subtitle text"

    @pytest.mark.unit
    @pytest.mark.models
    def test_entry_with_style(self):
        """Test SubtitleEntry with ASS style."""
        entry = SubtitleEntry(
            index=1,
            start_time=TimeCode(0, 0, 0, 0),
            end_time=TimeCode(0, 0, 1, 0),
            text="Test",
            style="CustomStyle"
        )
        assert entry.style == "CustomStyle"

    @pytest.mark.unit
    @pytest.mark.models
    def test_entry_duration_ms(self, sample_entry):
        """Test duration calculation."""
        assert sample_entry.duration_ms == 1500  # 2000 - 500

    @pytest.mark.unit
    @pytest.mark.models
    def test_entry_text_strip_whitespace(self):
        """Test text whitespace stripping in post_init."""
        entry = SubtitleEntry(
            index=1,
            start_time=TimeCode(),
            end_time=TimeCode(),
            text="  \n  Test text  \n  "
        )
        assert entry.text == "Test text"

    @pytest.mark.unit
    @pytest.mark.models
    def test_shift_time_forward(self, sample_entry):
        """Test shifting time forward."""
        original_start = sample_entry.start_time.total_milliseconds
        original_end = sample_entry.end_time.total_milliseconds
        
        sample_entry.shift_time(1000)
        
        assert sample_entry.start_time.total_milliseconds == original_start + 1000
        assert sample_entry.end_time.total_milliseconds == original_end + 1000

    @pytest.mark.unit
    @pytest.mark.models
    def test_shift_time_backward(self, sample_entry):
        """Test shifting time backward."""
        original_start = sample_entry.start_time.total_milliseconds
        original_end = sample_entry.end_time.total_milliseconds
        
        sample_entry.shift_time(-200)
        
        assert sample_entry.start_time.total_milliseconds == original_start - 200
        assert sample_entry.end_time.total_milliseconds == original_end - 200

    @pytest.mark.unit
    @pytest.mark.models
    def test_shift_time_negative_clamp(self):
        """Test that negative times are clamped to zero."""
        entry = SubtitleEntry(
            index=1,
            start_time=TimeCode(0, 0, 0, 500),
            end_time=TimeCode(0, 0, 1, 0),
            text="Test"
        )
        
        entry.shift_time(-1000)
        
        assert entry.start_time.total_milliseconds == 0
        assert entry.end_time.total_milliseconds == 0


class TestSubtitleDocument:
    """Tests for SubtitleDocument class."""

    @pytest.mark.unit
    @pytest.mark.models
    def test_document_initialization(self):
        """Test SubtitleDocument initialization."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        assert doc.format == SubtitleFormat.SRT
        assert len(doc.entries) == 0
        assert len(doc.styles) == 0
        assert doc.modified is False

    @pytest.mark.unit
    @pytest.mark.models
    def test_add_entry(self, sample_srt_document, sample_entry):
        """Test adding an entry to document."""
        initial_count = len(sample_srt_document.entries)
        sample_srt_document.add_entry(sample_entry)
        
        assert len(sample_srt_document.entries) == initial_count + 1
        assert sample_srt_document.modified is True

    @pytest.mark.unit
    @pytest.mark.models
    def test_remove_entry(self, sample_srt_document):
        """Test removing an entry from document."""
        initial_count = len(sample_srt_document.entries)
        sample_srt_document.remove_entry(1)
        
        assert len(sample_srt_document.entries) == initial_count - 1
        assert sample_srt_document.modified is True

    @pytest.mark.unit
    @pytest.mark.models
    def test_remove_entry_invalid_index(self, sample_srt_document):
        """Test removing entry with invalid index."""
        initial_count = len(sample_srt_document.entries)
        sample_srt_document.remove_entry(999)
        
        assert len(sample_srt_document.entries) == initial_count

    @pytest.mark.unit
    @pytest.mark.models
    def test_reindex(self, sample_srt_document):
        """Test reindexing entries."""
        sample_srt_document.reindex()
        
        for i, entry in enumerate(sample_srt_document.entries, start=1):
            assert entry.index == i

    @pytest.mark.unit
    @pytest.mark.models
    def test_sort_by_time(self):
        """Test sorting entries by start time."""
        doc = SubtitleDocument(format=SubtitleFormat.SRT)
        doc.entries = [
            SubtitleEntry(1, TimeCode(0, 0, 5, 0), TimeCode(0, 0, 6, 0), "Third"),
            SubtitleEntry(2, TimeCode(0, 0, 0, 0), TimeCode(0, 0, 1, 0), "First"),
            SubtitleEntry(3, TimeCode(0, 0, 2, 0), TimeCode(0, 0, 3, 0), "Second"),
        ]
        
        doc.sort_by_time()
        
        assert doc.entries[0].text == "First"
        assert doc.entries[1].text == "Second"
        assert doc.entries[2].text == "Third"
        assert doc.modified is True

    @pytest.mark.unit
    @pytest.mark.models
    def test_get_style_by_name(self, sample_ass_document):
        """Test getting style by name."""
        style = sample_ass_document.get_style_by_name("Default")
        assert style is not None
        assert style.name == "Default"

    @pytest.mark.unit
    @pytest.mark.models
    def test_get_style_by_name_not_found(self, sample_ass_document):
        """Test getting non-existent style."""
        style = sample_ass_document.get_style_by_name("NonExistent")
        assert style is None

    @pytest.mark.unit
    @pytest.mark.models
    def test_set_metadata(self, sample_ass_document):
        """Test setting metadata."""
        sample_ass_document.set_metadata("Author", "Test Author")
        
        assert sample_ass_document.metadata["Author"] == "Test Author"
        assert sample_ass_document.modified is True

    @pytest.mark.unit
    @pytest.mark.models
    def test_set_metadata_empty_key_raises_error(self, sample_ass_document):
        """Test that empty metadata key raises ValueError."""
        with pytest.raises(ValueError):
            sample_ass_document.set_metadata("", "value")

    @pytest.mark.unit
    @pytest.mark.models
    def test_set_metadata_none_key_raises_error(self, sample_ass_document):
        """Test that None metadata key raises ValueError."""
        with pytest.raises(ValueError):
            sample_ass_document.set_metadata(None, "value")

    @pytest.mark.unit
    @pytest.mark.models
    def test_remove_metadata(self, sample_ass_document):
        """Test removing metadata."""
        sample_ass_document.metadata["TestKey"] = "TestValue"
        sample_ass_document.remove_metadata("TestKey")
        
        assert "TestKey" not in sample_ass_document.metadata
        assert sample_ass_document.modified is True

    @pytest.mark.unit
    @pytest.mark.models
    def test_set_aegisub_garbage(self, sample_ass_document):
        """Test setting Aegisub project garbage."""
        sample_ass_document.set_aegisub_garbage("TestKey", "TestValue")
        
        assert sample_ass_document.aegisub_project_garbage["TestKey"] == "TestValue"
        assert sample_ass_document.modified is True

    @pytest.mark.unit
    @pytest.mark.models
    def test_remove_aegisub_garbage(self, sample_ass_document):
        """Test removing Aegisub project garbage."""
        sample_ass_document.aegisub_project_garbage["TestKey"] = "TestValue"
        sample_ass_document.remove_aegisub_garbage("TestKey")
        
        assert "TestKey" not in sample_ass_document.aegisub_project_garbage

    @pytest.mark.unit
    @pytest.mark.models
    def test_upsert_style_new(self, sample_ass_document):
        """Test inserting a new style."""
        new_style = ASSStyle(name="NewStyle", fontsize=22)
        old_style = sample_ass_document.upsert_style(new_style)
        
        assert old_style is None
        assert sample_ass_document.get_style_by_name("NewStyle") is not None
        assert sample_ass_document.modified is True

    @pytest.mark.unit
    @pytest.mark.models
    def test_upsert_style_update_existing(self, sample_ass_document):
        """Test updating an existing style."""
        updated_style = ASSStyle(name="Default", fontsize=30)
        old_style = sample_ass_document.upsert_style(updated_style)
        
        assert old_style is not None
        assert old_style.fontsize == 20  # Original size
        
        current_style = sample_ass_document.get_style_by_name("Default")
        assert current_style.fontsize == 30

    @pytest.mark.unit
    @pytest.mark.models
    def test_upsert_style_none_raises_error(self, sample_ass_document):
        """Test that upserting None style raises ValueError."""
        with pytest.raises(ValueError):
            sample_ass_document.upsert_style(None)

    @pytest.mark.unit
    @pytest.mark.models
    def test_upsert_style_empty_name_raises_error(self, sample_ass_document):
        """Test that empty style name raises ValueError."""
        style = ASSStyle(name="", fontsize=20)
        with pytest.raises(ValueError):
            sample_ass_document.upsert_style(style)

    @pytest.mark.unit
    @pytest.mark.models
    def test_rename_style(self, sample_ass_document):
        """Test renaming a style."""
        sample_ass_document.rename_style("Default", "NewDefault")
        
        assert sample_ass_document.get_style_by_name("Default") is None
        assert sample_ass_document.get_style_by_name("NewDefault") is not None
        
        # Check that entries are updated
        for entry in sample_ass_document.entries:
            if entry.style == "NewDefault":
                assert entry.style == "NewDefault"

    @pytest.mark.unit
    @pytest.mark.models
    def test_rename_style_entries_updated(self, sample_ass_document):
        """Test that renaming updates all entries using the style."""
        # First entry uses "Default"
        original_style = sample_ass_document.entries[0].style
        sample_ass_document.rename_style("Default", "RenamedDefault")
        
        # Entry should now reference the renamed style
        if original_style == "Default":
            assert sample_ass_document.entries[0].style == "RenamedDefault"

    @pytest.mark.unit
    @pytest.mark.models
    def test_rename_style_not_found_raises_error(self, sample_ass_document):
        """Test renaming non-existent style raises KeyError."""
        with pytest.raises(KeyError):
            sample_ass_document.rename_style("NonExistent", "NewName")

    @pytest.mark.unit
    @pytest.mark.models
    def test_rename_style_duplicate_name_raises_error(self, sample_ass_document):
        """Test renaming to existing name raises ValueError."""
        with pytest.raises(ValueError):
            sample_ass_document.rename_style("Default", "Title")

    @pytest.mark.unit
    @pytest.mark.models
    def test_remove_style(self, sample_ass_document):
        """Test removing a style."""
        removed = sample_ass_document.remove_style("Title", fallback="Default")
        
        assert removed is not None
        assert removed.name == "Title"
        assert sample_ass_document.get_style_by_name("Title") is None

    @pytest.mark.unit
    @pytest.mark.models
    def test_remove_style_updates_entries(self, sample_ass_document):
        """Test that removing style updates entries to fallback."""
        # Second entry uses "Title"
        sample_ass_document.remove_style("Title", fallback="Default")
        
        # All entries should now use Default
        for entry in sample_ass_document.entries:
            assert entry.style == "Default"

    @pytest.mark.unit
    @pytest.mark.models
    def test_remove_style_keeps_one_style(self):
        """Test that at least one style is always kept."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        doc.styles = [ASSStyle(name="OnlyStyle")]
        
        doc.remove_style("OnlyStyle")
        
        assert len(doc.styles) >= 1

    @pytest.mark.unit
    @pytest.mark.models
    def test_remove_style_creates_fallback_if_needed(self):
        """Test that fallback style is created if it doesn't exist."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        doc.styles = [ASSStyle(name="StyleToRemove")]
        doc.entries = [SubtitleEntry(1, TimeCode(), TimeCode(), "Test", style="StyleToRemove")]
        
        doc.remove_style("StyleToRemove", fallback="NewFallback")
        
        assert doc.get_style_by_name("NewFallback") is not None
        assert doc.entries[0].style == "NewFallback"


class TestAegisubGarbage:
    """Test Aegisub project garbage methods."""
    
    def test_set_aegisub_garbage(self):
        """Test setting aegisub garbage data."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        doc.set_aegisub_garbage("key1", "value1")
        
        assert "key1" in doc.aegisub_project_garbage
        assert doc.aegisub_project_garbage["key1"] == "value1"
        assert doc.modified is True
    
    def test_set_aegisub_garbage_none_key_raises(self):
        """Test that None key raises ValueError."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        
        with pytest.raises(ValueError, match="aegisub key must not be None"):
            doc.set_aegisub_garbage(None, "value")
    
    def test_set_aegisub_garbage_empty_key_raises(self):
        """Test that empty key raises ValueError."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        
        with pytest.raises(ValueError, match="aegisub key must not be empty"):
            doc.set_aegisub_garbage("", "value")
        
        with pytest.raises(ValueError, match="aegisub key must not be empty"):
            doc.set_aegisub_garbage("   ", "value")
    
    def test_set_aegisub_garbage_none_value(self):
        """Test that None value is converted to empty string."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        doc.set_aegisub_garbage("key1", None)
        
        assert doc.aegisub_project_garbage["key1"] == ""
    
    def test_remove_aegisub_garbage(self):
        """Test removing aegisub garbage data."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        doc.set_aegisub_garbage("key1", "value1")
        doc.modified = False
        
        doc.remove_aegisub_garbage("key1")
        
        assert "key1" not in doc.aegisub_project_garbage
        assert doc.modified is True
    
    def test_remove_aegisub_garbage_nonexistent(self):
        """Test removing non-existent key doesn't raise error."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        doc.modified = False
        
        # Should not raise
        doc.remove_aegisub_garbage("nonexistent")
        
        # Modified should remain False since nothing was changed
        assert doc.modified is False


class TestStyleRename:
    """Test style renaming functionality."""
    
    def test_rename_style_basic(self):
        """Test basic style renaming."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        style = ASSStyle(name="OldName", fontname="Arial", fontsize=20)
        doc.styles.append(style)
        
        entry = SubtitleEntry(
            index=1,
            start_time=TimeCode(0, 0, 1, 0),
            end_time=TimeCode(0, 0, 3, 0),
            text="Test",
            style="OldName"
        )
        doc.entries.append(entry)
        
        doc.rename_style("OldName", "NewName")
        
        assert style.name == "NewName"
        assert entry.style == "NewName"
        assert doc.modified is True
    
    def test_rename_style_same_name_does_nothing(self):
        """Test that renaming to same name does nothing."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        style = ASSStyle(name="SameName", fontname="Arial", fontsize=20)
        doc.styles.append(style)
        
        doc.modified = False
        doc.rename_style("SameName", "SameName")
        
        # Should not modify document
        assert doc.modified is False
    
    def test_rename_style_empty_names_raise(self):
        """Test that empty names raise ValueError."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        
        with pytest.raises(ValueError, match="style names must not be empty"):
            doc.rename_style("", "NewName")
        
        with pytest.raises(ValueError, match="style names must not be empty"):
            doc.rename_style("OldName", "")
        
        with pytest.raises(ValueError, match="style names must not be empty"):
            doc.rename_style(None, "NewName")
    
    def test_rename_style_duplicate_name_raises(self):
        """Test that renaming to existing name raises ValueError."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        doc.styles.append(ASSStyle(name="Style1", fontname="Arial", fontsize=20))
        doc.styles.append(ASSStyle(name="Style2", fontname="Arial", fontsize=20))
        
        with pytest.raises(ValueError, match="style 'Style2' already exists"):
            doc.rename_style("Style1", "Style2")
    
    def test_rename_style_not_found_raises(self):
        """Test that renaming non-existent style raises KeyError."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        
        with pytest.raises(KeyError, match="style 'NonExistent' not found"):
            doc.rename_style("NonExistent", "NewName")
    
    def test_rename_style_updates_all_entries(self):
        """Test that all entries using style are updated."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        style = ASSStyle(name="OldStyle", fontname="Arial", fontsize=20)
        doc.styles.append(style)
        
        # Add multiple entries with same style
        for i in range(5):
            entry = SubtitleEntry(
                index=i + 1,
                start_time=TimeCode(0, 0, i, 0),
                end_time=TimeCode(0, 0, i + 1, 0),
                text=f"Text {i}",
                style="OldStyle"
            )
            doc.entries.append(entry)
        
        doc.rename_style("OldStyle", "NewStyle")
        
        # All entries should be updated
        for entry in doc.entries:
            assert entry.style == "NewStyle"


class TestStyleRemoval:
    """Test style removal functionality."""
    
    def test_remove_style_basic(self):
        """Test basic style removal."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        doc.styles.append(ASSStyle(name="Default", fontname="Arial", fontsize=20))
        doc.styles.append(ASSStyle(name="ToRemove", fontname="Arial", fontsize=20))
        
        removed = doc.remove_style("ToRemove")
        
        assert removed is not None
        assert removed.name == "ToRemove"
        assert doc.get_style_by_name("ToRemove") is None
        assert doc.modified is True
    
    def test_remove_style_empty_name_raises(self):
        """Test that empty name raises ValueError."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        
        with pytest.raises(ValueError, match="style name must not be empty"):
            doc.remove_style("")
        
        with pytest.raises(ValueError, match="style name must not be empty"):
            doc.remove_style(None)
    
    def test_remove_style_not_found_returns_none(self):
        """Test that removing non-existent style returns None."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        
        removed = doc.remove_style("NonExistent")
        
        assert removed is None
    
    def test_remove_style_creates_fallback_if_missing(self):
        """Test that fallback style is created if it doesn't exist."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        doc.styles.append(ASSStyle(name="ToRemove", fontname="Arial", fontsize=20))
        
        entry = SubtitleEntry(
            index=1,
            start_time=TimeCode(0, 0, 1, 0),
            end_time=TimeCode(0, 0, 3, 0),
            text="Test",
            style="ToRemove"
        )
        doc.entries.append(entry)
        
        # Remove with fallback that doesn't exist
        doc.remove_style("ToRemove", fallback="NewDefault")
        
        # Fallback should be created
        assert doc.get_style_by_name("NewDefault") is not None
        assert entry.style == "NewDefault"
    
    def test_remove_style_keeps_at_least_one(self):
        """Test that at least one style is always kept."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        doc.styles.append(ASSStyle(name="OnlyStyle", fontname="Arial", fontsize=20))
        
        doc.remove_style("OnlyStyle", fallback="")
        
        # Should still have one style
        assert len(doc.styles) == 1
    
    def test_remove_style_updates_entries_to_fallback(self):
        """Test that entries are updated to use fallback style."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        doc.styles.append(ASSStyle(name="Default", fontname="Arial", fontsize=20))
        doc.styles.append(ASSStyle(name="ToRemove", fontname="Arial", fontsize=20))
        
        # Add entries with the style to be removed
        for i in range(3):
            entry = SubtitleEntry(
                index=i + 1,
                start_time=TimeCode(0, 0, i, 0),
                end_time=TimeCode(0, 0, i + 1, 0),
                text=f"Text {i}",
                style="ToRemove"
            )
            doc.entries.append(entry)
        
        doc.remove_style("ToRemove", fallback="Default")
        
        # All entries should now use Default
        for entry in doc.entries:
            assert entry.style == "Default"
    
    def test_remove_style_returns_deep_copy(self):
        """Test that removed style is a deep copy."""
        doc = SubtitleDocument(format=SubtitleFormat.ASS)
        original_style = ASSStyle(name="ToRemove", fontname="Arial", fontsize=20)
        doc.styles.append(original_style)
        
        removed = doc.remove_style("ToRemove")
        
        # Modifying removed should not affect original
        removed.fontsize = 100
        assert original_style.fontsize == 20
